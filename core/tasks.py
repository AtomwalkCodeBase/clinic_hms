"""
Celery tasks. Discovered by atomwalk/celery.py (autodiscover on "core").

TASK_CATALOG is what platform admin → Background Jobs offers when creating a
scheduled job or running one by hand: a label, a description, the kwargs it
takes (with defaults) and whether it runs per hospital. A hospital-scoped
job gets `tenant_db` in its kwargs — the jobs screen prefixes the job name
with that database key ("aw_sunrise_clinic: Daily reminders") so the
tenancy is visible at a glance, and the task points itself at that DB.
"""

from celery import shared_task
from django.core.management import call_command

TASK_CATALOG = {
    "core.process_document": {
        "label": "Process one uploaded document",
        "description": "Extract text, classify and file one My Reports upload. Queued automatically on upload.",
        "kwargs": {"doc_id": None},
        "tenant_aware": False,
        "schedulable": False,
    },
    "core.process_pending_documents": {
        "label": "Retry stuck document uploads",
        "description": "Processes uploads still queued/in progress after `stale` seconds; `retry_failed` also retries failed ones.",
        "kwargs": {"stale": 300, "retry_failed": False},
        "tenant_aware": False,
        "schedulable": True,
    },
    "core.extract_lab_values": {
        "label": "Extract lab values",
        "description": "Reads test values out of filed lab reports for Health Insights.",
        "kwargs": {"limit": 50},
        "tenant_aware": False,
        "schedulable": True,
    },
    "core.process_document_batches": {
        "label": "Drain folder uploads",
        "description": "Files documents from the direct-to-S3 folder/batch upload flow.",
        "kwargs": {"limit": 0},
        "tenant_aware": False,
        "schedulable": True,
    },
    "apps.registry.tasks.process_bulk_extractions": {
        "label": "Process mobile bulk uploads",
        "description": "Reads the oldest queued files of the patient app's bulk uploads and hands each text to My Reports, at most 'bulk_batch_limit' files per run.",
        "kwargs": {"limit": None, "budget_seconds": 240},
        "tenant_aware": False,
        "schedulable": True,
    },
    "apps.registry.tasks.periodic_reconcile": {
        "label": "Recover mobile uploads",
        "description": "Closes stalled or abandoned mobile bulk uploads and fails files stuck in processing.",
        "kwargs": {},
        "tenant_aware": False,
        "schedulable": True,
    },
    "core.generate_reminders": {
        "label": "Appointment & follow-up reminders",
        "description": "In-app reminders. All hospitals, or one hospital when scoped.",
        "kwargs": {},
        "tenant_aware": True,
        "schedulable": True,
    },
    "core.process_bulk_documents": {
        "label": "Process bulk uploads",
        "description": "Sorts uploads bigger than the instant threshold, a batch per run (oldest first).",
        "kwargs": {},
        "tenant_aware": False,
        "schedulable": True,
    },
    "core.llm_drain": {
        "label": "Run the AI queue",
        "description": "Sends queued documents to the LLM (local or GPU server) one at a time; waits while the server is down.",
        "kwargs": {},
        "tenant_aware": False,
        "schedulable": True,
    },
    "celery.backend_cleanup": {
        "label": "Clean up old task history",
        "description": "Deletes task-history rows older than 14 days.",
        "kwargs": {},
        "tenant_aware": False,
        "schedulable": True,
    },
}


def _command(name, *args, **opts):
    """Run a management command and hand its output back as the task result."""
    import io
    out = io.StringIO()
    call_command(name, *args, stdout=out, stderr=out, **opts)
    return out.getvalue()[-4000:]


@shared_task(name="core.process_document", ignore_result=True)
def process_document_task(doc_id: int) -> None:
    from core.pipeline.processing import process_document
    process_document(doc_id)


@shared_task(name="core.process_bulk_documents", soft_time_limit=290, time_limit=300)
def process_bulk_documents_task(limit=None, budget_seconds=240):
    """Big uploads: sort the next batch (see core.pipeline.routing.process_bulk)."""
    from core.pipeline.routing import process_bulk
    return process_bulk(limit=limit, budget_seconds=budget_seconds)


@shared_task(name="core.process_pending_documents")
def process_pending_documents_task(stale: int = 300, retry_failed: bool = False, limit: int = 200):
    return _command("process_pending_documents", stale=stale, retry_failed=retry_failed, limit=limit)


@shared_task(name="core.extract_lab_values")
def extract_lab_values_task(limit: int = 50):
    return _command("extract_lab_values", limit=limit)


@shared_task(name="core.process_document_batches")
def process_document_batches_task(limit: int = 0):
    return _command("process_document_batches", limit=limit)


@shared_task(name="core.generate_reminders")
def generate_reminders_task(tenant_db: str = ""):
    opts = {"db_name": tenant_db} if tenant_db else {}
    return _command("generate_reminders", **opts)


# ── LLM queue ("llm" — see CELERY_TASK_ROUTES) ───────────────────────────
# Consumed by a single-concurrency worker, so LLM calls go one at a time.

@shared_task(name="core.llm_drain", ignore_result=True, soft_time_limit=600, time_limit=660)
def llm_drain_task():
    """Classify the next queued document with the LLM, then queue itself for
    the one after. Stops when the queue is empty or the server is down —
    Beat's "Run the AI queue" job restarts it every minute."""
    from core.pipeline.llm_queue import drain_llm_queue, kick_llm_queue
    result = drain_llm_queue()
    if result == "done":
        kick_llm_queue()
    return result


@shared_task(name="core.llm_ask", bind=True, max_retries=None, soft_time_limit=600, time_limit=660)
def llm_ask_task(self, system_prompt, user_prompt, temperature=0.3, max_tokens=4096):
    """Any other question for the LLM. Waits (retries every minute) while the
    server is unreachable, then answers; the reply is in the task result:
    {content, prompt_tokens, completion_tokens, generation_time}."""
    from core import llm_client
    try:
        return llm_client.complete(system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens)
    except llm_client.LLMUnavailable as exc:
        raise self.retry(exc=exc, countdown=60)
