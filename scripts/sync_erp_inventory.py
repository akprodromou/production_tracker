"""
sync_erp_inventory.py
---------------------
Run from project root:
    python sync_erp_inventory.py inventory-2026-06-29.xlsx [--dry-run]

Weekly ERP inventory sync:
  - Creates missing materials and batches for new SKUs
  - Creates new batches for the difference when ERP > DB
  - Reduces existing batch quantities when ERP < DB
  - Reports conflicts where reduction was not possible
"""

import os
import sys

# Ensure project root (parent of this scripts/ folder) is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
import pandas as pd
from decimal import Decimal, InvalidOperation
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.db.models import Sum
from inventory.models import (
    Material, Location, Unit,
    RawMaterialBatch, ProductBatch,
    RawBatchAllocation, ProductBatchReservation,
)

LOCATION_MAP = {
    "000001": 7,
    "000002": 6,
    "000005": 3,
    "000006": 12,
    "000007": 2,
    "000009": 10,
    "000013": 11,
    "000014": 13,
}

UNIT_MAP = {
    "Τεμάχια": "pcs",
    "Κιλά":    "kg",
    "Λίτρα":   "litres",
}

DEFAULT_LOCATION_ID = 7
DRY_RUN = '--dry-run' in sys.argv


def sku_to_category(sku):
    if sku.startswith('07-'):
        return 'RAW'
    if sku.startswith('01-'):
        return 'FXD'
    s = sku.upper()
    if s.startswith('ΕΙΔΗ-') or s.startswith('\u0395\u0399\u0394\u0397-'):
        return 'CON'
    return 'FIN'


def get_or_create_unit(erp_unit_name):
    unit_name = UNIT_MAP.get(erp_unit_name, erp_unit_name)
    unit, created = Unit.objects.get_or_create(name=unit_name)
    if created:
        print(f"    Created unit: {unit_name}")
    return unit


def get_or_create_material(sku, name, erp_unit_name):
    try:
        return Material.objects.get(sku=sku), False
    except Material.DoesNotExist:
        pass
    category = sku_to_category(sku)
    unit = get_or_create_unit(erp_unit_name)
    if DRY_RUN:
        print(f"    [DRY RUN] Would create material: {sku} | {name} | category={category} | unit={unit.name}")
        return None, True
    material = Material.objects.create(sku=sku, name=name, category=category, unit=unit)
    print(f"    Created material: {sku} | {name} | category={category}")
    return material, True


def parse_erp(filepath):
    df = pd.read_excel(filepath, header=None, dtype=str)
    records = []
    current_location_code = None
    for _, row in df.iterrows():
        values = [str(v).strip() if str(v) != 'nan' else '' for v in row]
        non_empty = [v for v in values if v]
        if not non_empty:
            continue
        first = non_empty[0]
        if len(first) == 6 and first.isdigit():
            current_location_code = first
            continue
        if current_location_code and '-' in first and len(first) >= 10:
            sku = first
            raw = [str(v).strip() for v in row if str(v) not in ('nan', '') and str(v).strip() != '']
            try:
                if len(raw) < 5:
                    continue
                name     = raw[1]
                erp_unit = raw[3]
                qty      = Decimal(raw[4].replace(',', '.'))
            except (InvalidOperation, IndexError):
                continue
            if current_location_code not in LOCATION_MAP:
                continue
            records.append({
                'sku': sku, 'name': name, 'erp_unit': erp_unit,
                'qty': qty, 'location_code': current_location_code,
                'location_id': LOCATION_MAP[current_location_code],
            })
    return records


def get_db_totals():
    totals = {}
    for b in RawMaterialBatch.objects.select_related('material').all():
        key = (b.material.sku, b.location_id)
        totals[key] = totals.get(key, Decimal('0')) + b.total_quantity
    for b in ProductBatch.objects.select_related('material').all():
        key = (b.material.sku, b.location_id)
        totals[key] = totals.get(key, Decimal('0')) + b.quantity_produced
    return totals


def reduce_raw_batches(material, location_id, amount_to_reduce):
    remaining = amount_to_reduce
    conflicts = []
    for batch in RawMaterialBatch.objects.filter(
        material=material, location_id=location_id
    ).order_by('-created_at'):
        if remaining <= 0:
            break
        allocated = RawBatchAllocation.objects.filter(
            raw_batch=batch
        ).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
        reducible = batch.total_quantity - allocated
        if reducible <= 0:
            conflicts.append(f"    Batch {batch.lot_number}: fully allocated ({allocated}) — skipped")
            continue
        reduce_by = min(remaining, reducible)
        if not DRY_RUN:
            batch.total_quantity -= reduce_by
            batch.save()
        remaining -= reduce_by
    return amount_to_reduce - remaining, conflicts


