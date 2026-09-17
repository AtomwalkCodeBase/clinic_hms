"""
core/ocr.py
-----------
One entry point for turning an image — or a rasterised scanned-PDF page —
into text with a confidence score, for core.doc_classifier.

Engine order comes from ``settings.DOC_OCR_ENGINE``:

    "auto"      (default) — RapidOCR (the PP-OCR / PaddleOCR detection +
                recognition models running on ONNX Runtime; pip-only, CPU,
                no system package) when importable, otherwise Tesseract.
    "rapidocr"  — force RapidOCR.
    "paddleocr" — force the full PaddleOCR package (needs ``paddlepaddle``).
    "tesseract" — force Tesseract (needs the ``tesseract-ocr`` binary).
    "none"      — disable OCR entirely.

Why RapidOCR by default: on real phone photos a deep-learning text detector
copes with skew, perspective, glare and low contrast where Tesseract's line
model fragments. RapidOCR ships the same models as PaddleOCR but drops the
heavy ``paddlepaddle`` runtime, so it installs cleanly on a plain server.
Tesseract stays as the always-available fallback and for the born-digital
PDF path (which needs no OCR at all).

Nothing here is imported at module load: every backend is imported lazily
and any failure degrades to the next engine, then to an empty string. The
model objects are expensive to build, so each backend caches a singleton.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# One lock guards every backend's lazy singleton so concurrent OCR calls
# (gunicorn threads, the batch daemon, a warm-up thread) can't each build a
# model. Model construction is the only thing serialised; inference is not.
_INIT_LOCK = threading.Lock()


def _load_rgb(image_bytes: bytes):
    """bytes -> RGB numpy array, or None when the bytes aren't a usable image."""
    try:
        import numpy as np
        from PIL import Image
        return np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
    except Exception:
        return None


@dataclass
class OcrResult:
    text: str = ""
    conf: float | None = None      # mean line/word confidence, 0..1, or None
    engine: str = ""               # which backend actually produced this

    def as_tuple(self):
        return self.text, self.conf


# ── engine selection ───────────────────────────────────────────────────
def _engine_pref() -> str:
    try:
        from django.conf import settings
        return (getattr(settings, "DOC_OCR_ENGINE", "") or "auto").strip().lower()
    except Exception:
        return "auto"


_ORDER = {
    "auto":      ("rapidocr", "tesseract"),
    "rapidocr":  ("rapidocr",),
    "paddleocr": ("paddleocr", "tesseract"),
    "tesseract": ("tesseract",),
    "none":      (),
}


def run(image_bytes: bytes) -> OcrResult:
    """OCR a single image (JPEG/PNG bytes). Never raises."""
    if not image_bytes:
        return OcrResult()
    for name in _ORDER.get(_engine_pref(), _ORDER["auto"]):
        fn = _BACKENDS.get(name)
        if not fn:
            continue
        try:
            text, conf = fn(image_bytes)
        except _Unavailable:
            continue
        except Exception:
            logger.warning("core.ocr: %s backend failed, trying next", name, exc_info=True)
            continue
        if (text or "").strip():
            return OcrResult(text=text.strip(), conf=conf, engine=name)
    return OcrResult()


def available() -> str:
    """Name of the backend that would be used right now (for logs / /doctor)."""
    for name in _ORDER.get(_engine_pref(), _ORDER["auto"]):
        try:
            _probe(name)
            return name
        except _Unavailable:
            continue
    return "none"


class _Unavailable(Exception):
    """The backend's libraries (or binary) aren't installed on this host."""


def _probe(name: str) -> None:
    if name == "rapidocr":
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception as e:
            raise _Unavailable(str(e))
    elif name == "paddleocr":
        try:
            import paddleocr  # noqa: F401
        except Exception as e:
            raise _Unavailable(str(e))
    elif name == "tesseract":
        try:
            import pytesseract  # noqa: F401
        except Exception as e:
            raise _Unavailable(str(e))
        _locate_tesseract()
        try:
            import pytesseract
            if not (getattr(pytesseract.pytesseract, "tesseract_cmd", "") and
                    (shutil.which(pytesseract.pytesseract.tesseract_cmd)
                     or os.path.exists(pytesseract.pytesseract.tesseract_cmd))) \
               and not shutil.which("tesseract"):
                raise _Unavailable("tesseract binary not found")
        except _Unavailable:
            raise
        except Exception:
            pass


# ── RapidOCR (PP-OCR models on ONNX Runtime) ───────────────────────────
_RAPID = None


def _rapidocr(image_bytes: bytes):
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:
        raise _Unavailable(str(e))

    global _RAPID
    if _RAPID is None:
        with _INIT_LOCK:
            if _RAPID is None:
                _RAPID = RapidOCR()
    arr = _load_rgb(image_bytes)
    if arr is None:
        return "", None
    res, _elapse = _RAPID(arr)
    if not res:
        return "", None
    lines = [r[1] for r in res if len(r) > 1 and r[1]]
    scores = [float(r[2]) for r in res if len(r) > 2 and r[2] is not None]
    text = "\n".join(lines)
    conf = (sum(scores) / len(scores)) if scores else None
    return text, conf


