"""
core/pdf_qr.py
--------------
Overlay a QR code onto page 1 of an existing PDF.

Prescriptions are rendered by us (apps/opd/pdf.py) so their QR is drawn at
generation time. Lab reports are usually a file the lab *uploaded*, so there
is no generation step to hook — this stamps the "scan to save in My Reports"
QR onto that uploaded PDF instead.

Best-effort: any failure (not a PDF, pypdf/qrcode missing, encrypted file)
returns the original bytes unchanged.
"""

import io
import logging

logger = logging.getLogger(__name__)


def stamp_qr(pdf_bytes: bytes, token: str, *, caption: str = "Scan to save in My Reports") -> bytes:
    if not pdf_bytes or not token:
        return pdf_bytes
    try:
        import qrcode
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
    except Exception:
        return pdf_bytes

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return pdf_bytes
        page0 = reader.pages[0]
        pw = float(page0.mediabox.width)
        ph = float(page0.mediabox.height)

        qr = qrcode.QRCode(box_size=4, border=1)
        qr.add_data(token)
        qr.make(fit=True)
        qbuf = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(qbuf, format="PNG")
        qbuf.seek(0)

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(pw, ph))
        size = 20 * mm
        x = pw - size - 12 * mm
        y = ph - size - 12 * mm
        c.setFillColorRGB(1, 1, 1)
        c.rect(x - 2 * mm, y - 6 * mm, size + 4 * mm, size + 9 * mm, fill=1, stroke=0)
        c.drawImage(ImageReader(qbuf), x, y, width=size, height=size, mask="auto")
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.setFont("Helvetica", 5)
        c.drawCentredString(x + size / 2, y - 4 * mm, caption)
        c.save()
        buf.seek(0)

        overlay = PdfReader(buf).pages[0]
        page0.merge_page(overlay)

        writer = PdfWriter()
        for pg in reader.pages:
            writer.add_page(pg)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        logger.warning("pdf_qr.stamp_qr failed; returning original", exc_info=True)
        return pdf_bytes
