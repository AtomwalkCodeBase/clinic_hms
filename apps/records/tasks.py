"""
Celery tasks of the records pipeline: orchestration only — the work is in services.py and the rules are in
classification.py.

    extract_document_task    file → content check → text (DocumentText), then queues classify_document_task
    classify_document_task   rule engine → PatientDocumentClassification and the document's type

Each task retries on an unexpected error (Celery's own retry, with backoff); once its retries are used up the document
is marked failed, so the patient sees it and can retry. A file that can never work (empty, not a PDF/JPEG/PNG) is
failed straight away, without retries.
"""
import logging

from celery import shared_task

from . import services

logger = logging.getLogger(__name__)

# acks_late + reject_on_worker_lost: if a worker dies mid-task the message is redelivered instead of lost. Safe
# because both stages start with a status check and an advisory lock, so a redelivered or duplicate run for a
# document that already moved on is a no-op. ignore_result: nothing reads task results (the state is on the
# document).
_TASK_OPTS = dict(
    bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=300, retry_jitter=True,
    max_retries=3, acks_late=True, reject_on_worker_lost=True, ignore_result=True,
)


@shared_task(soft_time_limit=120, time_limit=180, **_TASK_OPTS)
def extract_document_task(self, document_id, queue=services.BULK_QUEUE):
    """File → content check → text, then queue classify_document_task on the same `queue` (so a single instant file
    is never stuck behind a bulk upload). Time-limited so a hung OCR call can't tie up a worker for ever; a limit
    hit is retried like any other error."""
    try:
        ready = services.extract_document(document_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.exception("records: extracting %s failed for good", document_id)
            services.fail_document_by_id(document_id, f"Couldn't read this file: {exc}")
            return
        raise
    if ready:
        classify_document_task.apply_async(args=[document_id, queue], queue=queue)


@shared_task(soft_time_limit=60, time_limit=90, **_TASK_OPTS)
def classify_document_task(self, document_id, queue=services.BULK_QUEUE):
    """Rule engine → classification, status and batch counters. Its own task so extraction of the next document
    never waits on it."""
    try:
        services.classify_document(document_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.exception("records: classifying %s failed for good", document_id)
            services.fail_document_by_id(document_id, f"Couldn't classify this file: {exc}")
            return
        raise
