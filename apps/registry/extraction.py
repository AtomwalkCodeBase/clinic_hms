"""
apps/registry/extraction.py
----------------------------
Shared by the instant (inline) path in portal_extraction_views.py and the
Celery task in tasks.py, so a file is validated, kept and extracted the same
way whichever path it came through:

  1. validate      type (magic bytes) / size / page count   -> invalid files are NEVER kept
  2. keep          the original goes to S3 at a permanent key (file_key)
  3. extract       OCR / pypdf -> structured JSON + text saved on the item
  4. hand off      the text goes to a shared_document row (file_into_reports), where the keyword
                   rules and the AI check (the second status) take over

Concurrency rule: a worker must CLAIM an item (queued -> processing, attempts+1,
one atomic UPDATE) before touching it, and may only write the outcome of the
attempt it claimed. A duplicate delivery, a late worker, or recovery having
already closed the item therefore can never overwrite a newer result.
"""

import logging
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 20
TYPE_MAX_BYTES = {
    "application/pdf": 5 * 1024 * 1024,     # 5 MB
    "image/jpeg": 12 * 1024 * 1024,         # 12 MB
    "image/png": 12 * 1024 * 1024,          # 12 MB
}
EXT_BY_MIME = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}
MAX_FILE_BYTES = max(TYPE_MAX_BYTES.values())

# Presigned upload links live 40 min; a batch still "pending" is only treated as
# abandoned 5 min after the last link could have expired — so an upload that is
# genuinely in progress is never cleaned up underneath the phone.
UPLOAD_URL_TTL = 40 * 60
PENDING_EXPIRY = timedelta(minutes=45)

# The Celery hard limit is 600s (time_limit on process_bulk_extractions in tasks.py); an item
# still "processing" a minute past that can't be running any more. (The web-server fallback has
# no hard limit, but a file that long is failed all the same — see reconcile_stuck_items.)
STUCK_ITEM_AFTER = timedelta(minutes=11)

# A file whose S3 read fails (S3's fault, not the patient's) goes back in line for the next run
# this many times before it is failed.
MAX_ITEM_ATTEMPTS = 3


def file_key_for(slug: str, item_id, mime_type: str) -> str:
    """Permanent S3 key for an item's original file — same layout on both paths."""
    return f"extraction-files/{slug}/{item_id}.{EXT_BY_MIME[mime_type]}"


def size_cap_for(mime_type: str) -> int:
    return TYPE_MAX_BYTES.get(mime_type, MAX_FILE_BYTES)


def size_problem(size: int, mime_type: str):
    cap = size_cap_for(mime_type)
    if size > cap:
        return f"File is too large (max {cap // (1024 * 1024)}MB)."
    return None


def validate_size_and_pages(raw: bytes, mime_type: str):
    """Returns a user-facing reason string if the file breaks a cap, else None. (Type is checked by the caller.)"""
    from core.doc_classifier import _pdf_page_count

    problem = size_problem(len(raw), mime_type)
    if problem:
        return problem
    if mime_type == "application/pdf":
        pages = _pdf_page_count(raw)
        if pages and pages > MAX_PDF_PAGES:
            return f"PDF has too many pages (max {MAX_PDF_PAGES})."
    return None


# ── claiming + conditional writes ────────────────────────────────────────────
def _items():
    from apps.registry.models import ExtractionItem
    return ExtractionItem.objects.using("default")


def claim_item(item_id):
    """
    Atomically queued -> processing (attempts + 1). Returns the claimed item, or
    None if it isn't claimable (already being processed, already finished, or
    closed by recovery) — the caller just stops.
    """
    won = _items().filter(pk=item_id, status="queued").update(
        status="processing", started_at=timezone.now(), attempts=F("attempts") + 1,
    )
    return _items().get(pk=item_id) if won else None


def _own(item):
    """Rows this worker may still write: still processing, still the attempt it claimed."""
    return _items().filter(pk=item.pk, status="processing", attempts=item.attempts)


def fail_item(item, reason: str, *, drop_file: bool = False) -> bool:
    """Marks the claimed attempt failed. False if it was no longer ours to write."""
    fields = {"status": "failed", "reason": reason[:160], "processed_at": timezone.now()}
    if drop_file:
        fields["file_key"] = ""
    ok = _own(item).update(**fields) == 1
    item.refresh_from_db()
    return ok


