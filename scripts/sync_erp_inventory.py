"""
sync_erp_inventory.py
---------------------
Syncs inventory quantities from the ERP xlsx export directly into the app.

For each SKU + location:
  - Deletes ALL existing batches (raw or product)
  - Creates ONE new batch with quantity = Διαθ. Υπολ. from ERP
  - Negative quantities are stored as-is (reflects ERP reality)
  - Zero quantities result in no batch being created
  - SKU+location combos present in DB but absent from ERP file are also deleted

Run from project root:
    python scripts/sync_erp_inventory.py inventory-YYYY-MM-DD.xlsx [--dry-run]

To run against Railway:
    $env:DATABASE_URL="postgresql://postgres:GSUajhGKPuJMLpItMmZbduFbjMVWAeNE@hayabusa.proxy.rlwy.net:55480/railway"
    python scripts/sync_erp_inventory.py inventory-2026-09-02.xlsx
    $env:DATABASE_URL=""

File naming convention: inventory-YYYY-MM-DD.xlsx

Export from Pylon ERP:
    Αποθήκη / Αναφορές / Εκτυπώσεις / (Είδη / Υπηρεσίες / Πάγια) / Υπόλοιπα / Υπόλοιπα ανά Αποθήκη και Είδος
    click «Μπάντες»
    click «Είδη»
    Διαθ. Υπ.: Ορατή
    Εκτέλεση Ως: Grid
    Εξαγωγές / Εξαγωγή σε Excel (xlsx)
"""

import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

import openpyxl
from decimal import Decimal, InvalidOperation
from datetime import date
from inventory.models import Material, Location, Unit, RawMaterialBatch, ProductBatch

DRY_RUN = '--dry-run' in sys.argv

LOCATION_MAP = {
    '000001': 7,
    '000002': 6,
    '000005': 3,
    '000006': 12,
    '000007': 2,
    '000009': 10,
    '000013': 11,
    '000014': 13,
}

UNIT_MAP = {
    'Τεμάχια': 'pcs',
    'Κιλά': 'kg',
    'Λίτρα': 'litres',
}


def sku_category(sku):
    if sku.startswith('07-'):
        return 'RAW'
    if sku.startswith('01-'):
        return 'FXD'
    if sku.upper().startswith('ΕΙΔΗ-'):
        return 'CON'
    return 'FIN'


def clean(v):
    if v is None:
        return ''
    return str(v).strip()


def to_decimal(v):
    if v is None:
        return None
    s = str(v).replace(',', '.').strip()
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_xlsx(filepath):
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    records = []
    current_loc_code = None

    for row in ws.iter_rows(values_only=True):
        col0 = clean(row[0]) if len(row) > 0 else ''
        col1 = clean(row[1]) if len(row) > 1 else ''

        if col0 and re.match(r'^\d{6}$', col0) and col0 in LOCATION_MAP:
            current_loc_code = col0
            continue

        if not current_loc_code or not col1 or '-' not in col1:
            continue

        sku      = col1
        name     = clean(row[2]) if len(row) > 2 else ''
        unit_erp = clean(row[5]) if len(row) > 5 else ''
        diath    = to_decimal(row[11]) if len(row) > 11 else None

        if diath is None:
            continue

        records.append({
            'sku':         sku,
            'name':        name,
            'unit_name':   UNIT_MAP.get(unit_erp, unit_erp),
            'qty':         diath,
            'location_code': current_loc_code,
            'location_id': LOCATION_MAP[current_loc_code],
        })

    wb.close()
    return records


