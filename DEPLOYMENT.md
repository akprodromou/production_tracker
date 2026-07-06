# Deployment Guide — YAF Procurement Tracking

## Standard Deployment (every time you make local changes)

### Step 1 — Export data and push to GitHub (local machine)

```powershell
python export_data.py
git add .
git commit -m "your description of changes"
git push origin main
```

Railway auto-deploys within ~2 minutes. The start command handles migrations
and static files automatically — no extra steps needed.

---

### Step 2 — Sync local data to Railway (optional)

Open the Railway console:
https://railway.com/project/d8f1fdab-6dcf-447e-9aac-aaf59943e31b/service/af0bab84-f5dc-4d18-ab0f-928fb4f008ad/console

**Option A — Merge (recommended):**
```bash
python manage.py loaddata data_export.json
```
- Records with the same primary key → updated with local values
- Records that exist locally but not online → inserted
- Records that exist online but not locally → left untouched
- Safe to use if data has been entered directly on Railway that you want to keep

**Option B — Full replace (use with caution):**
```bash
python manage.py flush --no-input
python manage.py loaddata data_export.json
```
- Wipes ALL Railway data first, then loads your local snapshot
- Use only when you want Railway to be an exact mirror of local with no exceptions

---

### Step 3 — If you added new Python packages

```powershell
pip freeze > requirements.txt
git add requirements.txt
git commit -m "deps: update requirements"
git push origin main
```

Railway reinstalls all packages automatically on the next deploy.

---

## Railway Start Command

No changes needed — already configured in Railway settings:

```
python manage.py collectstatic --no-input && python manage.py migrate && gunicorn core.wsgi --bind 0.0.0.0:$PORT
```

This runs on every deploy and handles:
- Static files (favicon, CSS, JS)
- Database migrations
- Starting the web server

---

## Quick Reference — The 90% Case

```powershell
# Local machine
python export_data.py
git add .
git commit -m "description"
git push origin main
```

Then in Railway console if needed:
```bash
python manage.py loaddata data_export.json
```

---

## Railway URLs

- **App:** https://productiontracker-production-bc0e.up.railway.app
- **Console:** https://railway.com/project/d8f1fdab-6dcf-447e-9aac-aaf59943e31b/service/af0bab84-f5dc-4d18-ab0f-928fb4f008ad/console
