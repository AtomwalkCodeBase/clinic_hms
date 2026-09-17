"""
core/image_quality.py
---------------------
The "is this photo readable?" gate that runs before an outside upload is
classified.

The point: a genuinely unreadable phone photo — motion-blurred, dark,
cropped, or too small — should be handed straight back to the patient with a
plain "retake this" rather than OCR'd into garbage and filed as "Other".
A clear photo, and any PDF with a real text layer, sail through untouched.

No OpenCV / numpy dependency: the blur metric is a Laplacian-variance
computed with a PIL convolution kernel, which is the same idea as
`cv2.Laplacian(...).var()`. If Pillow is unavailable the gate abstains
(returns ok) rather than blocking uploads.

Thresholds are deliberately lenient and `settings`-overridable — a
false "unreadable" costs the patient a retake, so we would rather let a
marginal image through to the classifier (which then parks it in the review
tray) than reject a usable one.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Overridable via settings.DOC_IMAGE_QUALITY = {"min_edge": 1000, ...}
_DEFAULTS = {
    "min_edge": 900,          # px, longest side
    "min_pixels": 480_000,    # ~800x600
    "dark_mean": 26,          # 0..255 grayscale mean below this -> too dark
    # A bright white lab-report/prescription page routinely averages 236-248
    # with plenty of contrast (dark ink against the paper) — that's a normal
    # photo, not glare. Genuine washout blows the highlights AND crushes
    # contrast at once, so "too bright" requires both signs together:
    # mean past `bright_mean` *and* stddev under `bright_stddev_max`.
    "bright_mean": 250,
    "bright_stddev_max": 22,
    "min_stddev": 12,         # flat / no contrast
    "blur_hp": 3.0,           # std-dev of the high-pass residual; below this -> too blurry
    "min_text_chars": 24,     # PDF text-layer length that counts as "digital"
}


@dataclass
class QualityResult:
    ok: bool
    reason: str = ""          # machine slug: "" | too_small | too_dark | too_bright | low_contrast | blurry | unreadable_ocr
    message: str = ""         # patient-facing
    detail: dict = None       # metrics, for tuning / audit

    def __post_init__(self):
        if self.detail is None:
            self.detail = {}


_PASS = QualityResult(ok=True)

_RETAKE = "Retake it in good light, hold the phone steady, and keep the whole page flat and in frame."


def _cfg():
    try:
        from django.conf import settings
        return {**_DEFAULTS, **getattr(settings, "DOC_IMAGE_QUALITY", {})}
    except Exception:
        return dict(_DEFAULTS)


def _pdf_has_text(raw: bytes, min_chars: int) -> bool:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "".join((page.extract_text() or "") for page in reader.pages[:3])
        return len(text.strip()) >= min_chars
    except Exception:
        return False


def assess(raw: bytes, mime_type: str) -> QualityResult:
    """
    Decide whether `raw` is worth trying to classify.

      * application/pdf with a usable text layer  -> ok (it's a digital report)
      * application/pdf with no text layer        -> ok here; the classifier's
            OCR step (or the review tray) handles image-only PDFs
      * image/jpeg | image/png                    -> the checks below
    """
    cfg = _cfg()

    if mime_type == "application/pdf":
        # A born-digital PDF is always fine. An image-only ("scanned") PDF we
        # don't rasterise here — let it through; OCR or the patient sorts it.
        return _PASS

    if mime_type not in ("image/jpeg", "image/png"):
        return _PASS

    try:
        from PIL import Image, ImageChops, ImageFilter, ImageStat
    except Exception:
        logger.info("image_quality: Pillow unavailable — skipping gate")
        return _PASS

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return QualityResult(
            ok=False, reason="unreadable_ocr",
            message="We couldn't open this image. " + _RETAKE,
        )

    w, h = img.size
    detail = {"w": w, "h": h}
    if max(w, h) < cfg["min_edge"] or (w * h) < cfg["min_pixels"]:
        return QualityResult(
            ok=False, reason="too_small", detail=detail,
            message="This photo is too small or low-resolution to read. " + _RETAKE,
        )

    gray = img.convert("L")
    # Downscale very large images before the convolution — the blur metric is
    # scale-tolerant and this keeps it fast.
    long_edge = max(gray.size)
    if long_edge > 1600:
        f = 1600 / long_edge
        gray = gray.resize((max(1, int(gray.size[0] * f)), max(1, int(gray.size[1] * f))))

    stat = ImageStat.Stat(gray)
    mean = stat.mean[0]
    stddev = stat.stddev[0]
    detail["mean"] = round(mean, 1)
    detail["stddev"] = round(stddev, 1)

    if mean < cfg["dark_mean"]:
        return QualityResult(ok=False, reason="too_dark", detail=detail,
                             message="This photo is too dark to read. " + _RETAKE)
    if mean > cfg["bright_mean"] and stddev < cfg["bright_stddev_max"]:
        return QualityResult(ok=False, reason="too_bright", detail=detail,
                             message="This photo is washed out by glare. " + _RETAKE)
    if stddev < cfg["min_stddev"]:
        return QualityResult(ok=False, reason="low_contrast", detail=detail,
                             message="We couldn't make out any text on this page. " + _RETAKE)

    # Blur proxy: the energy in the high-frequency residual (image minus its
    # own slight blur). A sharp page has fine detail that a 2px blur removes;
    # an already-blurred page has almost none, so the residual collapses to
    # near zero. Pillow's kernels clamp to 8-bit and lose dynamic range, so a
    # raw Laplacian variance is unreliable here — this survives it.
    hp = ImageChops.difference(gray, gray.filter(ImageFilter.GaussianBlur(2)))
    hp_std = ImageStat.Stat(hp).stddev[0]
    detail["blur_var"] = round(hp_std, 2)
    if hp_std < cfg["blur_hp"]:
        return QualityResult(ok=False, reason="blurry", detail=detail,
                             message="This photo is too blurry to read. " + _RETAKE)

    return QualityResult(ok=True, detail=detail)
