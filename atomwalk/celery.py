import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "atomwalk.settings.development")

app = Celery("atomwalk")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()          # finds apps/records/tasks.py