# ── full PaddleOCR (optional; needs paddlepaddle) ──────────────────────
_PADDLE = None


def _paddleocr(image_bytes: bytes):
    try:
        from paddleocr import PaddleOCR
    except Exception as e:
        raise _Unavailable(str(e))

    global _PADDLE
    if _PADDLE is None:
        with _INIT_LOCK:
            if _PADDLE is None:
                _PADDLE = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    arr = _load_rgb(image_bytes)
    if arr is None:
        return "", None
    res = _PADDLE.ocr(arr, cls=True)
    # res: [ [ [box, (text, score)], ... ] ]  (one entry per image)
    page = (res or [None])[0] or []
    lines = [ln[1][0] for ln in page if ln and ln[1] and ln[1][0]]
    scores = [float(ln[1][1]) for ln in page if ln and ln[1] and ln[1][1] is not None]
    text = "\n".join(lines)
    conf = (sum(scores) / len(scores)) if scores else None
    return text, conf


# ── Tesseract (fallback) ──────────────────────────────────────────────
_TESSERACT_LOCATED = False


def _locate_tesseract() -> None:
    """Point pytesseract at the binary. Linux: on PATH (no-op). Windows dev:
    probe the usual install paths. Override with settings.TESSERACT_CMD."""
    global _TESSERACT_LOCATED
    if _TESSERACT_LOCATED:
        return
    _TESSERACT_LOCATED = True
    try:
        import pytesseract
        from django.conf import settings

        override = getattr(settings, "TESSERACT_CMD", "") or ""
        if override:
            pytesseract.pytesseract.tesseract_cmd = override
            return
        if shutil.which("tesseract"):
            return
        for cand in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(cand):
                pytesseract.pytesseract.tesseract_cmd = cand
                return
    except Exception:
        pass


def _tesseract(image_bytes: bytes):
    try:
        import pytesseract
        from PIL import Image
    except Exception as e:
        raise _Unavailable(str(e))
    _locate_tesseract()
    not_found = getattr(pytesseract, "TesseractNotFoundError", None)
    try:
        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return "", None
        try:
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            words, confs = [], []
            for tok, c in zip(data.get("text", []), data.get("conf", [])):
                tok = (tok or "").strip()
                try:
                    c = float(c)
                except (TypeError, ValueError):
                    c = -1
                if tok and c >= 0:
                    words.append(tok)
                    confs.append(c)
            if words:
                return " ".join(words), (sum(confs) / len(confs) / 100.0) if confs else None
        except Exception:
            pass
        return pytesseract.image_to_string(img), None
    except Exception as e:
        if not_found is not None and isinstance(e, not_found):
            raise _Unavailable("tesseract binary not found")
        raise


_BACKENDS = {
    "rapidocr": _rapidocr,
    "paddleocr": _paddleocr,
    "tesseract": _tesseract,
}


# ── scanned-PDF rasterisation ─────────────────────────────────────────
def pdf_page_images(raw: bytes, *, max_pages: int = 3, dpi: int = 200) -> list[bytes]:
    """
    Render the first `max_pages` pages of an image-only PDF to PNG bytes so
    they can be OCR'd. Needs PyMuPDF (`pymupdf`); returns [] if it isn't
    installed or the file won't open.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return []
    out: list[bytes] = []
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        return []
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for page in list(doc)[:max_pages]:
            try:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                out.append(pix.tobytes("png"))
            except Exception:
                continue
    finally:
        doc.close()
    return out


# ── warm-up ───────────────────────────────────────────────────────────
_WARMED = False


def warmup() -> str:
    """
    Build the active engine's model now so the first real upload doesn't eat
    the ~3–4 s cold start. Safe to call many times (no-op after the first),
    from any thread, and a no-op when the engine is "none" or unavailable.
    Returns the engine it warmed ("" if nothing).
    """
    global _WARMED
    if _WARMED:
        return ""
    _WARMED = True
    name = available()
    if name in ("", "none"):
        return ""
    if name == "tesseract":
        return name   # binary check already ran in available(); no model to load
    # A small but real page — a degenerate 1x1 can send the detector's resize
    # path pathological on some builds, so give it something normal to chew.
    try:
        import io as _io
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (320, 110), "white")
        ImageDraw.Draw(im).text((12, 40), "warm up 12/09/2026", fill=(20, 20, 20))
        b = _io.BytesIO()
        im.save(b, "PNG")
        run(b.getvalue())
        logger.info("core.ocr: %s model warmed", name)
    except Exception:
        logger.warning("core.ocr: warmup failed for %s", name, exc_info=True)
    return name
