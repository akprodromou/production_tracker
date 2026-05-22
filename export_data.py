@"
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from django.core.management import call_command
with open('data_export.json', 'w', encoding='utf-8') as f:
    call_command('dumpdata', '--natural-foreign', '--natural-primary', '--exclude', 'contenttypes', '--exclude', 'auth.permission', '--indent', '2', stdout=f)
print('Done')
"@ | Out-File -FilePath export_data.py -Encoding utf8
python export_data.py
del export_data.py