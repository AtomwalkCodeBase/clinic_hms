"""
process_pending_documents
-------------------------
Safety net for the background document pipeline (core/pipeline): runs
every My Reports upload still sitting in queued / extracting / classifying
(older than --stale seconds, i.e. its worker died or was never running) or
failed (with --retry-failed), in this process.

    python manage.py process_pending_documents
    python manage.py process_pending_documents --retry-failed --stale 0
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone


class Command(BaseCommand):
    help = "Process My Reports uploads stuck in the background pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--stale", type=int, default=300,
                            help="Only rows queued/started more than this many seconds ago (default 300).")
        parser.add_argument("--retry-failed", action="store_true", help="Also retry rows that failed.")
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **opts):
        from apps.registry.models import SharedDocument
        from core.pipeline.processing import IN_FLIGHT, process_document

        cutoff = timezone.now() - timedelta(seconds=max(0, opts["stale"]))
        states = IN_FLIGHT + (("failed",) if opts["retry_failed"] else ())
        ids = list(
            SharedDocument.objects.using("default")
            .filter(processing_status__in=states, deleted_at__isnull=True)
            # queued bulk uploads wait for "Process bulk uploads" on purpose
            .exclude(processing_route="bulk", processing_status="queued")
            .filter(Q(processing_started_at__isnull=True, created_at__lt=cutoff)
                    | Q(processing_started_at__lt=cutoff))
            .order_by("created_at").values_list("id", flat=True)[: opts["limit"]]
        )
        for i, doc_id in enumerate(ids, 1):
            process_document(doc_id)
            self.stdout.write(f"[{i}/{len(ids)}] doc {doc_id} processed")
        self.stdout.write(f"done — {len(ids)} document(s)")
