"""
import_suppliers.py
--------------------
Reads the ERP suppliers xlsx and imports into the Supplier model.
Imports: code (Κωδικός), tin (ΑΦΜ), name (Όνομα), payment_terms (Όνομα - Τρόπος Πληρωμής).
All other fields (contacts, address, notes) remain blank for manual entry later.

Run from project root:
    python scripts/import_suppliers.py suppliers_list.xlsx [--dry-run]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

import pandas as pd
from inventory.models import Supplier

DRY_RUN = '--dry-run' in sys.argv


def clean(val):
    if val is None:
        return ''
    s = str(val).strip()
    return '' if s == 'nan' else s


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith('--'):
        print("Usage: python scripts/import_suppliers.py <suppliers.xlsx> [--dry-run]")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Reading: {filepath}\n")

    df = pd.read_excel(filepath, dtype=str)
    print(f"Found {len(df)} rows\n")

    created = updated = skipped = 0

    for i, row in df.iterrows():
        code         = clean(row.get('Κωδικός'))
        name         = clean(row.get('Όνομα'))
        tin          = clean(row.get('ΑΦΜ'))
        payment_terms = clean(row.get('Όνομα - Τρόπος Πληρωμής'))

        if not name:
            print(f"  Row {i+2}: missing name — skipped")
            skipped += 1
            continue

        if DRY_RUN:
            print(f"  DRY RUN | {code:<25} | {tin:<15} | {payment_terms:<30} | {name}")
            continue

        defaults = {
            'name':          name,
            'tin':           tin,
            'payment_terms': payment_terms,
        }

        if code:
            obj, was_created = Supplier.objects.update_or_create(
                code=code,
                defaults=defaults
            )
        else:
            # No code — match by name
            obj, was_created = Supplier.objects.update_or_create(
                name=name,
                defaults={**defaults, 'code': None}
            )

        if was_created:
            created += 1
            print(f"  CREATED: {code or '(no code)'} | {name}")
        else:
            updated += 1
            print(f"  UPDATED: {code or '(no code)'} | {name}")

    if DRY_RUN:
        print(f"\nDry run complete — no changes made.")
    else:
        print(f"\n{'='*60}")
        print(f"IMPORT COMPLETE")
        print(f"{'='*60}")
        print(f"  Created : {created}")
        print(f"  Updated : {updated}")
        print(f"  Skipped : {skipped}")


if __name__ == '__main__':
    main()
