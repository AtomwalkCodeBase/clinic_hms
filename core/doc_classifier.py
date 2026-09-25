"""
core/doc_classifier.py
----------------------
Sort an outside (no-QR) upload into the My Reports vault: what *kind* of
document it is (prescription / lab report / imaging / discharge summary /
other), for a lab report *which panel(s)* (CBC, Lipid, Thyroid...), and the
*date* printed on it. It never reads or stores a test value.

Pipeline, per document:

    1. image-quality gate   (core.image_quality)  -> unreadable? hand back
    2. text                 (PDF text layer; OCR for a photo)
    3. kind                 keyword vocabulary  -> prescription | lab_report | scan | discharge_summary | other
    4. panel(s)             core.report_types   -> categories[]  (lab_report only)
    5. date(s)              core.doc_dates      -> report_date + collection_date + source
    6. gate                 confident on kind AND panel AND date -> file it
                            otherwise -> review tray, asking only what failed

`classify(raw, mime_type)` keeps its old signature and its old ClassResult
attributes (`doc_type`, `confidence`, `method`, `doc_date`, `confident`);
callers that want the new fields read `categories`, `category_confidence`,
`collection_date`, `date_source`, `unreadable`.

An optional LLM stage can be slotted in behind `settings.DOC_CLASSIFIER_LLM`
for the low-confidence tail (see `_llm_refine`); it is a no-op by default and
the deterministic path above is complete without it.
"""

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from core import doc_dates, doc_rules, image_quality, ocr, report_types

logger = logging.getLogger(__name__)

CONFIDENT = 0.75          # kind gate
_MIN_TEXT = 40            # chars below which there's nothing to classify on

# ── kind vocabulary ─────────────────────────────────────────────────────
# Built-in defaults only. The live vocabulary is the doc_classification_rule
# table (platform admin → Classification rules), read through core.doc_rules;
# these tuples seeded that table and are the fallback when it is empty.
_LAB_HINTS = (
    "reference range", "reference interval", "ref. range", "ref range", "bio. ref",
    "normal range", "biological reference", "haemoglobin", "hemoglobin", "platelet",
    "wbc count", "rbc count", "differential count", "mg/dl", "mmol/l", "iu/l", "u/l",
    "ng/ml", "pg/ml", "meq/l", "specimen", "sample type", "collected on", "reported on",
    "test name", "result value", "lab no", "lab id", "pathology", "haematology",
    "biochemistry", "serology", "microbiology", "serum", "plasma", "investigation",
    "method :", "sample received", "nabl",
    # deliberately NOT included: bare "result", "units", "interpretation" —
    # too generic on their own (show up in imaging/discharge/admin text too)
    # and were enough by themselves to push kind confidence for near-empty
    # boilerplate text above the auto-file gate.
)
_RX_HINTS = (
    "prescription", "sig:", "rx", "tab.", "cap.", "syrup", "syp.", "tablet", "capsule",
    "ointment", "inj.", "once daily", "twice daily", "thrice daily", "every night",
    "before food", "after food", "at bedtime", "as needed", "1-0-1", "0-0-1", "1-1-1",
    "bd", "tds", "od ", "hs ", "sos", "chief complaint", "diagnosis:", "advice:",
    "advised", "follow up", "follow-up", "dosage", "duration", "frequency", "route",
    "reg. no", "regn no", "m.b.b.s", "mbbs", "consulting physician", "consultant",
    "medications", "next visit", "review after",
)
_IMG_HINTS = (
    "x-ray", "x ray", "radiograph", "ultrasound", "ultrasonography", "sonography",
    "usg ", "u.s.g", "ct scan", "c.t. scan", "mri ", "m.r.i", "doppler", "mammography",
    "mammogram", "dexa", "bone densitometry", "impression:", "impression :",
    "no significant abnormality", "no acute", "radiologist", "findings:", "findings :",
    "screening", "contrast study", "plain study", "echocardiography", "2d echo",
)
_DISCHARGE_HINTS = (
    "discharge summary", "discharge card", "date of admission", "date of discharge",
    "admission date", "discharge date", "course in the hospital", "hospital course",
    "condition at discharge", "condition on discharge", "discharge medications",
    "final diagnosis", "provisional diagnosis", "treatment given", "advice on discharge",
    "ip no", "ipd no", "mrd no", "bed no", "ward",
)
_NON_MEDICAL_HINTS = (
    # billing / receipts (patients often photograph the payment slip too)
    "invoice", "tax invoice", "proforma invoice", "bill no", "cash memo", "credit note",
    "debit note", "gst", "gstin", "cgst", "sgst", "igst", "hsn code", "sac code",
    "amount payable", "amount paid", "amount in words", "grand total", "sub total",
    "subtotal", "round off", "balance due", "receipt no", "payment received",
    "mode of payment", "upi ref", "transaction id", "order id", "unit price",
    "net amount", "billing address", "shipping address",
    # a pharmacy OP bill lists the same drug names as a real prescription —
    # these tokens are what actually distinguish "shop charging for medicine
    # already sold" from "doctor ordering medicine" (added 2026-09-22 after a
    # real pharmacy receipt was filed as a prescription in production: it hit
    # only "gst" from the list above, once, so the >=2-hits rule below never
    # fired; see _NON_MEDICAL_STRONG).
    "op receipt", "net payable", "total outstanding", "d.l.no",
    # identity documents (also a privacy red flag for the medical vault)
    "aadhaar", "aadhar", "uidai", "unique identification authority",
    "permanent account number", "income tax department", "passport no", "voter id",
    "election commission", "driving licence", "driving license",
    # other clearly non-clinical paperwork
    "curriculum vitae", "boarding pass", "e-ticket", "bank statement",
    "statement of account", "account no", "opening balance", "closing balance",
    "salary slip", "pay slip", "payslip", "admit card", "hall ticket",
    "mark sheet", "marksheet", "electricity bill", "rent agreement",
)
# A tighter subset: commerce/billing tokens specific enough that they don't
# plausibly appear on a genuine prescription or lab report even when one is
# ALSO full of drug names or lab terms (a pharmacy bill lists "Tab.", "Cream",
# dosage-looking batch numbers etc. — that's exactly why the general
# _medical_signal check alone isn't enough to catch it). 2+ of these force
# non_medical regardless of _medical_signal; also drives `res._bill_signal`,
# which lets a confident text-AI "not medical" verdict override even a
# keyword-confident real-kind result in _apply_opinion.
_NON_MEDICAL_STRONG = (
    "gstin", "cgst", "sgst", "igst", "hsn code", "sac code", "tax invoice",
    "proforma invoice", "cash memo", "upi ref", "transaction id",
    "op receipt", "net payable", "total outstanding", "d.l.no",
    "bill no", "receipt no",
)


