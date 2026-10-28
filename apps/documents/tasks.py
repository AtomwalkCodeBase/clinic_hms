"""Celery tasks of the records pipeline: orchestration only — the work is in the services folder and processing.py."""
import logging

from celery import shared_task

from apps.documents.models import DocumentExtraction, MedicalDocument
from apps.documents import lib_documents as records
from apps.documents import lib_processing

logger = logging.getLogger(__name__)

# acks_late + reject_on_worker_lost: if a worker dies mid-task the message is redelivered instead of lost. Safe
_TASK_OPTS = dict(
    bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=300, retry_jitter=True,
    max_retries=3, acks_late=True, reject_on_worker_lost=True, ignore_result=True,
)


@shared_task(soft_time_limit=120, time_limit=180, **_TASK_OPTS)
def extract_document_task(self, document_id, queue=records.BULK_QUEUE):
    """File → content check → text, then queue classify_document_task on the same `queue` (so a single instant file"""
    try:
        ready = records.extract_document(document_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.exception("records: extracting %s failed for good", document_id)
            records.fail_document_by_id(document_id, f"Couldn't read this file: {exc}")
            return
        raise
    if ready:
        classify_document_task.apply_async(args=[document_id, queue], queue=queue)


@shared_task(soft_time_limit=60, time_limit=90, **_TASK_OPTS)
def classify_document_task(self, document_id, queue=records.BULK_QUEUE):
    """Rule engine → classification, status and batch counters. Its own task so extraction of the next document"""
    try:
        records.classify_document(document_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.exception("records: classifying %s failed for good", document_id)
            records.fail_document_by_id(document_id, f"Couldn't classify this file: {exc}")
            return
        raise
    process_document_task.apply_async(args=[document_id], queue=queue)


def _is_transient(exc):
    """The LLM api being unreachable or failing on its side is worth retrying; a refusal (401, 400 ...) is not."""
    name = type(exc).__name__
    if name == "HTTPError":
        return getattr(getattr(exc, "response", None), "status_code", 0) >= 500
    return name in ("ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout")


@shared_task(bind=True, max_retries=6, acks_late=True, ignore_result=True)
def process_document_task(self, document_id, queue=records.BULK_QUEUE, force=False):
    """The LLM and the rules on one document's text. It never fails the document, which is already finished: when the LLM"""
    document = MedicalDocument.objects.select_related("patient").filter(pk=document_id).first()
    if document is None:
        return
    if records.is_awaiting_review(document):
        return                              # not confirmed by the patient yet: it is queued again the moment they confirm it
    try:
        result = lib_processing.process_document(document, force=force)
    except Exception as exc:
        DocumentExtraction.objects.filter(document_id=document_id).update(
            status=DocumentExtraction.Status.FAILED, normalised={"error": str(exc)[:2000]})
        if _is_transient(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=min(3600, 600 * 2 ** self.request.retries), queue=queue)
        logger.exception("records: reading the facts of document %s failed", document_id)
        return
    if result["status"] == "DONE":
        lib_processing.rebuild_patient(result["patient_id"])


@shared_task(ignore_result=True)
def rebuild_patient_task(patient_id):
    lib_processing.rebuild_patient(patient_id)


@shared_task(ignore_result=True)
def backfill_task(queue=records.BULK_QUEUE, limit=None):
    """Queues process_document_task for every document that has text and has not been processed, oldest first, so episodes"""
    done = DocumentExtraction.objects.filter(status__in=[DocumentExtraction.Status.DONE, DocumentExtraction.Status.SKIPPED])
    ids = (MedicalDocument.objects.filter(d_extraction__isnull=False).exclude(d_extraction__in=done)
           .order_by("created_at").values_list("pk", flat=True))
    for document_id in ids[:limit] if limit else ids:
        process_document_task.apply_async(args=[document_id, queue], queue=queue)
