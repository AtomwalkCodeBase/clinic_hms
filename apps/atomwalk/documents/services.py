"""Document pipeline, classification rules, timeline extraction, vitals, hospital write-through, episodes, growth references and schedule roadmaps."""
import io
import logging
import os
import uuid
import re
import csv
import math
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connections, transaction
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime
from core import ocr, storage
from core.file_validation import FileValidationError, validate_bytes
from apps.atomwalk.patients.models import Patient
from apps.atomwalk.documents.models import (
    DocumentBatch,
    DocumentExtraction,
    MedicalDocument,
    ClinicalEvent,
    GrowthMeasurement,
    Vitals,
    HealthEpisode,
    RecurrenceFlag,
)
from apps.atomwalk.documents.serializers import MAX_FILE_BYTES
from django.core.exceptions import ObjectDoesNotExist
from datetime import date, timedelta, datetime, time
from functools import lru_cache
from pathlib import Path
from django.utils import timezone
from apps.atomwalk.documents import services as episodes
from types import SimpleNamespace
from apps.hospital_master.patients.models import HospitalPatient
from core.response import error


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
    patient = Patient.objects.using("default").get(awpid=awpid)
    batch = DocumentBatch.objects.create(patient=patient)
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
    from apps.atomwalk.documents.tasks import extract_document_task
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
                       "processing_status": d.status, "doc_type": d.document_type, "method": method_of(d),
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
    """Move a document to a new state."""
    doc.status = status
    for k, v in fields.items():
        setattr(doc, k, v)
    doc.save()
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
        DocumentExtraction.objects.update_or_create(document=doc, defaults={"extracted_text": text, "engine": engine})
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
        result = classify_document_by_rules(text_of(doc))
        classification = store_rule_result(doc, result)
        review = classification.status == REVIEW_REQUIRED
        _end(doc, Status.REVIEW_REQUIRED if review else Status.COMPLETED, error_message="")
def reclassify_existing(limit=5000):
    """Run today's rules again over documents the rules classified (never a person's choice, never a hospital-issued
    document), using the text already extracted — no OCR. For after a keyword in classification.py was edited.
    Returns {"checked", "changed", "classified", "unclassified"}."""
    counts = {"checked": 0, "changed": 0, "classified": 0, "unclassified": 0}
    docs = (MedicalDocument.objects
            .filter(status__in=(Status.COMPLETED, Status.REVIEW_REQUIRED), source_hospital_id__isnull=True,
                    classification__status__in=(RULE_CLASSIFIED, REVIEW_REQUIRED),
                    extraction__isnull=False)
            .order_by("id")[:limit])
    for doc in docs:
        before = doc.document_type
        result = classify_document_by_rules(text_of(doc))
        store_rule_result(doc, result)
        doc.status = Status.REVIEW_REQUIRED if result["status"] == REVIEW_REQUIRED else Status.COMPLETED
        doc.save(update_fields=["document_type", "status", "updated_at"])
        counts["checked"] += 1
        counts["changed"] += doc.document_type != before
        counts["unclassified" if doc.document_type == NOT_CLASSIFIED else "classified"] += 1
    return counts
def correct_document(doc, document_type):
    """A person files the document under `document_type` - one file at a time. It replaces whatever the rules said
    and locks the document: once decided, nobody (not the patient, not an admin) can change it again.
    Works on a failed document too: the file is still there, so it becomes a normal completed one."""
    if is_confirmed(doc):
        raise DocumentLocked("This document is confirmed and can't be changed.")
    if doc.status in MedicalDocument.IN_PROGRESS:
        raise ValueError("This file is still being read.")
    store_human_choice(doc, document_type)
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
    return (Q(uploaded_by="patient", source_hospital_id__isnull=True, created_at__gte=start)
            & ~Q(classification__status__in=(HUMAN_CLASSIFIED, ISSUED)))
