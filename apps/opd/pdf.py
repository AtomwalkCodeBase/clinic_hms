"""
apps/opd/pdf.py
----------------
Renders a real, printable PDF for a Prescription — same reportlab pattern as
apps/billing/pdf.py's invoice PDF (see that module's docstring for why this
returns raw bytes rather than a rendered template, and why the view layer
wraps them as a base64 data URI instead of a raw application/pdf response).
"""
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

FREQ_LABEL = {
    "od": "Once daily", "bd": "Twice daily", "td": "3x daily", "qid": "4x daily",
    "sos": "As needed", "stat": "Immediately", "nocte": "At night", "mane": "Morning",
}
ROUTE_LABEL = {
    "oral": "Oral", "iv": "IV", "im": "IM", "sc": "Subcutaneous",
    "topical": "Topical", "inhaled": "Inhaled", "rectal": "Rectal", "sublingual": "Sublingual",
}


def generate_prescription_pdf(prescription, items, doctor_name, patient, branch, hospital_name, visit_date=None):
    """
    prescription: opd.Prescription instance
    items:        list of opd.PrescriptionItem
    doctor_name:  str (already resolved — Prescription only stores a raw
                  doctor_user_id, resolving the display name is the view's job)
    patient:      patients.Patient instance
    branch:       org.Branch instance (may be None)
    hospital_name: str
    visit_date:   date the encounter happened (may be None) — distinct from
                  created_at on the prescription row itself, which is fine
                  to fall back to if this isn't passed.
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
    c.drawRightString(right, height - 20 * mm, "PRESCRIPTION")
    c.setFont("Helvetica", 9)
    rx_label = prescription.rx_number or str(prescription.id)[:8]
    c.drawRightString(right, height - 26 * mm, f"Rx #: {rx_label}")
    when = visit_date or prescription.created_at
    c.drawRightString(right, height - 31 * mm, f"Date: {when.strftime('%d %b %Y') if when else '—'}")
    c.drawRightString(right, height - 36 * mm, f"Status: {prescription.status.replace('_', ' ').title()}")

    y -= 6 * mm
    c.setStrokeColor(colors.HexColor("#DDDDDD"))
    c.line(left, y, right, y)
    y -= 10 * mm

    # ── Patient / doctor ────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left, y, "Patient")
    c.drawString(left + 95 * mm, y, "Prescribing doctor")
    y -= 5 * mm
    c.setFont("Helvetica", 10)
    c.drawString(left, y, patient.full_name if patient else "—")
    c.drawString(left + 95 * mm, y, f"Dr. {doctor_name}" if doctor_name else "—")
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    if patient:
        detail_bits = [f"UHID: {patient.uhid}"]
        if patient.gender:
            detail_bits.append({"M": "Male", "F": "Female", "O": "Other"}.get(patient.gender, patient.gender))
        if getattr(patient, "date_of_birth", None):
            detail_bits.append(f"DOB: {patient.date_of_birth.strftime('%d %b %Y')}")
        c.drawString(left, y, " · ".join(detail_bits))
    y -= 12 * mm

    # ── Rx items table ──────────────────────────────────────────────────
    col_drug  = left
    col_dose  = left + 65 * mm
    col_freq  = left + 95 * mm
    col_route = left + 130 * mm
    col_days  = right

    def table_header():
        nonlocal y
        c.setFillColor(colors.HexColor("#F5F5F0"))
        c.rect(left, y - 6 * mm, right - left, 8 * mm, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(col_drug + 2 * mm, y - 4 * mm, "Medicine")
        c.drawString(col_dose, y - 4 * mm, "Dose")
        c.drawString(col_freq, y - 4 * mm, "Frequency")
        c.drawString(col_route, y - 4 * mm, "Route")
        c.drawRightString(col_days, y - 4 * mm, "Days")
        y -= 10 * mm

    table_header()
    c.setFont("Helvetica", 9)
    for item in items:
        if y < 50 * mm:
            c.showPage()
            y = height - 20 * mm
            c.setFont("Helvetica", 9)
            table_header()
        c.setFont("Helvetica-Bold", 9)
        c.drawString(col_drug + 2 * mm, y, (item.drug_name or "—")[:38])
        c.setFont("Helvetica", 9)
        c.drawString(col_dose, y, item.dosage or "—")
        c.drawString(col_freq, y, FREQ_LABEL.get(item.frequency, item.frequency) or "—")
        c.drawString(col_route, y, ROUTE_LABEL.get(item.route, item.route) or "—")
        c.drawRightString(col_days, y, str(item.duration_days) if item.duration_days else "—")
        y -= 6 * mm
        if item.instructions:
            c.setFont("Helvetica-Oblique", 8)
            c.setFillColor(colors.HexColor("#666666"))
            c.drawString(col_drug + 2 * mm, y, item.instructions[:100])
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 9)
            y -= 6 * mm
        y -= 2 * mm

    y -= 4 * mm
    c.setStrokeColor(colors.HexColor("#DDDDDD"))
    c.line(left, y, right, y)
    y -= 10 * mm

    # ── Notes ───────────────────────────────────────────────────────────
    if getattr(prescription, "notes", ""):
        if y < 30 * mm:
            c.showPage()
            y = height - 20 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left, y, "Notes")
        y -= 6 * mm
        c.setFont("Helvetica", 9)
        c.drawString(left, y, prescription.notes[:110])
        y -= 8 * mm

    # ── Footer ──────────────────────────────────────────────────────────
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawCentredString(width / 2, 15 * mm, "This is a system-generated prescription. Please consult your doctor before making any changes.")

    c.showPage()
    c.save()
    return buf.getvalue()
