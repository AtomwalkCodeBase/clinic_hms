"""apps/documents/ocr.py"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# One lock guards the lazy singleton so concurrent OCR calls (gunicorn threads, a warm-up thread) can't each build
_INIT_LOCK = threading.Lock()


# A phone photo or a big screenshot can be tens of megapixels. Decoding one costs about 4 bytes a pixel and the OCR models
MAX_OCR_SIDE = 2500
MAX_OCR_PIXELS = 100_000_000
# The other extreme is just as dangerous: RapidOCR scales a tiny image UP before reading it, so a 1x1 pixel PNG (a
MIN_OCR_SIDE = 32
# A thin strip is the same trap in another form: the short side is scaled up, so the long side grows with the shape.
MAX_OCR_ASPECT = 8


def image_size(raw: bytes):
    """(width, height) read from the image header only (nothing is decoded), or None if it isn't an image."""
    try:
        from PIL import Image
        return Image.open(io.BytesIO(raw)).size
    except Exception:
        return None


def _open_for_ocr(image_bytes: bytes):
    """bytes -> an RGB PIL image no larger than MAX_OCR_SIDE, or None when the bytes aren't a usable (or safe) image."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        if min(width, height) < MIN_OCR_SIDE:
            logger.warning("apps.documents.ocr: image of %dx%d is too small to read", width, height)
            return None
        if max(width, height) / min(width, height) > MAX_OCR_ASPECT:
            logger.warning("apps.documents.ocr: image of %dx%d is too thin to read", width, height)
            return None
        if width * height > MAX_OCR_PIXELS:
            logger.warning("apps.documents.ocr: image of %dx%d is too large to read", width, height)
            return None
        if max(width, height) > MAX_OCR_SIDE:
            img.draft("RGB", (MAX_OCR_SIDE, MAX_OCR_SIDE))        # JPEG: decode at a reduced size straight away
        img = img.convert("RGB")
        if max(img.size) > MAX_OCR_SIDE:
            img.thumbnail((MAX_OCR_SIDE, MAX_OCR_SIDE), Image.LANCZOS)
        return img
    except Exception:
        return None


def _load_rgb(image_bytes: bytes):
    """bytes -> RGB numpy array, or None when the bytes aren't a usable image."""
    img = _open_for_ocr(image_bytes)
    if img is None:
        return None
    import numpy as np
    return np.array(img)


@dataclass
class OcrResult:
    text: str = ""
    conf: float | None = None      # mean line/word confidence, 0..1, or None
    engine: str = ""               # which backend actually produced this

    def as_tuple(self):
        return self.text, self.conf


class _Unavailable(Exception):
    """RapidOCR isn't installed on this host."""


def run(image_bytes: bytes) -> OcrResult:
    """OCR a single image (JPEG/PNG bytes) with RapidOCR. Never raises."""
    if not image_bytes:
        return OcrResult()
    try:
        text, conf = _rapidocr(image_bytes)
    except _Unavailable:
        return OcrResult()
    except Exception:
        logger.warning("apps.documents.ocr: RapidOCR failed", exc_info=True)
        return OcrResult()
    if not (text or "").strip():
        return OcrResult()
    return OcrResult(text=text.strip(), conf=conf, engine="rapidocr")


def available() -> str:
    """"rapidocr" if the engine is installed on this host, else "none" (for logs)."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return "none"
    return "rapidocr"


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


# ── scanned-PDF rasterisation ─────────────────────────────────────────
def pdf_page_images(raw: bytes, *, max_pages: int = 3, dpi: int = 200) -> list[bytes]:
    """Render the first `max_pages` pages of an image-only PDF to PNG bytes so"""
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
