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

from core import doc_dates, image_quality, ocr, report_types

logger = logging.getLogger(__name__)

CONFIDENT = 0.75          # kind gate
_MIN_TEXT = 40            # chars below which there's nothing to classify on

# ── kind vocabulary ─────────────────────────────────────────────────────
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
    sources: dict = field(default_factory=dict)   # field -> "keyword"|"llm"|"vision"|"conflict"
    notes: str = ""                               # human-readable cross-layer disagreements
    _det_conf: float = 0.0                         # the keyword pass's own kind confidence
    _medical_signal: bool = False                 # keyword pass saw ANY lab/rx/img/discharge hint

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
        return "\n".join((page.extract_text() or "") for page in reader.pages[:8])
    except Exception:
        logger.warning("doc_classifier: pdf text extraction failed", exc_info=True)
        return ""


def _pdf_encrypted(raw: bytes) -> bool:
    try:
        from pypdf import PdfReader
        return bool(PdfReader(io.BytesIO(raw)).is_encrypted)
    except Exception:
        return False


def _locate_tesseract():
    """Back-compat re-export; the real implementation lives in core.ocr."""
    ocr._locate_tesseract()


def _ocr_text(raw: bytes, mime_type: str):
    """
    Returns (text, mean_confidence 0..100 or None) — the 0..100 scale is kept
    for classify()'s low-confidence check. The engine (RapidOCR / PaddleOCR /
    Tesseract) is chosen by core.ocr per settings.DOC_OCR_ENGINE.

    Image-only PDFs are now rasterised (PyMuPDF) and OCR'd page by page
    instead of being skipped.
    """
    if mime_type == "application/pdf":
        pages = ocr.pdf_page_images(raw, max_pages=3)
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


# ── kind scoring ────────────────────────────────────────────────────────
def _score(text_lower: str, hints) -> int:
    return sum(1 for h in hints if h in text_lower)


def _classify_kind(lower: str):
    """Returns (doc_type, confidence)."""
    lab = _score(lower, _LAB_HINTS)
    rx = _score(lower, _RX_HINTS)
    img = _score(lower, _IMG_HINTS)
    dis = _score(lower, _DISCHARGE_HINTS)
    non = _score(lower, _NON_MEDICAL_HINTS)

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
_STRONG_KEYWORD = 0.90   # a keyword verdict this sure is never overridden by a guess


def _apply_opinion(res: "ClassResult", out: dict, src: str) -> None:
    """
    Fold one labeller's answer (`src` = "llm" or "vision") into `res`,
    respecting what the deterministic keyword pass already decided:
      * agreement       → raise confidence, clear the field from `.needs`
      * keyword unsure  → take the labeller's value
      * keyword strong  → keep keyword, log the dissent
      * both sure, differ→ mark a conflict → the patient decides
    """
    if not out:
        return

    # ── kind ──────────────────────────────────────────────────────────
    k = out.get("kind")
    kconf = float(out.get("confidence") or 0.0)

    if k == "not_medical":
        # Trust a "not medical" verdict unless the deterministic pass is
        # *itself* confident about a real record. A faint keyword lean — a
        # screenshot that merely says "prescription", say — is not enough to
        # keep it: a confident vision "not medical" (>=0.75) overrides that.
        keyword_sure = res.confident and res.doc_type in (
            "prescription", "lab_report", "scan", "discharge_summary")
        if (not keyword_sure and not res.non_medical
                and (not res._medical_signal
                     or (src == "vision" and kconf >= 0.75))):
            res.non_medical = True
            res.doc_type = "other"
            res.sources["kind"] = src
            res.notes = (res.notes + f" {src}:not_medical").strip()
        return

    if k in ("prescription", "lab_report", "scan", "discharge_summary", "other"):
        det_kind_confident = (res._det_conf >= CONFIDENT and
                              res.doc_type in ("prescription", "lab_report", "scan", "discharge_summary"))
        if k == res.doc_type:
            res.confidence = max(res.confidence, kconf, 0.82)
            res.sources.setdefault("kind", res.sources.get("kind", "keyword"))
        elif det_kind_confident and res._det_conf >= _STRONG_KEYWORD:
            res.notes = (res.notes + f" {src}!={res.doc_type}(said {k} {kconf:.2f})").strip()
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
            res.doc_date = date(y, m, d)
            res.date_source = out.get("date_source") or src
            res.date_confidence = 0.80
            res.sources["date"] = src
        except Exception:
            pass


def _llm_refine(text: str, res: "ClassResult") -> "ClassResult":
    """
    Text-LLM layer — resolves the uncertain tail from the OCR text. Enabled
    only when `settings.DOC_CLASSIFIER_LLM` points at a callable `fn(text) ->
    dict`; a blank API key makes that callable a no-op. Never raises.
    """
    if res.unreadable or res.non_medical or not res.needs:
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
    _apply_opinion(res, out, "llm")
    return res


def _page_images(raw: bytes, mime_type: str) -> list:
    if mime_type in ("image/jpeg", "image/png"):
        return [raw]
    if mime_type == "application/pdf":
        try:
            return ocr.pdf_page_images(raw, max_pages=2)
        except Exception:
            return []
    return []


