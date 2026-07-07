import csv
from django.core.management.base import BaseCommand
from inventory.models import Client


class Command(BaseCommand):
    help = 'Import clients from a semicolon-delimited CSV'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        filepath = options['csv_file']
        dry_run  = options['dry_run']
        created = updated = skipped = 0

        with open(filepath, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=';')
            self.stdout.write(f'Columns detected: {reader.fieldnames}\n')

            for i, row in enumerate(reader, start=2):
                row = {
                    k.strip(): v.strip() if v else ''
                    for k, v in row.items() if k
                }

                code    = row.get('Code', '').strip()
                name    = row.get('Name', '').strip()
                tin     = row.get('TIN', '').strip()
                country = row.get('Country', '').strip()
                notes   = row.get('Notes', '').strip()

                if not name:
                    self.stdout.write(
                        self.style.WARNING(f'  Row {i}: missing Name — skipped: {row}')
                    )
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  DRY RUN | {code:<20} | {tin:<15} | {country:<30} | {name}'
                    )
                    continue

                obj, was_created = Client.objects.update_or_create(
                    code=code,
                    defaults={
                        'name':    name,
                        'tin':     tin,
                        'country': country,
                        'notes':   notes,
                    }
                )

                if was_created:
                    created += 1
                    self.stdout.write(f'  CREATED: {code} — {name}')
                else:
                    updated += 1
                    self.stdout.write(f'  UPDATED: {code} — {name}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run — nothing saved.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nDone — {created} created, {updated} updated, {skipped} skipped'
                )
            )