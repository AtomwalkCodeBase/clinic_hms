"""
The records pipeline. Everything is accepted at the door (sizes only); the content is checked inside the
pipeline, so one bad file never blocks the rest of its batch. Two independently-queued stages:

    save_upload()            files to S3 under patients/<awpid>/…, one DocumentBatch, one MedicalDocument per file
                             (status "queued")
    claim_documents()        the dispatcher picks queued / abandoned documents (and gives up after MAX_ATTEMPTS)
    extract_document()       S3 → one read: content check + SHA-256 → duplicate? → PDF text layer or OCR
    classify_document()      keyword rules → the document's one classification (a person can overwrite it)

Every document ends "completed", "failed" or "rejected" (a duplicate), so nothing waits forever, and the batch
counters follow. The keyword rules come from DocumentClassification on every call, so a change in Platform Admin
applies to the next document with no restart.
"""
import hashlib
import io
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta

from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone

from core import ocr, storage
from core.file_validation import FileValidationError, validate_bytes
from . import scoring
from .models import DocumentBatch, DocumentClassification, MedicalDocument, SweepConfig
from .serializers import MAX_FILE_BYTES

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3      # a document the workers keep dying on is failed, not retried forever
STUCK_MINUTES = 5     # how long "in progress" means the worker died
UPLOAD_THREADS = 8    # files sent to S3 at the same time
_UPLOAD_EXT = {"pdf", "jpg", "jpeg", "png"}
_DECLARED_MIME = {"application/pdf", "image/jpeg", "image/png"}
Status = MedicalDocument.Status
Source = MedicalDocument.Source
# keys of classification_details that describe one verdict (replaced whenever the verdict is)
_VERDICT_KEYS = ("method", "best_guess", "matched", "runner_up", "evidence", "note")


# ── upload ───────────────────────────────────────────────────────────────
def patient_file_path(awpid, batch_id, filename):
    """patients/<awpid>/documents/<batch id>/<random>.<ext> — never the uploader's file name."""
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return f"patients/{awpid}/documents/{batch_id}/{uuid.uuid4().hex}.{ext if ext in _UPLOAD_EXT else 'bin'}"


def _safe_delete(path: str) -> None:
    """Only ever deletes inside patients/ — a bug or a wrong path can't cost anything else in the bucket."""
    if path and path.startswith("patients/"):
        storage.delete(path)
    elif path:
        logger.warning("records: refusing to delete %r — not a patients/ object", path)


def save_upload(awpid, files):
    """`files` = [(uploaded_file, raw_bytes)]. One batch per upload, however many files. The files go to S3
    UPLOAD_THREADS at a time (one after another made a big upload wait for the sum of every transfer); if any
    transfer fails, everything already sent is deleted and nothing is saved."""
    batch = DocumentBatch.objects.create(awpid_id=awpid, total_files=len(files))
    paths = [patient_file_path(awpid, batch.id, f.name) for f, _ in files]

    def send(i):
        f, raw = files[i]
        declared = f.content_type if f.content_type in _DECLARED_MIME else "application/octet-stream"
        storage.put_bytes(paths[i], raw, mime_type=declared)

    try:
        with ThreadPoolExecutor(max_workers=min(UPLOAD_THREADS, len(files))) as pool:
            list(pool.map(send, range(len(files))))
        with transaction.atomic(using="default"):
            MedicalDocument.objects.bulk_create([
                MedicalDocument(awpid_id=awpid, batch=batch, title=MedicalDocument.title_from(f.name),
                                original_file_name=f.name[:255], file_path=path, size=len(raw),
                                uploaded_by="patient", status=Status.QUEUED)
                for (f, raw), path in zip(files, paths)])
    except Exception:
        for path in paths:
            _safe_delete(path)
        batch.delete()
        raise
    return batch, list(MedicalDocument.objects.filter(batch=batch).order_by("id"))


