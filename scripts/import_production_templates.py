"""
import_production_templates.py
-------------------------------
Run from project root:
    python scripts/import_production_templates.py production_run_templates_database.xlsx [--dry-run]
    python scripts/import_production_templates.py production_run_templates_database.xlsx

use file from Pylon as exported in xlsx:
Αποθήκη / Αναφορές / Εκτυπώσεις / Σύνθεση / Προδιαγραφές Σετ Κιτ

Reads the ERP "Set Kit Specifications" (Προδιαγραφές Σετ Κίτ) export and
creates/updates ProductionTemplate + ProductionTemplateComponent records
in the database. These act as ready-made "recipes": given a finished
product SKU, the template tells you which raw materials (and in what
ratio) are required to produce one unit.

File format (one block per finished product):
    <SKU>                                    <empty> <empty> <Product Name>
    <empty row>
    <empty>  Κωδικός          <empty> <empty> Όνομα
    <empty row>
    <empty>  <SKU>            <empty> <empty> <Product Name>
    <empty row>
    <empty>  <empty> Είδος - Όνομα <empty> <empty> Προδιαγραφή Σετ Κίτ - Όνομα ... Ποσ. Σετ : Ποσ. Υλικών (col 16)
    <empty row>
    <empty>  <empty> <Material Name>        <empty> <empty> <Product Name> ... <ratio> (col 16)
    <empty row>
    ... (repeat per component) ...
    <empty rows> -> next product block

Behaviour:
  - Finished product is matched to inventory.Material by SKU (column 0 of the block header row).
  - Each component is matched to inventory.Material by exact name match
    (column 2 of the component row), case-insensitive, trimmed.
  - If a template for that finished product already exists, its components
    are replaced with what's in the file (so re-running keeps things in sync).
  - Unmatched component names or unmatched finished-product SKUs are
    reported at the end, nothing is silently dropped.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django
import pandas as pd
import re
from decimal import Decimal, InvalidOperation

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from inventory.models import Material, ProductionTemplate, ProductionTemplateComponent

DRY_RUN = '--dry-run' in sys.argv
SKU_RE = re.compile(r'^\d{2}-\d+$')


def clean(v):
    s = str(v).strip()
    return '' if s == 'nan' else s


def parse_file(filepath):
    """
    Returns a list of blocks:
        {'sku': str, 'product_name': str, 'components': [{'name': str, 'ratio': Decimal}]}
    """
    df = pd.read_excel(filepath, header=None, dtype=str)

    blocks = []
    current = None

    for i, row in df.iterrows():
        c0  = clean(row[0])
        c2  = clean(row[2]) if len(row) > 2 else ''
        c5  = clean(row[5]) if len(row) > 5 else ''
        c16 = clean(row[16]) if len(row) > 16 else ''

        # New product block starts whenever column 0 looks like a SKU
        if SKU_RE.match(c0):
            if current:
                blocks.append(current)
            product_name = clean(row[3]) if len(row) > 3 else ''
            current = {'sku': c0, 'product_name': product_name, 'components': []}
            continue

        # Component row: col2 = material name, col5 = product name (confirms scope),
        # col16 = ratio. Skip the literal header row "Είδος - Όνομα".
        if current and c2 and c2 != 'Είδος - Όνομα' and c5 and c16:
            try:
                ratio = Decimal(c16.replace(',', '.'))
            except InvalidOperation:
                continue
            current['components'].append({'name': c2, 'ratio': ratio})

    if current:
        blocks.append(current)

    return blocks


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('--'):
        print("Usage: python scripts/import_production_templates.py <file.xlsx> [--dry-run]")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Reading: {filepath}\n")
    blocks = parse_file(filepath)
    print(f"Found {len(blocks)} product templates in file\n")

    templates_created = 0
    templates_updated = 0
    components_written = 0
    unmatched_products  = []
    unmatched_materials = set()

    for block in blocks:
        sku = block['sku']
        try:
            product = Material.objects.get(sku=sku)
        except Material.DoesNotExist:
            unmatched_products.append((sku, block['product_name']))
            continue

        # Resolve each component name to a Material
        resolved_components = []
        for comp in block['components']:
            name = comp['name']
            try:
                material = Material.objects.get(name__iexact=name)
            except Material.DoesNotExist:
                unmatched_materials.add(name)
                continue
            except Material.MultipleObjectsReturned:
                material = Material.objects.filter(name__iexact=name).first()
            resolved_components.append({'material': material, 'ratio': comp['ratio']})

        if not resolved_components:
            continue

        if DRY_RUN:
            exists = ProductionTemplate.objects.filter(product=product).exists()
            print(f"  [DRY RUN] {'Would update' if exists else 'Would create'} template: "
                  f"{sku} | {product.name} | {len(resolved_components)} components")
            continue

        template, created = ProductionTemplate.objects.get_or_create(product=product)
        if created:
            templates_created += 1
        else:
            templates_updated += 1
            # Replace existing components with what's in the file
            template.components.all().delete()

        for rc in resolved_components:
            ProductionTemplateComponent.objects.create(
                template=template,
                material=rc['material'],
                ratio=rc['ratio'],
            )
            components_written += 1

        print(f"  {'Created' if created else 'Updated'}: {sku} | {product.name} "
              f"| {len(resolved_components)} components")

    print(f"\n{'='*60}")
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}IMPORT COMPLETE")
    print(f"{'='*60}")
    print(f"  Templates created       : {templates_created}")
    print(f"  Templates updated       : {templates_updated}")
    print(f"  Components written      : {components_written}")

    if unmatched_products:
        print(f"\n⚠ Finished products not found in Material table ({len(unmatched_products)}):")
        for sku, name in unmatched_products:
            print(f"    {sku}  {name}")

    if unmatched_materials:
        print(f"\n⚠ Component material names not found in Material table ({len(unmatched_materials)}):")
        for name in sorted(unmatched_materials):
            print(f"    {name}")

    if not unmatched_products and not unmatched_materials:
        print("\n  No unmatched items.")


if __name__ == '__main__':
    main()
