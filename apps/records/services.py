"""
The records pipeline. Everything is accepted at the door (sizes only); the content is checked inside the
pipeline, so one bad file never blocks the rest of its batch. Two independently-queued Celery stages (tasks.py):

    save_upload()         files to the private S3 bucket through MedicalDocument.file, one DocumentBatch, one
                          MedicalDocument per file (status "queued"); start_processing() queues each
    extract_document()    file → content check → PDF text layer or OCR → DocumentText         (queued → extracting)
    classify_document()   DocumentText → rule engine (classification.py) → PatientDocumentClassification
                          and MedicalDocument.document_type                                    (→ classifying)

Every document ends "completed", "review_required" (read, but the rules could not tell what it is) or "failed",
so nothing waits forever, and the batch counters follow. The document types, keywords and scoring are in
classification.py — in code, not in the database.
"""
import io
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connections, transaction
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime

from core import ocr, storage
from core.file_validation import FileValidationError, validate_bytes
from apps.registry.models import PatientIdentity
from . import classification as rules
from .models import DocumentBatch, DocumentText, MedicalDocument
from .serializers import MAX_FILE_BYTES

logger = logging.getLogger(__name__)

UPLOAD_THREADS = 8    # files sent to S3 at the same time
_UPLOAD_EXT = {"pdf", "jpg", "jpeg", "png"}
_DECLARED_MIME = {"application/pdf", "image/jpeg", "image/png"}
Status = MedicalDocument.Status

# Two Celery queues, so one file never waits behind someone else's big upload: "instant" is for a single file,
# "bulk" for several. Run one worker per queue (celery -A atomwalk worker -Q instant / -Q bulk).
INSTANT_QUEUE = "instant"
BULK_QUEUE = "bulk"
MAX_SUBMIT = 100            # decisions in one submit call


# ── upload ───────────────────────────────────────────────────────────────
def _stored_name(filename):
    """<random>.<ext> — never the uploader's file name (that is kept apart, in MedicalDocument.file_name)."""
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return f"{uuid.uuid4().hex}.{ext if ext in _UPLOAD_EXT else 'bin'}"


def _safe_delete(name: str) -> None:
    """Only ever deletes inside documents/ or patients/ — a bug or a wrong path can't cost anything else in the bucket."""
    if name and name.startswith(("documents/", "patients/")):
        storage.delete(name)
    elif name:
        logger.warning("records: refusing to delete %r — not a documents/ or patients/ object", name)


def save_upload(awpid, files):
    """`files` = [(uploaded_file, raw_bytes)]. One batch per upload, however many files. The files go to S3
    UPLOAD_THREADS at a time (one after another made a big upload wait for the sum of every transfer); if any
    transfer fails, everything already sent is deleted and nothing is saved."""
    patient = PatientIdentity.objects.using("default").get(awpid=awpid)
    batch = DocumentBatch.objects.create(patient=patient, total_files=len(files))
    docs = [MedicalDocument(patient=patient, batch=batch, file_name=(f.name or "")[:100], size=len(raw),
                            uploaded_by="patient", status=Status.QUEUED)
            for f, raw in files]

    def send(i):
        f, raw = files[i]
        content = ContentFile(raw, name=_stored_name(f.name))
        content.content_type = f.content_type if f.content_type in _DECLARED_MIME else "application/octet-stream"
        docs[i].file.save(content.name, content, save=False)      # → S3: documents/<awpid>/<batch>/<name>

    try:
        with ThreadPoolExecutor(max_workers=min(UPLOAD_THREADS, len(files))) as pool:
            list(pool.map(send, range(len(files))))
        with transaction.atomic(using="default"):
            MedicalDocument.objects.bulk_create(docs)
    except Exception:
        for d in docs:
            _safe_delete(d.file.name if d.file else "")
        batch.delete()
        raise
    return batch, list(MedicalDocument.objects.filter(batch=batch).order_by("id"))


