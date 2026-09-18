"""
apps/lab/archive.py
-------------------
store_lab_report_document() — mirror a delivered LabReport into the registry
document vault as SharedDocument(doc_type="lab_report"), so it shows in the
patient's My Reports alongside prescriptions.

  - new lab reports      -> apps/lab/signals.py on deliver
  - existing lab reports  -> backfill_documents_from_records command

The file is, in order of preference:
  1. the PDF/image the lab uploaded (LabReport.file_url — S3 key or data URI),
     normalised to PDF and QR-stamped;
  2. a generated PDF from the parameter rows + summary (apps/lab/pdf.py),
     with the QR drawn in.

Idempotent by source_ref = "labreport:<id>" unless force=True. All tenant-DB
reads are explicit .using(db) with pk filters.
"""

import base64
import logging

logger = logging.getLogger(__name__)


def store_lab_report_document(report, db, tenant_id, *, force=False):
    from apps.lab.models import LabRequest, LabTest, LabReportItem
    from apps.org.models import Branch
    from apps.tenants.models import Tenant
    from apps.patients.models import Patient
    from apps.registry.models import SharedDocument
    from core import storage as blob_storage
    from core import normalise
    from core import report_types
    from core.qr_token import issue_url as qr_issue
    from core.pdf_qr import stamp_qr

    from apps.opd.archive import _self_heal

    patient = Patient.objects.using(db).filter(pk=report.patient_id).first() if report.patient_id else None
    awpid = getattr(patient, "awpid", "") or ""
    if not awpid:
        return None

    req = LabRequest.objects.using(db).filter(pk=report.request_id).first() if report.request_id else None
    test = LabTest.objects.using(db).filter(pk=req.test_id).first() if req and req.test_id else None
    test_name = test.name if test else "Lab Report"
    branch = Branch.objects.using(db).filter(pk=req.branch_id).first() if req and req.branch_id else None

    # The lab test's own catalog name ("Lipid Profile", "CBC") is a short,
    # admin-entered string — the same title-matching classify() uses on messy
    # OCR text works even more reliably here, so this gets a panel tag with
    # no OCR/LLM step at all, unlike an upload's classification path. Ignore
    # .confident (its 0.72 bar is calibrated for a title mention buried in a
    # full noisy OCR page) — any match at all on an isolated clean test name
    # is already as reliable as classification gets.
    panel_result = report_types.classify(test_name)
    report_categories = panel_result.categories

    tenant = Tenant.objects.using("default").filter(pk=tenant_id).first()
    hospital_name = tenant.name if tenant else "Hospital"
    when = report.delivered_at.date() if report.delivered_at else None

    src_ref = f"labreport:{report.id}"
    existing = SharedDocument.objects.using("default").filter(source_ref=src_ref).first()
    if existing is not None and not force:
        healed = _self_heal(existing, "", hospital_name, report.report_number or "", when)
        if report_categories and not healed.report_categories:
            healed.report_categories = report_categories
            healed.category_method = "keyword"
            healed.category_confidence = panel_result.confidence
            healed.save(using="default", update_fields=["report_categories", "category_method", "category_confidence"])
        return healed

    token = ""
    if report.report_number:
        try:
            token = qr_issue(doc_type="lab_report", public_document_id=report.report_number, awpid=awpid)
        except Exception:
            token = ""

    # 1. the file the lab uploaded, if any
    raw = report.file_url or ""
    pdf_bytes = None
    if raw.startswith("data:"):
        try:
            declared = (raw.split(";", 1)[0][5:] or "application/pdf").strip()
            data = base64.b64decode(raw.split(",", 1)[1])
            src_mime = declared if declared in ("application/pdf", "image/jpeg", "image/png") else "application/pdf"
            pdf_bytes, _ = normalise.to_pdf(data, src_mime)
        except Exception:
            logger.warning("lab archive: could not decode inline file for report %s", report.id, exc_info=True)
            pdf_bytes = None
    elif raw:
        try:
            data = blob_storage.get_bytes(raw)
            declared = (report.mime_type or "application/pdf").strip()
            src_mime = declared if declared in ("application/pdf", "image/jpeg", "image/png") else "application/pdf"
            pdf_bytes, _ = normalise.to_pdf(data, src_mime)
        except Exception:
            logger.warning("lab archive: could not fetch S3 file for report %s", report.id, exc_info=True)
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
    pdf_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
    try:
        file_ref = blob_storage.upload_data_uri(
            pdf_uri, prefix="lab-reports", mime_type="application/pdf",
            category="lab-report", identity=slug,
        )
    except blob_storage.StorageError:
        file_ref = pdf_uri  # local dev / no S3 — inline

    if existing is not None:  # force=True — replace in place
        existing.file_data = file_ref
        existing.title = title
        existing.hospital_label = hospital_name
        existing.public_document_id = report.report_number or ""
        existing.document_date = when
        if report_categories:
            existing.report_categories = report_categories
            existing.category_method = "keyword"
            existing.category_confidence = panel_result.confidence
        existing.save(using="default")
        return existing

    return SharedDocument.objects.using("default").create(
        awpid=awpid, title=title, doc_type="lab_report",
        report_categories=report_categories, category_method="keyword" if report_categories else "",
        category_confidence=panel_result.confidence if report_categories else None,
        file_name=f"{title}.pdf", mime_type="application/pdf", file_data=file_ref,
        uploaded_by="staff", source_tenant_id=tenant_id, source_ref=src_ref,
        public_document_id=report.report_number or "", hospital_label=hospital_name,
        classification_method="staff", verification_status="verified",
        review_state="filed", document_date=when,
    )
