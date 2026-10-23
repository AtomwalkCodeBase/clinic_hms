"""apps/opd/archive.py"""

import base64
import logging

logger = logging.getLogger(__name__)


def store_prescription_document(rx, db, hospital_id):
    from apps.opd.models import OPDEncounter, PrescriptionItem
    from apps.opd.pdf import generate_prescription_pdf
    from apps.hospital_master.models import Hospital
    from apps.documents.models import MedicalDocument
    from apps.documents.lib_documents import create_issued_document
    from core import storage as blob_storage

    items = list(PrescriptionItem.objects.using(db).filter(prescription=rx))
    if not items:
        return None

    enc = (OPDEncounter.objects.using(db).select_related("appointment__patient", "appointment__doctor", "appointment__branch_department__branch")
           .filter(pk=rx.encounter_id).first())
    appt = enc.appointment if enc else None
    patient = appt.patient if appt else None
    if not patient or not getattr(patient, "awpid", ""):
        return None

    branch = appt.branch_department.branch if appt else None
    hospital = Hospital.objects.using("default").filter(pk=hospital_id).first()
    hospital_name = hospital.name if hospital else "Hospital"

    doctor_name = appt.doctor.get_full_name()

    visit_date = appt.scheduled_date if appt else (rx.created_at.date() if rx.created_at else None)
    source = {"source_type": MedicalDocument.Source.ENCOUNTER, "source_id": str(rx.encounter_id)}

    existing = MedicalDocument.objects.using("default").filter(**source).first()
    if existing is not None:
        _write_drug_items(existing, items)
        return existing

    pdf_bytes = generate_prescription_pdf(
        prescription=rx, items=items, doctor_name=doctor_name, patient=patient,
        branch=branch, hospital_name=hospital_name, visit_date=visit_date,
    )
    pdf_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
    title = f"Prescription {rx.rx_number or str(rx.id)[:8]}" + (f" — {visit_date}" if visit_date else "")
    file_path = blob_storage.upload_data_uri(
        pdf_uri, prefix=f"patients/{patient.awpid}/prescriptions", mime_type="application/pdf",
        category="prescription",
    )
    doc = create_issued_document(
        awpid=patient.awpid, file_path=file_path, name=f"{title}.pdf", doc_type="prescription",
        source_hospital_id=hospital_id, **source, public_document_id=rx.rx_number or "",
        document_date=visit_date,
    )
    _write_drug_items(doc, items)
    return doc


def _write_drug_items(doc, items):
    """The drugs on the prescription, kept with its document so other hospitals can see what was prescribed."""
    from apps.documents.models import SharedPrescriptionItem
    rows = SharedPrescriptionItem.objects.using("default")
    rows.filter(document=doc).delete()
    rows.bulk_create(SharedPrescriptionItem(
        document=doc, drug_name=i.drug_name, dose=i.dosage, frequency=i.frequency, route=i.route, duration_days=i.duration_days)
        for i in items)


def build_consultation_summary(enc, db, hospital_id):
    """The typed consultation note of a visit as a PDF: (bytes, patient, visit_date)."""
    from apps.opd.models import Appointment, Prescription
    from apps.opd.pdf import generate_encounter_summary_pdf
    from apps.hospital_master.models import Hospital

    appointment = (Appointment.objects.using(db).select_related("patient", "doctor", "branch_department__branch").filter(pk=enc.appointment_id).first())
    patient = appointment.patient
    doctor_name = appointment.doctor.get_full_name()
    rx = Prescription.objects.using(db).filter(encounter_id=enc.id).first()
    rx_items = list(rx.rx_items.using(db).all()) if rx else []
    branch = appointment.branch_department.branch if appointment else None
    hospital = Hospital.objects.using("default").filter(pk=hospital_id).first()
    pdf = generate_encounter_summary_pdf(
        encounter=enc, appointment=appointment, diagnoses=enc.diagnoses or [], rx_items=rx_items, doctor_name=doctor_name,
        patient=patient, branch=branch, hospital_name=hospital.name if hospital else "Hospital")
    return pdf, patient, (appointment.scheduled_date if appointment else None)


def store_consultation_note_document(enc, db, hospital_id):
    """After sign: keep the typed note (history, examination, assessment, plan) with the patient's documents, like the prescription."""
    from apps.documents.models import MedicalDocument
    from apps.documents.lib_documents import create_issued_document, source_uuid
    from core import storage as blob_storage

    if not any((getattr(enc, f) or "").strip() for f in ("subjective", "objective", "assessment", "plan")) and not enc.diagnoses:
        return None
    ref = {"source_type": MedicalDocument.Source.ENCOUNTER, "source_id": source_uuid(f"{enc.id}:consultation-note")}
    existing = MedicalDocument.objects.using("default").filter(**ref).first()
    if existing is not None:
        return existing
    pdf_bytes, patient, visit_date = build_consultation_summary(enc, db, hospital_id)
    if not patient or not getattr(patient, "awpid", ""):
        return None
    pdf_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
    title = "Consultation Note" + (f" — {visit_date}" if visit_date else "")
    file_path = blob_storage.upload_data_uri(
        pdf_uri, prefix=f"patients/{patient.awpid}/consult-notes", mime_type="application/pdf", category="consult-note")
    return create_issued_document(
        awpid=patient.awpid, file_path=file_path, name=f"{title}.pdf", doc_type="consultation_note", source_hospital_id=hospital_id,
        source_type=ref["source_type"], source_id=ref["source_id"], document_date=visit_date, read_facts=False)