def run_extraction(item, raw: bytes, mime_type: str) -> bool:
    """
    Extracts `raw` and saves the result on the claimed `item` (status done /
    failed). True on success. The original file is already stored by now, so a
    failure here (e.g. a password-protected PDF) keeps the file and records why
    extraction didn't work. Writes are conditional on still owning the attempt.
    """
    from core import doc_classifier

    if _own(item).update(mime_type=mime_type, file_size=len(raw)) != 1:
        item.refresh_from_db()
        return False

    try:
        result = doc_classifier.extract_document(raw, mime_type)
    except doc_classifier.ExtractionError as exc:
        fail_item(item, exc.message)
        return False
    except Exception:
        logger.exception("extraction failed for item %s", item.id)
        fail_item(item, "Couldn't process this file.")
        return False

    ok = _own(item).update(
        status="done", reason="",
        extracted_text=result["text"], extraction_confidence=result["confidence"],
        page_count=result["page_count"], extraction_json=result, processed_at=timezone.now(),
    ) == 1
    item.refresh_from_db()
    if ok:
        file_into_reports(item, raw, mime_type, result["text"])
    return ok


# ── hand-off: the second status (keyword rules + AI check) ───────────────────
_TEXT_CAP = 20000     # same cap the My Reports pipeline keeps (core/pipeline/processing.py)


def file_into_reports(item, raw: bytes, mime_type: str, text: str) -> None:
    """
    Once a file's text has been read, give it a shared_document row and run the same steps a My
    Reports upload gets, minus the reading (already done): the keyword rules pick the type and file
    it, then — if wanted — it goes into the AI queue (shared_document.llm_status). The phone shows
    that status after "Read". Never raises: the extraction is already saved, so a failure here just
    leaves item.document empty (the phone then shows no AI step for this file).

    A byte-identical file the patient already has in My Reports is linked, not filed twice.
    """
    import hashlib

    from apps.registry.models import SharedDocument
    from core import doc_classifier as dc
    from core.pipeline import filing, log
    from core.pipeline.llm_queue import kick_llm_queue, wants_llm

    try:
        docs = SharedDocument.objects.using("default")
        content_hash = hashlib.sha256(raw).hexdigest()
        same = docs.filter(awpid=item.awpid, content_hash=content_hash, deleted_at__isnull=True).first()
        if same:
            _items().filter(pk=item.pk).update(document=same)
            log.event(same.id, "MOBILE", "the same file was uploaded again — linked to the existing document")
            return

        cr = dc.classify_text(text, llm="off")           # keyword rules only; the AI check is queued below
        fields = {**filing.verdict_fields(cr), **filing.filing_fields(cr), "classification_status": "partial"}
        if wants_llm(cr):
            fields.update(llm_status="queued", llm_queued_at=timezone.now())

        name = item.original_filename or "Upload"
        doc = docs.create(
            awpid=item.awpid, title=(name.rsplit(".", 1)[0] or name)[:200], file_name=name[:255],
            mime_type=mime_type, file_data=item.file_key, uploaded_by="patient", content_hash=content_hash,
            extracted_text=(text or "")[:_TEXT_CAP],
            processing_status="done", processing_route="instant" if item.batch_id is None else "bulk",
            processing_started_at=item.started_at, processed_at=timezone.now(),
            **fields,
        )
        _items().filter(pk=item.pk).update(document=doc)
        log.event(doc.id, "MOBILE", f"read {len(text or ''):,} characters · filed {filing.describe(fields)}")
        if fields.get("llm_status") == "queued":
            from core import llm_client
            log.event(doc.id, "AI QUEUED", f"waiting for the LLM ({llm_client.label()})")
            kick_llm_queue()
    except Exception:
        logger.exception("file_into_reports failed for item %s", item.id)


_AI_STATES = {"queued": "queued", "running": "running", "done": "done", "failed": "failed"}


def ai_map(doc_ids) -> dict:
    """{shared_document id: the AI-check status the phone shows}, for the given ids, in one query."""
    from apps.registry.models import SharedDocument

    ids = {i for i in doc_ids if i}
    if not ids:
        return {}
    labels = dict(SharedDocument.DOC_TYPE_CHOICES)
    out = {}
    rows = (SharedDocument.objects.using("default").filter(pk__in=ids)
            .values("id", "llm_status", "doc_type", "review_state", "deleted_at"))
    for d in rows:
        if d["deleted_at"]:
            continue                                     # the patient removed it from My Reports
        out[d["id"]] = {
            # queued | running | done | failed — the AI check; "skipped" = it wasn't needed (or isn't switched on)
            "status": _AI_STATES.get(d["llm_status"], "skipped"),
            "label": labels.get(d["doc_type"], "") if d["doc_type"] != "other" else "",
            "needs_review": d["review_state"] == "unsorted",
        }
    return out


AI_NONE = {"status": "none", "label": "", "needs_review": False}   # no My Reports row (hand-off failed / removed)
