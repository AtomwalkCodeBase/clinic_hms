"""
core/doc_crop.py
-----------------
Auto-crop and straighten a photographed document before OCR — the same
"find the page, flatten the perspective" step every document-scanner app
does (CamScanner, Google Drive's scan mode). Several real test photos
(2026-09-22) included background (desk, laptop bezel/keyboard) and were
shot at an angle; straightening the page before OCR is a classical, free
technique — cv2 is already a transitive dependency of rapidocr-onnxruntime
(it declares `opencv-python>=4.5.1.48`), so this adds no new package on
the server.

Deliberately conservative: if no confident 4-sided page is found — the
page already fills the frame, or the background is too similar to the
page to find an edge — returns None and the caller keeps using the
original image untouched. A wrong crop is worse than no crop.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MIN_AREA_FRACTION = 0.20    # candidate quad must cover at least this much of the frame
_ALREADY_FULL_FRAME = 0.92   # skip the transform if the page already fills ~the whole photo
_WORK_WIDTH = 900            # downscale for contour-finding speed; corners scaled back up
_MIN_OUTPUT_SIDE = 50        # refuse a degenerate (near-zero-size) result


def _order_points(pts):
    """4 arbitrary (x, y) points -> [top-left, top-right, bottom-right, bottom-left]."""
    import numpy as np
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[int(s.argmin())]        # smallest x+y -> top-left
    rect[2] = pts[int(s.argmax())]        # largest x+y  -> bottom-right
    diff = pts[:, 1] - pts[:, 0]           # y - x
    rect[1] = pts[int(diff.argmin())]     # smallest y-x -> top-right
    rect[3] = pts[int(diff.argmax())]     # largest y-x  -> bottom-left
    return rect


def find_document_quad(bgr):
    """
    Return the 4 ordered corner points (in ORIGINAL-image pixel coordinates)
    of the largest plausible page-shaped quadrilateral in the image, or
    None if nothing convincing enough was found.
    """
    import cv2
    import numpy as np

    h, w = bgr.shape[:2]
    if h < 20 or w < 20:
        return None
    scale = _WORK_WIDTH / w if w > _WORK_WIDTH else 1.0
    small = cv2.resize(bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else bgr

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    frame_area = small.shape[0] * small.shape[1]

    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(c)
        if area < frame_area * _MIN_AREA_FRACTION:
            break   # sorted descending — nothing smaller will qualify either
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            pts = approx.reshape(4, 2).astype("float32") / scale   # back to original coords
            return _order_points(pts)
    return None


def straighten(bgr, quad):
    """Perspective-correct `bgr` to a flat top-down view of the `quad` region."""
    import cv2
    import numpy as np

    tl, tr, br, bl = quad
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if width < _MIN_OUTPUT_SIDE or height < _MIN_OUTPUT_SIDE:
        return None
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    m = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(bgr, m, (width, height))


def auto_crop_straighten(raw: bytes) -> "bytes | None":
    """
    Best-effort: find the page in a photographed document and return a
    straightened JPEG. Returns None (caller keeps the original bytes
    unchanged) when no confident page-quad is found, the page already
    fills the frame, or anything goes wrong. Never raises.
    """
    try:
        import io
        import cv2
        import numpy as np
        from PIL import Image, ImageOps

        pil = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)).convert("RGB"))
        bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]

        quad = find_document_quad(bgr)
        if quad is None:
            return None
        if cv2.contourArea(quad) >= (h * w) * _ALREADY_FULL_FRAME:
            return None   # already fills the frame — nothing to gain, don't risk it

        warped = straighten(bgr, quad)
        if warped is None:
            return None

        buf = io.BytesIO()
        Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)).save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        logger.warning("doc_crop: auto_crop_straighten failed; using original image", exc_info=True)
        return None
