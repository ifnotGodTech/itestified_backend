import os

from celery import Celery

# Matches manage.py's own default -- local dev needs no extra env var to run
# a worker; Render sets DJANGO_SETTINGS_MODULE explicitly per service, so
# setdefault never overrides it there.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("itestified")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