def start_processing(document_ids, queue=BULK_QUEUE):
    """Queue each document's first stage on `queue`. If the queue can't be reached the document is marked failed -
    the patient sees it and can retry - rather than left "queued" for ever."""
    from .tasks import extract_document_task
    for document_id in document_ids:
        try:
            extract_document_task.apply_async(args=[document_id, queue], queue=queue)
        except Exception:
            logger.exception("records: couldn't queue document %s", document_id)
            doc = MedicalDocument.objects.filter(pk=document_id, status=Status.QUEUED).first()
            if doc:
                fail_document(doc, "Couldn't start processing this file. Please try again.")


def batch_summary(batch):
    """The batch and its documents, for the patient to follow: counts by status, then each file."""
    docs = list(batch.documents.select_related("classification").order_by("id"))
    counts = {s: 0 for s in Status.values}
    for d in docs:
        counts[d.status] = counts.get(d.status, 0) + 1
    finished = sum(counts.get(k, 0) for k in (Status.COMPLETED, Status.REVIEW_REQUIRED, Status.FAILED))
    return {
        "id": batch.id, "total_files": batch.total_files, "created_at": batch.created_at,
        "status": "processing" if batch.status == DocumentBatch.Status.PROCESSING else "completed",
        "progress_percent": int(round(100.0 * finished / batch.total_files)) if batch.total_files else 100,
        "counts": counts,
        "documents": [{"id": d.id, "file_name": d.file_name, "size": d.size, "status": d.status,
                       "processing_status": d.status, "doc_type": d.document_type, "method": rules.method_of(d),
                       "error": d.error_message} for d in docs],
    }


# ── processing ───────────────────────────────────────────────────────────
@contextmanager
def _locked(document_id):
    """True if this call got document_id's lock; released on exit. A Postgres advisory lock, so a live
    worker and a redelivered task can never act on the same document at once."""
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


def _in_status(document_id, *statuses):
    """The document, only if it is in one of `statuses`."""
    return MedicalDocument.objects.filter(pk=document_id, status__in=statuses).first()


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
    _end(doc, Status.FAILED, error_message=str(message)[:2000])


def fail_document_by_id(document_id, message):
    """For the task, once its retries are used up."""
    doc = _in_status(document_id, *MedicalDocument.IN_PROGRESS)
    if doc:
        fail_document(doc, message)


def extract_document(document_id):
    """Stage 1: file → content check → text. Returns True when the document is ready for classify_document.
    A file that can never work (empty, too big, not a PDF/JPEG/PNG) is failed here; any other error is raised so
    the Celery task retries it."""
    with _locked(document_id) as got:
        if not got:
            return False
        doc = _in_status(document_id, Status.QUEUED, Status.EXTRACTING, Status.CLASSIFYING)
        if not doc:
            return False
        if doc.status == Status.CLASSIFYING:      # a retry after the text was saved: only the hand-off is left
            return True
        if doc.status != Status.EXTRACTING:
            doc.status = Status.EXTRACTING
            doc.save(update_fields=["status", "updated_at"])
        doc.file.open("rb")
        try:
            raw = doc.file.read()
        finally:
            doc.file.close()
        try:
            if not raw:
                raise ValueError("The file is empty.")
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("The file is over 250 MB.")
            mime = validate_bytes(raw)          # real PDF / JPEG / PNG, by content — before any parser sees it
            if mime.startswith("image/"):
                size = ocr.image_size(raw)
                if size is None:
                    raise ValueError("This image could not be opened. It may be damaged.")
                if min(size) < ocr.MIN_OCR_SIDE:
                    raise ValueError(f"This image is only {size[0]}x{size[1]} pixels, too small to be a document. "
                                     "Please upload it again.")
        except FileValidationError as exc:
            fail_document(doc, f"This file is not a valid PDF, JPEG or PNG: {exc}")
            return False
        except ValueError as exc:
            fail_document(doc, exc)
            return False
        text, engine = extract_text(raw, mime)
        DocumentText.objects.update_or_create(document=doc, defaults={"extracted_text": text, "engine": engine})
        doc.mime_type, doc.size, doc.status = mime, len(raw), Status.CLASSIFYING
        doc.save(update_fields=["mime_type", "size", "status", "updated_at"])
        return True


