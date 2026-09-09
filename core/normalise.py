"""
core/normalise.py
-----------------
Every file that enters My Reports is stored as a PDF. Hospital-issued
documents and patient-uploaded PDFs pass through untouched; a JPEG or PNG the
patient uploads or photographs is converted here to a single-page PDF —
EXIF-rotated, metadata stripped, transparency flattened to white.

Pillow's own PDF encoder is used (one page sized to the image). A JPEG is
embedded as-is; a large opaque PNG is downscaled and re-encoded so the PDF
stays small. The longest edge is capped so a 12 MP phone photo does not
produce a 10 MB PDF.

Failure here is not fatal to an upload: callers catch the exception and store
the original bytes instead (see PortalDocumentListCreateView.post).
"""

import io

from PIL import Image, ImageOps

_MAX_EDGE = 2600  # px — enough to stay legible for a full A4 scan


def to_pdf(raw: bytes, mime_type: str) -> tuple:
    """
    Return (pdf_bytes, "application/pdf").

    - application/pdf  -> returned unchanged.
    - image/jpeg, image/png -> a single-page PDF, EXIF orientation applied,
      no metadata carried over, transparency composited onto white.
    """
    if mime_type == "application/pdf":
        return raw, "application/pdf"

    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)  # honour the camera's rotation flag

    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if max(img.size) > _MAX_EDGE:
        ratio = _MAX_EDGE / float(max(img.size))
        img = img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))), Image.LANCZOS)

    buf = io.BytesIO()
    # resolution drives the PDF page size; the saved PDF carries no EXIF.
    img.save(buf, format="PDF", resolution=150.0)
    return buf.getvalue(), "application/pdf"
