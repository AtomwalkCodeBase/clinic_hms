"""
apps/opd/pdf.py
----------------
Renders a real, printable PDF for a Prescription — same reportlab pattern as
apps/billing/pdf.py's invoice PDF (see that module's docstring for why this
returns raw bytes rather than a rendered template, and why the view layer
wraps them as a base64 data URI instead of a raw application/pdf response).
"""
import base64
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
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

    rx_label = prescription.rx_number or str(prescription.id)[:8]
    when = visit_date or prescription.created_at

    # ── QR: "scan to save in My Reports" ────────────────────────────────
    # Encodes an HMAC-signed token (core.qr_token) tying this Rx number to
    # the patient's AWPID, so the portal can verify a re-uploaded photo of
    # this sheet and file it under Prescriptions automatically. Best-effort:
    # a missing rx_number / awpid, or any error, just omits the QR.
    header_right = right
    try:
        awpid = getattr(patient, "awpid", "") if patient else ""
        if prescription.rx_number and awpid:
            import qrcode
            from core.qr_token import issue as _qr_issue
            _tok = _qr_issue(doc_type="prescription",
                             public_document_id=prescription.rx_number, awpid=awpid)
            _qr = qrcode.QRCode(box_size=4, border=1)
            _qr.add_data(_tok)
            _qr.make(fit=True)
            _qr_img = _qr.make_image(fill_color="black", back_color="white")
            qr_size = 20 * mm
            c.drawImage(ImageReader(_qr_img), right - qr_size, height - 20 * mm - qr_size + 4 * mm,
                        width=qr_size, height=qr_size, preserveAspectRatio=True, mask="auto")
            c.setFont("Helvetica", 6)
            c.drawCentredString(right - qr_size / 2, height - 20 * mm - qr_size + 1 * mm,
                                "Scan to save in My Reports")
            header_right = right - qr_size - 4 * mm
    except Exception:
        header_right = right

    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(header_right, height - 20 * mm, "PRESCRIPTION")
    c.setFont("Helvetica", 9)
    c.drawRightString(header_right, height - 26 * mm, f"Rx #: {rx_label}")
    c.drawRightString(header_right, height - 31 * mm, f"Date: {when.strftime('%d %b %Y') if when else '—'}")
    c.drawRightString(header_right, height - 36 * mm, f"Status: {prescription.status.replace('_', ' ').title()}")

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


