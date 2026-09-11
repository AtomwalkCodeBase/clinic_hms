import os
import sys
import threading

from django.apps import AppConfig

# Management commands that never serve an upload — no point warming the OCR
# model in them. The batch daemon warms it explicitly itself.
_OFFLINE_COMMANDS = {
    "migrate", "makemigrations", "collectstatic", "test", "shell", "dbshell",
    "dumpdata", "loaddata", "createsuperuser", "check", "showmigrations",
    "process_document_batches", "backfill_document_classification",
    "backfill_documents_from_records",
}


class PatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.patients"

    def ready(self):
        import apps.patients.signals  # noqa: F401 — registers signal handlers
        self._warm_ocr()

    def _warm_ocr(self):
        """Build the OCR model in a background thread at web-worker start so a
        patient's first single upload doesn't pay the cold-start latency.
        Skipped in offline management commands; fully best-effort."""
        argv1 = sys.argv[1] if len(sys.argv) > 1 else ""
        if argv1 in _OFFLINE_COMMANDS:
            return
        # runserver's autoreload starts ready() twice — only warm in the child
        if argv1 == "runserver" and os.environ.get("RUN_MAIN") != "true":
            return

        def _go():
            try:
                from core import ocr
                ocr.warmup()
            except Exception:
                pass

        threading.Thread(target=_go, name="ocr-warmup", daemon=True).start()
