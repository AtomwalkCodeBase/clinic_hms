"""
core/pipeline/routing.py — step 1: WHEN a document gets processed.

  route_for()      small upload → "instant" (processed inside the upload
                   request, the patient gets the result in the response);
                   big upload → "bulk" (left queued for the periodic job)
  process_bulk()   the periodic "Process bulk uploads" job: a batch per run
  bulk_fallback()  if Celery isn't running, sort bulk uploads in-process so
                   they don't wait forever

The thresholds live in the database (Background Jobs → Settings → Upload
routing): instant_max_files (default 3) and bulk_batch_limit (default 25).
"""

import time
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections

from core.pipeline import log
from core.pipeline.processing import process_document

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="doc-pipeline")


def route_for(batch_size, *, manual=False, qr_verified=False) -> str:
    """
    "instant" — up to instant_max_files files uploaded together, a manual
                upload, or a hospital-QR document (nothing to sort for the last two)
    "bulk"    — more files than that
    """
    from core import celery_runtime as rt
    if manual or qr_verified:
        return "instant"
    try:
        n = int(batch_size or 1)
    except (TypeError, ValueError):
        n = 1
    limit = rt.config().instant_max_files or 3
    return "instant" if n <= limit else "bulk"


def process_bulk(limit=None, budget_seconds=240) -> dict:
    """
    One run of the "Process bulk uploads" job: the oldest queued bulk uploads,
    at most `limit` (default bulk_batch_limit), stopping after `budget_seconds`
    so a run never outlives the task time limit. The rest waits for next run.
    """
    from apps.registry.models import SharedDocument
    from core import celery_runtime as rt

    limit = int(limit or rt.config().bulk_batch_limit or 25)
    waiting = (SharedDocument.objects.using("default")
               .filter(processing_route="bulk", processing_status="queued", deleted_at__isnull=True)
               .order_by("created_at", "id"))
    ids = list(waiting.values_list("id", flat=True)[:limit])
    if ids:
        log.event(None, "BULK RUN", f"starting: {len(ids)} of {waiting.count()} waiting (limit {limit})")

    t0, done = time.monotonic(), 0
    for doc_id in ids:
        if time.monotonic() - t0 > budget_seconds:
            break
        process_document(doc_id)
        done += 1

    left = waiting.count()
    if ids:
        log.event(None, "BULK RUN", f"finished: {done} sorted in {time.monotonic() - t0:.1f}s, {left} left for the next run")
    return {"processed": done, "remaining": left, "seconds": round(time.monotonic() - t0, 1)}


def bulk_fallback(doc_id: int) -> bool:
    """
    If the worker or Beat isn't running (no fresh heartbeat) and
    `inline_fallback` is on, sort this bulk upload in a small in-process pool
    instead of leaving it queued forever. Returns True if it did.
    """
    from core import celery_runtime as rt
    try:
        cfg = rt.config()
        if not cfg.inline_fallback or (rt.alive("worker", cfg) and rt.alive("beat", cfg)):
            return False
    except Exception:
        return False
    log.event(doc_id, "FALLBACK", "Celery isn't running — sorting inside the web server instead")
    _pool.submit(_run_in_thread, doc_id)
    return True


def _run_in_thread(doc_id: int) -> None:
    close_old_connections()
    try:
        process_document(doc_id)
    finally:
        close_old_connections()