def generate_encounter_summary_pdf(encounter, appointment, diagnoses, rx_items, doctor_name,
                                    patient, branch, hospital_name):
    """
    A real, printable consultation summary PDF — replaces the doctor's old
    "Download Summary" button, which built a plain .txt file client-side
    with no server round trip. Same reportlab pattern as
    generate_prescription_pdf/apps.billing.pdf.generate_invoice_pdf above.

    encounter:   opd.OPDEncounter instance (signed or draft — either way,
                 this reflects whatever's on the encounter right now)
    appointment: opd.Appointment instance (for chief_complaint/visit date)
    diagnoses:   encounter.diagnoses (list of {"code","description","is_primary"})
    rx_items:    list of opd.PrescriptionItem, or [] if nothing prescribed
    doctor_name: str (already resolved by the caller)
    patient:     patients.Patient instance
    branch:      org.Branch instance (may be None)
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
    c.drawRightString(right, height - 20 * mm, "CONSULTATION SUMMARY")
    c.setFont("Helvetica", 9)
    visit_date = appointment.scheduled_date if appointment else None
    c.drawRightString(right, height - 26 * mm, f"Date: {visit_date.strftime('%d %b %Y') if visit_date else '—'}")
    c.drawRightString(right, height - 31 * mm, f"Status: {encounter.get_status_display()}")

    y -= 6 * mm
    c.setStrokeColor(colors.HexColor("#DDDDDD"))
    c.line(left, y, right, y)
    y -= 10 * mm

    # ── Patient / doctor ────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left, y, "Patient")
    c.drawString(left + 95 * mm, y, "Consulting doctor")
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
    y -= 10 * mm

    def section_header(title):
        nonlocal y
        if y < 30 * mm:
            c.showPage()
            y = height - 20 * mm
        c.setFillColor(colors.HexColor("#F5F5F0"))
        c.rect(left, y - 6 * mm, right - left, 8 * mm, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left + 2 * mm, y - 4 * mm, title)
        y -= 11 * mm

    def wrapped_text(text, font="Helvetica", size=9, indent=0):
        """Simple word-wrap so long free-text fields don't run off the page edge."""
        nonlocal y
        c.setFont(font, size)
        max_width = right - left - indent
        words = (text or "").split()
        line = ""
        for word in words:
            trial = f"{line} {word}".strip()
            if c.stringWidth(trial, font, size) > max_width and line:
                if y < 20 * mm:
                    c.showPage()
                    y = height - 20 * mm
                    c.setFont(font, size)
                c.drawString(left + indent, y, line)
                y -= 5 * mm
                line = word
            else:
                line = trial
        if line:
            if y < 20 * mm:
                c.showPage()
                y = height - 20 * mm
                c.setFont(font, size)
            c.drawString(left + indent, y, line)
            y -= 5 * mm

    # ── Chief complaint ─────────────────────────────────────────────────
    chief_complaint = getattr(appointment, "chief_complaint", "") if appointment else ""
    if chief_complaint:
        section_header("Chief Complaint")
        wrapped_text(chief_complaint)
        y -= 4 * mm

    # ── Diagnoses ────────────────────────────────────────────────────────
    section_header(f"Diagnoses (ICD-10) — {len(diagnoses)}" if diagnoses else "Diagnoses (ICD-10)")
    if diagnoses:
        for d in diagnoses:
            if y < 20 * mm:
                c.showPage()
                y = height - 20 * mm
            c.setFont("Helvetica-Bold", 9)
            c.drawString(left + 2 * mm, y, d.get("code", "—"))
            c.setFont("Helvetica", 9)
            label = d.get("description", "")
            if d.get("is_primary"):
                label += "  (Primary)"
            c.drawString(left + 22 * mm, y, label[:90])
            y -= 6 * mm
    else:
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(left + 2 * mm, y, "None recorded")
        c.setFillColor(colors.black)
        y -= 6 * mm
    y -= 4 * mm

    # ── Prescription ─────────────────────────────────────────────────────
    section_header(f"Prescription — {len(rx_items)} item(s)" if rx_items else "Prescription")
    if rx_items:
        for item in rx_items:
            if y < 20 * mm:
                c.showPage()
                y = height - 20 * mm
            c.setFont("Helvetica-Bold", 9)
            c.drawString(left + 2 * mm, y, (item.drug_name or "—")[:38])
            c.setFont("Helvetica", 9)
            bits = [b for b in [item.dosage, FREQ_LABEL.get(item.frequency, item.frequency),
                                 ROUTE_LABEL.get(item.route, item.route),
                                 f"× {item.duration_days}d" if item.duration_days else None] if b]
            c.drawString(left + 65 * mm, y, " · ".join(bits))
            y -= 6 * mm
    else:
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(left + 2 * mm, y, "None recorded")
        c.setFillColor(colors.black)
        y -= 6 * mm
    y -= 4 * mm

    # ── Advice + follow-up ─────────────────────────────────────────────
    if encounter.advice_to_patient or encounter.follow_up_in_days:
        section_header("Advice & Follow-up")
        if encounter.advice_to_patient:
            wrapped_text(encounter.advice_to_patient)
        if encounter.follow_up_in_days:
            if y < 20 * mm:
                c.showPage()
                y = height - 20 * mm
            c.setFont("Helvetica", 9)
            c.drawString(left + 2 * mm, y, f"Follow-up in {encounter.follow_up_in_days} day(s)")
            y -= 6 * mm

    # ── Footer ──────────────────────────────────────────────────────────
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawCentredString(width / 2, 15 * mm, "This is a system-generated consultation summary. Please consult your doctor before making any changes.")

    c.showPage()
    c.save()
    return buf.getvalue()


def images_to_pdf(page_data_uris, *, header=None):
    """
    Stitch a list of "data:image/...;base64,..." strings into one PDF, one
    image per A4 page, scaled to fit with a margin and aspect ratio kept.

    Used to archive the consult-pad's raw handwriting (ConsultSession
    rx_pages / note_pages) as a permanent PDF on encounter sign — see
    apps.opd.views._store_handwriting_pdfs.

    Returns PDF bytes, or None if nothing decodable was passed.
    """
    imgs = []
    for uri in page_data_uris or []:
        if not isinstance(uri, str) or "," not in uri:
            continue
        try:
            raw = base64.b64decode(uri.split(",", 1)[1])
            imgs.append(ImageReader(BytesIO(raw)))
        except Exception:
            continue
    if not imgs:
        return None

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 12 * mm
    top_pad = 16 * mm if header else margin

    for i, img in enumerate(imgs):
        if header:
            c.setFont("Helvetica-Oblique", 8)
            c.setFillColor(colors.HexColor("#777777"))
            c.drawString(margin, height - 11 * mm, f"{header}  ·  page {i + 1} of {len(imgs)}")
            c.setFillColor(colors.black)

        iw, ih = img.getSize()
        avail_w = width - 2 * margin
        avail_h = height - top_pad - margin
        scale = min(avail_w / iw, avail_h / ih)
        dw, dh = iw * scale, ih * scale
        x = (width - dw) / 2
        y = height - top_pad - dh
        c.drawImage(img, x, y, width=dw, height=dh, preserveAspectRatio=True, mask="auto")
        c.showPage()

    c.save()
    return buf.getvalue()