def batch_summary(batch):
    """The batch and its documents, for the patient to follow: counts by status, then each file."""
    docs = list(batch.documents.order_by("id"))
    counts = {s: 0 for s in Status.values}
    for d in docs:
        counts[d.status] = counts.get(d.status, 0) + 1
    return {
        "id": batch.id, "total_files": batch.total_files, "created_at": batch.created_at,
        "status": "processing" if batch.status == DocumentBatch.Status.PROCESSING else "completed",
        "counts": counts,
        "documents": [{"id": d.id, "file_name": d.file_name, "size": d.size, "status": d.status,
                       "doc_type": d.doc_type, "method": d.method, "error": d.error} for d in docs],
    }


# ── processing ───────────────────────────────────────────────────────────
@contextmanager
def _locked(document_id):
    """True if this call got document_id's lock; released on exit. A Postgres advisory lock, so a live
    worker and a redelivered or re-dispatched task can never act on the same document at once."""
    conn = connections["default"]
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [document_id])
        got = cur.fetchone()[0]
    try:
        yield got
    finally:
        if got:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [document_id])


def _in_status(document_id, status):
    """The document, only if it is in `status`."""
    return MedicalDocument.objects.filter(pk=document_id, status=status).first()


def _end(doc, status, **fields):
    """Move a document to a new state and bring its batch counters in line."""
    doc.status = status
    for k, v in fields.items():
        setattr(doc, k, v)
    doc.save()
    if doc.batch_id:
        doc.batch.refresh()


def fail_document(doc, message):
    logger.warning("records: document %s failed: %s", doc.id, message)
    _end(doc, Status.FAILED, error=str(message)[:2000])


def claim_documents(limit, ids=None):
    """The dispatcher. Claims up to `limit` documents that are queued, or were claimed more than
    STUCK_MINUTES ago and never finished (worker died). Returns [(document id, "extract" | "classify")].
    skip_locked, so two dispatchers never take the same row; a document already tried MAX_ATTEMPTS
    times is failed here instead of being sent again."""
    cutoff = timezone.now() - timedelta(minutes=STUCK_MINUTES)
    picked = []
    with transaction.atomic(using="default"):
        qs = (MedicalDocument.objects.select_for_update(skip_locked=True, of=("self",))
              .filter(Q(status=Status.QUEUED)
                      | (Q(status__in=(Status.EXTRACTING, Status.CLASSIFYING))
                         & (Q(claimed_at__lt=cutoff) | Q(claimed_at__isnull=True))))
              .order_by("id"))
        if ids is not None:
            qs = qs.filter(id__in=ids)
        for doc in qs[:limit]:
            if doc.attempts >= MAX_ATTEMPTS:
                fail_document(doc, f"Processing did not finish after {MAX_ATTEMPTS} attempts.")
                continue
            stage = "classify" if doc.status == Status.CLASSIFYING else "extract"
            doc.status = Status.CLASSIFYING if stage == "classify" else Status.EXTRACTING
            doc.attempts += 1
            doc.claimed_at = timezone.now()
            doc.save(update_fields=["status", "attempts", "claimed_at", "updated_at"])
            picked.append((doc.id, stage))
    return picked


def _duplicate_of(doc):
    """The earlier document of the same patient with the same content, if there is one that is still alive
    (not removed, not failed or rejected). The earliest upload always wins, so a batch with two identical files
    keeps the first."""
    return (MedicalDocument.objects
            .filter(awpid_id=doc.awpid_id, content_hash=doc.content_hash, id__lt=doc.id,
                    deleted_at__isnull=True, hidden_at__isnull=True)
            .exclude(status__in=(Status.FAILED, Status.REJECTED))
            .order_by("id").first())


def _reject_duplicate(doc, original):
    _end(doc, Status.REJECTED, classification_details={**(doc.classification_details or {}), "duplicate_of": original.id},
         error=f"Same as {original.original_file_name}, uploaded {original.created_at:%d %b %Y}.")


