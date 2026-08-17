"""
apps/billing/pdf.py
--------------------
Renders a real, printable PDF for an Invoice — reportlab is already a
project dependency (used by the demo-seed script for synthetic lab report
PDFs; see apps/registry/management/commands/seed_full_demo.py) but this is
the first place it's used for an actual production document.

Returns raw PDF bytes; the view layer wraps them as a base64 data URI so the
frontend can open them the same way every other in-app file viewer does
(JWT auth is a bearer header, not a cookie, so a plain <a href> to the API
url won't carry credentials — see frontend/src/utils/fileViewer.js).
"""
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _money(v):
    return f"Rs. {Decimal(v or 0):,.2f}"


def _qr_image(text):
    """
    A compact QR receipt (HMS-09c-2) — no public verification portal exists
    in this product yet, so rather than link to a URL that would 404, the
    code encodes the receipt itself (invoice #, patient, amount, date) as
    plain text. Still genuinely useful: any QR scanner app shows the payment
    confirmation without the patient needing to unfold/photograph the paper.
    """
    import qrcode
    qr = qrcode.QRCode(box_size=4, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")


def generate_invoice_pdf(invoice, items, payments, patient, branch, hospital_name):
    """
    invoice: billing.Invoice instance
    items:   list of billing.InvoiceItem
    payments: list of billing.Payment
    patient: patients.Patient instance
    branch:  org.Branch instance (may be None)
    hospital_name: str
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    left = 20 * mm
    right = width - 20 * mm
    y = height - 20 * mm

    # ── Header ──────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 18)
    c.drawString(left, y, hospital_name or "Hospital")
    c.setFont("Helvetica", 9)
    y -= 6 * mm
    if branch:
        addr_parts = [p for p in [branch.address, branch.city, branch.state, branch.pincode] if p]
        if addr_parts:
            c.drawString(left, y, ", ".join(addr_parts))
            y -= 5 * mm
        if branch.phone:
            c.drawString(left, y, f"Phone: {branch.phone}")
            y -= 5 * mm

    c.setFont("Helvetica-Bold", 14)
    qr_col_right = right - 26 * mm  # leave room for the QR block at top-right
    c.drawRightString(qr_col_right, height - 20 * mm, "INVOICE")
    c.setFont("Helvetica", 9)
    c.drawRightString(qr_col_right, height - 26 * mm, f"Invoice #: {invoice.invoice_number}")
    c.drawRightString(qr_col_right, height - 31 * mm, f"Date: {invoice.created_at.strftime('%d %b %Y') if invoice.created_at else '—'}")
    c.drawRightString(qr_col_right, height - 36 * mm, f"Status: {invoice.status.replace('_', ' ').title()}")

    # QR receipt — invoice #, patient, amount, date encoded as plain text
    # (see _qr_image docstring for why it's not a URL).
    try:
        qr_text = (
            f"{hospital_name or 'Hospital'}\n"
            f"Invoice: {invoice.invoice_number}\n"
            f"Patient: {patient.full_name if patient else '—'} ({patient.uhid if patient else '—'})\n"
            f"Amount: {_money(invoice.total_amount)}\n"
            f"Status: {invoice.status.replace('_', ' ').title()}\n"
            f"Date: {invoice.created_at.strftime('%d %b %Y') if invoice.created_at else '—'}"
        )
        qr_img = _qr_image(qr_text)
        qr_size = 22 * mm
        c.drawImage(ImageReader(qr_img), right - qr_size, height - 20 * mm - qr_size,
                    width=qr_size, height=qr_size, preserveAspectRatio=True, mask="auto")
    except Exception:
        # QR generation is a nice-to-have, not the reason this PDF exists —
        # never let it block the invoice itself from rendering.
        pass

    y -= 6 * mm
    c.setStrokeColor(colors.HexColor("#DDDDDD"))
    c.line(left, y, right, y)
    y -= 10 * mm

    # ── Bill to ─────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left, y, "Billed to")
    y -= 5 * mm
    c.setFont("Helvetica", 10)
    c.drawString(left, y, patient.full_name if patient else "—")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    if patient:
        detail_bits = [f"UHID: {patient.uhid}"]
        if patient.gender:
            detail_bits.append({"M": "Male", "F": "Female", "O": "Other"}.get(patient.gender, patient.gender))
        if patient.mobile:
            detail_bits.append(patient.mobile)
        c.drawString(left, y, " · ".join(detail_bits))
    y -= 12 * mm

    # ── Line items table ────────────────────────────────────────────────
    col_desc  = left
    col_qty   = left + 95 * mm
    col_price = left + 115 * mm
    col_tax   = left + 140 * mm
    col_total = right

    def table_header():
        nonlocal y
        c.setFillColor(colors.HexColor("#F5F5F0"))
        c.rect(left, y - 6 * mm, right - left, 8 * mm, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(col_desc + 2 * mm, y - 4 * mm, "Description")
        c.drawCentredString(col_qty, y - 4 * mm, "Qty")
        c.drawRightString(col_price + 12 * mm, y - 4 * mm, "Unit Price")
        c.drawCentredString(col_tax, y - 4 * mm, "Tax %")
        c.drawRightString(col_total, y - 4 * mm, "Total")
        y -= 10 * mm

    table_header()
    c.setFont("Helvetica", 9)
    for item in items:
        if y < 40 * mm:  # new page if running out of room
            c.showPage()
            y = height - 20 * mm
            c.setFont("Helvetica", 9)
            table_header()
        c.drawString(col_desc + 2 * mm, y, (item.description or "—")[:60])
        c.drawCentredString(col_qty, y, str(item.quantity))
        c.drawRightString(col_price + 12 * mm, y, _money(item.unit_price))
        c.drawCentredString(col_tax, y, f"{item.tax_rate}%")
        c.drawRightString(col_total, y, _money(item.total))
        y -= 7 * mm

    y -= 4 * mm
    c.setStrokeColor(colors.HexColor("#DDDDDD"))
    c.line(left, y, right, y)
    y -= 8 * mm

    # ── Totals ──────────────────────────────────────────────────────────
    def totals_row(label, value, bold=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10 if bold else 9)
        c.drawString(col_price - 20 * mm, y, label)
        c.drawRightString(col_total, y, value)
        y -= 6 * mm

    totals_row("Subtotal", _money(invoice.subtotal))
    if invoice.tax_amount:
        totals_row("Tax", _money(invoice.tax_amount))
    if invoice.discount_amount:
        totals_row("Discount", f"- {_money(invoice.discount_amount)}")
    totals_row("Total", _money(invoice.total_amount), bold=True)
    totals_row("Paid", _money(invoice.paid_amount))
    balance = Decimal(invoice.total_amount or 0) - Decimal(invoice.paid_amount or 0)
    totals_row("Balance due", _money(balance), bold=True)

    # ── Payments ────────────────────────────────────────────────────────
    if payments:
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left, y, "Payment history")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        for p in payments:
            if y < 30 * mm:
                c.showPage()
                y = height - 20 * mm
                c.setFont("Helvetica", 9)
            when = p.paid_at.strftime("%d %b %Y, %I:%M %p") if p.paid_at else "—"
            ref = f" (ref: {p.transaction_ref})" if p.transaction_ref else ""
            c.drawString(left, y, f"{when} — {_money(p.amount)} via {p.payment_mode}{ref}")
            y -= 6 * mm

    # ── Footer ──────────────────────────────────────────────────────────
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawCentredString(width / 2, 15 * mm, "This is a system-generated invoice.")

    c.showPage()
    c.save()
    return buf.getvalue()
