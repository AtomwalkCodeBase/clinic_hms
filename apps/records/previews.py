"""
Preview pictures: a small JPEG of a stored document, drawn when a phone asks for it.

    render_preview(raw, mime, page, width)   one page of a PDF, or a photo, as JPEG bytes

Nothing is stored: the app asks for page 1 at a small width for the list thumbnails and keeps the answer (the view sends
cache headers and an ETag). The original file is never touched, and Download still serves it as it is.

The limits follow core/ocr.py, where a 1x1 or a very thin image once used 4-5 GB of memory on the 2 GB server: an image
that is too big, too thin or unreadable is refused with PreviewUnavailable (the app then shows the document's type icon).
"""
import io
import logging
import threading

logger = logging.getLogger(__name__)

MIN_WIDTH = 120
MAX_WIDTH = 1800
DEFAULT_WIDTH = 300
JPEG_QUALITY = 78
MAX_PIXELS = 50_000_000          # an image bigger than this is not drawn
MIN_SIDE = 32                    # the same floor as OCR: anything smaller is not a document
MAX_ASPECT = 8                   # a thinner strip than 8:1 is not drawn
MAX_ZOOM = 4.0                   # the largest scale a PDF page is drawn at
MAX_BYTES = 40 * 1024 * 1024     # the view refuses to read a bigger file to draw a picture

# Drawing is the heavy part, so only a few run at once in one process; the rest wait instead of using more memory.
_SLOTS = threading.BoundedSemaphore(4)


class PreviewUnavailable(Exception):
    """The file can't be drawn (damaged, encrypted, too big or too thin). The message is safe to show."""


class NoSuchPage(Exception):
    """The file has no such page (a photo has only page 1)."""


def clamp_width(width):
    try:
        width = int(width)
    except (TypeError, ValueError):
        return DEFAULT_WIDTH
    return max(MIN_WIDTH, min(MAX_WIDTH, width))


def render_preview(raw, mime, page=1, width=DEFAULT_WIDTH):
    """JPEG bytes of `page` (1-based) of the PDF or photo in `raw`, `width` pixels wide (a smaller image is not
    enlarged). Raises NoSuchPage or PreviewUnavailable."""
    width = clamp_width(width)
    if page < 1:
        raise NoSuchPage()
    with _SLOTS:
        if mime == "application/pdf":
            return _render_pdf_page(raw, page, width)
        if mime in ("image/jpeg", "image/png"):
            if page != 1:
                raise NoSuchPage()
            return _render_image(raw, width)
    raise PreviewUnavailable("This kind of file can't be previewed.")


def _render_pdf_page(raw, page, width):
    try:
        import fitz  # PyMuPDF
    except Exception:
        raise PreviewUnavailable("Previews are not available right now.")
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise PreviewUnavailable("This PDF could not be opened.")
    try:
        if doc.needs_pass:
            raise PreviewUnavailable("This PDF is password protected.")
        if page > doc.page_count:
            raise NoSuchPage()
        pg = doc[page - 1]
        rect = pg.rect
        if rect.width < 1 or rect.height < 1 or max(rect.width, rect.height) / min(rect.width, rect.height) > MAX_ASPECT:
            raise PreviewUnavailable("This page can't be previewed.")
        zoom = min(width / rect.width, MAX_ZOOM)
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    except (PreviewUnavailable, NoSuchPage):
        raise
    except Exception:
        logger.warning("preview: drawing a PDF page failed", exc_info=True)
        raise PreviewUnavailable("This page could not be drawn.")
    finally:
        doc.close()


def _render_image(raw, width):
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size                       # header only, nothing decoded yet
    except Exception:
        raise PreviewUnavailable("This image could not be opened.")
    if min(w, h) < MIN_SIDE or max(w, h) / min(w, h) > MAX_ASPECT or w * h > MAX_PIXELS:
        raise PreviewUnavailable("This image can't be previewed.")
    try:
        if img.format == "JPEG":
            img.draft("RGB", (width * 2, width * 3))      # decode at a reduced size straight away
        img = ImageOps.exif_transpose(img)                # a phone photo is stored sideways with a rotation tag
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.split()[-1])
            img = flat
        else:
            img = img.convert("RGB")
        if img.width > width:
            img = img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()
    except Exception:
        logger.warning("preview: drawing an image failed", exc_info=True)
        raise PreviewUnavailable("This image could not be drawn.")