@dataclass
class ClassResult:
    # ── kept for older callers ──
    doc_type: str = "other"
    confidence: float = 0.0
    method: str = "ocr_keyword"           # qr | ocr_keyword | llm | patient_confirmed | unreadable
    doc_date: "date | None" = None        # == report_date
    text_len: int = 0
    # ── new ──
    categories: list = field(default_factory=list)        # panel slugs, primary first (lab_report only)
    category_labels: list = field(default_factory=list)
    category_confidence: float = 0.0
    multi: bool = False                                   # health package (>1 panel)
    collection_date: "date | None" = None
    date_source: str = ""                                 # collection|report|received|issue|consult|bare
    date_confidence: float = 0.0
    unreadable: bool = False
    quality_reason: str = ""
    quality_message: str = ""
    # True only when the text is clearly a non-clinical document (an invoice,
    # an ID, a boarding pass...) with zero medical signal. Callers skip it —
    # nothing is filed. Strict on purpose: a false positive would drop a real
    # record, so it needs 2+ non-medical cues AND no lab/rx/imaging/discharge
    # hit at all.
    non_medical: bool = False
    # ── audit / provenance ──
    sources: dict = field(default_factory=dict)   # field -> "keyword"|"llm"|"conflict"
    notes: str = ""                               # human-readable cross-layer disagreements
    _det_conf: float = 0.0                         # the keyword pass's own kind confidence
    _medical_signal: bool = False                 # keyword pass saw ANY lab/rx/img/discharge hint
    _bill_signal: bool = False                    # keyword pass saw >=1 commerce/billing token
                                                   # (_NON_MEDICAL_STRONG) — lets a confident text-AI
                                                   # "not medical" verdict override even a keyword-
                                                   # confident real-kind result (see _apply_opinion)
    # ── per-classifier verdicts, kept separately for the agreement report ──
    text: str = ""                                # the page text classified
    rule_kind: str = ""                           # keyword pass verdict (not_medical possible)
    rule_conf: float = 0.0
    rule_scores: dict = field(default_factory=dict)   # core.doc_rules.score() output
    llm_out: dict = field(default_factory=dict)       # raw sanitised text-LLM answer

    @property
    def kind(self) -> str:
        return self.doc_type

    @property
    def report_date(self):
        return self.doc_date

    @property
    def confident(self) -> bool:
        """The old 'file it without asking' gate — kind only, for back-compat."""
        return (not self.unreadable
                and self.confidence >= CONFIDENT
                and self.doc_type in ("prescription", "lab_report", "scan", "discharge_summary"))

    @property
    def fully_confident(self) -> bool:
        """Kind AND (panel, if a lab report) AND date are all trustworthy."""
        if not self.confident:
            return False
        if self.doc_type == "lab_report" and self.category_confidence < report_types.CONFIDENT:
            return False
        if self.doc_date is not None and self.date_confidence < 0.5:
            return False
        return True

    @property
    def needs(self) -> list:
        """Which fields the patient still has to confirm. Empty == file it."""
        if self.unreadable:
            return ["file"]
        out = []
        if not self.confident:
            out.append("kind")
        if self.doc_type == "lab_report" and self.category_confidence < report_types.CONFIDENT:
            out.append("category")
        if self.doc_date is None or self.date_confidence < 0.5:
            out.append("date")
        return out


