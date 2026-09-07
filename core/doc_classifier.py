"""
core/doc_classifier.py
----------------------
Decides whether a NO-QR document is a prescription or a lab report, from its
text. Used only when the QR path did not identify the document.

Text is gathered, in order:
  1. the PDF's own text layer (pypdf) — most lab PDFs have one;
  2. OCR of an image / image-only PDF (pytesseract), if the tesseract binary
     is installed. If it is not, OCR is skipped, confidence stays low, and
     the document lands in the patient's Unsorted tray — it is never misfiled.

classify() returns a ClassResult(doc_type, confidence, method, doc_date).
`ClassResult.confident` is the "file it automatically" gate; anything below
it goes to the Unsorted tray for a one-tap confirmation.

The keyword lists are deliberately conservative and will need tuning against
real reports. Because the confidence gate is strict, a wrong guess costs one
extra tap, not a misfiled record.
"""

import io
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

CONFIDENT = 0.75
_MIN_TEXT = 40  # chars — below this we have nothing to classify on

_LAB_HINTS = (
    "reference range", "reference interval", "ref. range", "ref range", "bio. ref",
    "normal range", "biological reference", "haemoglobin", "hemoglobin", "platelet",
    "wbc count", "rbc count", "differential count", "mg/dl", "mmol/l", "iu/l", "u/l",
    "ng/ml", "pg/ml", "meq/l", "specimen", "sample type", "collected on", "reported on",
    "test name", "result value", "lab no", "lab id", "pathology", "haematology",
    "biochemistry", "serology", "microbiology", "serum", "plasma", "investigation",
)
_RX_HINTS = (
    "prescription", "sig:", "tab.", "cap.", "syrup", "tablet", "capsule", "ointment",
    "once daily", "twice daily", "thrice daily", "every night", "before food",
    "after food", "at bedtime", "as needed", "chief complaint", "diagnosis:",
    "advice:", "follow up", "follow-up", "dosage", "duration", "frequency", "route",
    "reg. no", "regn no", "m.b.b.s", "mbbs", "consulting physician", "medications",
)

_DATE_RES = (
    re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](20\d{2})\b"),  # dd-mm-yyyy
    re.compile(r"\b(20\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})\b"),  # yyyy-mm-dd
)


class ClassResult:
    __slots__ = ("doc_type", "confidence", "method", "doc_date", "text_len")

    def __init__(self, doc_type, confidence, method, doc_date=None, text_len=0):
        self.doc_type = doc_type
        self.confidence = confidence
        self.method = method
        self.doc_date = doc_date
        self.text_len = text_len

    @property
    def confident(self) -> bool:
        return self.confidence >= CONFIDENT and self.doc_type in ("prescription", "lab_report")

    def __repr__(self):
        return (f"<ClassResult {self.doc_type} conf={self.confidence} "
                f"method={self.method} date={self.doc_date} textlen={self.text_len}>")


def _pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:8])
    except Exception:
        logger.warning("doc_classifier: pdf text extraction failed", exc_info=True)
        return ""


def _ocr_text(raw: bytes, mime_type: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.info("doc_classifier: pytesseract not installed — OCR skipped")
        return ""
    if mime_type == "application/pdf":
        # Rendering PDF pages to images needs poppler/pymupdf; a text-less PDF
        # just falls through to Unsorted for now.
        return ""
    try:
        img = Image.open(io.BytesIO(raw))
        return pytesseract.image_to_string(img)
    except getattr(pytesseract, "TesseractNotFoundError", Exception):
        logger.info("doc_classifier: tesseract binary not found — OCR skipped")
        return ""
    except Exception:
        logger.warning("doc_classifier: OCR failed", exc_info=True)
        return ""


def _score(text_lower: str, hints) -> int:
    return sum(1 for h in hints if h in text_lower)


def _extract_date(text: str):
    for rx in _DATE_RES:
        m = rx.search(text)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        try:
            if g[0] > 1000:
                return date(g[0], g[1], g[2])
            return date(g[2], g[1], g[0])
        except ValueError:
            continue
    return None


def classify(raw: bytes, mime_type: str) -> ClassResult:
    """
    `raw` is the ORIGINAL uploaded bytes (before PDF normalisation), `mime_type`
    the verified type ("application/pdf" | "image/jpeg" | "image/png").
    """
    text = _pdf_text(raw) if mime_type == "application/pdf" else ""
    if len(text.strip()) < _MIN_TEXT:
        ocr = _ocr_text(raw, mime_type)
        text = (text + "\n" + ocr).strip() if text else ocr.strip()
    else:
        text = text.strip()

    if len(text) < _MIN_TEXT:
        return ClassResult("other", 0.0, "ocr_keyword", None, len(text))

    lower = text.lower()
    lab = _score(lower, _LAB_HINTS)
    rx = _score(lower, _RX_HINTS)
    doc_date = _extract_date(text)

    if lab == 0 and rx == 0:
        return ClassResult("other", 0.0, "ocr_keyword", doc_date, len(text))

    if lab >= rx:
        doc_type, lead = "lab_report", lab
    else:
        doc_type, lead = "prescription", rx
    margin = abs(lab - rx)

    if lead >= 3 and margin >= 2:
        conf = min(0.95, 0.60 + 0.07 * lead + 0.05 * margin)
    elif lead >= 2 and margin >= 1:
        conf = 0.62
    else:
        conf = 0.40
    return ClassResult(doc_type, round(conf, 2), "ocr_keyword", doc_date, len(text))
