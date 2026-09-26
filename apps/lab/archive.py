"""
apps/lab/archive.py
-------------------
store_lab_report_document() — on delivery (apps/lab/signals.py), store the
LabReport as a SharedDocument(doc_type="lab_report") so it shows in the
patient's My Reports. Idempotent by source_ref = "labreport:<id>".

The file is the PDF/image the lab uploaded (normalised to PDF, QR-stamped),
or else a PDF generated from the released result (apps/lab/pdf.py).
All tenant-DB reads are explicit .using(db) with pk filters.
"""

import base64
import logging

logger = logging.getLogger(__name__)

_MIMES = ("application/pdf", "image/jpeg", "image/png")


def store_lab_report_document(report, db, tenant_id):
    from apps.lab.models import LabRequest, LabTest, LabReportItem
    from apps.org.models import Branch
    from apps.tenants.models import Tenant
    from apps.patients.models import Patient
    from apps.records.models import SharedDocument
    from core import storage as blob_storage
    from core import normalise
    from core.qr_token import issue_url as qr_issue
    from core.pdf_qr import stamp_qr

    patient = Patient.objects.using(db).filter(pk=report.patient_id).first() if report.patient_id else None
    awpid = getattr(patient, "awpid", "") or ""
    if not awpid:
        return None

    src_ref = f"labreport:{report.id}"
    existing = SharedDocument.objects.using("default").filter(source_ref=src_ref).first()
    if existing is not None:
        return existing

    req = LabRequest.objects.using(db).filter(pk=report.request_id).first() if report.request_id else None
    test = LabTest.objects.using(db).filter(pk=req.test_id).first() if req and req.test_id else None
    test_name = test.name if test else "Lab Report"
    branch = Branch.objects.using(db).filter(pk=req.branch_id).first() if req and req.branch_id else None
    tenant = Tenant.objects.using("default").filter(pk=tenant_id).first()
    hospital_name = tenant.name if tenant else "Hospital"
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
    slug = blob_storage.identity_slug(name=getattr(patient, "full_name", ""), identifier=awpid)
    s3_key = blob_storage.upload_data_uri(
        "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii"),
        prefix="lab-reports", mime_type="application/pdf", category="lab-report", identity=slug,
    )
    return SharedDocument.objects.using("default").create(
        awpid=awpid, title=title, doc_type="lab_report",
        file_name=f"{title}.pdf", mime_type="application/pdf", s3_key=s3_key,
        uploaded_by="staff", source_tenant_id=tenant_id, source_ref=src_ref,
        public_document_id=report.report_number or "", hospital_label=hospital_name,
        method="staff", document_date=when,
    )