# ── text extraction (unchanged behaviour) ───────────────────────────────
def _pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:30])
    except Exception:
        logger.warning("doc_classifier: pdf text extraction failed", exc_info=True)
        return ""


def _pdf_encrypted(raw: bytes) -> bool:
    try:
        from pypdf import PdfReader
        return bool(PdfReader(io.BytesIO(raw)).is_encrypted)
    except Exception:
        return False


def _ocr_text(raw: bytes, mime_type: str):
    """
    Returns (text, mean_confidence 0..100 or None) — the 0..100 scale is kept
    for classify()'s low-confidence check. The engine (RapidOCR) is chosen by
    core.ocr per settings.DOC_OCR_ENGINE.

    Image-only PDFs are now rasterised (PyMuPDF) and OCR'd page by page
    instead of being skipped.
    """
    if mime_type == "application/pdf":
        pages = ocr.pdf_page_images(raw, max_pages=30)
        if not pages:
            return "", None
        texts, confs = [], []
        for png in pages:
            r = ocr.run(png)
            if r.text.strip():
                texts.append(r.text)
                if r.conf is not None:
                    confs.append(r.conf)
        text = "\n".join(texts)
        conf = (sum(confs) / len(confs) * 100.0) if confs else None
        return text, conf

    r = ocr.run(raw)
    return r.text, (r.conf * 100.0 if r.conf is not None else None)


def _pdf_page_count(raw: bytes) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:
        return 0