def classify_document(document_id):
    """Stage 2: the rule engine on the extracted text → the document's classification. A person's choice is never
    overwritten. The document ends "completed", or "review_required" if the rules could not tell what it is."""
    with _locked(document_id) as got:
        if not got:
            return
        doc = _in_status(document_id, Status.CLASSIFYING)
        if not doc:
            return
        result = rules.classify_document_by_rules(rules.text_of(doc))
        classification = rules.store_rule_result(doc, result)
        review = classification.status == rules.REVIEW_REQUIRED
        _end(doc, Status.REVIEW_REQUIRED if review else Status.COMPLETED, error_message="")


def reclassify_existing(limit=5000):
    """Run today's rules again over documents the rules classified (never a person's choice, never a hospital-issued
    document), using the text already extracted — no OCR. For after a keyword in classification.py was edited.
    Returns {"checked", "changed", "classified", "unclassified"}."""
    counts = {"checked": 0, "changed": 0, "classified": 0, "unclassified": 0}
    docs = (MedicalDocument.objects
            .filter(status__in=(Status.COMPLETED, Status.REVIEW_REQUIRED), source_tenant_id__isnull=True,
                    classification__status__in=(rules.RULE_CLASSIFIED, rules.REVIEW_REQUIRED),
                    text__isnull=False)
            .order_by("id")[:limit])
    for doc in docs:
        before = doc.document_type
        result = rules.classify_document_by_rules(rules.text_of(doc))
        rules.store_rule_result(doc, result)
        doc.status = Status.REVIEW_REQUIRED if result["status"] == rules.REVIEW_REQUIRED else Status.COMPLETED
        doc.save(update_fields=["document_type", "status", "updated_at"])
        if doc.batch_id:
            doc.batch.refresh()
        counts["checked"] += 1
        counts["changed"] += doc.document_type != before
        counts["unclassified" if doc.document_type == rules.NOT_CLASSIFIED else "classified"] += 1
    return counts


def correct_document(doc, document_type):
    """A person files the document under `document_type` - one file at a time. It replaces whatever the rules said
    and locks the document: once decided, nobody (not the patient, not an admin) can change it again.
    Works on a failed document too: the file is still there, so it becomes a normal completed one."""
    if rules.is_confirmed(doc):
        raise rules.DocumentLocked("This document is confirmed and can't be changed.")
    if doc.status in MedicalDocument.IN_PROGRESS:
        raise ValueError("This file is still being read.")
    rules.store_human_choice(doc, document_type)
    _end(doc, Status.COMPLETED, error_message="")


# ── the review step: which uploads still wait for the patient's decision ─────
def review_starts_at():
    """When the review step began (settings.RECORDS_REVIEW_FROM, an ISO date-time). Everything uploaded before it is
    already part of the patient's documents and never needs review; unset means the review step is off."""
    raw = getattr(settings, "RECORDS_REVIEW_FROM", "") or ""
    when = parse_datetime(raw) if raw else None
    if when is not None and when.tzinfo is None:
        from django.utils import timezone
        when = timezone.make_aware(when)
    return when


def awaiting_review_q():
    """Q for a patient's own uploads, made after the review step began, whose type nobody has confirmed yet."""
    start = review_starts_at()
    if start is None:
        return Q(pk__in=[])
    return (Q(uploaded_by="patient", source_tenant_id__isnull=True, created_at__gte=start)
            & ~Q(classification__status__in=(rules.HUMAN_CLASSIFIED, rules.ISSUED)))


