from celery import shared_task

from . import services
from .models import SweepConfig


@shared_task(soft_time_limit=120, time_limit=180)
def extract_document_task(document_id):
    """S3 → RapidOCR → save text, then dispatch classify_document_task. Time-limited so a hung OCR
    call can't tie up a worker forever; a limit hit is caught like any other failure ("failed")."""
    services.extract_document(document_id)


@shared_task(soft_time_limit=300, time_limit=360)
def classify_document_task(document_id):
    """Rules, then Ollama if score < 75 → save result / status / error. Its own task, and its own
    (longer) time limit, so a slow LLM call never blocks extraction of the next document."""
    services.classify_document(document_id)


@shared_task
def recover_stuck_documents():
    """Every SweepConfig.sweep_interval_seconds (Beat, DB-backed — see SweepConfig.save()): send up
    to SweepConfig.sweep_dispatch_limit documents (Platform Admin → Records settings) that are either
    freshly queued (a bulk upload deferred at intake — see SweepConfig.instant_max_files — or one
    whose initial dispatch failed) or stuck in ocr/classifying for 5+ minutes (worker died) — routed
    to whichever stage's task matches where each document currently is."""
    rows = services.documents_ready_for_pickup(limit=SweepConfig.current().sweep_dispatch_limit)
    for document_id, status in rows:
        (classify_document_task if status == "classifying" else extract_document_task).delay(document_id)
    return len(rows)
