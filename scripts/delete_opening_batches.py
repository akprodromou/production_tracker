"""
delete_opening_batches.py
-------------------------
One-time cleanup: deletes all OPENING- prefixed raw material and product batches.
These are legacy from the initial stock import and are superseded by ERP-SYNC batches.

Run with --dry-run first to see what will be deleted.

Run from project root:
    python scripts/delete_opening_batches.py [--dry-run]

Against Railway:
    $env:DATABASE_URL="postgresql://postgres:GSUajhGKPuJMLpItMmZbduFbjMVWAeNE@hayabusa.proxy.rlwy.net:55480/railway"
    python scripts/delete_opening_batches.py --dry-run
    python scripts/delete_opening_batches.py
    $env:DATABASE_URL=""
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from inventory.models import RawMaterialBatch, ProductBatch

DRY_RUN = '--dry-run' in sys.argv

print(f"{'[DRY RUN] ' if DRY_RUN else ''}Scanning for OPENING- batches...\n")

raw_qs = RawMaterialBatch.objects.filter(lot_number__startswith='OPENING-').select_related('material', 'location')
fin_qs = ProductBatch.objects.filter(batch_number__startswith='OPENING-').select_related('material', 'location')

print(f"Raw material batches: {raw_qs.count()}")
for b in raw_qs:
    print(f"  {b.lot_number} | {b.material.sku} | {b.location.name} | qty={b.total_quantity}")

print(f"\nProduct batches: {fin_qs.count()}")
for b in fin_qs:
    print(f"  {b.batch_number} | {b.material.sku} | {b.location.name} | qty={b.quantity_produced}")

total = raw_qs.count() + fin_qs.count()
print(f"\nTotal to delete: {total}")

if not DRY_RUN and total > 0:
    raw_qs.delete()
    fin_qs.delete()
    print(f"\nDeleted {total} OPENING- batches.")
elif DRY_RUN:
    print("\nDry run — nothing deleted.")
else:
    print("\nNothing to delete.")
