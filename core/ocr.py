"""
core/ocr.py
-----------
One entry point for turning an image — or a rasterised scanned-PDF page —
into text with a confidence score, for core.doc_classifier.

Engine comes from ``settings.DOC_OCR_ENGINE``:

    "rapidocr"  (default) — RapidOCR (the PP-OCR / PaddleOCR detection +
                recognition models running on ONNX Runtime; pip-only, CPU,
                no system package). This is the only engine in use.
    "auto"      — same as "rapidocr".
    "paddleocr" — force the full PaddleOCR package (needs ``paddlepaddle``,
                which is not installed by default).
    "none"      — disable OCR entirely.

Any other value (including the removed "tesseract" and "both") behaves like
"auto", i.e. RapidOCR.

Why RapidOCR: on real phone photos a deep-learning text detector copes with
skew, perspective, glare and low contrast. RapidOCR ships the same models as
PaddleOCR but drops the heavy ``paddlepaddle`` runtime, so it installs cleanly
on a plain server. One engine also costs roughly half the reading time and
memory of running a second one on the 1-CPU server. Tesseract was removed: it
was only ever a fallback / an experimental "both" mode. A born-digital PDF
needs no OCR at all.

Nothing here is imported at module load: every backend is imported lazily
and any failure degrades to the next engine, then to an empty string. The
model objects are expensive to build, so each backend caches a singleton.
"""

from __future__ import annotations

import io
import logging
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
    "auto":      ("rapidocr",),
    "rapidocr":  ("rapidocr",),
    "paddleocr": ("paddleocr",),
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
    """The backend's libraries aren't installed on this host."""


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


_BACKENDS = {
    "rapidocr": _rapidocr,
    "paddleocr": _paddleocr,
}


# ── scanned-PDF rasterisation ─────────────────────────────────────────
def pdf_page_images(raw: bytes, *, max_pages: int = 30, dpi: int = 200) -> list[bytes]:
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
