"""
One-off backfill of existing documents (oldest first).

  python manage.py peds_backfill [--limit 500] [--sync]
"""
from django.core.management.base import BaseCommand

from apps.documents.tasks import backfill_task


class Command(BaseCommand):
    help = "Extract pediatric timeline data from existing patient documents"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)
        parser.add_argument("--sync", action="store_true", help="run inline instead of Celery")

    def handle(self, *args, **o):
        if o["sync"]:
            backfill_task(limit=o["limit"])
            self.stdout.write("Backfill queued inline")
        else:
            r = backfill_task.delay(limit=o["limit"])
            self.stdout.write(f"Queued backfill task {r.pk}")
