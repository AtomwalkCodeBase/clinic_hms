"""The document pipeline: upload, extraction, the keyword rules that classify a document, the patient's review step and hospital-issued documents."""

import io
import logging
import mimetypes
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime

from apps.documents import ocr
from apps.documents.models import CHOOSABLE_TYPES, CLASSIFIER_HOSPITAL, CLASSIFIER_RULES, DOCUMENT_TYPES, DocumentBatch, DocumentClassification, DocumentExtraction, HUMAN_CLASSIFIED, ISSUED, MedicalDocument, NOT_CLASSIFIED, REVIEW_REQUIRED, RULE_CLASSIFIED
from apps.documents.serializers import MAX_FILE_BYTES
from apps.opd.models import HospitalPatient
from apps.patients.models import Patient
from core import storage
from core.api.response import error
from core.utils.file_validation import FileValidationError, validate_bytes
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.db import connections, transaction
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)


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
    """(date, None) for a YYYY-MM-DD value between 1900 and today (or later when allow_future); a blank value gives"""
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
    """A keyword counts once per type: if it is listed twice (at any level, spelt differently or as a plural), only the"""
    for levels in rules.values():
        seen = set()
        for level in ("strong", "medium", "weak"):
            levels[level] = [k for k in levels.get(level, []) if not (_canon(k) in seen or seen.add(_canon(k)))]
    return rules
DOCUMENT_RULES = _dedupe_levels(DOCUMENT_RULES)
# Patterns that are not words. A written dose such as 1-0-1 or 0-1-0 (morning-noon-night) is a clue for a prescription,
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
    """Whole-word match: not glued to other letters (digits are fine, so "500mg" finds "mg"). The words of a phrase may"""
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
    """The rules' verdict on `text`:"""
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
    """Save the rules' verdict: the classification row and the document's current type. A person's choice is"""
    classification, _ = DocumentClassification.objects.using("default").get_or_create(document=document)
    if classification.status in (HUMAN_CLASSIFIED, ISSUED):
        return classification
    classification.ai_classification = result["best_guess"] or NOT_CLASSIFIED
    classification.classifier = CLASSIFIER_RULES
    classification.rule_score = result["score"]
    classification.second_best_score = result["second_best_score"]
    classification.rule_matches = result["matched_rules"]
    classification.status = result["status"]
    classification.save()
    document.doc_classification = result["document_type"]
    return classification
def store_human_choice(document, document_type):
    """A person files the document under `document_type`. It replaces whatever the rules said."""
    if document_type not in CHOOSABLE_TYPES:
        raise ValueError("Choose one of the available document types.")
    classification, _ = DocumentClassification.objects.using("default").get_or_create(document=document)
    classification.human_classification = document_type
    classification.status = HUMAN_CLASSIFIED
    classification.save()
    document.doc_classification = document_type
    return classification
def store_issued_type(document, document_type):
    """A hospital-issued document brings its own type: no rules, no review."""
    document_type = document_type if document_type in CHOOSABLE_TYPES else "other"
    classification, _ = DocumentClassification.objects.using("default").get_or_create(document=document)
    classification.classifier = CLASSIFIER_HOSPITAL
    classification.ai_classification = NOT_CLASSIFIED
    classification.status = ISSUED
    classification.save()
    document.doc_classification = document_type
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
        return document.d_classification
    except ObjectDoesNotExist:
        return None
def method_of(document):
    """How the type was decided: "rule" (the keyword rules), "staff" (a person, or the hospital that issued the"""
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
    if c and c.status == RULE_CLASSIFIED and c.ai_classification not in (None, "", NOT_CLASSIFIED):
        return c.ai_classification
    return None
def best_guess_of(document):
    """For a document no type fit: the type the rules came closest to (else "")."""
    c = _classification(document)
    if document.doc_classification == NOT_CLASSIFIED and c and c.ai_classification not in (None, "", NOT_CLASSIFIED):
        return c.ai_classification
    return ""
def text_of(document):
    try:
        return document.d_extraction.extracted_text
    except ObjectDoesNotExist:
        return ""


UPLOAD_THREADS = 8    # files sent to S3 at the same time
_UPLOAD_EXT = {"pdf", "jpg", "jpeg", "png"}
_DECLARED_MIME = {"application/pdf", "image/jpeg", "image/png"}
Status = MedicalDocument.Status


