# Deploy Backend To Render

This repo now includes a Render Blueprint at [`/render.yaml`](/Users/mac/Documents/AI AGENTS/CURSOR PROJ/figma_exporter/render.yaml).

## Option 1: One-click Blueprint (recommended)

1. Push this repo to GitHub.
2. In Render, go to `Blueprints` and connect the repo.
3. Render will create:
   - `itestified-backend` (Web Service)
   - `itestified-scheduled-publisher` (Cron Job)
   - `itestified-db` (Postgres)
4. Fill the `sync: false` env vars in Render dashboard:
   - `ADMIN_ENTRY_CODE`
   - `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
   - `DEFAULT_FROM_EMAIL`, `SUPPORT_EMAIL`
   - `GOOGLE_OAUTH_CLIENT_IDS`
   - Cloudinary keys/URL for server-side video uploads
   - Flutterwave keys/redirect URL (if donations are enabled)

## Option 2: Manual Service Setup

Use these values:

- Root directory: `backend`
- Build command:
  - `pip install -r requirements/production.txt`
  - `python manage.py collectstatic --noinput`
  - `python manage.py migrate --noinput`
- Start command:
  - `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 120`
- Cron command:
  - `python manage.py publish_scheduled_testimonies && python manage.py publish_due_scriptures && python manage.py publish_due_inspirational_pictures`
- Environment variable:
  - `DJANGO_SETTINGS_MODULE=config.settings.production`

## Required env vars

At minimum:

- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS` (include your Render domain)
- `DJANGO_CSRF_TRUSTED_ORIGINS` (full `https://...` origin)
- `DATABASE_URL` from the Render Postgres `connectionString`
  - alternatively: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`
- `ADMIN_ENTRY_CODE`
- `GOOGLE_OAUTH_CLIENT_IDS`
- `CLOUDINARY_URL` or `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET`

## Post-deploy checks

1. Open `https://<your-service>.onrender.com/api/v1/`
2. Open `https://<your-service>.onrender.com/admin/`
3. Test mobile login and `GET /api/v1/content/home-feed/`
4. Confirm the scheduled publisher cron job has run successfully at least once.

If `DisallowedHost` appears, add the exact domain to `DJANGO_ALLOWED_HOSTS` and redeploy.
