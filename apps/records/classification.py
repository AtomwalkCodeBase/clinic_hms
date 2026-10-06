"""
Document classification — the rule engine, and the one place that decides a document's type.

    OCR text  ->  classify_document_by_rules()  ->  PatientDocumentClassification  (+ MedicalDocument.document_type)

The Celery task (tasks.py) only orchestrates; the document types, the keywords and the scoring all live here, in
code. There is no database table of types and nothing configurable at run time: to change a keyword, edit
DOCUMENT_RULES below. No LLM, no vision model: rules only.

Scoring (not a probability — nothing here is calibrated against labelled data yet):

    strong keyword    +10        medium keyword    +3        weak keyword    +1

Keywords are matched as whole words (so "rx" is not found inside "xerox"), each keyword counts once. The type with
the highest score wins only if it beats the runner-up by at least MIN_MARGIN points; otherwise the document is
"not_classified" and needs a person (status "review_required"). A person's choice always replaces the rules'.

Codes are lower-case snake_case everywhere (database, API, apps), e.g. "lab_report".
"""
import re

from django.core.exceptions import ObjectDoesNotExist

# ── the types (fixed: the rule engine never creates new ones) ─────────────
NOT_CLASSIFIED = "not_classified"      # no verdict yet, or no type fits well enough

DOCUMENT_TYPES = {
    "prescription": "Prescription",
    "lab_report": "Lab Report",
    "imaging_report": "Imaging Report",
    "discharge_summary": "Discharge Summary",
    "consultation_note": "Consultation Note",
    "medical_bill": "Medical Bill",
    "vaccination_record": "Vaccination Record",
    "referral_letter": "Referral Letter",
    "medical_certificate": "Medical Certificate",
    "other": "Other",
    NOT_CLASSIFIED: "Not Classified",
}
DOCUMENT_TYPE_CHOICES = list(DOCUMENT_TYPES.items())
# What a person may file a document under. "not_classified" is a state, not a choice.
CHOOSABLE_TYPES = [code for code in DOCUMENT_TYPES if code != NOT_CLASSIFIED]

# ── classification result states (PatientDocumentClassification.status) ──
RULE_CLASSIFIED = "rule_classified"      # the rules found a clear winner
REVIEW_REQUIRED = "review_required"      # weak or ambiguous: a person has to decide
HUMAN_CLASSIFIED = "human_classified"    # a person chose the type (never overwritten by the rules)
ISSUED = "issued"                        # a hospital supplied the type with the document it made

CLASSIFIER_RULES = "rule_engine"
CLASSIFIER_HUMAN = "human"
CLASSIFIER_HOSPITAL = "hospital"

# ── scoring ──────────────────────────────────────────────────────────────
WEIGHTS = {"strong": 10, "medium": 3, "weak": 1}
MIN_MARGIN = 5      # the winner must lead the runner-up by this many points

DOCUMENT_RULES = {
    "prescription": {
        "strong": ["prescription", "e-prescription", "rx", "c/o", "chief complaints", "medication prescribed", "take medicine", "prescribed by"],
        "medium": ["tablet", "tab", "capsule", "cap", "syrup", "syp", "injection", "inj", "mg", "ml", "dosage", "once daily", "twice daily",
                   "bd", "tds", "od", "hs", "qid", "sos", "before food", "after food", "before breakfast", "at night", "ointment",
                   "eye drops", "next visit", "review after", "adv"],
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
        "strong": ["invoice", "tax invoice", "amount payable", "total amount", "bill no", "gst", "gstin", "net payable", "amount in words",
                   "receipt", "authorised signatory", "payment mode"],
        "medium": ["subtotal", "sub total", "discount", "quantity", "rate", "net amount", "qty", "mrp", "batch", "with thanks", "rupees", "charges"],
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


def _dedupe_levels(rules):
    """A keyword counts once per type: if it is listed at two levels, only the strongest one stays."""
    for levels in rules.values():
        seen = set()
        for level in ("strong", "medium", "weak"):
            levels[level] = [k for k in levels.get(level, []) if not (k in seen or seen.add(k))]
    return rules


DOCUMENT_RULES = _dedupe_levels(DOCUMENT_RULES)


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
    """Whole-word match: not glued to other letters (digits are fine, so "500mg" finds "mg")."""
    if keyword not in _PATTERNS:
        _PATTERNS[keyword] = re.compile(r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])")
    return _PATTERNS[keyword]


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", s)


def _found(keyword, text, squashed):
    """Whole-word match; for a phrase, also tolerate OCR dropping the spaces ("ReferenceRange")."""
    if _pattern(keyword).search(text):
        return True
    return " " in keyword and len(_squash(keyword)) > 5 and _squash(keyword) in squashed


def calculate_document_scores(text):
    """{type: {"score": int, "matched_rules": [{"keyword", "weight", "level"}]}} for every type that has rules."""
    text = prepare_text(text)
    squashed = _squash(text)
    scores = {}
    for document_type, rules in DOCUMENT_RULES.items():
        score, matched = 0, []
        for level in ("strong", "medium", "weak"):
            for keyword in rules.get(level, []):
                if _found(keyword, text, squashed):
                    score += WEIGHTS[level]
                    matched.append({"keyword": keyword, "weight": WEIGHTS[level], "level": level})
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
    from .models import PatientDocumentClassification
    classification, _ = PatientDocumentClassification.objects.using("default").get_or_create(document=document)
    if classification.status in (HUMAN_CLASSIFIED, ISSUED):
        return classification
    classification.ai_document_type = result["best_guess"] or NOT_CLASSIFIED
    classification.classifier = CLASSIFIER_RULES
    classification.rule_score = result["score"]
    classification.second_best_score = result["second_best_score"]
    classification.score_margin = result["score_margin"]
    classification.rule_matches = result["matched_rules"]
    classification.final_document_type = result["document_type"]
    classification.status = result["status"]
    classification.save()
    document.document_type = result["document_type"]
    return classification


def store_human_choice(document, document_type):
    """A person files the document under `document_type`. It replaces whatever the rules said."""
    if document_type not in CHOOSABLE_TYPES:
        raise ValueError("Choose one of the available document types.")
    from .models import PatientDocumentClassification
    classification, _ = PatientDocumentClassification.objects.using("default").get_or_create(document=document)
    classification.human_document_type = document_type
    classification.final_document_type = document_type
    classification.status = HUMAN_CLASSIFIED
    classification.save()
    document.document_type = document_type
    return classification


def store_issued_type(document, document_type):
    """A hospital-issued document brings its own type: no rules, no review."""
    from .models import PatientDocumentClassification
    document_type = document_type if document_type in CHOOSABLE_TYPES else "other"
    classification, _ = PatientDocumentClassification.objects.using("default").get_or_create(document=document)
    classification.classifier = CLASSIFIER_HOSPITAL
    classification.ai_document_type = None
    classification.final_document_type = document_type
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
        return document.text.extracted_text
    except ObjectDoesNotExist:
        return ""