def document_counts(awpid):
    """What the My Documents dropdown and the badges need: {"total", "awaiting_review", "unclassified", "by_type"}.
    Only finished, confirmed-or-grandfathered documents count towards the types; the files waiting for review are
    counted apart."""
    docs = MedicalDocument.objects.using("default").filter(patient__awpid=awpid)
    awaiting = awaiting_review_q()
    done = (Status.COMPLETED, Status.REVIEW_REQUIRED)
    by_type = {code: 0 for code in rules.CHOOSABLE_TYPES}
    for row in docs.exclude(awaiting).filter(status__in=done).values("document_type").annotate(n=Count("id")):
        if row["document_type"] in by_type:
            by_type[row["document_type"]] = row["n"]
    return {
        "total": docs.exclude(awaiting).filter(status__in=done).count(),
        "awaiting_review": docs.filter(awaiting, status__in=done).count(),
        "unclassified": docs.exclude(awaiting).filter(status__in=done, document_type=rules.NOT_CLASSIFIED).count(),
        "by_type": by_type,
    }


def submit_decisions(awpid, decisions):
    """The patient's final answer for a list of files: [{"document_id", "document_type"}]. Each file is checked on
    its own - a bad one never stops the rest. Returns ({"submitted": [id], "rejected": [{"document_id", "reason"}]}).
    A submitted file gets the person's type and is locked. Sending the same list again changes nothing."""
    wanted = [d["document_id"] for d in decisions]
    docs = {d.id: d for d in MedicalDocument.objects.using("default").filter(patient__awpid=awpid, pk__in=wanted)
            .select_related("classification")}
    submitted, rejected, seen = [], [], set()

    def reject(doc_id, reason):
        rejected.append({"document_id": doc_id, "reason": reason})

    for decision in decisions:
        doc_id, doc_type = decision["document_id"], decision["document_type"]
        doc = docs.get(doc_id)
        if doc_id in seen:
            continue
        seen.add(doc_id)
        if doc is None or doc.source_tenant_id or doc.uploaded_by == "staff":
            reject(doc_id, "not_found")
        elif doc_type not in rules.CHOOSABLE_TYPES:
            reject(doc_id, "invalid_type")
        elif rules.is_confirmed(doc):
            reject(doc_id, "already_confirmed")
        elif doc.status in MedicalDocument.IN_PROGRESS:
            reject(doc_id, "still_processing")
        elif doc.status == Status.FAILED:
            reject(doc_id, "failed")
        else:
            try:
                with transaction.atomic(using="default"):
                    correct_document(doc, doc_type)
                submitted.append(doc_id)
            except rules.DocumentLocked:
                reject(doc_id, "already_confirmed")
            except ValueError:
                reject(doc_id, "still_processing")
    return {"submitted": submitted, "rejected": rejected}


def retry_document(doc):
    """Put a file that failed back in the queue (the caller then queues it with start_processing)."""
    if doc.status != Status.FAILED:
        raise ValueError("Only a file that failed can be tried again.")
    _end(doc, Status.QUEUED, error_message="")


def create_issued_document(*, awpid, file_path, name, doc_type, source_tenant_id, source_ref, mime_type="application/pdf",
                           public_document_id="", document_date=None):
    """A document a hospital made for the patient (signed prescription, lab report, handwriting): it is already in
    the bucket at `file_path` and already has its type, from its source, so it skips the pipeline and is stored as
    completed."""
    doc = MedicalDocument(
        patient=PatientIdentity.objects.using("default").get(awpid=awpid), file_name=(name or "")[:100],
        mime_type=mime_type, uploaded_by="staff", source_tenant_id=source_tenant_id, source_ref=source_ref,
        document_ref=public_document_id, document_date=document_date, status=Status.COMPLETED)
    doc.file = file_path
    doc.save(using="default")
    rules.store_issued_type(doc, doc_type)
    doc.save(using="default", update_fields=["document_type"])
    return MedicalDocument.objects.using("default").get(pk=doc.pk)


def extract_text(raw, mime):
    """(text, engine). PDF text layer if it has one ("pdf_text"), otherwise RapidOCR on the image or the first PDF
    pages ("ocr")."""
    if mime == "application/pdf":
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages[:5]).strip()
        if len(text) >= 40:
            return text, "pdf_text"
        return "\n".join(ocr.run(png).text for png in ocr.pdf_page_images(raw)).strip(), "ocr"
    return ocr.run(raw).text.strip(), "ocr"