def get_or_create_unit(name):
    unit, _ = Unit.objects.get_or_create(
        name=name, defaults={'abbreviation': name[:10]}
    )
    return unit


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('--'):
        print("Usage: python scripts/sync_erp_inventory.py <inventory.xlsx> [--dry-run]")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Reading: {filepath}\n")
    records = parse_xlsx(filepath)
    print(f"Found {len(records)} ERP line items\n")

    today        = date.today().isoformat()
    written      = 0
    skipped_zero = 0
    deleted_stale = 0
    errors       = []

    # Track which (sku, location_id) combos appear in ERP file
    erp_combos = set()

    for rec in records:
        sku      = rec['sku']
        qty      = rec['qty']
        loc_id   = rec['location_id']
        name     = rec['name']
        category = sku_category(sku)

        if category in ('FXD', 'CON'):
            continue

        erp_combos.add((sku, loc_id))

        try:
            material = Material.objects.get(sku=sku)
        except Material.DoesNotExist:
            if qty == 0:
                skipped_zero += 1
                continue
            unit = get_or_create_unit(rec['unit_name'])
            if not DRY_RUN:
                material = Material.objects.create(
                    sku=sku, name=name, category=category, unit=unit
                )
                print(f"  CREATED material: {sku} | {name}")
            else:
                print(f"  [DRY RUN] Would create material: {sku} | {name}")
                continue

        try:
            location = Location.objects.get(pk=loc_id)
        except Location.DoesNotExist:
            errors.append(f"Location {loc_id} not found — skipped {sku}")
            continue

        batch_ref = f"ERP-SYNC-{today}-{sku}-{loc_id}"

        if DRY_RUN:
            action = f"SET {qty}" if qty != 0 else "DELETE ALL (qty=0)"
            print(f"  [DRY RUN] {action}: {sku} @ {location.name}")
            continue

        # Delete all existing batches for this SKU + location
        if category == 'FIN':
            ProductBatch.objects.filter(material=material, location_id=loc_id).delete()
        else:
            RawMaterialBatch.objects.filter(material=material, location_id=loc_id).delete()

        if qty == 0:
            skipped_zero += 1
            continue

        if category == 'FIN':
            ProductBatch.objects.create(
                material=material,
                batch_number=batch_ref,
                quantity_produced=qty,
                location=location,
            )
        else:
            RawMaterialBatch.objects.create(
                material=material,
                lot_number=batch_ref,
                total_quantity=qty,
                location=location,
            )

        print(f"  {'+'if qty>0 else ''}{qty:>10} | {sku:<20} | {location.name}")
        written += 1

    # ── Delete stale batches for SKUs seen in ERP but missing locations ──
    # For any SKU that appeared in the ERP file, delete batches for locations
    # that are in our LOCATION_MAP but NOT in the ERP file for that SKU
    print("\nCleaning up stale batches for locations no longer in ERP...")
    erp_skus = {sku for sku, _ in erp_combos}
    all_loc_ids = set(LOCATION_MAP.values())

    for sku in erp_skus:
        category = sku_category(sku)
        if category in ('FXD', 'CON'):
            continue
        try:
            material = Material.objects.get(sku=sku)
        except Material.DoesNotExist:
            continue

        # Locations in our map but not in ERP file for this SKU
        erp_locs_for_sku = {loc_id for s, loc_id in erp_combos if s == sku}
        stale_locs = all_loc_ids - erp_locs_for_sku

        for loc_id in stale_locs:
            if category == 'FIN':
                deleted = ProductBatch.objects.filter(material=material, location_id=loc_id)
            else:
                deleted = RawMaterialBatch.objects.filter(material=material, location_id=loc_id)

            count = deleted.count()
            if count > 0:
                if not DRY_RUN:
                    deleted.delete()
                try:
                    loc = Location.objects.get(pk=loc_id)
                    loc_name = loc.name
                except Location.DoesNotExist:
                    loc_name = str(loc_id)
                print(f"  STALE DELETED: {sku} @ {loc_name} ({count} batch{'es' if count>1 else ''})")
                deleted_stale += count

    print(f"\n{'='*60}")
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}SYNC COMPLETE")
    print(f"{'='*60}")
    print(f"  Batches written      : {written}")
    print(f"  Zero qty skipped     : {skipped_zero}")
    print(f"  Stale batches deleted: {deleted_stale}")
    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    {e}")
    else:
        print("\n  No errors.")


if __name__ == '__main__':
    main()
