import csv
import os
import django
from decimal import Decimal, InvalidOperation

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from inventory.models import Material, Location, RawMaterialBatch, ProductBatch, MaterialTransaction

CSV_FILE = 'stock_inventory_001_-_Sheet.csv'

CATEGORY_MAP = {
    'raw material': 'RAW',
    'packaging':    'PKG',
    'finished product': 'FIN',
    '': 'RAW',  # default for empty category
}

def run(dry_run=False):
    created_raw  = 0
    created_fin  = 0
    skipped      = 0
    errors       = []

    # Track seen (sku, location_id) pairs to deduplicate
    seen = set()

    with open(CSV_FILE, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        print(f"Columns: {reader.fieldnames}\n")

        for i, row in enumerate(reader, start=2):
            row = {k.strip(): v.strip() if v else '' for k, v in row.items() if k}

            location_id  = row.get('Location ID', '').strip()
            location_name= row.get('Location Name', '').strip()
            sku          = row.get('SKU', '').strip()
            qty_str      = row.get('Quantity', '').strip()
            category_raw = row.get('Material Category', '').strip().lower()

            # Skip empty rows
            if not sku or not qty_str:
                skipped += 1
                continue

            # Parse quantity
            try:
                qty = Decimal(qty_str)
            except InvalidOperation:
                print(f"  Row {i}: invalid quantity '{qty_str}' for {sku} — skipped")
                skipped += 1
                continue

            # Skip negative quantities (ERP corrections)
            if qty <= 0:
                print(f"  Row {i}: skipping {sku} — quantity {qty} <= 0")
                skipped += 1
                continue

            # Deduplicate — keep first occurrence of (sku, location_id)
            key = (sku, location_id)
            if key in seen:
                print(f"  Row {i}: duplicate {sku} @ location {location_id} — skipped")
                skipped += 1
                continue
            seen.add(key)

            # Resolve category
            category = CATEGORY_MAP.get(category_raw, 'RAW')

            # Resolve location
            try:
                location = Location.objects.get(pk=int(location_id))
            except (Location.DoesNotExist, ValueError):
                msg = f"  Row {i}: location ID {location_id} not found — skipped {sku}"
                print(msg)
                errors.append(msg)
                skipped += 1
                continue

            # Resolve material
            try:
                material = Material.objects.get(sku=sku)
            except Material.DoesNotExist:
                msg = f"  Row {i}: SKU {sku} not found in materials — skipped"
                print(msg)
                errors.append(msg)
                skipped += 1
                continue

            lot_or_batch = f"OPENING-{sku}-{location_id}"

            if dry_run:
                print(f"  DRY RUN | {category:<4} | {sku:<15} | {qty:>10} | "
                      f"{location_name:<25} | ref: {lot_or_batch}")
                continue

            if category == 'FIN':
                # Create ProductBatch — skip if batch_number already exists
                if ProductBatch.objects.filter(batch_number=lot_or_batch).exists():
                    print(f"  SKIP (exists): {lot_or_batch}")
                    skipped += 1
                    continue
                ProductBatch.objects.create(
                    material         = material,
                    batch_number     = lot_or_batch,
                    quantity_produced= qty,
                    location         = location,
                )
                created_fin += 1
                print(f"  FIN BATCH: {lot_or_batch} | {material.name} | {qty}")

            else:
                # Raw or PKG — create RawMaterialBatch + PRODUCED transaction
                # Skip if lot already exists for this material
                if RawMaterialBatch.objects.filter(
                    lot_number=lot_or_batch, material=material
                ).exists():
                    print(f"  SKIP (exists): {lot_or_batch}")
                    skipped += 1
                    continue
                batch = RawMaterialBatch.objects.create(
                    material      = material,
                    lot_number    = lot_or_batch,
                    total_quantity= qty,
                    location      = location,
                )
                # Create PRODUCED transaction so stock appears in the ledger
                MaterialTransaction.objects.create(
                    raw_material_batch = batch,
                    transaction_type   = 'PRODUCED',
                    quantity           = qty,
                    reference          = 'Opening stock import',
                )
                created_raw += 1
                print(f"  RAW BATCH: {lot_or_batch} | {material.name} | {qty}")

    print(f"\n{'DRY RUN — nothing saved' if dry_run else 'Import complete'}")
    print(f"  Raw/PKG batches created : {created_raw}")
    print(f"  Product batches created : {created_fin}")
    print(f"  Skipped                 : {skipped}")
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors:
            print(f"    {e}")


if __name__ == '__main__':
    import sys
    dry = '--dry-run' in sys.argv
    if dry:
        print("=== DRY RUN — nothing will be saved ===\n")
    run(dry_run=dry)
