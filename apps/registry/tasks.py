"""
apps/registry/tasks.py
-----------------------
Background work for the mobile upload-and-extract flow (see
apps/patients/portal_extraction_views.py). It reads the text; the hand-off to My Reports
(keyword rules + the AI queue) happens right after each read, in
apps/registry/extraction.py, which also holds the shared validate/keep/extract logic.

It follows the same design as the My Reports pipeline (core/pipeline/routing.py):

  * instant — a small upload is read inside the request (the sync endpoint).
  * bulk    — a big upload is saved as "queued" in the DATABASE. Start only marks it;
              the scheduled job "Process mobile bulk uploads" (process_bulk_extractions,
              below) reads the oldest queued files, at most bulk_batch_limit per run,
              one after another. The database is the queue, so Start never depends on
              the broker being up.
  * If Celery isn't running (no fresh worker/Beat heartbeat) and inline_fallback is
    on, Start reads the batch inside the web server instead (bulk_fallback), exactly
    like routing.bulk_fallback does for My Reports uploads.

The limits (instant_max_files, bulk_batch_limit, inline_fallback) are the ones on
platform admin -> Background Jobs -> Settings (core.celery_runtime).

Only ONE run reads files at a time (a Postgres advisory lock), so overlapping runs, or
a worker plus the web-server fallback, never add up in memory: each read holds an OCR
model (~135 MB idle, ~424 MB peak), which matters on the 2GB server. A file is claimed
with one atomic UPDATE, so it is never read twice.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# Batch is treated as stalled only if BOTH hold: none of its own files finished for
# STALL_BATCH_AFTER, and no file anywhere in the system finished for WORKER_QUIET_AFTER.
# A batch merely waiting behind other patients' files (busy but healthy worker) is
# therefore never cancelled for waiting.
STALL_BATCH_AFTER = timedelta(minutes=30)
WORKER_QUIET_AFTER = timedelta(minutes=15)
ABSOLUTE_MAX_AGE = timedelta(hours=24)      # backstop for anything the rules above miss
START_RETRY_WINDOW = timedelta(minutes=2)   # a batch whose Start failed (S3 couldn't be checked) keeps its files this long

_LOCK_KEY = 0x6D6F6278                      # "mobx" — Postgres advisory lock id: one reading run at a time
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mobile-bulk")   # web-server fallback (serial, memory-safe)


def _event(message: str) -> None:
    """One line in the shared pipeline log (Background Jobs -> Pipeline log)."""
    from core.pipeline import log
    log.event(None, "MOBILE", message)


# ── reading one file ─────────────────────────────────────────────────────────
def process_item(item_id) -> bool:
    """
    Reads one queued file: claim it, check it, extract, save, update its batch.
    True if this call did the work (False: someone else has it, or it's already final).
    Never raises — an unexpected error fails that one file and the run carries on.
    """
    from apps.registry.extraction import claim_item, fail_item

    item = claim_item(item_id)
    if item is None:
        logger.info("process_item: item %s not claimable (missing, taken, or already final)", item_id)
        return False
    try:
        _process_claimed(item)
    except Exception:
        logger.exception("process_item: unexpected error for item %s", item_id)
        fail_item(item, "Couldn't process this file.")
        _finalise_if_done(item.batch_id)
    return True


def _process_claimed(item) -> None:
    from apps.registry.extraction import (
        MAX_ITEM_ATTEMPTS, fail_item, run_extraction, size_problem, validate_size_and_pages,
    )
    from apps.registry.models import ExtractionItem
    from core import storage, file_validation

    def reject(reason: str, *, discard: bool = True):
        """Validation failed: the phone already PUT the file to S3, but an invalid file is never kept."""
        if discard and item.file_key:
            try:
                storage.delete(item.file_key)
            except Exception:
                logger.warning("could not delete rejected file %s", item.file_key, exc_info=True)
        fail_item(item, reason, drop_file=discard)
        _finalise_if_done(item.batch_id)

    def storage_trouble(exc):
        """S3 itself misbehaved (not the patient's file): put it back in line for the next run, then give up."""
        logger.warning("process_item: storage error for item %s", item.pk, exc_info=True)
        if item.attempts < MAX_ITEM_ATTEMPTS:
            ExtractionItem.objects.using("default").filter(
                pk=item.pk, status="processing", attempts=item.attempts).update(status="queued")
        else:
            reject("Storage was unavailable. Please upload this file again.", discard=False)

    # Look before downloading: a presigned PUT can't cap size, and a huge object read
    # into memory could take down a 2GB server.
    try:
        size = storage.head_size(item.file_key)
    except Exception as exc:
        return storage_trouble(exc)
    if size is None:
        return reject("Upload didn't finish. Please upload this file again.", discard=False)
    problem = size_problem(size, item.mime_type)
    if problem:
        return reject(problem)

    try:
        raw = storage.get_bytes(item.file_key)
    except Exception as exc:
        return storage_trouble(exc)

    try:
        mime_type = file_validation.validate_bytes(raw)
    except file_validation.FileValidationError as exc:
        return reject(str(exc))
    problem = validate_size_and_pages(raw, mime_type)
    if problem:
        return reject(problem)

    run_extraction(item, raw, mime_type)
    _finalise_if_done(item.batch_id)


# ── the queue: the oldest waiting files, one after another ───────────────────
def _drain(limit: int, budget_seconds, batch_id=None) -> dict:
    """
    Reads up to `limit` queued files (oldest batch first), stopping early after
    `budget_seconds` (None = no cap) so a run never outlives the task time limit.
    `batch_id` restricts it to one batch (the web-server fallback).
    """
    from apps.registry.models import ExtractionBatch, ExtractionItem

    waiting = ExtractionItem.objects.using("default").filter(
        status="queued", batch__status__in=("queued", "processing"))
    if batch_id:
        waiting = waiting.filter(batch_id=batch_id)
    total = waiting.count()
    rows = list(waiting.order_by("batch__queued_at", "created_at", "id").values_list("id", "batch_id")[:limit])
    if rows:
        _event(f"starting: {len(rows)} of {total} waiting file(s) (limit {limit})")

    t0, done, started = time.monotonic(), 0, set()
    for item_id, bid in rows:
        if budget_seconds is not None and time.monotonic() - t0 > budget_seconds:
            break
        if bid not in started:
            started.add(bid)
            now = timezone.now()
            ExtractionBatch.objects.using("default").filter(pk=bid, status="queued").update(
                status="processing", started_at=now, last_progress_at=now)
        if process_item(item_id):
            done += 1

    left = waiting.count()
    if rows:
        _event(f"finished: {done} file(s) read in {time.monotonic() - t0:.1f}s, {left} left for the next run")
    return {"processed": done, "remaining": left, "seconds": round(time.monotonic() - t0, 1)}


def _run_locked(limit: int, budget_seconds, batch_id=None) -> dict:
    """_drain, but only if no other run (worker or web-server fallback) is reading files right now."""
    from django.db import connections

    conn = connections["default"]
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [_LOCK_KEY])
        if not cur.fetchone()[0]:
            return {"skipped": "another run is already reading files"}
    try:
        return _drain(limit, budget_seconds, batch_id)
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", [_LOCK_KEY])


# Own limits (the global default is 300/360 s): a 20-page scan can take a few minutes, and
# STUCK_ITEM_AFTER (extraction.py, 11 min) assumes a hard kill at 10 min. The run also stops
# taking new files after budget_seconds, so one long file never pushes it past the hard limit.
@shared_task(ignore_result=True, soft_time_limit=540, time_limit=600)
def process_bulk_extractions(limit=None, budget_seconds=240):
    """
    Beat entry point — "Process mobile bulk uploads" (seeded by migration 0061, every minute; the
    interval is editable on Background Jobs). Reads the oldest queued files, at most
    bulk_batch_limit (Background Jobs -> Settings, default 25) per run.
    """
    from core import celery_runtime as rt

    limit = int(limit or rt.config().bulk_batch_limit or 25)
    return _run_locked(limit, budget_seconds)


def bulk_fallback(batch_id) -> bool:
    """
    If the worker or Beat isn't running (no fresh heartbeat) and `inline_fallback` is on, read this
    batch in a small in-process pool inside the web server instead of leaving it queued with nobody to
    read it. Returns True if it did. (Same rule as core.pipeline.routing.bulk_fallback.)
    """
    from core import celery_runtime as rt

    try:
        cfg = rt.config()
        if not cfg.inline_fallback or (rt.alive("worker", cfg) and rt.alive("beat", cfg)):
            return False
    except Exception:
        return False
    _event(f"FALLBACK — Celery isn't running: reading batch {batch_id} inside the web server instead")
    _pool.submit(_run_batch_inline, str(batch_id))
    return True


def _run_batch_inline(batch_id: str) -> None:
    from django.db import close_old_connections

    close_old_connections()
    try:
        _run_locked(limit=50, budget_seconds=None, batch_id=batch_id)
    except Exception:
        logger.exception("mobile bulk fallback failed for batch %s", batch_id)
    finally:
        close_old_connections()


# ── batch bookkeeping ────────────────────────────────────────────────────────
def _set_progress(batch, done: int, failed: int):
    batch.completed = done
    batch.failed = failed
    batch.processed = done + failed
    batch.progress_percent = min(100, int(round(100 * batch.processed / batch.total_files))) if batch.total_files else 0


def _final_status(done: int, failed: int) -> str:
    if failed == 0:
        return "done"
    return "failed" if done == 0 else "partial"


def _progress_fields(batch):
    return {
        "completed": batch.completed, "failed": batch.failed,
        "processed": batch.processed, "progress_percent": batch.progress_percent,
    }


def _finalise_if_done(batch_id):
    """Recomputes counters from the item rows; closes the batch once every file has finished."""
    from apps.registry.models import ExtractionBatch

    if not batch_id:
        return
    batches = ExtractionBatch.objects.using("default")
    batch = batches.filter(pk=batch_id).first()
    if not batch:
        return
    items = batch.items.all()
    done = items.filter(status="done").count()
    failed = items.filter(status="failed").count()
    _set_progress(batch, done, failed)
    now = timezone.now()

    if done + failed >= batch.total_files:
        status = _final_status(done, failed)
        # Only one caller can move the batch out of an active state — so a
        # completion is announced exactly once, however the last items interleave.
        won = batches.filter(pk=batch_id, status__in=ExtractionBatch.ACTIVE_STATUSES).update(
            status=status, finished_at=now, last_progress_at=now, **_progress_fields(batch))
        if won:
            batch.status = status
            _notify_batch_complete(batch)
        else:
            batches.filter(pk=batch_id).update(**_progress_fields(batch))
    else:
        batches.filter(pk=batch_id).update(last_progress_at=now, **_progress_fields(batch))


def abort_batch(batch, reason: str, status: str = "cancelled"):
    """
    Force-finishes a batch that can never complete on its own — abandoned
    upload, stalled worker, nothing arrived in S3 — so it stops counting as
    "active" and blocking that patient's next bulk upload. Never-validated
    uploads (possibly half-uploaded) are deleted from S3 rather than left as
    orphans. No push is sent.
    """
    from apps.registry.models import ExtractionBatch
    from core import storage

    unfinished = batch.items.exclude(status__in=("done", "failed"))
    for key in unfinished.exclude(file_key="").values_list("file_key", flat=True):
        try:
            storage.delete(key)
        except Exception:
            logger.warning("could not delete unfinished upload %s", key, exc_info=True)
    unfinished.update(status="failed", reason=reason[:160], processed_at=timezone.now(), file_key="")

    items = batch.items.all()
    _set_progress(batch, items.filter(status="done").count(), items.filter(status="failed").count())
    now = timezone.now()
    ExtractionBatch.objects.using("default").filter(
        pk=batch.pk, status__in=ExtractionBatch.ACTIVE_STATUSES,
    ).update(status=status, finished_at=now, last_progress_at=now, **_progress_fields(batch))
    batch.refresh_from_db()


def _notify_batch_complete(batch):
    from apps.registry.models import PushDeviceToken
    from core.push import send_push

    target_awpid = batch.initiated_by_awpid or batch.awpid
    tokens = list(
        PushDeviceToken.objects.using("default")
        .filter(awpid=target_awpid).values_list("token", flat=True)
    )
    if not tokens:
        return
    if batch.status == "done":
        title, body = "Upload complete", f"Extracted {batch.completed} of {batch.total_files} files."
    elif batch.status == "partial":
        title = "Upload complete"
        body = f"Extracted {batch.completed} of {batch.total_files} files — {batch.failed} failed."
    else:
        title, body = "Upload didn't work", "None of your files could be extracted. Please try again."
    send_push(tokens, title, body, data={"batch_id": str(batch.id), "type": "extraction_batch_done"})


# ── recovery ─────────────────────────────────────────────────────────────────
def reconcile_stuck_items(batch) -> int:
    """
    Closes out items left "processing" past the worker's hard time limit (the
    worker was killed, or Celery killed the task). The conditional update means
    a worker that is somehow still alive and finishes later cannot overwrite it.
    """
    from apps.registry.extraction import STUCK_ITEM_AFTER
    from apps.registry.models import ExtractionItem

    now = timezone.now()
    n = 0
    for it in batch.items.filter(status="processing", started_at__lt=now - STUCK_ITEM_AFTER):
        n += ExtractionItem.objects.using("default").filter(
            pk=it.pk, status="processing", attempts=it.attempts,
        ).update(status="failed", reason="Took too long to process.", processed_at=now)
    if n:
        _finalise_if_done(batch.pk)
    return n


def reconcile_stale_batches(awpid=None) -> int:
    """
    Closes batches that cannot make progress, WITHOUT cancelling healthy ones:
      pending      upload never finished (past the presigned-link lifetime), or a failed
                   Start wasn't retried within START_RETRY_WINDOW
      queued /     stalled only if none of its own files finished for STALL_BATCH_AFTER AND no
      processing   file anywhere finished for WORKER_QUIET_AFTER (i.e. the worker itself is not
                   working). A batch waiting behind other patients' files is not stalled.
      any          older than ABSOLUTE_MAX_AGE
    Called lazily (start / create / status) and by the periodic_reconcile task.
    """
    from apps.registry.extraction import PENDING_EXPIRY
    from apps.registry.models import ExtractionBatch, ExtractionItem

    now = timezone.now()
    qs = ExtractionBatch.objects.using("default").filter(status__in=ExtractionBatch.ACTIVE_STATUSES)
    if awpid:
        qs = qs.filter(awpid=awpid)
    worker_alive = ExtractionItem.objects.using("default").filter(
        processed_at__gte=now - WORKER_QUIET_AFTER).exists()

    closed = 0
    for b in qs:
        reason = None
        if b.created_at < now - ABSOLUTE_MAX_AGE:
            reason = "Timed out before finishing. Please upload again."
        elif b.status == "pending":
            if b.start_failed_at and b.start_failed_at < now - START_RETRY_WINDOW:
                reason = "Processing was unavailable. Please upload again."
            elif b.created_at < now - PENDING_EXPIRY:
                reason = "The upload didn't finish. Please upload again."
        else:
            reconcile_stuck_items(b)
            b.refresh_from_db()
            if b.status not in ExtractionBatch.ACTIVE_STATUSES:
                continue
            last = b.last_progress_at or b.queued_at or b.created_at
            if last < now - STALL_BATCH_AFTER and not worker_alive:
                reason = "Processing stalled. Please upload again."
        if reason:
            abort_batch(b, reason)
            closed += 1
    return closed


@shared_task
def periodic_reconcile():
    """Beat entry point — cleans up abandoned/stalled batches and files stuck in processing, even if nobody opens the app."""
    n = reconcile_stale_batches()
    if n:
        logger.info("periodic_reconcile closed %s batch(es)", n)
    return n