def source_uuid(value):
    """MedicalDocument.source_id is a UUID. An encounter's id already is one; any other id (a lab request "<db>:<n>", a"""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"atomwalk:{value}")


def display_name(doc):
    """What the patient sees for a file: the name it was uploaded with (kept in document_ref_name), else its stored name."""
    return doc.document_ref_name or os.path.basename(doc.file_name.name or "")


def uploaded_by_of(doc):
    """The API still says who added a file as "patient" or "staff" (what the screens read); the model keeps patient / hospital."""
    return "staff" if doc.created_by_type == "H" else "patient"


def size_of(doc):
    """The stored file's size in bytes, or None when it can't be read (one call to storage: for a single document, not a list)."""
    try:
        return doc.file_name.size
    except Exception:
        return None


def document_rows(queryset, limit=50):
    """Documents in the shape the history screens read: id, title, file_name, mime_type, doc_type, uploaded_by, created_at."""
    return [{"id": d.id, "title": display_name(d), "file_name": display_name(d), "mime_type": mime_of(d),
             "doc_type": d.doc_classification, "uploaded_by": uploaded_by_of(d), "created_at": d.created_at}
            for d in queryset.order_by("-created_at")[:limit]]


def mime_of(doc):
    """The file's type, from its extension (the content itself was verified when it was extracted)."""
    return mimetypes.guess_type(doc.file_name.name or "")[0] or "application/pdf"


# Two Celery queues, so one file never waits behind someone else's big upload: "instant" is for a single file,
INSTANT_QUEUE = "instant"
BULK_QUEUE = "bulk"
MAX_SUBMIT = 100            # decisions in one submit call
# ── upload ───────────────────────────────────────────────────────────────
def _stored_name(filename):
    """<random>.<ext> — never the uploader's file name (that is kept apart, in MedicalDocument.document_ref_name)."""
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return f"{uuid.uuid4().hex}.{ext if ext in _UPLOAD_EXT else 'bin'}"
def _safe_delete(name: str) -> None:
    """Only ever deletes inside documents/ or patients/ — a bug or a wrong path can't cost anything else in the bucket."""
    if name and name.startswith(("documents/", "patients/")):
        storage.delete(name)
    elif name:
        logger.warning("records: refusing to delete %r — not a documents/ or patients/ object", name)
def save_upload(awpid, files):
    """`files` = [(uploaded_file, raw_bytes)]. One batch per upload, however many files. The files go to S3"""
    patient = Patient.objects.using("default").get(awpid=awpid)
    batch = DocumentBatch.objects.create(patient=patient)
    docs = [MedicalDocument(patient=patient, batch=batch, document_ref_name=(f.name or "")[:50],
                            created_by_type="P", status=Status.QUEUED)
            for f, raw in files]

    def send(i):
        f, raw = files[i]
        content = ContentFile(raw, name=_stored_name(f.name))
        content.content_type = f.content_type if f.content_type in _DECLARED_MIME else "application/octet-stream"
        docs[i].file_name.save(content.name, content, save=False)      # → S3: patients/<awpid>/documents/<name>

    try:
        with ThreadPoolExecutor(max_workers=min(UPLOAD_THREADS, len(files))) as pool:
            list(pool.map(send, range(len(files))))
        with transaction.atomic(using="default"):
            MedicalDocument.objects.bulk_create(docs)
    except Exception:
        for d in docs:
            _safe_delete(d.file_name.name if d.file_name else "")
        batch.delete()
        raise
    return batch, list(MedicalDocument.objects.filter(batch=batch).order_by("id"))
def start_processing(document_ids, queue=BULK_QUEUE):
    """Queue each document's first stage on `queue`. If the queue can't be reached the document is marked failed -"""
    from apps.documents.tasks import extract_document_task
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
    docs = list(batch.b_documents.select_related("d_classification").order_by("id"))
    counts = {s: 0 for s in Status.values}
    for d in docs:
        counts[d.status] = counts.get(d.status, 0) + 1
    finished = sum(counts.get(k, 0) for k in (Status.COMPLETED, Status.REVIEW_REQUIRED, Status.FAILED))
    total = len(docs)
    return {
        "id": batch.id, "total_files": total, "created_at": batch.created_at,
        "status": "processing" if finished < total else "completed",
        "progress_percent": int(round(100.0 * finished / total)) if total else 100,
        "counts": counts,
        "documents": [{"id": d.id, "file_name": display_name(d), "status": d.status,
                       "processing_status": d.status, "doc_type": d.doc_classification, "method": method_of(d),
                       "error": d.error_message} for d in docs],
    }
