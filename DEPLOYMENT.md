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
and static files automatically — **the database is never touched by a git push**.

---

## ⚠️ WARNING — loaddata overwrites Railway data

**`python manage.py loaddata data_export.json` replaces any Railway record
that shares a primary key with your local snapshot.**

- Data entered directly on Railway **will be overwritten** if you run `loaddata`
- Railway's free/hobby tier has **no automatic backups** — overwritten data is gone
- Only run `loaddata` when you deliberately want Railway to mirror your local database

**When NOT to run loaddata:**
- You have entered data directly on Railway that you want to keep
- You are only deploying code changes (git push handles this automatically)

**When it IS safe to run loaddata:**
- First-time setup / initial data seed
- You have entered all data locally and Railway has nothing you want to keep
- You have explicitly decided to overwrite Railway with your local snapshot

---

## Syncing local data to Railway (use with caution)

Open the Railway console:
https://railway.com/project/d8f1fdab-6dcf-447e-9aac-aaf59943e31b/service/af0bab84-f5dc-4d18-ab0f-928fb4f008ad/console

**Option A — Merge (safer):**
```bash
python manage.py loaddata data_export.json
```
- Records with the same primary key → **overwritten** with local values
- Records that exist locally but not online → inserted
- Records that exist online but not locally → left untouched
- Still overwrites matching records — see warning above

**Option B — Full replace (destructive):**
```bash
python manage.py flush --no-input
python manage.py loaddata data_export.json
```
- Wipes **ALL** Railway data first, then loads local snapshot
- Use only when Railway should be an exact mirror of local with no exceptions

---

## Recommended workflow going forward

**Code changes only (most common case):**
```powershell
git add .
git commit -m "description"
git push origin main
```
→ Railway redeploys, database untouched. ✅

**Data entry:** do it directly on Railway to avoid sync conflicts.

**Local development:** use local SQLite freely. Only sync to Railway when needed.

---

## If you added new Python packages

```powershell
pip freeze > requirements.txt
git add requirements.txt
git commit -m "deps: update requirements"
git push origin main
```

---

## Railway Start Command

Already configured — do not change unless instructed:

```
python manage.py collectstatic --no-input && python manage.py migrate && gunicorn core.wsgi --bind 0.0.0.0:$PORT
```

Runs on every deploy: static files, schema migrations, web server start.
Never wipes data.

---

## Railway URLs

- **App:** https://productiontracker-production-bc0e.up.railway.app
- **Console:** https://railway.com/project/d8f1fdab-6dcf-447e-9aac-aaf59943e31b/service/af0bab84-f5dc-4d18-ab0f-928fb4f008ad/console
