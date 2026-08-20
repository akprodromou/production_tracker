"""
update_material_names.py
------------------------
Updates material names in the database to match ERP names from the
inventory xlsx file (same format as used by sync_erp_inventory.py).

Run from project root:
    python update_material_names.py inventory-2026-08-20.xlsx [--dry-run]

To run against Railway:
    $env:DATABASE_URL="postgresql://postgres:GSUajhGKPuJMLpItMmZbduFbjMVWAeNE@hayabusa.proxy.rlwy.net:55480/railway"
    python update_material_names.py inventory-2026-08-20.xlsx
    $env:DATABASE_URL=""
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

import openpyxl
from inventory.models import Material

DRY_RUN = '--dry-run' in sys.argv

LOCATION_CODES = {'000001','000002','000005','000006','000007','000009','000013','000014'}


def parse_inventory(filepath):
    """Parse inventory xlsx — same format as sync_erp_inventory.py.
    Returns dict: {sku: erp_name}
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    names = {}
    current_location = None

    for row in ws.iter_rows(values_only=True):
        values = [str(v).strip() if v is not None else '' for v in row]
        non_empty = [v for v in values if v]
        if not non_empty:
            continue
        first = non_empty[0]

        # Location header row
        if len(first) == 6 and first.isdigit():
            current_location = first
            continue

        # Material row
        if current_location and current_location in LOCATION_CODES and '-' in first and len(first) >= 8:
            sku  = first
            name = non_empty[1] if len(non_empty) > 1 else ''
            if name and sku not in names:  # keep first occurrence
                names[sku] = name

    wb.close()
    return names


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('--'):
        print("Usage: python update_material_names.py <inventory.xlsx> [--dry-run]")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Reading: {filepath}\n")
    erp_names = parse_inventory(filepath)
    print(f"Found {len(erp_names)} SKUs in ERP file\n")

    updated = skipped_same = not_found = 0

    for sku, erp_name in sorted(erp_names.items()):
        try:
            mat = Material.objects.get(sku=sku)
        except Material.DoesNotExist:
            not_found += 1
            continue

        if mat.name == erp_name:
            skipped_same += 1
            continue

        print(f"  {'DRY RUN | ' if DRY_RUN else ''}UPDATE: {sku}")
        print(f"    OLD: {mat.name}")
        print(f"    NEW: {erp_name}")

        if not DRY_RUN:
            mat.name = erp_name
            mat.save(update_fields=['name'])
        updated += 1

    print(f"\n{'='*60}")
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}COMPLETE")
    print(f"{'='*60}")
    print(f"  Updated      : {updated}")
    print(f"  Already same : {skipped_same}")
    print(f"  Not in DB    : {not_found}")


if __name__ == '__main__':
    main()
