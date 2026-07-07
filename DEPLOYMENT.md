# Deployment Guide — YAF Procurement Tracking

## Setup: Point local machine at Railway's Postgres (one-time)

This makes local and Railway use the **same database** — changes anywhere
appear everywhere instantly.

### Step 1 — Install python-dotenv

```powershell
pip install python-dotenv
pip freeze > requirements.txt
```

### Step 2 — Get your DATABASE_URL from Railway

Railway dashboard → your **Postgres** service → **Variables** tab →
copy the value of `DATABASE_URL`. It looks like:
```
postgresql://postgres:xxxx@monorail.proxy.rlwy.net:xxxxx/railway
```

### Step 3 — Create a local .env file

In your project root, create a file called `.env` (no extension):
```
DATABASE_URL=postgresql://postgres:xxxx@monorail.proxy.rlwy.net:xxxxx/railway
```

⚠️ **Never commit `.env` to git.** Check that `.gitignore` contains `.env`.

### Step 4 — Verify .gitignore

```powershell
python setup_env_database.py
```

Then check `.gitignore` contains `.env` — if not, add it:
```powershell
echo ".env" >> .gitignore
```

### Step 5 — Test locally

```powershell
python manage.py runserver
```

Your local app now reads/writes Railway's Postgres directly.

---

## Daily workflow (once setup is complete)

### Deploy code changes

```powershell
git add .
git commit -m "description of changes"
git push origin main
```

Railway auto-deploys within ~2 minutes. Since both environments share the
same database, **no data sync is needed** — ever.

### Adding new Python packages

```powershell
pip install <package>
pip freeze > requirements.txt
git add requirements.txt
git commit -m "deps: add <package>"
git push origin main
```

---

## ⚠️ WARNING — loaddata overwrites Railway data

**Do NOT run `python manage.py loaddata` on Railway** unless you are
doing a full reset and don't mind losing all online data.

Once you are using the shared Postgres setup above, `data_export.json`
and `loaddata` are no longer part of your workflow.

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
- **Postgres Variables:** Railway dashboard → Postgres service → Variables tab
