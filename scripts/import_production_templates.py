"""
import_production_templates.py
-------------------------------

Export from Pylon EPR:
    Αποθήκη / Αναφορές / Εκτυπώσεις / Σύνθεση / Προδιαγραφές Σετ Κιτ
    Μπάντες / Υλικά / Είδος - Κωδικός > Ορατό: Ναι
    Εκτέλεση ως: Grid
    Εξαγωγές / Εξαγωγή σε Excel

To run against Railway, run from project root:
    $env:DATABASE_URL="postgresql://postgres:GSUajhGKPuJMLpItMmZbduFbjMVWAeNE@hayabusa.proxy.rlwy.net:55480/railway"
    python scripts/import_production_templates.py production_run_templates_database.xlsx
    $env:DATABASE_URL=""

Reads the ERP "Set Kit Specifications" (Προδιαγραφές Σετ Κίτ) export and
creates/updates ProductionTemplate + ProductionTemplateComponent records
in the database. These act as ready-made "recipes": given a finished
product SKU, the template tells you which raw materials (and in what
ratio) are required to produce one unit.

Behaviour:
  - Finished product is matched to inventory.Material by SKU (column 0 of the block header row).
  - Each component is matched to inventory.Material by exact name match
    (column 2 of the component row), case-insensitive, trimmed.
  - If a template for that finished product already exists, its components
    are replaced with what's in the file (so re-running keeps things in sync).
  - Unmatched component names or unmatched finished-product SKUs are
    reported at the end, nothing is silently dropped.
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

import openpyxl
from decimal import Decimal, InvalidOperation
from inventory.models import Material, ProductionTemplate, ProductionTemplateComponent

DRY_RUN = '--dry-run' in sys.argv


def parse_xlsx(filepath):
    """
    Parse the ERP set-kit xlsx.
    Structure:
      - Row with col0 = finished product SKU (6-digit starts row group)
      - Component rows: col2=name, col15=ratio, col21=component SKU
    Returns list of dicts: {sku, product_name, components: [{sku, ratio}]}
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    templates = []
    current = None

    for row in ws.iter_rows(values_only=True):
        col0  = str(row[0]).strip()  if row[0]  else ''
        col2  = str(row[2]).strip()  if len(row) > 2  and row[2]  else ''
        col3  = str(row[3]).strip()  if len(row) > 3  and row[3]  else ''
        col15 = row[15] if len(row) > 15 else None
        col21 = str(row[21]).strip() if len(row) > 21 and row[21] else ''

        # New finished product header row
        if col0 and '-' in col0 and col3:
            if current:
                templates.append(current)
            current = {'sku': col0, 'product_name': col3, 'components': []}
            continue

        # Component row: has a component SKU in col21 and ratio in col15
        if current and col21 and '-' in col21 and col15 is not None:
            try:
                ratio = Decimal(str(col15))
            except InvalidOperation:
                continue
            if ratio > 0:
                current['components'].append({'sku': col21, 'ratio': ratio})

    if current:
        templates.append(current)

    wb.close()
    return templates


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('--'):
        print("Usage: python scripts/import_production_templates.py <file.xlsx> [--dry-run]")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Reading: {filepath}\n")
    templates = parse_xlsx(filepath)
    print(f"Found {len(templates)} product templates in file\n")

    templates_created  = 0
    templates_updated  = 0
    components_written = 0
    skipped_no_product = []
    skipped_no_component = []

    for block in templates:
        sku          = block['sku']
        product_name = block['product_name']
        components   = block['components']

        try:
            product = Material.objects.get(sku=sku)
        except Material.DoesNotExist:
            skipped_no_product.append(f"{sku}  {product_name}")
            continue

        # Resolve components by SKU
        resolved = []
        for comp in components:
            try:
                mat = Material.objects.get(sku=comp['sku'])
                resolved.append((mat, comp['ratio']))
            except Material.DoesNotExist:
                skipped_no_component.append(f"{comp['sku']} (component of {sku})")

        if not resolved:
            skipped_no_product.append(f"{sku}  {product_name} — no components resolved")
            continue

        if DRY_RUN:
            exists = ProductionTemplate.objects.filter(product=product).exists()
            print(f"  {'Would update' if exists else 'Would create'}: {sku} | {product.name} | {len(resolved)} components")
            continue

        template, created = ProductionTemplate.objects.get_or_create(product=product)
        if created:
            templates_created += 1
        else:
            templates_updated += 1
            template.components.all().delete()

        for mat, ratio in resolved:
            ProductionTemplateComponent.objects.create(
                template=template,
                material=mat,
                ratio=ratio,
            )
            components_written += 1

        print(f"  {'Created' if created else 'Updated'}: {sku} | {product.name} | {len(resolved)} components")

    print(f"\n{'='*60}")
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}IMPORT COMPLETE")
    print(f"{'='*60}")
    print(f"  Templates created  : {templates_created}")
    print(f"  Templates updated  : {templates_updated}")
    print(f"  Components written : {components_written}")

    if skipped_no_product:
        print(f"\n  Finished products not found or no components ({len(skipped_no_product)}):")
        for s in skipped_no_product:
            print(f"    {s}")

    if skipped_no_component:
        print(f"\n  Component SKUs not found ({len(skipped_no_component)}):")
        for s in skipped_no_component[:20]:
            print(f"    {s}")
        if len(skipped_no_component) > 20:
            print(f"    ... and {len(skipped_no_component)-20} more")


if __name__ == '__main__':
    main()
