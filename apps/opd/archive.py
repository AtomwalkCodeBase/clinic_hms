"""
apps/opd/archive.py
-------------------
store_prescription_document() — render a Prescription to a PDF (with the
"scan to save in My Reports" QR, via apps/opd/pdf.py) and mirror it into the
registry document vault as SharedDocument(doc_type="prescription").

Extracted from apps.opd.views._store_prescription_pdf so the same code path
serves both:
  - new prescriptions        (EncounterSignView, on sign)
  - existing prescriptions    (backfill_documents_from_records command)

Idempotent by source_ref = "encounter:<id>". When a row already exists it is
"self-healed" — blank metadata fields (doctor_label / hospital_label /
public_document_id / document_date) added after the first mirror are
backfilled without re-rendering the PDF. Pass force=True to fully rebuild.

All tenant-DB reads are explicit .using(db) with pk filters — no relation
traversal, which this project's multi-DB router mis-routes to "default".
"""

import base64
import logging
import uuid as _uuid

logger = logging.getLogger(__name__)


def store_prescription_document(rx, db, tenant_id, *, force=False):
    from apps.opd.models import OPDEncounter, Appointment, PrescriptionItem
    from apps.opd.pdf import generate_prescription_pdf
    from apps.org.models import StaffUser, Branch
    from apps.tenants.models import Tenant
    from apps.patients.models import Patient
    from apps.registry.models import SharedDocument
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
    doctor_label = f"Dr. {doctor_name}" if doctor_name else ""

    visit_date = appt.scheduled_date if appt else (rx.created_at.date() if rx.created_at else None)
    src_ref = f"encounter:{rx.encounter_id}"

    existing = SharedDocument.objects.using("default").filter(source_ref=src_ref).first()
    if existing is not None and not force:
        return _self_heal(existing, doctor_label, hospital_name, rx.rx_number or "", visit_date)

    pdf_bytes = generate_prescription_pdf(
        prescription=rx, items=items, doctor_name=doctor_name, patient=patient,
        branch=branch, hospital_name=hospital_name, visit_date=visit_date,
    )
    pdf_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
    title = f"Prescription {rx.rx_number or str(rx.id)[:8]}" + (f" — {visit_date}" if visit_date else "")
    slug = blob_storage.identity_slug(name=patient.full_name, identifier=patient.awpid)
    try:
        file_ref = blob_storage.upload_data_uri(
            pdf_uri, prefix="prescriptions", mime_type="application/pdf",
            category="prescription", identity=slug,
        )
    except blob_storage.StorageError:
        file_ref = pdf_uri  # local dev / no S3 — inline

    if existing is not None:  # force=True — replace the file/metadata in place
        existing.file_data = file_ref
        existing.title = title
        existing.doctor_label = doctor_label
        existing.hospital_label = hospital_name
        existing.public_document_id = rx.rx_number or ""
        existing.document_date = visit_date
        existing.save(using="default")
        return existing

    return SharedDocument.objects.using("default").create(
        awpid=patient.awpid, title=title, doc_type="prescription",
        file_name=f"{title}.pdf", mime_type="application/pdf", file_data=file_ref,
        uploaded_by="staff", source_tenant_id=tenant_id, source_ref=src_ref,
        public_document_id=rx.rx_number or "", hospital_label=hospital_name,
        doctor_label=doctor_label, classification_method="staff",
        verification_status="verified", review_state="filed", document_date=visit_date,
    )


def _self_heal(doc, doctor_label, hospital_label, public_id, doc_date):
    fields = []
    if doctor_label and not doc.doctor_label:
        doc.doctor_label = doctor_label
        fields.append("doctor_label")
    if hospital_label and not doc.hospital_label:
        doc.hospital_label = hospital_label
        fields.append("hospital_label")
    if public_id and not doc.public_document_id:
        doc.public_document_id = public_id
        fields.append("public_document_id")
    if doc_date and not doc.document_date:
        doc.document_date = doc_date
        fields.append("document_date")
    if fields:
        doc.save(using="default", update_fields=fields)
    return doc
