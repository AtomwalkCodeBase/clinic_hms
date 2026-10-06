"""
apps/opd/archive.py
-------------------
store_prescription_document() — on encounter sign, render the Prescription to
a PDF (with the "scan to save in My Reports" QR, apps/opd/pdf.py) and store it
as a MedicalDocument(document_type=prescription). Idempotent by
source_ref = "encounter:<id>".

All tenant-DB reads are explicit .using(db) with pk filters — no relation
traversal, which this project's multi-DB router mis-routes to "default".
"""

import base64
import logging
import uuid as _uuid

logger = logging.getLogger(__name__)


def store_prescription_document(rx, db, tenant_id):
    from apps.opd.models import OPDEncounter, Appointment, PrescriptionItem
    from apps.opd.pdf import generate_prescription_pdf
    from apps.org.models import StaffUser, Branch
    from apps.tenants.models import Tenant
    from apps.patients.models import Patient
    from apps.records.models import MedicalDocument
    from apps.records.services import create_issued_document
    from core import storage as blob_storage

    items = list(PrescriptionItem.objects.using(db).filter(prescription=rx))
    if not items:
        return None

    enc = OPDEncounter.objects.using(db).filter(pk=rx.encounter_id).first()
    appt = (Appointment.objects.using(db).filter(pk=enc.appointment_id).first()
            if enc and enc.appointment_id else None)
    patient_uuid = (enc.patient_id if enc else None) or getattr(rx, "patient_id", None)
    patient = Patient.objects.using(db).filter(uuid=patient_uuid).first() if patient_uuid else None
    if not patient or not getattr(patient, "awpid", ""):
        return None

    branch = (Branch.objects.using(db).filter(pk=appt.branch_id).first()
              if appt and appt.branch_id else None)
    tenant = Tenant.objects.using("default").filter(pk=tenant_id).first()
    hospital_name = tenant.name if tenant else "Hospital"

    doctor_name = None
    try:
        raw = rx.doctor_user_id.int if isinstance(rx.doctor_user_id, _uuid.UUID) else rx.doctor_user_id
        doctor_name = StaffUser.objects.using(db).get(pk=raw).get_full_name()
    except Exception:
        pass

    visit_date = appt.scheduled_date if appt else (rx.created_at.date() if rx.created_at else None)
    src_ref = f"encounter:{rx.encounter_id}"

    existing = MedicalDocument.objects.using("default").filter(source_ref=src_ref).first()
    if existing is not None:
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
    return create_issued_document(
        awpid=patient.awpid, file_path=file_path, name=f"{title}.pdf", doc_type="prescription",
        source_tenant_id=tenant_id, source_ref=src_ref, public_document_id=rx.rx_number or "",
        document_date=visit_date,
    )