def extract_document(document_id):
    """Stage 1: S3 → one read (content check + hash) → duplicate check → text. Hands off to classify_document_task."""
    with _locked(document_id) as got:
        if not got:
            return
        doc = _in_status(document_id, Status.EXTRACTING)
        if not doc:
            return
        try:
            raw = storage.get_bytes(doc.file_path)
            if not raw:
                raise ValueError("The file is empty.")
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("The file is over 250 MB.")
            mime = validate_bytes(raw)          # real PDF / JPEG / PNG, by content — before any parser sees it
        except FileValidationError as exc:
            fail_document(doc, f"This file is not a valid PDF, JPEG or PNG: {exc}")
            return
        except Exception as exc:
            logger.exception("records: reading %s failed", document_id)
            fail_document(doc, exc)
            return
        doc.mime_type, doc.content_hash, doc.size = mime, hashlib.sha256(raw).hexdigest(), len(raw)
        doc.save(update_fields=["mime_type", "content_hash", "size", "updated_at"])
        details = doc.classification_details or {}
        original = None if details.get("keep_duplicate") else _duplicate_of(doc)
        if original:
            _reject_duplicate(doc, original)
            return
        try:
            text = extract_text(raw, mime)
        except Exception as exc:
            logger.exception("records: extraction failed for %s", document_id)
            fail_document(doc, exc)
            return
        doc.status, doc.claimed_at = Status.CLASSIFYING, timezone.now()
        doc.classification_details = {**details, "extracted_text": text}
        doc.save(update_fields=["status", "claimed_at", "classification_details", "updated_at"])
    from .tasks import classify_document_task
    classify_document_task.delay(document_id)


def classify_document(document_id):
    """Stage 2: keyword rules → the document's classification. A person's verdict is never overwritten."""
    with _locked(document_id) as got:
        if not got:
            return
        doc = _in_status(document_id, Status.CLASSIFYING)
        if not doc:
            return
        try:
            details = doc.classification_details or {}
            original = None if details.get("keep_duplicate") else _duplicate_of(doc)   # last guard: the earlier twin has saved its hash by now
            if original:
                _reject_duplicate(doc, original)
                return
            if doc.classification_source != Source.HUMAN:
                _apply_verdict(doc, details.get("extracted_text", ""))
            _end(doc, Status.COMPLETED, error="")
        except Exception as exc:
            logger.exception("records: classification failed for %s", document_id)
            fail_document(doc, exc)


def _apply_verdict(doc, text):
    """Run the rules on `text` and record the verdict on `doc` (a person's verdict is never passed in here)."""
    code, confidence, details = classify(text)
    doc.classification = DocumentClassification.objects.using("default").get(code=code) if code else None
    doc.classification_source, doc.score = Source.SYSTEM, confidence
    kept = {k: v for k, v in (doc.classification_details or {}).items() if k not in _VERDICT_KEYS}
    doc.classification_details = {**kept, "method": "rule", **details,
                                  **({} if code else {"note": "Unable to classify — no configured type fits."})}


def reclassify_existing(limit=5000):
    """Run today's rules again over documents that were classified by the rules (never a person's verdict, never
    a hospital-issued one), using the text already extracted — no OCR. For after the keywords or the settings
    were tuned. Returns {"checked", "changed", "classified", "unclassified"}."""
    counts = {"checked": 0, "changed": 0, "classified": 0, "unclassified": 0}
    docs = (MedicalDocument.objects.filter(status=Status.COMPLETED, source_tenant_id__isnull=True)
            .exclude(classification_source=Source.HUMAN).order_by("id")[:limit])
    for doc in docs:
        text = (doc.classification_details or {}).get("extracted_text")
        if not text:
            continue
        before = (doc.classification_id, doc.score)
        _apply_verdict(doc, text)
        doc.save(update_fields=["classification", "classification_source", "score", "classification_details", "updated_at"])
        counts["checked"] += 1
        counts["changed"] += (doc.classification_id, doc.score) != before
        counts["classified" if doc.classification_id else "unclassified"] += 1
    return counts