def reduce_fin_batches(material, location_id, amount_to_reduce):
    remaining = amount_to_reduce
    conflicts = []
    for batch in ProductBatch.objects.filter(
        material=material, location_id=location_id
    ).order_by('-created_at'):
        if remaining <= 0:
            break
        reserved = ProductBatchReservation.objects.filter(
            product_batch=batch
        ).aggregate(t=Sum('quantity_reserved'))['t'] or Decimal('0')
        reducible = batch.quantity_produced - reserved
        if reducible <= 0:
            conflicts.append(f"    Batch {batch.batch_number}: fully reserved ({reserved}) — skipped")
            continue
        reduce_by = min(remaining, reducible)
        if not DRY_RUN:
            batch.quantity_produced -= reduce_by
            batch.save()
        remaining -= reduce_by
    return amount_to_reduce - remaining, conflicts


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('--'):
        print("Usage: python sync_erp_inventory.py <erp_export.xlsx> [--dry-run]")
        sys.exit(1)
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Reading: {filepath}\n")
    erp_records = parse_erp(filepath)
    print(f"Found {len(erp_records)} ERP line items\n")

    db_totals         = get_db_totals()
    today             = date.today().isoformat()
    created_materials = 0
    created_raw       = 0
    created_fin       = 0
    reduced_raw       = 0
    reduced_fin       = 0
    skipped_same      = 0
    all_conflicts     = []

    for rec in erp_records:
        sku         = rec['sku']
        erp_qty     = max(rec['qty'], Decimal('0'))
        location_id = rec['location_id']
        loc_code    = rec['location_code']
        name        = rec['name']
        erp_unit    = rec['erp_unit']

        material, mat_created = get_or_create_material(sku, name, erp_unit)
        if mat_created:
            created_materials += 1
        if material is None:
            continue

        try:
            location = Location.objects.get(pk=location_id)
        except Location.DoesNotExist:
            print(f"  Location {location_id} not found — skipped {sku}")
            continue

        db_qty = db_totals.get((sku, location_id), Decimal('0'))
        diff   = erp_qty - db_qty

        if diff == 0:
            skipped_same += 1
            continue

        category = material.category
        label    = f"ERP-SYNC-{today}-{sku}-{loc_code}"

        if diff > 0:
            if category in ('RAW', 'PKG'):
                if not DRY_RUN:
                    if not RawMaterialBatch.objects.filter(lot_number=label, material=material).exists():
                        RawMaterialBatch.objects.create(
                            material=material, lot_number=label,
                            total_quantity=diff, location=location,
                            status='IN_WAREHOUSE_RAW',
                        )
                created_raw += 1
                print(f"  + RAW: {label} | {name[:40]} | +{diff} @ {location.name}")
            elif category == 'FIN':
                if not DRY_RUN:
                    if not ProductBatch.objects.filter(batch_number=label).exists():
                        ProductBatch.objects.create(
                            material=material, batch_number=label,
                            quantity_produced=diff, location=location,
                        )
                created_fin += 1
                print(f"  + FIN: {label} | {name[:40]} | +{diff} @ {location.name}")
            else:
                print(f"  SKIP non-stock category '{category}': {sku}")

        else:
            reduce_by = abs(diff)
            print(f"  ↓ {sku} @ {location.name}: DB={db_qty}, ERP={erp_qty}, reducing by {reduce_by}")
            if category in ('RAW', 'PKG'):
                reduced, conflicts = reduce_raw_batches(material, location_id, reduce_by)
                reduced_raw += 1
            elif category == 'FIN':
                reduced, conflicts = reduce_fin_batches(material, location_id, reduce_by)
                reduced_fin += 1
            else:
                continue
            if conflicts:
                all_conflicts.extend([f"  {sku} @ {location.name}:"] + conflicts)
            if reduced < reduce_by:
                all_conflicts.append(
                    f"  {sku} @ {location.name}: reduced {reduced} of {reduce_by} needed — {reduce_by - reduced} unresolved"
                )

    print(f"\n{'='*60}")
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}SYNC COMPLETE")
    print(f"{'='*60}")
    print(f"  Materials created   : {created_materials}")
    print(f"  RAW batches created : {created_raw}")
    print(f"  FIN batches created : {created_fin}")
    print(f"  RAW batches reduced : {reduced_raw}")
    print(f"  FIN batches reduced : {reduced_fin}")
    print(f"  Unchanged           : {skipped_same}")
    if all_conflicts:
        print(f"\n⚠  CONFLICTS ({len(all_conflicts)} notices) — some batches could not be reduced:")
        for c in all_conflicts:
            print(c)
    else:
        print("\n  No conflicts.")


if __name__ == '__main__':
    main()
