# Deployment Guide — YAF Procurement Tracking

## How it works

- **Code** lives in GitHub. Every `git push` triggers a Railway redeploy automatically.
- **Data** lives in Railway's Postgres database. It is never touched by a `git push`.
- **Local development** uses a separate SQLite database for testing only.

---

## Deploying code changes (the only thing you need to do regularly)

```powershell
git add .
git commit -m "description of changes"
git push origin main
```

That's it. Railway redeploys within ~2 minutes. Your Railway data is safe.

---

## Syncing ERP data to Railway

ERP sync scripts (`sync_erp_inventory.py`, `import_suppliers.py`, `import_clients.py`,
`import_production_templates.py`) use `update_or_create` — they never delete existing
records, only create new ones or update matching ones.

Run them locally but pointed at Railway's Postgres using the public connection string:

```powershell
$env:DATABASE_URL="postgresql://postgres:GSUajhGKPuJMLpItMmZbduFbjMVWAeNE@hayabusa.proxy.rlwy.net:55480/railway"

python scripts/sync_erp_inventory.py Inventory-YYYY-MM-DD.xlsx
python manage.py import_clients clients-YYYY-MM-DD.csv
python scripts/import_suppliers.py suppliers_list.xlsx
python scripts/import_production_templates.py production_run_templates_database.xlsx

$env:DATABASE_URL=""
```

The `$env:DATABASE_URL=""` at the end restores local SQLite for normal development.

---

## Adding new Python packages

```powershell
pip install <package>
pip freeze > requirements.txt
git add requirements.txt
git commit -m "deps: add <package>"
git push origin main
```

---

## Entering data

Enter all real data directly on Railway:
**https://productiontracker-production-bc0e.up.railway.app**

Use your local app only for testing and development.

---

## ⚠️ NEVER run these on Railway unless you want to wipe all data

```bash
python manage.py flush
python manage.py loaddata data_export.json
```

These commands **delete and replace** all Railway data with your local snapshot.
Only use them if Railway's database is blank and you need to seed it from scratch.

---

## Railway Start Command

Already configured — do not change:

```
python manage.py collectstatic --no-input && python manage.py migrate && gunicorn core.wsgi --bind 0.0.0.0:$PORT
```

---

## Railway URLs

- **App:** https://productiontracker-production-bc0e.up.railway.app
- **Console:** https://railway.com/project/d8f1fdab-6dcf-447e-9aac-aaf59943e31b/service/af0bab84-f5dc-4d18-ab0f-928fb4f008ad/console
- **Postgres public host:** hayabusa.proxy.rlwy.net:55480