# ── processing ───────────────────────────────────────────────────────────
@contextmanager
def _locked(document_id):
    """True if this call got document_id's lock; released on exit. A Postgres advisory lock, so a live"""
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
    """Stage 1: file → content check → text. Returns True when the document is ready for classify_document."""
    with _locked(document_id) as got:
        if not got:
            return False
        doc = _in_status(document_id, Status.QUEUED, Status.EXTRACTING, Status.CLASSIFYING)
        if not doc:
            return False
        if doc.status == Status.CLASSIFYING:
            return True
        if doc.status != Status.EXTRACTING:
            doc.status = Status.EXTRACTING
            doc.save(update_fields=["status", "updated_at"])
        raw = storage.get_bytes(doc.file_name.name)
        try:
            if not raw:
                raise ValueError("The file is empty.")
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("The file is over 250 MB.")
            mime = validate_bytes(raw)
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
        doc.status = Status.CLASSIFYING
        doc.save(update_fields=["status", "updated_at"])
        return True
def classify_document(document_id):
    """Stage 2: the rule engine on the extracted text → the document's classification. A person's choice is never"""
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
    """Run today's rules again over documents the rules classified (never a person's choice, never a hospital-issued"""
    counts = {"checked": 0, "changed": 0, "classified": 0, "unclassified": 0}
    docs = (MedicalDocument.objects
            .filter(status__in=(Status.COMPLETED, Status.REVIEW_REQUIRED), source_hospital_id__isnull=True,
                    d_classification__status__in=(RULE_CLASSIFIED, REVIEW_REQUIRED),
                    d_extraction__isnull=False)
            .order_by("id")[:limit])
    for doc in docs:
        before = doc.doc_classification
        result = classify_document_by_rules(text_of(doc))
        store_rule_result(doc, result)
        doc.status = Status.REVIEW_REQUIRED if result["status"] == REVIEW_REQUIRED else Status.COMPLETED
        doc.save(update_fields=["doc_classification", "status", "updated_at"])
        counts["checked"] += 1
        counts["changed"] += doc.doc_classification != before
        counts["unclassified" if doc.doc_classification == NOT_CLASSIFIED else "classified"] += 1
    return counts
def correct_document(doc, document_type):
    """A person files the document under `document_type` - one file at a time. It replaces whatever the rules said"""
    if is_confirmed(doc):
        raise DocumentLocked("This document is confirmed and can't be changed.")
    if doc.status in MedicalDocument.IN_PROGRESS:
        raise ValueError("This file is still being read.")
    store_human_choice(doc, document_type)
    _end(doc, Status.COMPLETED, error_message="")
# ── the review step: which uploads still wait for the patient's decision ─────
def review_starts_at():
    """When the review step began (settings.RECORDS_REVIEW_FROM, an ISO date-time). Everything uploaded before it is"""
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
    return (Q(created_by_type="P", source_hospital_id__isnull=True, created_at__gte=start)
            & ~Q(d_classification__status__in=(HUMAN_CLASSIFIED, ISSUED)))
def document_counts(awpid):
    """What the My Documents dropdown and the badges need: {"total", "awaiting_review", "unclassified", "by_type"}."""
    docs = MedicalDocument.objects.using("default").filter(patient__awpid=awpid)
    awaiting = awaiting_review_q()
    done = (Status.COMPLETED, Status.REVIEW_REQUIRED)
    by_type = {code: 0 for code in CHOOSABLE_TYPES}
    for row in docs.exclude(awaiting).filter(status__in=done).values("doc_classification").annotate(n=Count("id")):
        if row["doc_classification"] in by_type:
            by_type[row["doc_classification"]] = row["n"]
    return {
        "total": docs.exclude(awaiting).filter(status__in=done).count(),
        "awaiting_review": docs.filter(awaiting, status__in=done).count(),
        "unclassified": docs.exclude(awaiting).filter(status__in=done, doc_classification=NOT_CLASSIFIED).count(),
        "by_type": by_type,
    }