def _vision_refine(res: "ClassResult", raw: bytes, mime_type: str, *, thin_text: bool) -> "ClassResult":
    """
    Vision layer — the last automated fallback. Sends the page image(s) to a
    VLM. Runs only when the text layers left something open: the kind is
    unresolved, a lab report's panel is unknown, the OCR text was too thin to
    trust, or the earlier layers disagreed. OFF unless a vision model is
    configured. Never raises.
    """
    try:
        from core import doc_classifier_vision as _v
        if not _v.enabled() or res.non_medical:
            return res
        trigger = (
            thin_text
            or "kind" in res.needs
            or (res.doc_type == "lab_report" and "category" in res.needs)
            or res.sources.get("kind") == "conflict"
        )
        if not trigger:
            return res
        imgs = _page_images(raw, mime_type)
        if not imgs:
            return res
        out = _v.classify_images(imgs) or {}
    except Exception:
        logger.exception("doc_classifier: vision refine failed; keeping earlier result")
        return res
    _apply_opinion(res, out, "vision")
    return res


# ── public API ─────────────────────────────────────────────────────────
def classify_text(text: str) -> ClassResult:
    """
    Deterministic keyword pass + the text-LLM refine. Callers that only have
    text (tests, the QR-less single-page path) use this; `classify()` wraps it
    with extraction, the image gate and the vision layer.
    """
    text = (text or "").strip()
    if len(text) < _MIN_TEXT:
        return ClassResult(doc_type="other", confidence=0.0, text_len=len(text))

    lower = " " + " ".join(text.lower().split()) + " "
    kind, kconf = _classify_kind(lower)

    res = ClassResult(doc_type=kind, confidence=kconf, method="ocr_keyword", text_len=len(text))
    res._det_conf = kconf
    res._medical_signal = bool(
        _score(lower, _LAB_HINTS) or _score(lower, _RX_HINTS)
        or _score(lower, _IMG_HINTS) or _score(lower, _DISCHARGE_HINTS)
    )
    if res.confident:
        res.sources["kind"] = "keyword"

    # Clearly-not-a-medical-document → the caller drops it, nothing is stored.
    if _score(lower, _NON_MEDICAL_HINTS) >= 2 and not res._medical_signal:
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

    dr = doc_dates.extract(text)
    res.doc_date = dr.report_date
    res.collection_date = dr.collection_date
    res.date_source = dr.source
    res.date_confidence = dr.confidence
    if dr.report_date is not None and dr.confidence >= 0.5:
        res.sources["date"] = "keyword"

    return _llm_refine(text, res)


def _quality_fallback_vision(raw: bytes, mime_type: str) -> "ClassResult | None":
    """
    The quality gate wants to bounce this image with a "retake". Before we do,
    let the vision model look — a marginally blurry / dim photo of an obvious
    prescription, or of an obvious non-document, is still worth a verdict, and
    vision handles both. Returns a ClassResult only when vision is *confident*
    (a real kind at/above the gate, or a clear "not medical"); a shrug returns
    None and the caller falls back to "unreadable".
    """
    try:
        from core import doc_classifier_vision as _v
        if not _v.enabled():
            return None
        imgs = _page_images(raw, mime_type)
        if not imgs:
            return None
        out = _v.classify_images(imgs) or {}
    except Exception:
        logger.exception("doc_classifier: quality-fallback vision failed")
        return None
    if not out:
        return None
    res = ClassResult(doc_type="other", confidence=0.0, method="vision")
    _apply_opinion(res, out, "vision")   # folds in kind + panel + date in one pass
    if res.non_medical:
        return res
    # The quality gate would have bounced this photo to "retake". If vision
    # nonetheless commits to a real kind, trust it and file rather than send
    # the patient to the review tray for a photo they think is fine. Read the
    # raw vision confidence — _apply_opinion clamps `res.confidence` down when
    # the keyword pass had nothing to agree with.
    vconf = float(out.get("confidence") or 0.0)
    if res.doc_type in ("prescription", "lab_report", "scan", "discharge_summary") and vconf >= 0.60:
        res.confidence = max(res.confidence, vconf, CONFIDENT)
        res.sources["kind"] = "vision"
        res.method = "vision"
        return res
    return None


def classify(raw: bytes, mime_type: str, *, check_quality: bool = True) -> ClassResult:
    """
    Full pipeline. `raw` is the ORIGINAL uploaded bytes, `mime_type` the
    verified type ("application/pdf" | "image/jpeg" | "image/png").

      quality gate → encrypted check → text (PDF layer / OCR) →
      deterministic keyword pass → text-LLM → vision-LLM → verdict
    """
    if check_quality:
        q = image_quality.assess(raw, mime_type)
        if not q.ok:
            vres = _quality_fallback_vision(raw, mime_type)
            if vres is not None:
                return vres
            return ClassResult(
                doc_type="other", confidence=0.0, method="unreadable",
                unreadable=True, quality_reason=q.reason, quality_message=q.message,
            )

    if mime_type == "application/pdf" and _pdf_encrypted(raw):
        return ClassResult(
            doc_type="other", confidence=0.0, method="unreadable", unreadable=True,
            quality_reason="encrypted",
            quality_message="This PDF is password-protected, so it couldn't be read. "
                            "Remove the password and upload it again.",
        )

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

    res = classify_text(text) if len(text) >= _MIN_TEXT else \
        ClassResult(doc_type="other", confidence=0.0, text_len=len(text))

    res = _vision_refine(res, raw, mime_type, thin_text=thin_text)

    # An IMAGE we couldn't read anything usable from → "retake", not a blind
    # "Other". (A PDF can't be retaken — it just falls to the review tray.)
    if (thin_text and mime_type in ("image/jpeg", "image/png")
            and not res.non_medical and res.doc_type == "other"
            and res.confidence < 0.40
            and res.sources.get("kind") not in ("llm", "vision")):
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
