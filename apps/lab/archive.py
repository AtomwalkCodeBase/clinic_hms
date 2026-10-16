"""
apps/lab/archive.py
-------------------
store_lab_report_document() — on delivery (apps/lab/signals.py), store the
LabReport as a MedicalDocument(document_type=lab_report) so it shows in the
patient's My Reports. Idempotent by source_type "lab_report" + source_id = the report id.

The file is the PDF/image the lab uploaded (normalised to PDF, QR-stamped),
or else a PDF generated from the released result (apps/lab/pdf.py).
All hospital-DB reads are explicit .using(db) with pk filters.
"""

import base64
import logging

logger = logging.getLogger(__name__)

_MIMES = ("application/pdf", "image/jpeg", "image/png")


def store_lab_report_document(report, db, hospital_id):
    from apps.lab.models import LabRequest, LabTest, LabReportItem
    from apps.facility.models import Branch
    from apps.hospital_master.models import Hospital
    from apps.hospital_patients.models import HospitalPatient
    from apps.documents.models import MedicalDocument
    from apps.documents.lib_documents import create_issued_document
    from core import storage as blob_storage
    from core import normalise
    from core.qr_token import issue_url as qr_issue
    from core.pdf_qr import stamp_qr

    patient = HospitalPatient.objects.using(db).filter(pk=report.patient_id).first() if report.patient_id else None
    awpid = getattr(patient, "awpid", "") or ""
    if not awpid:
        return None

    source = {"source_type": MedicalDocument.Source.LAB_REPORT, "source_id": str(report.id)}
    existing = MedicalDocument.objects.using("default").filter(**source).first()
    if existing is not None:
        return existing

    req = LabRequest.objects.using(db).filter(pk=report.request_id).first() if report.request_id else None
    test = LabTest.objects.using(db).filter(pk=req.test_id).first() if req and req.test_id else None
    test_name = test.name if test else "Lab Report"
    branch = Branch.objects.using(db).filter(pk=req.branch_id).first() if req and req.branch_id else None
    hospital = Hospital.objects.using("default").filter(pk=hospital_id).first()
    hospital_name = hospital.name if hospital else "Hospital"
    when = report.delivered_at.date() if report.delivered_at else None

    token = ""
    if report.report_number:
        try:
            token = qr_issue(doc_type="lab_report", public_document_id=report.report_number, awpid=awpid)
        except Exception:
            token = ""

    # 1. the file the lab uploaded, if any (S3 key or an older inline data URI)
    raw, pdf_bytes = report.file_url or "", None
    try:
        if raw.startswith("data:"):
            declared = (raw.split(";", 1)[0][5:] or "application/pdf").strip()
            pdf_bytes, _ = normalise.to_pdf(base64.b64decode(raw.split(",", 1)[1]),
                                            declared if declared in _MIMES else "application/pdf")
        elif raw:
            declared = (report.mime_type or "application/pdf").strip()
            pdf_bytes, _ = normalise.to_pdf(blob_storage.get_bytes(raw),
                                            declared if declared in _MIMES else "application/pdf")
    except Exception:
        logger.warning("lab archive: couldn't read the uploaded file for report %s", report.id, exc_info=True)
        pdf_bytes = None

    # 2. no usable file -> generate one from the released result
    if pdf_bytes is None:
        from apps.lab.pdf import generate_lab_report_pdf
        items = list(LabReportItem.objects.using(db).filter(report_id=report.id))
        pdf_bytes = generate_lab_report_pdf(
            report=report, items=items, patient=patient, branch=branch,
            hospital_name=hospital_name, test_name=test_name, qr_token=token,
        )
    elif token:
        pdf_bytes = stamp_qr(pdf_bytes, token)

    title = f"{test_name}" + (f" — {when}" if when else "")
    file_path = blob_storage.upload_data_uri(
        "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii"),
        prefix=f"patients/{awpid}/lab-reports", mime_type="application/pdf", category="lab-report",
    )
    return create_issued_document(
        awpid=awpid, file_path=file_path, name=f"{title}.pdf", doc_type="lab_report",
        source_hospital_id=hospital_id, **source, public_document_id=report.report_number or "",
        document_date=when,
    )