def submit_decisions(awpid, decisions):
    """The patient's final answer for a list of files: [{"document_id", "document_type"}]. Each file is checked on"""
    wanted = [d["document_id"] for d in decisions]
    docs = {d.id: d for d in MedicalDocument.objects.using("default").filter(patient__awpid=awpid, pk__in=wanted)
            .select_related("d_classification")}
    submitted, rejected, seen = [], [], set()

    def reject(doc_id, reason):
        rejected.append({"document_id": doc_id, "reason": reason})

    for decision in decisions:
        doc_id, doc_type = decision["document_id"], decision["document_type"]
        doc = docs.get(doc_id)
        if doc_id in seen:
            continue
        seen.add(doc_id)
        if doc is None or doc.source_hospital_id or doc.created_by_type == "H":
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
    """A patient may remove an upload that failed, or one that has been read but whose type they have not confirmed yet"""
    if doc.status == Status.FAILED:
        return True
    if doc.status not in (Status.COMPLETED, Status.REVIEW_REQUIRED):
        return False
    return MedicalDocument.objects.using("default").filter(pk=doc.pk).filter(awaiting_review_q()).exists()
def dismiss_document(doc):
    """The patient removes an upload (see `can_discard`): its stored copy and its rows. A document that is being read"""
    if not can_discard(doc):
        raise ValueError("Only a file that failed, or one you haven't confirmed yet, can be removed.")
    batch, name = doc.batch, (doc.file_name.name if doc.file_name else "")
    doc.delete()
    _safe_delete(name)
    if batch:
        if not batch.b_documents.exists():
            batch.delete()
def _queue_processing(document_id):
    """Read a hospital-issued document for the timeline too (its text, then its facts), once its row is committed."""
    def queue():
        try:
            from apps.documents.tasks import process_document_task
            process_document_task.apply_async(args=[document_id], queue=BULK_QUEUE)
        except Exception:
            logger.warning("records: couldn't queue the timeline facts for document %s", document_id, exc_info=True)
    transaction.on_commit(queue, using="default")
def create_issued_document(*, awpid, file_path, name, doc_type, source_hospital_id, source_type, source_id, mime_type="application/pdf",
                           public_document_id="", document_date=None):
    """A document a hospital made for the patient (signed prescription, lab report, handwriting): it is already in"""
    doc = MedicalDocument(
        patient=Patient.objects.using("default").get(awpid=awpid), created_by_type="H",
        source_hospital_id=source_hospital_id, source_type=source_type,
        source_id=source_uuid(source_id) if source_id else None, document_ref_name=(public_document_id or name or "")[:50], document_date=document_date, status=Status.COMPLETED)
    doc.file_name = file_path
    doc.save(using="default")
    store_issued_type(doc, doc_type)
    doc.save(using="default", update_fields=["doc_classification"])
    _queue_processing(doc.pk)
    return MedicalDocument.objects.using("default").get(pk=doc.pk)
def extract_text(raw, mime):
    """(text, engine). PDF text layer if it has one ("pdf_text"), otherwise RapidOCR on the image or the first PDF"""
    if mime == "application/pdf":
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages[:5]).strip()
        if len(text) >= 40:
            return text, "pdf_text"
        return "\n".join(ocr.run(png).text for png in ocr.pdf_page_images(raw)).strip(), "ocr"
    return ocr.run(raw).text.strip(), "ocr"


def _read_file(doc):
    return storage.get_bytes(doc.file_name.name)
def document_text(doc):
    """The document's extracted text. A hospital-issued document skipped the upload pipeline, so it has none yet:"""
    try:
        stored = doc.d_extraction.extracted_text
    except DocumentExtraction.DoesNotExist:
        stored = ""
    if stored:
        return stored
    text, engine = extract_text(_read_file(doc), mime_of(doc))      # not read yet (the extraction row may already exist, empty)
    DocumentExtraction.objects.update_or_create(document=doc, defaults={"extracted_text": text, "engine": engine})
    return text


def batch_counts(batch):
    counts = dict(batch.b_documents.values_list("status").annotate(n=Count("id")))
    total = sum(counts.values())
    processed = counts.get(MedicalDocument.Status.COMPLETED, 0) + counts.get(MedicalDocument.Status.REVIEW_REQUIRED, 0)
    failed = counts.get(MedicalDocument.Status.FAILED, 0)
    status = "processing" if processed + failed < total else "completed_with_errors" if failed else "completed"
    return {"total_files": total, "processed_files": processed, "failed_files": failed, "status": status}
