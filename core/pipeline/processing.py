"""
core/pipeline/processing.py — step 2: WHAT happens to one document.

process_document(doc_id):

    queued → extracting    read the text: PDF text layer, else OCR   (doc_classifier.extract)
           → classifying   keyword rules pick the type               (doc_classifier.classify, llm="off")
                           → file it                                  (filing.py)
           → done          converted to one PDF; AI check queued if wanted (llm_queue.py)
           → failed        unexpected error — waits for the patient to file it by hand

Two shortcuts: "Organize manually" uploads (the patient already chose the
folder) and hospital-QR documents skip reading and classifying entirely.

The LLM never runs here — it's queued (llm_queue.py) so an upload never waits
on the LLM server.
"""

import base64
import logging
import time

from django.utils import timezone

from core.pipeline import filing, log
from core.pipeline.llm_queue import kick_llm_queue, wants_llm

logger = logging.getLogger(__name__)

IN_FLIGHT = ("queued", "extracting", "classifying")
_TEXT_CAP = 20000


def process_document(doc_id: int) -> None:
    """Read, classify and file one document. Safe to call twice; never raises."""
    from apps.registry.models import SharedDocument

    qs = SharedDocument.objects.using("default")
    # Claim it: only a row still waiting (or failed, for a retry) moves on —
    # so two workers can never process the same document.
    claimed = qs.filter(pk=doc_id, deleted_at__isnull=True,
                        processing_status__in=IN_FLIGHT + ("failed",)) \
                .update(processing_status="extracting", processing_error="",
                        processing_started_at=timezone.now())
    if not claimed:
        return
    doc = qs.get(pk=doc_id)

    t0 = time.monotonic()
    try:
        _process(doc)
        log.event(doc_id, "DONE", f"processed in {time.monotonic() - t0:.1f}s")
    except Exception as exc:
        logger.exception("pipeline: doc %s failed", doc_id)
        log.error(doc_id, "FAILED", f"{exc.__class__.__name__}: {str(exc)[:150]}")
        fields = {
            "processing_status": "failed",
            "processing_error": (str(exc) or exc.__class__.__name__)[:200],
            "processed_at": timezone.now(),
        }
        if doc.verification_status != "verified" and doc.classification_method != "patient_manual":
            fields.update(review_state="unsorted", verification_status="needs_review",
                          review_needs=["kind"],
                          review_notes="We couldn't process this file automatically — tell us what it is.")
        filing.save(doc, **fields)


def _process(doc) -> None:
    from core import doc_classifier as dc

    raw = _read_bytes(doc)
    mime_type = doc.mime_type or "application/pdf"
    fields = {}

    if doc.classification_method == "patient_manual":
        # "Organize manually": the patient's choice is final — no OCR/rules/LLM.
        filing.save(doc, processing_status="classifying")
        log.event(doc.id, "MANUAL", f"filed as {doc.doc_type} by the patient — no AI")

    elif doc.verification_status == "verified":
        # The hospital QR already fixed the type — nothing to classify.
        filing.save(doc, processing_status="classifying")
        fields["classification_status"] = "closed"
        log.event(doc.id, "QR", f"hospital-verified {doc.doc_type} — no AI")

    else:
        # 1. read the text
        t = time.monotonic()
        ex = dc.extract(raw, mime_type)
        filing.save(doc, processing_status="classifying", extracted_text=(ex.text or "")[:_TEXT_CAP])
        if ex.early is not None and ex.early.unreadable:
            log.event(doc.id, "TEXT", f"unreadable — {ex.early.quality_reason or 'quality check failed'}")
        else:
            log.event(doc.id, "TEXT", f"{len(ex.text or ''):,} characters read in {time.monotonic() - t:.1f}s")

        # 2. keyword rules pick the type (the LLM is queued separately, below)
        cr = dc.classify(raw, mime_type, extracted=ex, llm="off")
        fields.update(filing.verdict_fields(cr))
        fields.update(filing.filing_fields(cr))
        fields["classification_status"] = "partial"          # a person still has to confirm
        if cr.rule_kind:
            log.event(doc.id, "RULES", f"{cr.rule_kind} {log.pct(cr.rule_conf)}")
        log.event(doc.id, "FILED", filing.describe(fields))

        # 3. AI check wanted? → into the AI queue
        if wants_llm(cr):
            fields.update(llm_status="queued", llm_queued_at=timezone.now())

    # 4. one PDF for everything (a photo becomes a single-page PDF)
    fields.update(_normalise(doc, raw, mime_type))
    fields.update(processing_status="done", processed_at=timezone.now(), processing_error="")
    filing.save(doc, **fields)

    if fields.get("llm_status") == "queued":
        from core import llm_client
        log.event(doc.id, "AI QUEUED", f"waiting for the LLM ({llm_client.label()})")
        kick_llm_queue()


# ── helpers ──────────────────────────────────────────────────────────────
def _read_bytes(doc) -> bytes:
    from core import storage
    raw = doc.file_data or ""
    if raw.startswith("data:"):
        return base64.b64decode(raw.split(",", 1)[1])
    return storage.get_bytes(raw)


def _normalise(doc, raw, mime_type) -> dict:
    """Photo → single-page PDF, stored next to (and replacing) the original."""
    from core import normalise, storage
    if mime_type == "application/pdf" or (doc.file_data or "").startswith("data:"):
        return {}
    try:
        pdf_bytes, new_mime = normalise.to_pdf(raw, mime_type)
    except Exception:
        logger.exception("pipeline: PDF conversion failed for doc %s; keeping the original", doc.id)
        return {}
    if new_mime != "application/pdf":
        return {}
    old_key = doc.file_data
    new_key = old_key.rsplit(".", 1)[0] + ".pdf"
    storage.put_bytes(new_key, pdf_bytes, mime_type=new_mime)
    if new_key != old_key:
        storage.delete(old_key)
    name = doc.file_name or ""
    if "." in name:
        name = name.rsplit(".", 1)[0] + ".pdf"
    return {"file_data": new_key, "mime_type": new_mime, "file_name": name}
