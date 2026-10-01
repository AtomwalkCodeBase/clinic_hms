import logging

from celery import shared_task

from . import services
from .models import SweepConfig

logger = logging.getLogger(__name__)

# acks_late + reject_on_worker_lost: if a worker dies mid-task the message is redelivered instead of
# lost. Safe because both stages start with a status check and an advisory lock, so a redelivered or
# duplicate run for a document that already moved on is a no-op.
# ignore_result: nothing reads task results (state lives on MedicalDocument.status).
_TASK_OPTS = dict(acks_late=True, reject_on_worker_lost=True, ignore_result=True)


@shared_task(soft_time_limit=120, time_limit=180, **_TASK_OPTS)
def extract_document_task(document_id):
    """S3 → content check → text, then dispatch classify_document_task. Time-limited so a hung OCR
    call can't tie up a worker forever; a limit hit is caught like any other failure ("failed")."""
    services.extract_document(document_id)


@shared_task(soft_time_limit=60, time_limit=90, **_TASK_OPTS)
def classify_document_task(document_id):
    """Keyword rules → classification, status and batch counters. Its own task so extraction of the
    next document never waits on it."""
    services.classify_document(document_id)


_STAGES = {"extract": extract_document_task, "classify": classify_document_task}


def dispatch_documents(limit, ids=None):
    """Claim up to `limit` documents (see services.claim_documents) and send each to its stage's task.
    A broker hiccup leaves that document claimed; it is picked up again once its claim goes stale."""
    sent = 0
    for document_id, stage in services.claim_documents(limit, ids):
        try:
            _STAGES[stage].delay(document_id)
            sent += 1
        except Exception:
            logger.exception("records: couldn't dispatch document %s", document_id)
    return sent


@shared_task(**_TASK_OPTS)
def recover_stuck_documents():
    """The dispatcher: every SweepConfig.sweep_interval_seconds (Beat, DB-backed — see SweepConfig.save())
    send up to SweepConfig.sweep_dispatch_limit documents that are queued (a bulk upload deferred at intake,
    or one whose initial dispatch failed) or abandoned in extracting/classifying for 5+ minutes."""
    return dispatch_documents(SweepConfig.current().sweep_dispatch_limit)