class ExtractionError(Exception):
    """Raised by extract_text() when a file can't be opened at all (not a classification concern)."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def extract_document(raw: bytes, mime_type: str) -> dict:
    """
    Extraction-only entry point for the upload-and-extract mobile flow: no
    kind classification, no panel matching, no date extraction, no blur/
    quality "retake" gate — those are classification-adjacent concerns
    deliberately deferred to a later phase. Kept independent of classify()
    (reusing only the same private _pdf_text/_ocr_text helpers) so neither
    pipeline can be perturbed by future changes to the other.

    Returns the structured result that gets stored as JSON on the item (and
    is what the later classification stage will read):
        {version, text, char_count, page_count, confidence, method, mime_type,
         extracted_at, duration_ms}
    `method` says how the text was obtained: "pdf_text" (text layer only),
    "ocr" (no usable text layer / an image), or "pdf_text+ocr" (both).
    `confidence` is the OCR confidence 0..100, None when OCR never ran.

    Raises ExtractionError for an encrypted PDF — the one pre-extraction
    guard kept, as crash prevention rather than a classification/quality check.
    """
    import time
    from datetime import datetime, timezone

    started = time.monotonic()
    is_pdf = mime_type == "application/pdf"
    if is_pdf and _pdf_encrypted(raw):
        raise ExtractionError("encrypted", "This PDF is password-protected and couldn't be read.")

    layer_text = _pdf_text(raw).strip() if is_pdf else ""
    conf = None
    if len(layer_text) < _MIN_TEXT:
        ocr_text, conf = _ocr_text(raw, mime_type)
        ocr_text = (ocr_text or "").strip()
        text = (layer_text + "\n" + ocr_text).strip() if layer_text else ocr_text
        method = "pdf_text+ocr" if (layer_text and ocr_text) else ("ocr" if ocr_text or not layer_text else "pdf_text")
    else:
        text, method = layer_text, "pdf_text"

    return {
        "version": 1,
        "text": text,
        "char_count": len(text),
        "page_count": _pdf_page_count(raw) if is_pdf else None,
        "confidence": conf,
        "method": method,
        "mime_type": mime_type,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def extract_text(raw: bytes, mime_type: str) -> "tuple[str, float | None]":
    """(text, ocr_confidence_0_to_100_or_None) — the tuple view of extract_document()."""
    r = extract_document(raw, mime_type)
    return r["text"], r["confidence"]


# ── kind scoring ────────────────────────────────────────────────────────
def _score(text_lower: str, hints) -> int:
    return sum(1 for h in hints if h in text_lower)


def _classify_kind(lower: str):
    """Returns (doc_type, confidence)."""
    lab = _score(lower, doc_rules.hints("lab_report"))
    rx = _score(lower, doc_rules.hints("prescription"))
    img = _score(lower, doc_rules.hints("scan"))
    dis = _score(lower, doc_rules.hints("discharge_summary"))
    non = _score(lower, doc_rules.hints("not_medical"))

    # A results table with a reference-range column is the single strongest
    # "this is a lab report" signal; drug lines with a dose pattern the same
    # for a prescription. Discharge and imaging are checked before lab so a
    # discharge summary that quotes a few labs isn't miscalled.
    scores = {"lab_report": lab, "prescription": rx, "scan": img, "discharge_summary": dis, "other": non}
    kind = max(scores, key=scores.get)
    lead = scores[kind]
    rest = sorted(scores.values(), reverse=True)[1]
    margin = lead - rest

    if kind == "discharge_summary" and dis >= 2:
        return "discharge_summary", min(0.95, 0.62 + 0.08 * dis)
    if kind == "scan" and img >= 2 and img > lab:
        return "scan", min(0.95, 0.6 + 0.09 * img)
    if kind == "other" and non >= 2 and non > max(lab, rx):
        return "other", 0.85           # confidently non-medical (an invoice etc.)

    if lead == 0:
        return "other", 0.0
    if lead >= 3 and margin >= 2:
        conf = min(0.96, 0.60 + 0.07 * lead + 0.05 * margin)
    elif lead >= 2 and margin >= 1:
        conf = 0.62
    else:
        conf = 0.4
    return kind, round(conf, 2)


# ── LLM tail (optional, off by default) ─────────────────────────────────
# ── layer merge ───────────────────────────────────────────────────────
# A keyword verdict this sure is not overridden by a WEAK challenger — but
# (2026-09-22 change) it no longer wins unconditionally: a challenger that is
# ALSO confident (kconf >= _CHALLENGE_CONF) turns it into a genuine conflict
# instead of being silently ignored. This is what makes the merge an actual
# vote between the two layers rather than "keyword wins if sure enough".
_STRONG_KEYWORD = 0.90
_CHALLENGE_CONF = 0.80   # how sure the text AI must be to contest a strong keyword result
_BILL_OVERRIDE_CONF = 0.85   # how sure a not_medical verdict must be to override, given billing evidence


def _apply_opinion(res: "ClassResult", out: dict, src: str) -> None:
    """
    Fold the text-AI's answer (`src` is always "llm" — the vision layer was
    removed 2026-09-22) into `res` as a real vote against the deterministic
    keyword pass, not a rubber stamp:
      * agreement                → raise confidence, clear the field from `.needs`
      * keyword unsure           → take the AI's value
      * keyword strong, AI weak    → keep keyword, log the dissent
      * keyword strong, AI ALSO confident → conflict → the patient decides
      * "not medical" vs. a confident keyword real-kind → overridden only when
        the keyword pass itself saw billing/commerce evidence (`_bill_signal`)
        alongside the drug/lab words that made it look medical — this is the
        fix for a pharmacy bill that lists the same medicine names as the
        prescription it's billing for (2026-09-22, see _NON_MEDICAL_STRONG)

    `src` is kept as a parameter (rather than hardcoded) purely so notes/logs
    say who made each call — there is currently only one caller (_llm_refine).
    """
    if not out:
        return

    # ── kind ──────────────────────────────────────────────────────────
    k = out.get("kind")
    kconf = float(out.get("confidence") or 0.0)

    if k == "not_medical":
        if res.non_medical:
            return
        keyword_sure = res.confident   # confidence>=CONFIDENT AND a real kind
        bill_override = (res._bill_signal and kconf >= _BILL_OVERRIDE_CONF)
        if not keyword_sure:
            # Keyword never confidently claimed a real kind — a "not medical"
            # verdict is cheap to trust unless the text at least LEANS
            # medical (some rx/lab/img/discharge word matched) with no
            # billing evidence to explain that away.
            if not res._medical_signal or bill_override:
                res.non_medical = True
                res.doc_type = "other"
                res.sources["kind"] = src
                res.notes = (res.notes + f" {src}:not_medical").strip()
        elif bill_override:
            # Keyword WAS confident about a real kind — only billing
            # evidence backing up a very sure "not medical" verdict beats
            # that (a pharmacy bill listing drug names, not a prescription).
            was = res.doc_type
            res.non_medical = True
            res.doc_type = "other"
            res.sources["kind"] = f"{src}+billing"
            res.notes = (res.notes + f" overridden: keyword said {was}"
                         f" but {src} said not_medical {kconf:.2f} +billing evidence").strip()
        else:
            res.notes = (res.notes + f" {src}:not_medical ({kconf:.2f}) ignored — "
                         "keyword confident, no billing evidence").strip()
        return

    if k in ("prescription", "lab_report", "scan", "discharge_summary", "other"):
        det_kind_confident = (res._det_conf >= CONFIDENT and
                              res.doc_type in ("prescription", "lab_report", "scan", "discharge_summary"))
        if k == res.doc_type:
            res.confidence = max(res.confidence, kconf, 0.82)
            res.sources.setdefault("kind", res.sources.get("kind", "keyword"))
        elif det_kind_confident and res._det_conf >= _STRONG_KEYWORD:
            if kconf >= _CHALLENGE_CONF:
                # Both sides are confident and disagree — a genuine conflict,
                # not a coin flip either way. Drop below the auto-file gate.
                res.confidence = 0.60
                res.sources["kind"] = "conflict"
                res.notes = (res.notes + f" conflict keyword={res.doc_type}"
                             f" {src}={k}({kconf:.2f})").strip()
            else:
                res.notes = (res.notes + f" {src}!={res.doc_type}"
                             f"(said {k} {kconf:.2f}, too weak to challenge)").strip()
        elif "kind" in res.needs:
            res.doc_type = k
            res.confidence = kconf if kconf >= CONFIDENT else min(max(res.confidence, 0.50), 0.66)
            res.sources["kind"] = src
            res.method = src
        elif det_kind_confident and kconf >= 0.70:
            res.confidence = 0.60          # drop below the gate → review tray
            res.sources["kind"] = "conflict"
            res.notes = (res.notes + f" conflict keyword={res.doc_type} {src}={k}").strip()

    # ── panel (lab reports only) ─────────────────────────────────────
    cats = [c for c in (out.get("categories") or []) if c in report_types.PANELS_BY_SLUG]
    if cats and res.doc_type == "lab_report":
        if "category" in res.needs:
            res.categories = cats
            res.category_labels = [report_types.label_for(c) for c in cats]
            res.category_confidence = max(res.category_confidence, 0.80)
            res.multi = len(cats) > 1
            res.sources["category"] = src
        elif res.categories and cats[0] == res.categories[0]:
            res.category_confidence = max(res.category_confidence, 0.88)

    # ── date ────────────────────────────────────────────────────────
    if out.get("report_date") and "date" in res.needs:
        try:
            y, m, d = (int(x) for x in str(out["report_date"])[:10].split("-"))
            dt = date(y, m, d)
            # Same sanity gate the keyword pass applies: a report can't be dated
            # in the future (or before 2000). Drop it so the patient is asked.
            if doc_dates._plausible(dt):
                res.doc_date = dt
                res.date_source = out.get("date_source") or src
                res.date_confidence = 0.80
                res.sources["date"] = src
        except Exception:
            pass


def _llm_refine(text: str, res: "ClassResult", llm="auto") -> "ClassResult":
    """
    Text-LLM layer — resolves the uncertain tail from the OCR text, and now
    also double-checks a document the keyword pass otherwise considered
    fully resolved IF it saw any billing/commerce token (`res._bill_signal`):
    a single "GST" or "Bill No." mention isn't enough for the deterministic
    non_medical override (which wants 2+), but it's reason enough to ask the
    AI for a second opinion before auto-filing something that might be a
    pharmacy bill rather than a prescription. A document with zero billing
    signal and nothing else unresolved still skips the AI call entirely.
    Enabled only when `settings.DOC_CLASSIFIER_LLM` points at a callable
    `fn(text) -> dict`; a blank API key makes that callable a no-op. Never
    raises.
    """
    # llm: "auto" = call the configured LLM for the unsure tail, "off" = skip
    # (the background pipeline queues it separately — core/pipeline/llm_queue.py),
    # a dict = a verdict that was already fetched (the queued LLM task) — fold it in.
    if isinstance(llm, dict):
        if not llm:
            return res
        res.llm_out = dict(llm)
        _apply_opinion(res, llm, "llm")
        return res
    if llm == "off" or res.unreadable or res.non_medical or (not res.needs and not res._bill_signal):
        return res
    try:
        from django.conf import settings
        from django.utils.module_loading import import_string
        path = getattr(settings, "DOC_CLASSIFIER_LLM", "") or ""
        if not path:
            return res
        out = import_string(path)(text) or {}
    except Exception:
        logger.exception("doc_classifier: text-LLM refine failed; keeping earlier result")
        return res
    res.llm_out = dict(out)
    _apply_opinion(res, out, "llm")
    return res


# ── public API ─────────────────────────────────────────────────────────
def classify_text(text: str, llm="auto") -> ClassResult:
    """
    Deterministic keyword pass + the text-LLM refine. Callers that only have
    text (tests, the QR-less single-page path) use this; `classify()` wraps
    it with extraction and the image quality gate.
    """
    text = (text or "").strip()
    if len(text) < _MIN_TEXT:
        return ClassResult(doc_type="other", confidence=0.0, text_len=len(text))

    lower = " " + " ".join(text.lower().split()) + " "
    kind, kconf = _classify_kind(lower)

    res = ClassResult(doc_type=kind, confidence=kconf, method="ocr_keyword", text_len=len(text))
    res._det_conf = kconf
    res._medical_signal = bool(
        _score(lower, doc_rules.hints("lab_report")) or _score(lower, doc_rules.hints("prescription"))
        or _score(lower, doc_rules.hints("scan")) or _score(lower, doc_rules.hints("discharge_summary"))
    )
    if res.confident:
        res.sources["kind"] = "keyword"

    # Clearly-not-a-medical-document → the caller drops it, nothing is stored.
    # Two tiers: 2+ STRONG commerce/billing tokens force it regardless of
    # _medical_signal (catches a pharmacy bill that also lists drug names —
    # see _NON_MEDICAL_STRONG); otherwise the older, more cautious rule of
    # 2+ of ANY non-medical hint (the rules table's "not_medical" keywords)
    # with zero medical signal at all.
    non_strong = _score(lower, _NON_MEDICAL_STRONG)
    res._bill_signal = non_strong >= 1
    if non_strong >= 2 or (_score(lower, doc_rules.hints("not_medical")) >= 2 and not res._medical_signal):
        res.non_medical = True
        res.doc_type = "other"
        res.sources["kind"] = "keyword"

    if kind == "lab_report":
        pr = report_types.classify(text)
        res.categories = pr.categories
        res.category_labels = pr.labels
        res.category_confidence = pr.confidence
        res.multi = pr.multi
        if pr.confidence >= report_types.CONFIDENT:
            res.sources["category"] = "keyword"
            # A decisive panel match (CBC / Lipid / Thyroid ...) is itself
            # strong evidence this is a lab report, even when the generic
            # kind vocabulary was thin (unusual header wording, or a panel
            # whose own titles don't happen to hit _LAB_HINTS). Let it
            # corroborate kind confidence instead of leaving a
            # well-identified report stuck below the auto-file gate.
            res.confidence = max(res.confidence, 0.80)
            res._det_conf = max(res._det_conf, 0.80)
            if res.confident:
                res.sources.setdefault("kind", "keyword")

    # The rule-based verdict, frozen before any LLM/vision layer can move it.
    res.text = text
    res.rule_kind = "not_medical" if res.non_medical else res.doc_type
    res.rule_conf = round(res.confidence, 2)
    res.rule_scores = doc_rules.score(lower)

    dr = doc_dates.extract(text)
    res.doc_date = dr.report_date
    res.collection_date = dr.collection_date
    res.date_source = dr.source
    res.date_confidence = dr.confidence
    if dr.report_date is not None and dr.confidence >= 0.5:
        res.sources["date"] = "keyword"

    return _llm_refine(text, res, llm)


@dataclass
class Extracted:
    text: str = ""
    thin_text: bool = False
    early: "ClassResult | None" = None   # set when extraction already decided (unreadable…)


def extract(raw: bytes, mime_type: str, *, check_quality: bool = True) -> Extracted:
    """
    Stage 1 of classify(), exposed so the background pipeline can report
    "extracting" and "classifying" as separate steps:

      auto-crop/straighten (images, if DOC_AUTO_CROP) → quality gate →
      encrypted check → text (PDF layer / OCR)

    No vision/image-model stage (removed 2026-09-22): a blurry/dark image
    that fails the quality gate goes straight to "retake". The ORIGINAL bytes
    (not the cropped version) are what the caller stores — cropping only
    feeds a cleaner image into the quality gate and OCR.
    """
    if check_quality and mime_type in ("image/jpeg", "image/png"):
        try:
            from django.conf import settings
            if getattr(settings, "DOC_AUTO_CROP", False):
                from core import doc_crop
                cropped = doc_crop.auto_crop_straighten(raw)
                if cropped:
                    raw = cropped   # use the straightened version for quality + OCR only
        except Exception:
            logger.warning("doc_classifier: auto-crop step failed; using original image", exc_info=True)

    if check_quality:
        q = image_quality.assess(raw, mime_type)
        if not q.ok:
            return Extracted(early=ClassResult(
                doc_type="other", confidence=0.0, method="unreadable",
                unreadable=True, quality_reason=q.reason, quality_message=q.message,
            ))

    if mime_type == "application/pdf" and _pdf_encrypted(raw):
        return Extracted(early=ClassResult(
            doc_type="other", confidence=0.0, method="unreadable", unreadable=True,
            quality_reason="encrypted",
            quality_message="This PDF is password-protected, so it couldn't be read. "
                            "Remove the password and upload it again.",
        ))

    text = _pdf_text(raw) if mime_type == "application/pdf" else ""
    ocr_conf = None
    if len(text.strip()) < _MIN_TEXT:
        ocr_text, ocr_conf = _ocr_text(raw, mime_type)
        text = (text + "\n" + ocr_text).strip() if text else (ocr_text or "").strip()
    else:
        text = text.strip()

    thin_text = (
        len(text) < _MIN_TEXT
        or (mime_type in ("image/jpeg", "image/png") and ocr_conf is not None
            and ocr_conf < 45 and len(text) < 120)
    )
    return Extracted(text=text, thin_text=thin_text)


def classify(raw: bytes, mime_type: str, *, check_quality: bool = True,
             extracted: "Extracted | None" = None, llm="auto") -> ClassResult:
    """
    Full pipeline. `raw` is the ORIGINAL uploaded bytes, `mime_type` the
    verified type ("application/pdf" | "image/jpeg" | "image/png").

      extract() [auto-crop → quality gate → encrypted check → text] →
      deterministic keyword pass → text-LLM (unless llm="off") → verdict

    Pass `extracted` (from extract()) to skip stage 1. The background
    pipeline calls this with llm="off" and queues the LLM separately.
    """
    ex = extracted if extracted is not None else extract(raw, mime_type, check_quality=check_quality)
    if ex.early is not None:
        return ex.early
    text, thin_text = ex.text, ex.thin_text

    res = classify_text(text, llm) if len(text) >= _MIN_TEXT else \
        ClassResult(doc_type="other", confidence=0.0, text_len=len(text), text=text)

    # An IMAGE we couldn't read anything usable from → "retake", not a blind
    # "Other". (A PDF can't be retaken — it just falls to the review tray.)
    if (thin_text and mime_type in ("image/jpeg", "image/png")
            and not res.non_medical and res.doc_type == "other"
            and res.confidence < 0.40
            and res.sources.get("kind") != "llm"):
        return ClassResult(
            doc_type="other", confidence=0.0, method="unreadable", unreadable=True,
            quality_reason="unreadable_ocr",
            quality_message="We couldn't read enough of this photo. " + image_quality._RETAKE,
        )
    return res


# ── back-compat shim ───────────────────────────────────────────────────
def _extract_date(text: str):
    """Kept for any external caller; prefer core.doc_dates.extract()."""
    return doc_dates.extract(text).report_date
