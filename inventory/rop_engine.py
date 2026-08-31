"""
inventory/rop_engine.py
-----------------------
Reorder Point calculation engine.

Sales files must be placed in the sales_data/ folder in the project root.
File naming convention: sales-sheet-YYYY-MM.xlsx
Example: sales-sheet-2026-02.xlsx, sales-sheet-2026-03.xlsx

The script reads the N most recent files (default 6) and aggregates sales
by SKU using columns:
  - "Κωδικός Είδους" (col index 10): SKU
  - "Ποσ. 1ης Μ.Μ." (col index 11): quantity sold

Only FIN product SKUs are included (prefixes: 02,03,04,05,06,08,10,11).
"""

import os
import re
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
import statistics

import openpyxl
from django.db.models import Sum

SALES_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'sales_data'
)

FIN_PREFIXES = ('02-', '03-', '04-', '05-', '06-', '08-', '10-', '11-')

FILE_PATTERN = re.compile(r'sales-sheet-(\d{4})-(\d{2})\.xlsx$', re.IGNORECASE)


def get_sales_files(n=12):
    """Return up to n most recent sales xlsx files, sorted oldest first."""
    if not os.path.isdir(SALES_DATA_DIR):
        return []
    files = []
    for fname in os.listdir(SALES_DATA_DIR):
        m = FILE_PATTERN.match(fname)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            files.append((year, month, fname))
    files.sort()
    return files[-n:]


def get_all_available_files():
    """Return all available sales files sorted oldest first."""
    return get_sales_files(n=24)


def get_default_selected_months(all_files):
    """Return the 6 most recent month labels as defaults."""
    labels = [f'{m:02d}/{y}' for y, m, _ in all_files]
    return labels[-6:]


def parse_sales_file(filepath):
    """
    Parse a raw ERP sales export xlsx.
    Returns dict: {sku: total_qty}
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    totals = defaultdict(Decimal)
    header_found = False

    sku_col = qty_col = None

    for row in ws.iter_rows(values_only=True):
        if not header_found:
            # Find header row
            row_vals = [str(v).strip() if v else '' for v in row]
            if 'Κωδικός Είδους' in row_vals:
                sku_col = row_vals.index('Κωδικός Είδους')
                qty_col = row_vals.index('Ποσ. 1ης Μ.Μ.') if 'Ποσ. 1ης Μ.Μ.' in row_vals else None
                header_found = True
            continue

        if sku_col is None or qty_col is None:
            continue

        sku = str(row[sku_col]).strip() if row[sku_col] else ''
        if not any(sku.startswith(p) for p in FIN_PREFIXES):
            continue

        try:
            qty = Decimal(str(row[qty_col]).replace(',', '.'))
            if qty > 0:
                totals[sku] += qty
        except Exception:
            continue

    wb.close()
    return dict(totals)


def get_current_stock():
    """
    Returns dict: {sku: available_qty} from ProductBatch,
    subtracting order-linked reservations.
    """
    from inventory.models import ProductBatch, ProductBatchReservation
    from django.db.models import Sum

    stock = {}
    for pb in ProductBatch.objects.select_related('material').all():
        sku = pb.material.sku
        if not any(sku.startswith(p) for p in FIN_PREFIXES):
            continue
        reserved = ProductBatchReservation.objects.filter(
            product_batch=pb,
            order_line__isnull=False
        ).aggregate(t=Sum('quantity_reserved'))['t'] or Decimal('0')
        available = pb.quantity_produced - reserved
        stock[sku] = stock.get(sku, Decimal('0')) + available
    return stock


def get_lead_times():
    """Returns dict: {sku_prefix: lead_time_months}"""
    from inventory.models import LeadTimeConfig
    return {lt.sku_prefix: lt.lead_time_months for lt in LeadTimeConfig.objects.all()}


def get_settings():
    """Returns the singleton ReorderSettings object (creates default if missing)."""
    from inventory.models import ReorderSettings
    obj, _ = ReorderSettings.objects.get_or_create(pk=1)
    return obj


def calculate_rop(selected_months=None):
    """
    Main calculation function.
    selected_months: list of 'MM/YYYY' labels to include, or None for last 6.
    Returns list of dicts, one per SKU.
    """
    settings   = get_settings()
    z_score    = float(settings.z_score)
    lead_times = get_lead_times()
    stock      = get_current_stock()

    all_files = get_all_available_files()
    if not all_files:
        return [], []

    # Determine which months to use
    if selected_months is None:
        selected_months = settings.selected_months or get_default_selected_months(all_files)

    # Filter files to selected months
    files = [
        (y, m, fname) for y, m, fname in all_files
        if f'{m:02d}/{y}' in selected_months
    ]
    files.sort()

    if not files:
        return [], []

    # Build month labels and per-month sales
    monthly_data = {}   # {sku: {month_label: qty}}
    month_labels = []
    all_skus = set()
    sku_names = {}

    for year, month, fname in files:
        label = f'{month:02d}/{year}'
        month_labels.append(label)
        filepath = os.path.join(SALES_DATA_DIR, fname)
        sales = parse_sales_file(filepath)
        for sku, qty in sales.items():
            all_skus.add(sku)
            if sku not in monthly_data:
                monthly_data[sku] = {}
            monthly_data[sku][label] = qty

    # Get material names from DB
    from inventory.models import Material
    mat_map = {m.sku: m.name for m in Material.objects.filter(
        sku__in=all_skus
    )}

    rows = []
    for sku in sorted(all_skus):
        monthly_sales = [
            float(monthly_data.get(sku, {}).get(lbl, Decimal('0')))
            for lbl in month_labels
        ]

        total     = sum(monthly_sales)
        avg       = total / len(monthly_sales) if monthly_sales else 0
        std       = statistics.stdev(monthly_sales) if len(monthly_sales) > 1 else 0
        cv        = (std / avg) if avg > 0 else 0

        prefix    = sku[:2]
        lead_time = float(lead_times.get(prefix, Decimal('2')))
        safety    = z_score * std * (lead_time ** 0.5)
        rop       = avg * lead_time + safety

        current   = float(stock.get(sku, Decimal('0')))
        gap       = current - rop
        reorder   = gap < 0

        rop_r     = round(rop)
        current_r = round(current)
        rows.append({
            'sku':           sku,
            'name':          mat_map.get(sku, ''),
            'monthly_sales': monthly_sales,
            'total':         round(total, 1),
            'avg':           round(avg, 1),
            'std':           round(std, 1),
            'cv':            round(cv, 3),
            'lead_time':     lead_time,
            'safety_stock':  round(safety, 1),
            'rop':           rop_r,
            'current_stock': current_r,
            'gap':           current_r - rop_r,
            'reorder':       reorder,
        })

    return rows, month_labels
