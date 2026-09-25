"""
core/pipeline/llm_queue.py — step 3: the AI queue.

shared_document.llm_status IS the queue:

    ""  → not needed     queued → waiting     running → with the LLM     done / failed

  wants_llm(cr)      does this document need an AI check?
                     DOC_PIPELINE_LLM_ALWAYS=True → every readable document
                     False → only when the rules were unsure (< 75%), a
                     panel/date is missing, or a billing word was seen
  kick_llm_queue()   "have a look now" — sends a core.llm_drain task
  drain_llm_queue()  takes the OLDEST queued document, asks the LLM, stores the
                     verdict. One at a time: a Postgres lock plus a
                     one-at-a-time "llm" worker. If the LLM server is down it
                     stops; Beat's "Run the AI queue" job (every minute)
                     starts it again, so it resumes by itself.
  _llm_one(doc)      the actual LLM call + merging the verdict in

The LLM is local Ollama or the production GPU server — core/llm_client.py,
switched with LLM_MODE in .env.
"""

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.pipeline import filing, log

logger = logging.getLogger(__name__)

_LOCK_KEY = 0x6C6C_6D71          # "llmq" — Postgres advisory lock id
_STALE_RUNNING = 1800            # a "running" row older than this was left by a crash


def wants_llm(cr) -> bool:
    from core import doc_classifier_llm as dcl
    if not dcl._enabled() or cr.unreadable or not (cr.text or "").strip():
        return False
    # _bill_signal: one billing token (GST, Bill No…) on an otherwise-confident
    # page still earns an AI second opinion — it may be a pharmacy bill, not a
    # prescription (commit 7e6961a).
    return bool(settings.DOC_PIPELINE_LLM_ALWAYS or cr.needs or not cr.confident
                or getattr(cr, "_bill_signal", False))


def kick_llm_queue() -> None:
    try:
        from core import celery_runtime as rt
        rt.send("core.llm_drain")
    except Exception:
        logger.info("pipeline: couldn't nudge the AI queue now; Beat will within a minute")


def llm_queue_counts() -> dict:
    from apps.registry.models import SharedDocument
    from django.db.models import Count
    rows = (SharedDocument.objects.using("default").filter(deleted_at__isnull=True)
            .exclude(llm_status="").values_list("llm_status").annotate(n=Count("id")))
    return dict(rows)


def drain_llm_queue() -> str:
    """Process ONE queued document. Returns "done" | "empty" | "offline" | "busy"."""
    from django.db import connection
    from apps.registry.models import SharedDocument
    from core import llm_client

    qs = SharedDocument.objects.using("default")
    # A crashed worker may have left a row "running" — put it back in line.
    qs.filter(llm_status="running", llm_queued_at__lt=timezone.now() - timedelta(seconds=_STALE_RUNNING)) \
      .update(llm_status="queued")

    waiting = qs.filter(llm_status="queued", deleted_at__isnull=True)
    if not waiting.exists():
        return "empty"
    if not llm_client.status()["online"]:
        log.event(None, "AI OFFLINE", f"{llm_client.label()} not answering — {waiting.count()} waiting, retry in a minute")
        return "offline"

    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [_LOCK_KEY])
        if not cur.fetchone()[0]:
            return "busy"                                    # another drain is running
    try:
        doc = waiting.order_by("llm_queued_at", "id").first()
        if doc is None:
            return "empty"
        if not qs.filter(pk=doc.pk, llm_status="queued").update(llm_status="running", llm_queued_at=timezone.now()):
            return "busy"
        try:
            _llm_one(doc)
        except llm_client.LLMUnavailable as exc:
            qs.filter(pk=doc.pk).update(llm_status="queued")     # back in line
            log.event(doc.pk, "AI OFFLINE", f"{exc} — back in the queue")
            return "offline"
        except Exception as exc:
            logger.exception("pipeline: AI check failed for doc %s", doc.pk)
            log.error(doc.pk, "AI FAILED", f"{exc.__class__.__name__}: {str(exc)[:150]}")
            qs.filter(pk=doc.pk).update(llm_status="failed")
        return "done"
    finally:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", [_LOCK_KEY])


def _llm_one(doc) -> None:
    """Ask the LLM about one document. Store its verdict; if nobody has
    confirmed the document yet, re-file it with rules + LLM combined."""
    from core import doc_classifier as dc, doc_classifier_llm as dcl, llm_client

    log.event(doc.pk, "AI START", f"sending to {llm_client.label()}")
    t0 = time.monotonic()
    out = dcl.classify(doc.extracted_text, raise_unavailable=True)
    if not out:
        filing.save(doc, llm_status="failed")
        log.error(doc.pk, "AI FAILED", "no usable answer from the LLM")
        return

    fields = {
        "llm_doc_type": str(out.get("kind") or "")[:20],
        "llm_confidence": out.get("confidence"),
        "llm_scores": out.get("scores") or {},
        "llm_model": (dcl.model_name() or "")[:80],
        "llm_status": "done",
    }
    try:
        doc.refresh_from_db()
    except type(doc).DoesNotExist:
        log.event(doc.pk, "AI RESULT", f"{fields['llm_doc_type']} — the document was deleted meanwhile, nothing saved")
        return
    untouched = (doc.classification_status != "closed" and not doc.human_action
                 and doc.deleted_at is None and doc.verification_status != "verified")
    if untouched:
        fields.update(filing.filing_fields(dc.classify_text(doc.extracted_text, llm=out)))
        after = f"→ {filing.describe(fields)}"
    else:
        after = "→ stored only (the patient already confirmed this document)"
    filing.save(doc, **fields)
    log.event(doc.pk, "AI RESULT",
              f"{fields['llm_doc_type']} {log.pct(fields['llm_confidence'])} in {time.monotonic() - t0:.1f}s {after}")
