import csv
from django.core.management.base import BaseCommand
from inventory.models import Material, Unit


# Maps the Greek/English category names in your CSV to model codes
CATEGORY_MAP = {
    'raw material':   'RAW',
    'packaging':      'PKG',
    'finished product': 'FIN',
    'consumables':    'CON',
    'fixed costs':    'FXD',
    'raw':            'RAW',
    'pkg':            'PKG',
    'fin':            'FIN',
    'con':            'CON',
    'fxd':            'FXD',
    # Greek equivalents if they appear
    'πρώτη ύλη':      'RAW',
    'συσκευασία':     'PKG',
    'έτοιμο προϊόν':  'FIN',
    'αναλώσιμα':      'CON',
    'πάγια':          'FXD',
}


class Command(BaseCommand):
    help = 'Import materials from a semicolon-delimited CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Path to the CSV file')
        parser.add_argument(
            '--default-category', type=str, default='RAW',
            help='Fallback category code if CSV value not recognised (default: RAW)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview without writing to the database'
        )

    def handle(self, *args, **options):
        filepath         = options['csv_file']
        default_category = options['default_category'].upper()
        dry_run          = options['dry_run']

        created = updated = skipped = 0

        with open(filepath, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=';')
            self.stdout.write(f'Columns detected: {reader.fieldnames}\n')

            for i, row in enumerate(reader, start=2):  # start=2 accounts for header row
                # Clean all values — strip whitespace and trailing tabs/spaces
                row = {
                    k.strip(): v.strip() if v else ''
                    for k, v in row.items()
                    if k  # skip None keys from trailing delimiters
                }

                sku       = row.get('SKU', '').strip()
                name      = row.get('Name', '').strip()
                unit_name = row.get('Unit', 'pcs').strip() or 'pcs'
                cat_raw   = row.get('Category', '').strip().lower()

                # Resolve category
                category = CATEGORY_MAP.get(cat_raw, None)
                if not category:
                    self.stdout.write(
                        self.style.WARNING(
                            f'  Row {i}: unrecognised category "{cat_raw}" '
                            f'— using {default_category}'
                        )
                    )
                    category = default_category

                if not sku or not name:
                    self.stdout.write(
                        self.style.WARNING(f'  Row {i}: missing SKU or Name — skipped: {row}')
                    )
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  DRY RUN | {sku:<20} | {category} | '
                        f'{unit_name:<6} | {name}'
                    )
                    continue

                unit, _ = Unit.objects.get_or_create(name=unit_name)

                obj, was_created = Material.objects.update_or_create(
                    sku=sku,
                    defaults={
                        'name':     name,
                        'unit':     unit,
                        'category': category,
                    }
                )

                if was_created:
                    created += 1
                    self.stdout.write(f'  CREATED: {sku} — {name}')
                else:
                    updated += 1
                    self.stdout.write(f'  UPDATED: {sku} — {name}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run — nothing was saved.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nDone — {created} created, {updated} updated, {skipped} skipped'
                )
            )