def correct_document(doc, code):
    """A person overwrites the document's classification — one file at a time. It replaces whatever was there
    (the rules' verdict is not kept). Works on a failed document too: the file is still there, so it becomes a
    normal completed one. A rejected duplicate stays rejected."""
    if doc.status == Status.REJECTED:
        raise ValueError("This file is a duplicate of another report and was not kept.")
    kept = {k: v for k, v in (doc.classification_details or {}).items() if k not in _VERDICT_KEYS}
    doc.classification = DocumentClassification.for_code(code)
    doc.classification_source, doc.score = Source.HUMAN, None
    doc.classification_details = {**kept, "method": "human"}
    _end(doc, Status.COMPLETED, error="")


def keep_duplicate(doc):
    """The patient wants a file we rejected as a duplicate anyway: it goes through the pipeline again, this time
    without the duplicate check."""
    if doc.status != Status.REJECTED:
        raise ValueError("Only a duplicate can be kept.")
    _end(doc, Status.QUEUED, classification_details={**(doc.classification_details or {}), "keep_duplicate": True},
         attempts=0, error="")


def retry_document(doc):
    """Put a file that failed back in the queue."""
    if doc.status != Status.FAILED:
        raise ValueError("Only a file that failed can be tried again.")
    _end(doc, Status.QUEUED, attempts=0, error="")


def create_issued_document(*, awpid, file_path, name, doc_type, source_tenant_id, source_ref, mime_type="application/pdf",
                           title="", public_document_id="", hospital_label="", doctor_label="", document_date=None):
    """A document a hospital made for the patient (signed prescription, lab report, handwriting): it already
    has its type, from its source, so it skips the pipeline and is stored as completed."""
    doc = MedicalDocument.objects.using("default").create(
        awpid_id=awpid, title=title or MedicalDocument.title_from(name), original_file_name=name, mime_type=mime_type,
        file_path=file_path, uploaded_by="staff", source_tenant_id=source_tenant_id, source_ref=source_ref,
        public_document_id=public_document_id, hospital_label=hospital_label, doctor_label=doctor_label,
        document_date=document_date, status=Status.COMPLETED, classification=DocumentClassification.for_code(doc_type),
        classification_source=Source.HUMAN)
    return MedicalDocument.objects.using("default").get(pk=doc.pk)


def extract_text(raw, mime):
    """PDF text layer if it has one, otherwise RapidOCR on the image / first PDF pages."""
    if mime == "application/pdf":
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages[:5]).strip()
        if len(text) >= 40:
            return text
        return "\n".join(ocr.run(png).text for png in ocr.pdf_page_images(raw)).strip()
    return ocr.run(raw).text.strip()


# ── classification ───────────────────────────────────────────────────────
def load_rules():
    """{code: keywords text} of the active, patient-facing types that have at least one keyword — read fresh
    every time."""
    return {t.code: t.keywords for t in
            DocumentClassification.objects.using("default").filter(is_active=True, is_staff_only=False) if t.keyword_list}


def classify(text):
    """Returns (code | None, confidence 0–100, details). Only the types Platform Admin configured are
    compared. The best one is filed if its confidence reaches the bar (SweepConfig.min_confidence) and it has
    real evidence; otherwise nothing fits: code is None ("unable to classify") and details["best_guess"]
    says what the rules came closest to, for whoever reviews it."""
    cfg = SweepConfig.current()
    best, confidence, details = scoring.score(text, load_rules(), scale=cfg.evidence_scale)
    if best and confidence >= cfg.min_confidence and details["evidence"] >= scoring.MIN_EVIDENCE:
        return best, confidence, details
    return None, confidence, details