def document_counts(awpid):
    """What the My Documents dropdown and the badges need: {"total", "awaiting_review", "unclassified", "by_type"}.
    Only finished, confirmed-or-grandfathered documents count towards the types; the files waiting for review are
    counted apart."""
    docs = MedicalDocument.objects.using("default").filter(patient__awpid=awpid)
    awaiting = awaiting_review_q()
    done = (Status.COMPLETED, Status.REVIEW_REQUIRED)
    by_type = {code: 0 for code in CHOOSABLE_TYPES}
    for row in docs.exclude(awaiting).filter(status__in=done).values("document_type").annotate(n=Count("id")):
        if row["document_type"] in by_type:
            by_type[row["document_type"]] = row["n"]
    return {
        "total": docs.exclude(awaiting).filter(status__in=done).count(),
        "awaiting_review": docs.filter(awaiting, status__in=done).count(),
        "unclassified": docs.exclude(awaiting).filter(status__in=done, document_type=NOT_CLASSIFIED).count(),
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
        if doc is None or doc.source_hospital_id or doc.uploaded_by == "staff":
            reject(doc_id, "not_found")
        elif doc_type not in CHOOSABLE_TYPES:
            reject(doc_id, "invalid_type")
        elif is_confirmed(doc):
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
            except DocumentLocked:
                reject(doc_id, "already_confirmed")
            except ValueError:
                reject(doc_id, "still_processing")
    return {"submitted": submitted, "rejected": rejected}
def retry_document(doc):
    """Put a file that failed back in the queue (the caller then queues it with start_processing)."""
    if doc.status != Status.FAILED:
        raise ValueError("Only a file that failed can be tried again.")
    _end(doc, Status.QUEUED, error_message="")
def can_discard(doc):
    """A patient may remove an upload that failed, or one that has been read but whose type they have not confirmed yet
    (the Needs Review and Ready to Submit lists). Never one still being read - the worker is using it - and never one
    already confirmed, which is part of their records."""
    if doc.status == Status.FAILED:
        return True
    if doc.status not in (Status.COMPLETED, Status.REVIEW_REQUIRED):
        return False
    return MedicalDocument.objects.using("default").filter(pk=doc.pk).filter(awaiting_review_q()).exists()
def dismiss_document(doc):
    """The patient removes an upload (see `can_discard`): its stored copy and its rows. A document that is being read
    or is already confirmed is never deleted here, so nothing in the patient's records is ever lost. The batch is
    brought in line with what is left (and removed when nothing is)."""
    if not can_discard(doc):
        raise ValueError("Only a file that failed, or one you haven't confirmed yet, can be removed.")
    batch, name = doc.batch, (doc.file.name if doc.file else "")
    doc.delete()
    _safe_delete(name)
    if batch:
        if not batch.documents.exists():
            batch.delete()
def _queue_insights(document_id):
    """Read a hospital-issued document for the timeline too (its text, then its insights), once its row is committed.
    The hospital's save never fails because the queue is down: run_all() fills in what was missed."""
    def queue():
        try:
            from apps.atomwalk.documents.tasks import insights_document_task
            insights_document_task.apply_async(args=[document_id], queue=BULK_QUEUE)
        except Exception:
            logger.warning("records: couldn't queue insights for document %s", document_id, exc_info=True)
    transaction.on_commit(queue, using="default")
def create_issued_document(*, awpid, file_path, name, doc_type, source_hospital_id, source_type, source_id, mime_type="application/pdf",
                           public_document_id="", document_date=None):
    """A document a hospital made for the patient (signed prescription, lab report, handwriting): it is already in
    the bucket at `file_path` and already has its type, from its source, so it skips the upload pipeline (no
    classification) and is stored as completed. Its text and timeline insights are read in the background."""
    doc = MedicalDocument(
        patient=Patient.objects.using("default").get(awpid=awpid), file_name=(name or "")[:100],
        mime_type=mime_type, uploaded_by="staff", source_hospital_id=source_hospital_id,
        source_type=source_type, source_id=source_id,
        document_ref=public_document_id, document_date=document_date, status=Status.COMPLETED)
    doc.file = file_path
    doc.save(using="default")
    store_issued_type(doc, doc_type)
    doc.save(using="default", update_fields=["document_type"])
    _queue_insights(doc.pk)
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


from apps.atomwalk.documents.models import NOT_CLASSIFIED, DOCUMENT_TYPES, DOCUMENT_TYPE_CHOICES, CHOOSABLE_TYPES, RULE_CLASSIFIED, REVIEW_REQUIRED, HUMAN_CLASSIFIED, ISSUED, CLASSIFIER_RULES, CLASSIFIER_HUMAN, CLASSIFIER_HOSPITAL  # noqa: F401  (stored values, defined with the models)

# ── scoring ──────────────────────────────────────────────────────────────
WEIGHTS = {"strong": 10, "medium": 3, "weak": 1}
MIN_MARGIN = 5      # the winner must lead the runner-up by this many points
DOCUMENT_RULES = {
    "prescription": {
        "strong": ["prescription", "e-prescription", "rx", "c/o", "chief complaints", "medication prescribed", "take medicine", "prescribed by"],
        "medium": ["tablet", "tab", "capsule", "cap", "syrup", "syp", "injection", "inj", "mg", "ml", "dosage", "once daily", "twice daily",
                   "once a day", "once in a day", "twice a day", "thrice a day", "three times a day", "dispense",
                   "bd", "tds", "od", "hs", "qid", "sos", "before food", "after food", "before breakfast", "at night", "ointment",
                   "cream", "lotion", "drops", "topical", "orally", "eye drops", "next visit", "review after", "adv"],
        "weak": ["diagnosis", "advice", "follow up", "doctor", "dr", "timings"],
    },
    "lab_report": {
        "strong": ["laboratory report", "lab report", "reference range", "specimen", "test result", "pathology", "pathologist",
                   "biological reference interval", "reference interval", "bio. ref", "investigation", "test name"],
        "medium": ["hemoglobin", "haemoglobin", "wbc", "rbc", "platelet", "glucose", "creatinine", "cholesterol", "blood sugar", "urine",
                   "sample", "parameter", "observed value", "sample collected", "report date", "checked by", "end of report", "hba1c", "tsh",
                   "bilirubin", "sgot", "sgpt", "triglycerides", "hdl", "ldl", "uric acid", "specific gravity", "pus cells", "widal", "dengue",
                   "crp", "esr", "vitamin d", "sodium", "potassium", "troponin", "inr", "aptt", "culture", "sensitivity", "nabl", "serum"],
        "weak": ["result", "unit", "range", "normal", "high", "low", "method"],
    },
    "imaging_report": {
        "strong": ["radiology report", "imaging report", "x-ray", "xray", "mri", "ct scan", "ncct", "ultrasound", "usg", "sonography", "echocardiography",
                   "mammography", "doppler", "radiologist", "radiodiagnosis", "clinical information", "accession", "modality", "bi-rads"],
        "medium": ["impression", "findings", "contrast", "lesion", "scan", "technique", "comparison", "radiograph", "effusion", "standard protocol", "echo"],
        "weak": ["normal", "view", "study"],
    },
    "discharge_summary": {
        "strong": ["discharge summary", "date of discharge", "discharge date", "hospital course", "date of admission", "condition at discharge",
                   "advice on discharge", "discharge medications", "discharge card", "ip no"],
        "medium": ["admission date", "discharge medication", "discharged", "admission", "discharge", "ward", "procedure", "presenting complaints",
                   "treatment given", "resident medical officer"],
        "weak": ["diagnosis", "follow up", "admitted", "diet", "activity"],
    },
    "consultation_note": {
        "strong": ["consultation note", "clinical notes", "opd note", "consultation summary", "history of present illness", "chief complaint",
                   "visit type", "soap", "opd consultation", "progress note"],
        "medium": ["examination", "assessment", "subjective", "objective", "systemic examination", "vitals", "afebrile", "past history", "hpi"],
        "weak": ["complaint", "advice", "follow up", "plan", "review"],
    },
    "medical_bill": {
        "strong": ["invoice", "tax invoice", "amount payable", "total amount", "bill no", "net payable", "amount in words",
                   "receipt", "authorised signatory", "payment mode"],
        "medium": ["gst", "gstin", "subtotal", "sub total", "discount", "quantity", "rate", "net amount", "qty", "mrp", "batch", "with thanks", "rupees", "charges"],
        "weak": ["total", "amount", "paid"],
    },
    "vaccination_record": {
        "strong": ["vaccination certificate", "vaccination record", "immunization record", "immunisation record", "vaccine", "immunization",
                   "immunisation", "vaccination", "batch no", "next due", "date given"],
        "medium": ["dose", "bcg", "opv", "dpt", "dtp", "dtwp", "mmr", "hepatitis b", "covid", "booster", "ipv", "hib", "rotavirus", "guardian",
                   "covishield", "due at"],
        "weak": ["vaccinated"],
    },
    "referral_letter": {
        "strong": ["referral letter", "referred to", "refer to", "kindly see", "kind attention", "referral", "dear dr", "dear doctor", "for opinion",
                   "yours sincerely"],
        "medium": ["for further evaluation", "reason for referral", "kind opinion", "current medication", "presented with", "enclosed", "year-old"],
        "weak": ["regards", "sincerely", "thank you", "sub"],
    },
    "medical_certificate": {
        "strong": ["medical certificate", "fitness certificate", "to whom it may concern", "certified that", "certify", "sick leave", "medically fit",
                   "fit to resume", "unfit"],
        "medium": ["unfit for", "rest for", "recommended rest", "advised rest", "leave", "issued", "ref. no", "for the purpose", "recovered"],
        "weak": ["certificate", "registration no"],
    },
    # "other" has no rules on purpose: only a person files a document there.
}
def _canon(keyword):
    """What makes two keywords the same: letters and digits only, plural dropped ("x-ray" = "xray", "sub total" = "subtotal")."""
    k = re.sub(r"[^a-z0-9]", "", keyword.lower())
    return k[:-1] if len(k) > 3 and k.endswith("s") else k
def _dedupe_levels(rules):
    """A keyword counts once per type: if it is listed twice (at any level, spelt differently or as a plural), only the
    strongest one stays."""
    for levels in rules.values():
        seen = set()
        for level in ("strong", "medium", "weak"):
            levels[level] = [k for k in levels.get(level, []) if not (_canon(k) in seen or seen.add(_canon(k)))]
    return rules
DOCUMENT_RULES = _dedupe_levels(DOCUMENT_RULES)
# Patterns that are not words. A written dose such as 1-0-1 or 0-1-0 (morning-noon-night) is a clue for a prescription,
# but only a medium one: a discharge summary lists doses too. Each digit is 0-3 and none touches another digit, so a date
# like 11-09-2026 can not match.
PATTERN_RULES = {
    "prescription": [("medium", "1-0-1 dose pattern", re.compile(r"(?<![0-9])[0-3]\s*-\s*[0-3]\s*-\s*[0-3](?![0-9])"))],
}
# ── the engine (pure: no database) ───────────────────────────────────────
def normalize_text(text):
    """Lower-case, whitespace collapsed to single spaces."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower()).strip()
# A measurement unit such as mg/dL is not a dose, and a "Ref. Doctor" line is not a prescriber: neither should push a
# lab report towards "prescription".
_UNIT_RE = re.compile(r"(?<![a-z])(?:mg|ml|mcg|ug|ng|pg|g|u|iu|miu|uiu|mmol|meq)\s*/\s*(?:dl|l|ml|min|hr|cumm|kg|hpf)(?![a-z])")
_REF_DOCTOR_RE = re.compile(r"(?<![a-z])ref(?:erred|\.)?\s*(?:by|doctor)\b[^\n]*")
def prepare_text(text):
    """What the rules read: lower-cased, units and "Ref. Doctor" lines taken out, whitespace collapsed."""
    t = (text or "").lower()
    t = _REF_DOCTOR_RE.sub(" ", t)
    t = _UNIT_RE.sub(" xunitx ", t)
    return normalize_text(t)
_PATTERNS = {}
def _pattern(keyword):
    """Whole-word match: not glued to other letters (digits are fine, so "500mg" finds "mg"). The words of a phrase may
    be separated by spaces, hyphens or nothing at all ("follow up" = "Follow-up" = "Followup"), and the last word may
    be a plural ("prescription" = "Prescriptions")."""
    if keyword not in _PATTERNS:
        words = [re.escape(w) for w in re.split(r"[\s\-]+", keyword) if w]
        body = r"[\s\-]*".join(words)
        if keyword[-1].isalpha():
            body += "s?"
        _PATTERNS[keyword] = re.compile(r"(?<![a-z])" + body + r"(?![a-z])")
    return _PATTERNS[keyword]
def _squash(s):
    return re.sub(r"[^a-z0-9]", "", s)
def _found(keyword, text, squashed):
    """Whole-word match; for a phrase, also tolerate OCR dropping the spaces ("ReferenceRange")."""
    if _pattern(keyword).search(text):
        return True
    return " " in keyword and len(_squash(keyword)) > 5 and _squash(keyword) in squashed
def calculate_document_scores(text):
    """{type: {"score": int, "matched_rules": [{"keyword", "weight", "level"}]}} for every type that has """
    text = prepare_text(text)
    squashed = _squash(text)
    scores = {}
    for document_type, type_rules in DOCUMENT_RULES.items():
        score, matched = 0, []
        for level in ("strong", "medium", "weak"):
            for keyword in type_rules.get(level, []):
                if _found(keyword, text, squashed):
                    score += WEIGHTS[level]
                    matched.append({"keyword": keyword, "weight": WEIGHTS[level], "level": level})
        for level, name, regex in PATTERN_RULES.get(document_type, []):
            if regex.search(text):
                score += WEIGHTS[level]
                matched.append({"keyword": name, "weight": WEIGHTS[level], "level": level})
        scores[document_type] = {"score": score, "matched_rules": matched}
    return scores
def classify_document_by_rules(text):
    """The rules' verdict on `text`:

        document_type      the winning type, or "not_classified"
        status             "rule_classified" or "review_required"
        best_guess         the highest-scoring type ("" if nothing matched), even when it did not win
        score / second_best_score / score_margin
        matched_rules      what matched for the best-scoring type
    """
    scores = calculate_document_scores(text)
    ranked = sorted(scores.items(), key=lambda item: (-item[1]["score"], item[0]))
    best_type, best = ranked[0]
    second = ranked[1][1]["score"] if len(ranked) > 1 else 0
    margin = best["score"] - second
    result = {"score": best["score"], "second_best_score": second, "score_margin": margin,
              "matched_rules": best["matched_rules"]}
    if best["score"] == 0:
        return {**result, "document_type": NOT_CLASSIFIED, "status": REVIEW_REQUIRED, "best_guess": ""}
    if margin < MIN_MARGIN:
        return {**result, "document_type": NOT_CLASSIFIED, "status": REVIEW_REQUIRED, "best_guess": best_type}
    return {**result, "document_type": best_type, "status": RULE_CLASSIFIED, "best_guess": best_type}
# ── recording a verdict (the only code that writes classification state) ──
def store_rule_result(document, result):
    """Save the rules' verdict: the classification row and the document's current type. A person's choice is
    never overwritten. Does not touch the document's pipeline status."""
    from apps.atomwalk.documents.models import PatientDocumentClassification
    classification, _ = PatientDocumentClassification.objects.using("default").get_or_create(document=document)
    if classification.status in (HUMAN_CLASSIFIED, ISSUED):
        return classification
    classification.ai_document_type = result["best_guess"] or NOT_CLASSIFIED
    classification.classifier = CLASSIFIER_RULES
    classification.rule_score = result["score"]
    classification.second_best_score = result["second_best_score"]
    classification.score_margin = result["score_margin"]
    classification.rule_matches = result["matched_rules"]
    classification.status = result["status"]
    classification.save()
    document.document_type = result["document_type"]
    return classification
def store_human_choice(document, document_type):
    """A person files the document under `document_type`. It replaces whatever the rules said."""
    if document_type not in CHOOSABLE_TYPES:
        raise ValueError("Choose one of the available document types.")
    from apps.atomwalk.documents.models import PatientDocumentClassification
    classification, _ = PatientDocumentClassification.objects.using("default").get_or_create(document=document)
    classification.human_document_type = document_type
    classification.status = HUMAN_CLASSIFIED
    classification.save()
    document.document_type = document_type
    return classification
def store_issued_type(document, document_type):
    """A hospital-issued document brings its own type: no rules, no review."""
    from apps.atomwalk.documents.models import PatientDocumentClassification
    document_type = document_type if document_type in CHOOSABLE_TYPES else "other"
    classification, _ = PatientDocumentClassification.objects.using("default").get_or_create(document=document)
    classification.classifier = CLASSIFIER_HOSPITAL
    classification.ai_document_type = None
    classification.status = ISSUED
    classification.save()
    document.document_type = document_type
    return classification
# ── the review flow: what a patient may choose, and what is final ──────────
class DocumentLocked(ValueError):
    """The document is confirmed (a person or the hospital decided its type): nothing may change it any more."""
def document_type_choices():
    """[{"code", "label"}] - what a person may file a document under (the one list every app reads)."""
    return [{"code": code, "label": DOCUMENT_TYPES[code]} for code in CHOOSABLE_TYPES]
# ── reading a document's classification (the model carries no shortcuts for these) ──
def _classification(document):
    try:
        return document.classification
    except ObjectDoesNotExist:
        return None
def method_of(document):
    """How the type was decided: "rule" (the keyword rules), "staff" (a person, or the hospital that issued the
    document), "" (not classified)."""
    c = _classification(document)
    if c is None:
        return ""
    if c.status in (HUMAN_CLASSIFIED, ISSUED):
        return "staff"
    return "rule" if c.classifier == CLASSIFIER_RULES else ""
def score_of(document):
    c = _classification(document)
    return c.rule_score if c else None
def is_confirmed(document):
    """True once a person (or the hospital that issued it) has decided the type - the document is then locked."""
    c = _classification(document)
    return bool(c and c.status in (HUMAN_CLASSIFIED, ISSUED))
def suggested_type_of(document):
    """The type the rules filed it under, or None if they could not tell (or a person has already decided)."""
    c = _classification(document)
    if c and c.status == RULE_CLASSIFIED and c.ai_document_type not in (None, "", NOT_CLASSIFIED):
        return c.ai_document_type
    return None
def best_guess_of(document):
    """For a document no type fit: the type the rules came closest to (else "")."""
    c = _classification(document)
    if document.document_type == NOT_CLASSIFIED and c and c.ai_document_type not in (None, "", NOT_CLASSIFIED):
        return c.ai_document_type
    return ""
def text_of(document):
    try:
        return document.extraction.extracted_text
    except ObjectDoesNotExist:
        return ""


logger = logging.getLogger(__name__)
EXTRACTOR_VERSION = "medspacy-1"
VERSION = 3
VOCABULARY = Path(__file__).with_name("vocabulary.csv")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# 14/03/2026 (day first) · 2026-03-14 · 14 Mar 2026
_DATE = re.compile(r"(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{4})"
                   r"|(?P<y2>\d{4})-(?P<m2>\d{2})-(?P<d2>\d{2})"
                   r"|(?P<d3>\d{1,2})[ -](?P<mon>[A-Za-z]{3})[a-z]*[ ,-]+(?P<y3>\d{4})")
_BIRTH = re.compile(r"\bdob\b|d\.o\.b|date of birth|\bborn\b", re.I)       # a birth date is never the event's date
_UNCERTAIN = re.compile(r"suspect|unconfirmed|not confirmed|possible|probable|rule out|r/o|\bquery\b", re.I)
_RESOLVED = re.compile(r"resolved|recovered|settled|subsided|completed the (?:prescribed )?course", re.I)
_VACCINE = re.compile(r"vaccin|immuni[sz]|booster|birth dose|\bBCG\b|\bOPV\b|\bDPT\b|\bMMR\b", re.I)   # "Hepatitis B - birth dose" is a vaccine, not a diagnosis
_STRENGTH = re.compile(r"\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|iu)\b", re.I)
_FREQUENCY = re.compile(r"\b(?:OD|BD|BID|TDS|TID|QID|HS|SOS|\d-\d-\d|once daily|twice daily|thrice daily)\b", re.I)
_GLUED = re.compile(r"(?<=[A-Za-z]{3})(?=\d{2,}(?:mg|mcg|ml|g)?)", re.I)   # OCR joins a drug and its dose: "Aldactone25MG"
_PRODUCT = re.compile(r"\s*(?:syrup|syp|tablets?|tab|capsules?|cap|drops|lozenges?|cream|gel|ointment|spray|lotion|inhaler)", re.I)   # "Cough Syrup" is a product, not a cough
@lru_cache(maxsize=1)
def _vocabulary():
    """{word: (name, kind, nature)} from vocabulary.csv. A row's name and each of its synonyms are words."""
    with VOCABULARY.open(encoding="utf-8", newline="") as f:
        return {word.lower(): (row["name"], row["kind"], row["nature"] or "unknown")
                for row in csv.DictReader(f) for word in [row["name"], *filter(None, row["synonyms"].split("|"))]}
@lru_cache(maxsize=1)
def _pipeline():
    """The medSpaCy pipeline that finds the vocabulary's words and flags negated / family / suspected / historical."""
    import spacy
    from loguru import logger as pyrush_log
    from medspacy.target_matcher import TargetRule
    pyrush_log.disable("PyRuSH")                     # its sentence splitter logs every token at debug level
    nlp = spacy.blank("en")
    for name in ("medspacy_pyrush", "medspacy_target_matcher", "medspacy_context"):
        nlp.add_pipe(name)
    nlp.get_pipe("medspacy_target_matcher").add([TargetRule(word, kind) for word, (_, kind, _) in _vocabulary().items()])
    return nlp
def _dates_in(line):
    found = []
    for m in _DATE.finditer(line):
        g = m.groupdict()
        try:
            if g["d"]:
                found.append(date(int(g["y"]), int(g["m"]), int(g["d"])))
            elif g["y2"]:
                found.append(date(int(g["y2"]), int(g["m2"]), int(g["d2"])))
            else:
                found.append(date(int(g["y3"]), _MONTHS.index(g["mon"].lower()) + 1, int(g["d3"])))
        except ValueError:                           # 31/02/2026, or three letters that are not a month
            pass
    latest = date.today() + timedelta(days=366)     # a misread year ("2614") is no date; a follow-up next month is
    return [d for d in found if date(1900, 1, 1) <= d <= latest]
def _line_dates(line):
    return [] if _BIRTH.search(line) else _dates_in(line)
def _dose(rest):
    """"500 mg BD" from what follows a medication on its line (up to the next comma), or None."""
    parts = [m.group(0) for m in (_STRENGTH.search(rest), _FREQUENCY.search(rest)) if m]
    return " ".join(parts) or None
def build_insights(text, fixed_date=None):
    """The insights JSON for one document's text. `fixed_date` is a hospital document's own date, given to every finding."""
    nlp = _pipeline()
    text = _GLUED.sub(" ", text)
    header = next((d for line in text.splitlines() for d in _line_dates(line)), None)
    entries = []
    for ent in nlp(text).ents:
        start = text.rfind("\n", 0, ent.start_char) + 1
        end = text.find("\n", ent.end_char)
        end = len(text) if end < 0 else end
        line = text[start:end].strip()
        if ent.label_ != "medication" and _PRODUCT.match(text[ent.end_char:end]):
            continue
        if ent.label_ == "condition" and _VACCINE.search(line):
            continue
        sentence = ent.sent.text
        on_line = _line_dates(line)
        when = fixed_date or (on_line[0] if on_line else header)
        entries.append({
            "date": when.isoformat() if when else None, "word": ent._.target_rule.literal.lower(), "evidence": line[:300],
            "dose": _dose(re.split(r"[,;]", text[ent.end_char:end])[0]) if ent.label_ == "medication" else None,
            "negated": ent._.is_negated, "family": ent._.is_family,
            "uncertain": bool(ent._.is_uncertain or _UNCERTAIN.search(sentence)),
            "when": "resolved" if _RESOLVED.search(sentence) else "history" if ent._.is_historical else "planned" if ent._.is_hypothetical else "current",
        })
    return {"version": VERSION, "entries": entries}
def _read_file(doc):
    doc.file.open("rb")
    try:
        return doc.file.read()
    finally:
        doc.file.close()
def _text_of(doc):
    """The document's extracted text. A hospital-issued document skipped the upload pipeline, so it has none yet:
    read it from its file now, the same way an upload is read."""
    try:
        return doc.extraction.extracted_text
    except DocumentExtraction.DoesNotExist:
        text, engine = extract_text(_read_file(doc), doc.mime_type or "application/pdf")
        DocumentExtraction.objects.create(document=doc, extracted_text=text, engine=engine)
        return text
def run_insights(document_id):
    """Read one document (extracting its text first if it has none) and save its insights."""
    doc = MedicalDocument.objects.get(pk=document_id)
    hospital_date = (doc.document_date or doc.created_at.date()) if doc.source_hospital_id else None
    insights = build_insights(_text_of(doc), hospital_date)
    DocumentExtraction.objects.filter(document=doc).update(
        normalised=insights, status=DocumentExtraction.Status.DONE, processed_at=timezone.now(), error="", extractor_version=EXTRACTOR_VERSION)
    _write_events(doc, insights)
def _write_events(doc, insights):
    """The conditions found in a document become clinical events of its patient (and the patient's episodes are rebuilt).
    A person's verdict on an event (verified or rejected) is never overwritten by a new reading."""
    events = ClinicalEvent.objects.using("default")
    events.filter(document=doc, source="EXTRACTED", is_verified=False, is_rejected=False).delete()
    vocab = _vocabulary()
    for e in insights["entries"]:
        name, kind, nature = vocab.get(e["word"], (None, None, None))
        if kind != "condition" or e["negated"] or e["family"] or not e["date"]:
            continue
        if events.filter(document=doc, condition_text=name, event_date=e["date"]).exists():
            continue                                    # already there, or a person has dealt with it
        events.create(patient=doc.patient, document=doc, event_date=e["date"], event_type="DIAGNOSIS", condition_text=name,
                      condition_group=name.upper()[:40], category=nature.upper() if nature in ("acute", "chronic") else "",
                      is_provisional=e["uncertain"], evidence=e["evidence"][:255], source="EXTRACTED",
                      source_hospital_id=doc.source_hospital_id)
    episodes.rebuild(doc.patient)
def run_all(redo=False):
    """Insights for every finished document that has none yet, hospital-issued ones included (redo=True: for all, e.g.
    after adding rows to vocabulary.csv). Returns how many were done."""
    docs = MedicalDocument.objects.filter(status__in=(MedicalDocument.Status.COMPLETED, MedicalDocument.Status.REVIEW_REQUIRED))
    if not redo:
        docs = docs.filter(Q(extraction__isnull=True) | ~Q(extraction__status=DocumentExtraction.Status.DONE))
    done = 0
    for document_id in list(docs.values_list("id", flat=True)):
        try:
            run_insights(document_id)
            done += 1
        except Exception:
            logger.warning("records: insights for document %s failed", document_id, exc_info=True)
    return done
def build_timeline(awpid, *, audience="patient", hospital_id=None, start=None, end=None, kind=None, name=None, nature=None, when=None, include_hidden=False):
    """{"days": [{"date", "entries"}], "undated": [entries]} for a patient's confirmed documents, newest day first.

    Each stored word is looked up in vocabulary.csv for its name, kind and acute / chronic (a word no longer in the
    vocabulary is skipped). One finding per date and name: a repeat in the same or another report only adds a source,
    and it is hidden (negated, family, suspected) only if every mention is. `start`/`end` are ISO dates, `name` is
    part of a name; undated findings are left out when a date range is asked for.

    `audience`: "patient" leaves medications out (a list of past drugs does nothing for the patient, and the
    Prescriptions page has them); "staff" (a doctor or nurse) includes them, with their dose and frequency.
    `hospital_id`: only the documents that hospital issued, for staff when the patient has not agreed to
    cross-hospital sharing."""
    from apps.atomwalk.hospital_master.models import Hospital
    vocab = _vocabulary()
    docs = list(MedicalDocument.objects.filter(patient__awpid=awpid, extraction__status=DocumentExtraction.Status.DONE,
                                               status__in=(MedicalDocument.Status.COMPLETED, MedicalDocument.Status.REVIEW_REQUIRED))
                .exclude(awaiting_review_q()).select_related("extraction"))
    if hospital_id is not None:
        docs = [d for d in docs if d.source_hospital_id == int(hospital_id)]
    hospitals = dict(Hospital.objects.using("default").filter(id__in={d.source_hospital_id for d in docs if d.source_hospital_id})
                     .values_list("id", "name"))             # the hospital behind a hospital-issued document
    merged = {}
    for d in docs:
        for e in d.extraction.normalised["entries"]:
            if e["word"] not in vocab:
                continue
            canonical, word_kind, word_nature = vocab[e["word"]]
            if audience == "patient" and word_kind == "medication":
                continue
            m = merged.setdefault((e["date"], canonical), {
                "date": e["date"], "name": canonical, "kind": word_kind, "nature": word_nature, "negated": True, "family": True,
                "uncertain": True, "whens": set(), "evidence": e["evidence"], "dose": None, "sources": {}})
            for flag in ("negated", "family", "uncertain"):
                m[flag] = m[flag] and e[flag]
            m["whens"].add(e["when"])
            m["dose"] = m["dose"] or e.get("dose")
            if e["when"] == "resolved":
                m["evidence"] = e["evidence"]            # "… resolved" says more than the heading before it
            m["sources"].setdefault(d.id, {"document_id": d.id, "file_name": d.file_name, "document_type": d.document_type, "evidence": e["evidence"],
                                           "hospital": hospitals.get(d.source_hospital_id, "")})
    for m in merged.values():
        whens = m.pop("whens")
        m["when"] = "resolved" if "resolved" in whens else "current" if "current" in whens else sorted(whens)[0]
        m["sources"] = list(m["sources"].values())
        if m["uncertain"]:
            m["nature"] = "unknown"                      # "asthma is suspected" is not a chronic condition
    kept = [m for m in merged.values()
            if (include_hidden or not (m["negated"] or m["family"] or m["uncertain"]))
            and (not kind or m["kind"] == kind) and (not name or name.lower() in m["name"])
            and (not nature or m["nature"] == nature) and (not when or m["when"] == when)]
    dated = [m for m in kept if m["date"] and (not start or m["date"] >= start) and (not end or m["date"] <= end)]
    days = {}
    for m in sorted(dated, key=lambda m: m["date"], reverse=True):
        days.setdefault(m["date"], []).append(m)
    return {"days": [{"date": d, "entries": es} for d, es in days.items()],
            "undated": [] if (start or end) else [m for m in kept if not m["date"]]}


VITAL_SIGNS = ("systolic_bp", "diastolic_bp", "pulse_rate", "temperature", "spo2", "respiratory_rate", "blood_sugar_rbs", "nurse_notes")
GROWTH = ("height_cm", "weight_kg", "head_circumference_cm")
ADULT_GROWTH = ("height_cm", "weight_kg")                    # an adult's height and weight are kept with the other vitals
def _number(value):
    return float(value) if value is not None else None
def _merged(vitals, growth):
    """One object with every field of a visit's vitals, whichever table it came from."""
    one = SimpleNamespace(id=None, recorded_at=None, recorded_by_user_id=None, bmi=None, nurse_notes="",
                          **{f: None for f in VITAL_SIGNS + GROWTH if f != "nurse_notes"})
    for row in (growth, vitals):                               # vitals last: its note and time win
        if row is None:
            continue
        for f in VITAL_SIGNS + GROWTH + ("bmi",):
            if hasattr(row, f) and getattr(row, f) not in (None, ""):
                setattr(one, f, getattr(row, f))
        one.recorded_by_user_id = row.recorded_by_user_id or one.recorded_by_user_id
        one.recorded_at = getattr(row, "recorded_at", None) or timezone.make_aware(datetime.combine(row.measured_on, time(12, 0)))
        one.id = row.id
    return one
def save_visit(patient, appointment_id, hospital_id, user_id, data, *, is_minor):
    """
    Store what the nurse recorded for a visit. `patient` is the atomwalk patient (or None), `data` the validated fields.
    A child's height, weight and head size go to growth_measurement; everything else, and an adult's height and weight,
    to vitals. Returns the visit's vitals as one object.
    """
    common = {"patient": patient, "source_hospital_id": hospital_id, "recorded_by_user_id": user_id}
    kept = VITAL_SIGNS if is_minor else VITAL_SIGNS + ADULT_GROWTH
    Vitals.objects.using("default").update_or_create(
        appointment_id=appointment_id, defaults={**common, **{f: data[f] for f in kept if f in data}})
    if is_minor:
        growth = {f: data[f] for f in GROWTH if f in data}
        rows = GrowthMeasurement.objects.using("default").filter(appointment_id=appointment_id)
        if any(v is not None for v in growth.values()):
            GrowthMeasurement.objects.using("default").update_or_create(
                appointment_id=appointment_id, defaults={**common, "measured_on": timezone.localdate(), **growth})
        elif growth:
            rows.delete()                                      # the nurse cleared them
    return visit_vitals(appointment_id)
def visits_vitals(appointment_ids):
    """{appointment id: that visit's vitals as one object} for the visits that have any."""
    ids = list(appointment_ids)
    vitals = {v.appointment_id: v for v in Vitals.objects.using("default").filter(appointment_id__in=ids)}
    growth = {g.appointment_id: g for g in GrowthMeasurement.objects.using("default").filter(appointment_id__in=ids)}
    return {i: _merged(vitals.get(i), growth.get(i)) for i in set(vitals) | set(growth)}
def visit_vitals(appointment_id):
    return visits_vitals([appointment_id]).get(appointment_id)
def attach_vitals(appointments):
    """Load the vitals of a page of appointments in two queries instead of one per appointment (Appointment.vitals)."""
    appointments = list(appointments)
    found = visits_vitals(a.id for a in appointments)
    for a in appointments:
        a.__dict__["vitals"] = found.get(a.id)
    return appointments
def recorded(appointment_ids):
    """Which of these appointments have vitals recorded."""
    ids = list(appointment_ids)
    done = set(Vitals.objects.using("default").filter(appointment_id__in=ids).values_list("appointment_id", flat=True))
    return done | set(GrowthMeasurement.objects.using("default").filter(appointment_id__in=ids).values_list("appointment_id", flat=True))
def history_readings(awpid, limit=20):
    """
    A patient's latest readings, newest first, one per visit, in the shape the history screens and the emergency summary
    read (bp_systolic, resp_rate ... head_circumference_cm). Another hospital's id is never part of it.
    """
    by_visit, loose = {}, []
    for row in list(Vitals.objects.using("default").filter(patient__awpid=awpid).order_by("-recorded_at")[:limit]) + \
            list(GrowthMeasurement.objects.using("default").filter(patient__awpid=awpid, is_rejected=False).order_by("-measured_on")[:limit]):
        (by_visit.setdefault(row.appointment_id, []) if row.appointment_id else loose).append(row)
    readings = [_reading(*pair) for pair in ((r, None) for r in loose)]
    readings += [_reading(*[next((r for r in rows if isinstance(r, cls)), None) for cls in (Vitals, GrowthMeasurement)])
                 for rows in by_visit.values()]
    return sorted(readings, key=lambda r: r["recorded_at"], reverse=True)[:limit]
def _reading(vitals, growth):
    one = _merged(vitals, growth)
    return {"recorded_at": one.recorded_at, "source": (vitals or growth).source, "bp_systolic": one.systolic_bp,
            "bp_diastolic": one.diastolic_bp, "pulse_rate": one.pulse_rate, "spo2": one.spo2, "temperature": one.temperature,
            "weight_kg": one.weight_kg, "height_cm": one.height_cm, "head_circumference_cm": one.head_circumference_cm,
            "resp_rate": one.respiratory_rate, "blood_sugar_mgdl": one.blood_sugar_rbs}
def growth_points(awpid, *, hospital_id=None, include_other=True):
    """
    The points of a growth chart, one per day, oldest first: {"date", height_cm, weight_kg, head_circumference_cm, bmi,
    "source"}. With a `hospital_id` (the staff view) a reading is "this_hospital" or "other_hospital", and other
    hospitals' readings are left out unless `include_other` and only count on days this hospital has none. Without it (the
    patient's own view) the source is the reading's own: clinic or home.
    """
    points = {}
    rows = [(g.measured_on, g, g.head_circumference_cm) for g in
            GrowthMeasurement.objects.using("default").filter(patient__awpid=awpid, is_rejected=False)]
    rows += [(v.recorded_at.date(), v, None) for v in
             Vitals.objects.using("default").filter(patient__awpid=awpid) if v.height_cm or v.weight_kg]
    for day, row, head in sorted(rows, key=lambda r: r[0]):
        if not (row.height_cm or row.weight_kg or head):
            continue
        if hospital_id is None:
            source = row.source
        elif row.source_hospital_id == hospital_id:
            source = "this_hospital"
        elif include_other:
            source = "other_hospital"
        else:
            continue
        point = {"date": str(day), "height_cm": _number(row.height_cm), "weight_kg": _number(row.weight_kg),
                 "head_circumference_cm": _number(head), "bmi": _number(row.bmi), "source": source}
        if str(day) not in points or (source == "this_hospital" and points[str(day)]["source"] != "this_hospital"):
            points[str(day)] = point
    return sorted(points.values(), key=lambda p: p["date"])
__all__ = ["save_visit", "visit_vitals", "visits_vitals", "attach_vitals", "recorded", "history_readings", "growth_points"]


logger = logging.getLogger(__name__)
def sync_encounter_to_hie(encounter, db, patient, hospital_id=None):
    """
    Copy this encounter's diagnoses to the shared clinical events so other hospitals can see this patient's
    cross-provider history. Never blocks sign-off: all failures are logged and swallowed.

    `hospital_id` is the atomwalk id of the hospital writing the rows (request.hospital_id);
    when omitted (seed commands) it is resolved from `db` — see resolve_source_hospital_id.
    """
    if patient is None or not getattr(patient, "awpid", None):
        logger.warning("HIE sync skipped for encounter %s: no patient/awpid.", encounter.id)
        return

    from apps.atomwalk.documents.models import ClinicalEvent
    from apps.atomwalk.patients.models import Patient
    from apps.atomwalk.hospital_master.services import resolve_source_hospital_id
    from apps.atomwalk.documents import services as episodes
    from apps.atomwalk.documents.services import condition_group

    shared = Patient.objects.using("default").filter(awpid=patient.awpid).first()
    if shared is None:
        logger.warning("HIE sync skipped for encounter %s: %s has no shared patient.", encounter.id, patient.awpid)
        return
    source_hospital_id = hospital_id or resolve_source_hospital_id(db)
    seen_on = getattr(getattr(encounter, "appointment", None), "scheduled_date", None) or date.today()

    # OPDEncounter.diagnoses is a JSON list of {code, description}
    for diag in (encounter.diagnoses or []):
        try:
            ClinicalEvent.objects.using("default").update_or_create(
                patient=shared, source_hospital_id=source_hospital_id, event_type="DIAGNOSIS", icd10=diag.get("code", ""),
                defaults={"condition_text": diag.get("description", ""), "clinical_status": "active", "event_date": seen_on,
                          "condition_group": condition_group(diag.get("code"), diag.get("description")), "source": "HOSPITAL"},
            )
        except Exception:
            logger.exception("HIE ClinicalEvent write failed for encounter=%s", encounter.id)
    try:
        episodes.rebuild(shared)
    except Exception:
        logger.exception("Episodes rebuild failed for encounter=%s", encounter.id)


EPISODE_GAP_DAYS = 30
RECURRENCE_EPISODES = 3
RECURRENCE_MONTHS = 12
_SEVERITY = ["NORMAL", "MILD", "ABNORMAL", "CRITICAL"]
def condition_group(code, text):
    """What counts as "the same condition": the ICD-10 category (J06.9 -> J06), else the condition's name."""
    return (code or "").strip().upper()[:3] or (text or "").strip().upper()[:40]
def _episodes_of(events):
    """Split one condition's events (oldest first) into episodes: a list of event lists."""
    if events[0].category == "CHRONIC":
        return [events]
    episodes = [[events[0]]]
    for event in events[1:]:
        if (event.event_date - episodes[-1][-1].event_date).days > EPISODE_GAP_DAYS:
            episodes.append([event])
        else:
            episodes[-1].append(event)
    return episodes
def rebuild(patient, today=None):
    """Recompute the patient's episodes and recurrence flags from their events."""
    today = today or date.today()
    events = list(ClinicalEvent.objects.using("default")
                  .filter(patient=patient, is_rejected=False, event_date__isnull=False).exclude(condition_group="")
                  .order_by("event_date", "id"))
    by_group = {}
    for event in events:
        by_group.setdefault(event.condition_group, []).append(event)

    kept = set()
    for group, group_events in by_group.items():
        for episode_events in _episodes_of(group_events):
            first, last = episode_events[0], episode_events[-1]
            chronic = first.category == "CHRONIC"
            key = group if chronic else f"{group}:{first.event_date}"
            kept.add(key)
            episode, _ = HealthEpisode.objects.using("default").update_or_create(patient=patient, key=key, defaults={
                "condition_group": group, "label": first.condition_text[:255] or group, "category": first.category or "ACUTE",
                "start_date": first.event_date, "end_date": None if chronic else last.event_date, "last_seen": last.event_date,
                "peak_severity": max((e.severity for e in episode_events), key=_SEVERITY.index), "event_count": len(episode_events),
                "is_provisional": all(e.is_provisional for e in episode_events)})
            ClinicalEvent.objects.using("default").filter(pk__in=[e.pk for e in episode_events]).update(episode=episode)
    HealthEpisode.objects.using("default").filter(patient=patient).exclude(key__in=kept).delete()
    _flag_recurrences(patient, today)
def _flag_recurrences(patient, today):
    since = today - timedelta(days=30 * RECURRENCE_MONTHS)
    counts = {}
    for episode in HealthEpisode.objects.using("default").filter(patient=patient, category="ACUTE", start_date__gte=since):
        counts.setdefault(episode.condition_group, []).append(episode)
    flags = RecurrenceFlag.objects.using("default")
    repeating = {g: es for g, es in counts.items() if len(es) >= RECURRENCE_EPISODES}
    for group, group_episodes in repeating.items():
        flags.update_or_create(patient=patient, condition_group=group, defaults={
            "label": group_episodes[0].label, "triggered_on": max(e.start_date for e in group_episodes),
            "rule": {"episodes": RECURRENCE_EPISODES, "months": RECURRENCE_MONTHS}, "episodes_last_12m": len(group_episodes),
            "clinical_hint": f"{len(group_episodes)} episodes in {RECURRENCE_MONTHS} months"})
    flags.filter(patient=patient).exclude(condition_group__in=repeating).delete()
def rebuild_all():
    """Every patient that has events (after a change to the rules above)."""
    from apps.atomwalk.patients.models import Patient
    ids = ClinicalEvent.objects.using("default").values_list("patient_id", flat=True).distinct()
    for patient in Patient.objects.using("default").filter(pk__in=[i for i in ids if i]):
        rebuild(patient)
_episodes_all__ = ["rebuild", "rebuild_all", "condition_group"]


PATIENT_NOT_FOUND = "Patient not found."
def get_patient(request, pk):
    """This hospital's patient row, or None."""
    return HospitalPatient.objects.using(request.hospital_db).filter(pk=pk).first()
def text(data, key):
    """A request field as stripped text ('' when missing)."""
    return (data.get(key) or "").strip()
def staff_name(request, fallback="Staff"):
    """Who is doing this, for the 'recorded by' columns."""
    return getattr(request.user, "full_name", None) or getattr(request.user, "email", fallback)
def parse_date(value, field, label, *, allow_future=False):
    """
    (date, None) for a YYYY-MM-DD value between 1900 and today (or later when allow_future); a blank value gives
    (None, None); anything else gives (None, a 400 response to return as it is).
    """
    if not value:
        return None, None
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, error(f"{label} must be a valid date.", errors={field: "Enter a valid date."})
    if parsed.year < 1900 or (parsed > date.today() and not allow_future):
        return None, error(f"{label} ({parsed.isoformat()}) doesn't look right — please check the date.",
                           errors={field: "Check the date — it is out of range."})
    return parsed, None


# measurement -> sex -> [(age_months, L, M, S), ...] sorted by age
REFERENCE_TABLES = {
    "weight": {
        "M": [
            (0, 0.3487, 3.3464, 0.1460), (1, 0.2297, 4.4709, 0.1340), (2, 0.1970, 5.5675, 0.1239),
            (3, 0.1738, 6.3762, 0.1173), (6, 0.1257, 7.9340, 0.1096), (9, 0.0917, 8.9014, 0.1088),
            (12, 0.0644, 9.6479, 0.1092), (18, 0.0211, 10.9385, 0.1112), (24, -0.0137, 12.1515, 0.1143),
            (36, -0.0689, 14.3429, 0.1212), (48, -0.1131, 16.3489, 0.1276), (60, -0.1506, 18.3366, 0.1352),
        ],
        "F": [
            (0, 0.3809, 3.2322, 0.1417), (1, 0.1714, 4.1873, 0.1372), (2, 0.0962, 5.1282, 0.1300),
            (3, 0.0402, 5.8458, 0.1262), (6, -0.0756, 7.2970, 0.1220), (9, -0.1507, 8.2254, 0.1220),
            (12, -0.2024, 8.9481, 0.1227), (18, -0.2637, 10.2315, 0.1231), (24, -0.2941, 11.4775, 0.1239),
            (36, -0.3201, 13.8503, 0.1292), (48, -0.3361, 16.0697, 0.1388), (60, -0.3518, 18.2193, 0.1482),
        ],
    },
    # 0-24mo from the length-for-age (recumbent) table, 24-60mo from the
    # height-for-age (standing) table — see module docstring for why.
    "height": {
        "M": [
            (0, 1, 49.8842, 0.0379), (1, 1, 54.7244, 0.0356), (2, 1, 58.4249, 0.0342),
            (3, 1, 61.4292, 0.0333), (6, 1, 67.6236, 0.0316), (9, 1, 71.9687, 0.0312),
            (12, 1, 75.7488, 0.0314), (18, 1, 82.2587, 0.0328), (24, 1, 87.8161, 0.0348),
            (36, 1, 96.0835, 0.0386), (48, 1, 103.3273, 0.0406), (60, 1, 109.9638, 0.0421),
        ],
        "F": [
            (0, 1, 49.1477, 0.0379), (1, 1, 53.6872, 0.0364), (2, 1, 57.0673, 0.0357),
            (3, 1, 59.8029, 0.0352), (6, 1, 65.7311, 0.0345), (9, 1, 70.1435, 0.0344),
            (12, 1, 74.0150, 0.0348), (18, 1, 80.7079, 0.0360), (24, 1, 86.4153, 0.0373),
            (36, 1, 95.0515, 0.0401), (48, 1, 102.7312, 0.0419), (60, 1, 109.4233, 0.0435),
        ],
    },
    "head_circumference": {
        "M": [
            (0, 1, 34.4618, 0.0369), (1, 1, 37.2759, 0.0313), (2, 1, 39.1285, 0.0300),
            (3, 1, 40.5135, 0.0292), (6, 1, 43.3306, 0.0282), (9, 1, 44.9998, 0.0279),
            (12, 1, 46.0661, 0.0279), (18, 1, 47.3711, 0.0280), (24, 1, 48.2515, 0.0282),
            (36, 1, 49.4612, 0.0287), (48, 1, 50.2115, 0.0291), (60, 1, 50.7375, 0.0295),
        ],
        "F": [
            (0, 1, 33.8787, 0.0350), (1, 1, 36.5463, 0.0321), (2, 1, 38.2521, 0.0317),
            (3, 1, 39.5328, 0.0314), (6, 1, 42.1995, 0.0309), (9, 1, 43.8300, 0.0305),
            (12, 1, 44.8965, 0.0303), (18, 1, 46.2424, 0.0299), (24, 1, 47.1822, 0.0296),
            (36, 1, 48.5099, 0.0291), (48, 1, 49.3321, 0.0288), (60, 1, 49.9229, 0.0285),
        ],
    },
}
MEASUREMENTS = ("weight", "height", "head_circumference")
def _lms(measurement, sex, age_months):
    """The (L, M, S) coefficients for this child, or None when the table doesn't cover them (WHO covers 0-60 months, M or F)."""
    table = REFERENCE_TABLES.get(measurement, {}).get(sex)
    if not table or age_months is None or not 0 <= age_months <= 60:
        return None
    for (a0, *c0), (a1, *c1) in zip(table, table[1:]):
        if a0 <= age_months <= a1:
            frac = (age_months - a0) / (a1 - a0)
            return tuple(x0 + frac * (x1 - x0) for x0, x1 in zip(c0, c1))
    return tuple(table[-1][1:])
def get_percentile(measurement, sex, age_months, value):
    """
    {"z_score", "percentile" (0-100)} for one measurement, or None when it can't be scored (no value, age outside
    0-60 months, sex not M or F). measurement: "weight" (kg), "height" or "head_circumference" (cm).
    """
    lms = _lms(measurement, sex, age_months)
    if value is None or lms is None:
        return None
    L, M, S = lms
    value = float(value)
    z = (((value / M) ** L) - 1) / (L * S) if L != 0 else math.log(value / M) / S
    z = max(-5, min(5, z))                         # a wildly out-of-range reading shouldn't blow up the percentile
    return {"z_score": round(z, 2), "percentile": round(0.5 * (1 + math.erf(z / math.sqrt(2))) * 100, 1)}
_MEASURED = {"weight": "weight_kg", "height": "height_cm", "head_circumference": "head_circumference_cm"}
def add_percentiles(series, gender, date_of_birth, *, only_source=None):
    """
    Add a "percentiles" dict to each reading in `series` (dicts with "date" as YYYY-MM-DD, weight_kg, height_cm,
    head_circumference_cm, "source") taken before the child turned 5. `only_source` limits it to readings from that
    source. Returns whether any reading got a percentile.
    """
    if gender not in ("M", "F") or not date_of_birth:
        return False
    found = False
    for point in series:
        if only_source and point["source"] != only_source:
            continue
        taken = date.fromisoformat(point["date"])
        months = (taken.year - date_of_birth.year) * 12 + (taken.month - date_of_birth.month)
        if not 0 <= months <= 60:
            continue
        point["percentiles"] = {}
        for name in MEASUREMENTS:
            result = get_percentile(name, gender, months, point[_MEASURED[name]])
            if result:
                point["percentiles"][name] = result
                found = True
    return found


# slack before "upcoming" flips to "due_now", so a slightly early visit does not look due yet
DUE_LEAD_DAYS = 14
# for a rule with no max_age_days: how long after min_age_days "due_now" lasts before it becomes "past_window"
PAST_WINDOW_GRACE_DAYS = 90
def rule_get(rule, key):
    """A rule may be a model instance or a plain dict."""
    return rule.get(key) if isinstance(rule, dict) else getattr(rule, key, None)
def timing_for(age_days, min_age_days, max_age_days):
    if age_days is None or min_age_days is None:
        return None
    if age_days < min_age_days - DUE_LEAD_DAYS:
        return "upcoming"
    past_from = max_age_days if max_age_days is not None else min_age_days + PAST_WINDOW_GRACE_DAYS
    return "past_window" if age_days >= past_from else "due_now"
def same_name(a, b):
    return (a or "").strip().lower() == (b or "").strip().lower()
def merge(rules, records, *, date_of_birth, same_slot, matched, open_slot):
    """
    One entry per rule, in rule order, then the records that matched no rule (extra=True).
      same_slot(rule, record) -> bool   does this record fill this slot (each record fills at most one)
      matched(rule_or_None, record)     the entry for a slot with a record (rule is None for an extra record)
      open_slot(rule, timing)           the entry for a slot with no record
    """
    age_days = (date.today() - date_of_birth).days if date_of_birth else None
    used, roadmap = set(), []
    for rule in rules:
        record = next((r for r in records if r.id not in used and same_slot(rule, r)), None)
        if record:
            used.add(record.id)
            roadmap.append(matched(rule, record))
        else:
            timing = timing_for(age_days, rule_get(rule, "min_age_days"), rule_get(rule, "max_age_days"))
            roadmap.append(open_slot(rule, timing))
    roadmap += [matched(None, r) for r in records if r.id not in used]
    return roadmap
def rules_for(noun, hospital_id=None):
    """
    The rules to build a roadmap from, in display order: `noun` is "vaccination" or "milestone". A hospital's staff pass
    their hospital_id and get that hospital's active schedule; with no hospital_id (the patient portal, which spans
    hospitals) or when the hospital has none set, the system "Default Schedule" template is used.
    """
    from apps.atomwalk.documents import models
    from apps.atomwalk.hospital_master.models import Hospital

    Schedule = getattr(models, f"{noun.title()}Schedule")
    schedule = None
    if hospital_id:
        hospital = Hospital.objects.using("default").filter(pk=hospital_id).first()
        schedule_id = getattr(hospital, f"active_{noun}_schedule_id", None)
        schedule = Schedule.objects.using("default").filter(pk=schedule_id, active=True).first() if schedule_id else None
    if not schedule:
        schedule = (Schedule.objects.using("default")
                    .filter(owner_hospital_id__isnull=True, is_template=True, active=True).order_by("id").first())
    return list(schedule.rules.order_by("sort_order")) if schedule else []


def _serialize_matched(rule, record):
    status = "completed" if record.verification_status == record.STATUS_VERIFIED else record.verification_status
    return {
        "vaccine_name": record.vaccine_name,
        "scheduled_label": rule_get(rule, "scheduled_label") if rule else record.scheduled_label,
        "administered_date": str(record.administered_date) if record.administered_date else None,
        "due_date": str(record.due_date) if record.due_date else None,
        "reason": record.reason,
        "dose_number": record.dose_number,
        "status": status,
        "timing": None,                       # a real record already settled this slot
        "source": record.source,
        "verification_status": record.verification_status,
        "record_id": record.id,
        "has_certificate": bool(record.file_data),
        "recorded_by": record.recorded_by,    # "staff" or "patient" (a parent's upload)
        "verified_by_name": record.verified_by_name,
        "extra": rule is None,                # a record that fits no slot of the schedule
    }
def build_roadmap(awpid, date_of_birth, rules, *, viewer_hospital_id=None, hie_consent=True):
    """
    `rules`: a queryset or list of VaccinationScheduleRule (or dicts with vaccine_name, scheduled_label, min_age_days,
    max_age_days), in display order; the caller picks the schedule (see rules_for in roadmap.py).

    `hie_consent=False` drops records from OTHER hospitals than viewer_hospital_id. Two kinds stay visible anyway:
    records never attributed to a hospital (source_hospital_id is None), and "pending_review" ones, because any
    hospital's staff must be able to review a parent's upload. Only the staff roadmap passes False; the patient
    portal never filters.
    """
    from apps.atomwalk.documents.models import ImmunizationRecord

    records = ImmunizationRecord.objects.using("default").filter(patient__awpid=awpid)
    if not hie_consent:
        from django.db.models import Q
        records = records.filter(Q(source_hospital_id__isnull=True) | Q(source_hospital_id=viewer_hospital_id)
                                 | Q(verification_status=ImmunizationRecord.STATUS_PENDING))

    def open_slot(rule, timing):
        return {
            "vaccine_name": rule_get(rule, "vaccine_name"), "scheduled_label": rule_get(rule, "scheduled_label"),
            "administered_date": None, "due_date": None, "reason": "", "dose_number": None,
            "status": "unknown", "timing": timing, "source": None, "verification_status": None,
            "record_id": None, "has_certificate": False, "recorded_by": None, "verified_by_name": None, "extra": False,
        }

    return merge(
        list(rules), list(records.order_by("administered_date")), date_of_birth=date_of_birth,
        same_slot=lambda rule, r: (r.scheduled_label == rule_get(rule, "scheduled_label")
                                   and same_name(r.vaccine_name, rule_get(rule, "vaccine_name"))),
        matched=_serialize_matched, open_slot=open_slot)
def summarize_roadmap(roadmap):
    """
    Counts for "N of M completed". Only the schedule's own slots count (not `extra` records).
    `next_recommended` is the first unknown slot that is due now.
    stats: completed; upcoming (unknown, window not open yet); needs_review (pending_review, or unknown and due now /
    past window: an open question for the parent or doctor); outside (records, extra or not, not given at a clinic).
    """
    slots = [item for item in roadmap if not item.get("extra")]
    unknown = [i for i in slots if i["status"] == "unknown"]
    completed = sum(1 for i in slots if i["status"] == "completed")
    return {
        "completed_count": completed,
        "total_count": len(slots),
        "next_recommended": next((i for i in unknown if i.get("timing") == "due_now"), None),
        "stats": {
            "completed": completed,
            "upcoming": sum(1 for i in unknown if i.get("timing") == "upcoming"),
            "needs_review": sum(1 for i in slots if i["status"] == "pending_review")
                            + sum(1 for i in unknown if i.get("timing") in ("due_now", "past_window")),
            "outside": sum(1 for i in roadmap if i.get("source") not in (None, "clinic")),
        },
    }


def _milestone_roadmap_serialize_matched(rule, record):
    return {
        "domain": record.domain,
        "milestone": record.milestone,
        "scheduled_label": rule_get(rule, "scheduled_label") if rule else record.scheduled_label,
        "achieved_date": str(record.achieved_date) if record.achieved_date else None,
        "assessed_date": str(record.assessed_date) if record.assessed_date else None,
        "status": record.status,
        "timing": None,                      # a real assessment already settled this slot
        "notes": record.notes,
        "record_id": record.id,
        "recorded_by_name": record.recorded_by_name,
        "extra": rule is None,
    }
def milestone_roadmap_build_roadmap(awpid, date_of_birth, rules, *, viewer_hospital_id=None, hie_consent=True):
    """
    The child's real MilestoneRecord rows laid over a schedule's rules (see roadmap.py). `rules` is a queryset or
    list of MilestoneScheduleRule (or dicts with domain, milestone, scheduled_label, min_age_days, max_age_days),
    already in display order. `hie_consent=False` drops records logged at a hospital other than viewer_hospital_id;
    there is no cross-hospital review step for milestones, so nothing is exempt.
    """
    from apps.atomwalk.documents.models import MilestoneRecord

    records = MilestoneRecord.objects.using("default").filter(patient__awpid=awpid)
    if not hie_consent:
        from django.db.models import Q
        records = records.filter(Q(source_hospital_id__isnull=True) | Q(source_hospital_id=viewer_hospital_id))

    def open_slot(rule, timing):
        return {
            "domain": rule_get(rule, "domain"), "milestone": rule_get(rule, "milestone"),
            "scheduled_label": rule_get(rule, "scheduled_label"), "achieved_date": None, "assessed_date": None,
            "status": "unassessed", "timing": timing, "notes": "", "record_id": None, "recorded_by_name": None,
            "extra": False,
        }

    return merge(
        list(rules), list(records.order_by("assessed_date")), date_of_birth=date_of_birth,
        same_slot=lambda rule, r: (r.scheduled_label == rule_get(rule, "scheduled_label")
                                   and r.domain == rule_get(rule, "domain")
                                   and same_name(r.milestone, rule_get(rule, "milestone"))),
        matched=_milestone_roadmap_serialize_matched, open_slot=open_slot)
def milestone_roadmap_summarize_roadmap(roadmap):
    """Counts for "N of M achieved": only the schedule's own slots count (not `extra` assessments)."""
    slots = [item for item in roadmap if not item.get("extra")]
    unassessed = [i for i in slots if i["status"] == "unassessed"]
    achieved = sum(1 for i in slots if i["status"] == "achieved")
    return {
        "achieved_count": achieved,
        "total_count": len(slots),
        "next_recommended": next((i for i in unassessed if i.get("timing") == "due_now"), None),
        "stats": {
            "achieved": achieved,
            "upcoming": sum(1 for i in unassessed if i.get("timing") == "upcoming"),
            "needs_review": sum(1 for i in slots if i["status"] == "concern")
                            + sum(1 for i in unassessed if i.get("timing") in ("due_now", "past_window")),
            "not_yet": sum(1 for i in slots if i["status"] == "not_yet"),
        },
    }


def vaccination_rule_dict(rule):
    return {
        "id": rule.id,
        "vaccine_name": rule.vaccine_name,
        "dose_number": rule.dose_number,
        "scheduled_label": rule.scheduled_label,
        "min_age_days": rule.min_age_days,
        "max_age_days": rule.max_age_days,
        "mandatory": rule.mandatory,
        "sort_order": rule.sort_order,
    }
def milestone_rule_dict(rule):
    return {
        "id": rule.id,
        "domain": rule.domain,
        "milestone": rule.milestone,
        "scheduled_label": rule.scheduled_label,
        "min_age_days": rule.min_age_days,
        "max_age_days": rule.max_age_days,
        "mandatory": rule.mandatory,
        "sort_order": rule.sort_order,
    }
def schedule_dict(schedule, active_id=None, rule_count=None):
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "is_template": schedule.is_template,
        "active": schedule.active,
        "owner_hospital_id": schedule.owner_hospital_id,
        "is_active_for_this_hospital": active_id is not None and schedule.id == active_id,
        "rule_count": rule_count if rule_count is not None else schedule.rules.count(),
    }
def template_dict(schedule, rule_count=None, hospitals_using=None):
    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "active": schedule.active,
        "created_at": schedule.created_at.isoformat(),
        "updated_at": schedule.updated_at.isoformat(),
        "rule_count": rule_count if rule_count is not None else schedule.rules.count(),
        "hospitals_using": hospitals_using,
    }
