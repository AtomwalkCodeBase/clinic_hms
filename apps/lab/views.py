import logging

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.api.response import success, created, error, not_found
from core.api.permissions import IsHospitalAdmin, IsHospitalStaff, IsLabTech
from core.api.permissions import RequireFeature
from core.utils.nntm import get_next_number
from core.api.pagination import paginate_queryset
from core.utils.file_validation import validate_data_uri, FileValidationError
from core import storage as blob_storage
from apps.billing.models import OptionList
from apps.lab.serializers import (
    LabTestSerializer,
    LabRequestSerializer,
    LabReportSerializer,
    LabRequestChoiceSerializer,
    SampleTypeSerializer,
)
from apps.lab.models import LabTest, LabRequest, LabReport, LabReportItem

logger = logging.getLogger(__name__)


class LabCatalogView(APIView):
    """GET  /api/v1/lab/catalog/  — active tests, for doctor/nurse/patient pickers."""
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def get_permissions(self):
        if self.request.method == "POST":                 # only the lab (or the hospital admin) edits the catalogue
            return [IsAuthenticated(), (IsLabTech | IsHospitalAdmin)(), RequireFeature("feat_lab")()]
        return super().get_permissions()

    def get(self, request):
        tests = LabTest.objects.using(request.hospital_db)
        if request.query_params.get("include_inactive") != "1":
            tests = tests.filter(is_active=True)
        return success(data=LabTestSerializer(tests, many=True).data)

    def post(self, request):
        db = request.hospital_db
        s = LabTestSerializer(data=request.data, context={"hospital_db": db})
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        validated = dict(s.validated_data)
        # Code is never typed by hand — NNTM assigns it, same as UHID/invoice/
        if not validated.get("code"):
            validated["code"] = self._next_test_code(request, db)

        test = LabTest.objects.using(db).create(**validated)
        return created(data=LabTestSerializer(test).data, message="Test added to catalog.")

    def _next_test_code(self, request, db):
        from apps.hospital_setup.models import NextNumber, Branch

        branch_id = getattr(request.user, "branch_id", None)
        if not branch_id:
            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            branch_id = branch.id if branch else None
        if not branch_id:
            return ""

        # Idempotent — covers branches created before "lab_test" existed as
        NextNumber.objects.using(db).get_or_create(
            branch_id=branch_id, entity="lab_test",
            defaults={"prefix": "LT-", "pad_length": 4, "last_number": 0},
        )
        code, _ = get_next_number(branch_id=branch_id, entity="lab_test", using=db)
        return code


class LabTestDetailView(APIView):
    """PATCH /api/v1/lab/catalog/{id}/ — edit price/turnaround/name, or deactivate."""
    permission_classes = [IsAuthenticated, IsLabTech, RequireFeature("feat_lab")]

    def patch(self, request, pk):
        db = request.hospital_db
        try:
            test = LabTest.objects.using(db).get(pk=pk)
        except LabTest.DoesNotExist:
            return not_found("Test not found.")
        s = LabTestSerializer(test, data=request.data, partial=True, context={"hospital_db": db})
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        s.save()
        return success(data=LabTestSerializer(test).data, message="Test updated.")


# ── Sample Type catalog — "make it configurable" ────────────────────────────
class SampleTypeListCreateView(APIView):
    """GET  /api/v1/lab/sample-types/  — active list, for the Lab Test"""
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsLabTech(), RequireFeature("feat_lab")()]
        return [IsAuthenticated(), IsHospitalStaff(), RequireFeature("feat_lab")()]

    def get(self, request):
        types = OptionList.objects.using(request.hospital_db).filter(list_type=OptionList.LIST_SAMPLE_TYPE)
        if request.query_params.get("include_inactive") != "1":
            types = types.filter(is_active=True)
        return success(data=SampleTypeSerializer(types, many=True).data)

    def post(self, request):
        s = SampleTypeSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        data = dict(s.validated_data)
        data["value"] = data.get("label", "")
        obj = OptionList.objects.using(request.hospital_db).create(
            list_type=OptionList.LIST_SAMPLE_TYPE, is_system=False, **data
        )
        return created(data=SampleTypeSerializer(obj).data, message="Sample type added.")


class SampleTypeDetailView(APIView):
    """PATCH /api/v1/lab/sample-types/{id}/ — edit or deactivate a sample type."""
    permission_classes = [IsAuthenticated, IsLabTech, RequireFeature("feat_lab")]

    def patch(self, request, pk):
        db = request.hospital_db
        try:
            obj = OptionList.objects.using(db).get(pk=pk, list_type=OptionList.LIST_SAMPLE_TYPE)
        except OptionList.DoesNotExist:
            return not_found("Sample type not found.")
        if obj.is_system and request.data.get("is_active") is False:
            return error("This is one of the default sample types — it can't be deactivated.")
        s = SampleTypeSerializer(obj, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(obj, attr, val)
        if "label" in s.validated_data:
            obj.value = s.validated_data["label"]
        obj.save(using=db)
        return success(data=SampleTypeSerializer(obj).data, message="Sample type updated.")


class LabRequestListCreateView(APIView):
    """GET  /api/v1/lab/requests/  — filter by encounter_id, appointment_id,"""
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def get(self, request):
        db = request.hospital_db
        qs = LabRequest.objects.using(db).select_related("test", "patient").order_by("-ordered_at")
        if encounter_id := request.query_params.get("encounter_id"):
            qs = qs.filter(encounter_id=encounter_id)
        if appointment_id := request.query_params.get("appointment_id"):
            qs = qs.filter(appointment_id=appointment_id)
        if patient_id := request.query_params.get("patient_id"):
            qs = qs.filter(patient_id=patient_id)
        if status_filter := request.query_params.get("status"):
            qs = qs.filter(status=status_filter)
        page_items, meta = paginate_queryset(request, qs)
        patients = [r.patient for r in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)
        return success(data={
            "results": LabRequestSerializer(page_items, many=True, context={"db": db}).data,
            "pagination": meta,
        })

    def post(self, request):
        from apps.opd.models import OPDEncounter

        db = request.hospital_db
        encounter_id = request.data.get("encounter_id")
        if not encounter_id:
            return error("encounter_id is required.", errors={"encounter_id": "Required."})
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment__patient", "appointment__branch_department").get(pk=encounter_id)
        except OPDEncounter.DoesNotExist:
            return not_found("Encounter not found.")

        patient = enc.appointment.patient

        test_ids = request.data.get("tests")
        if not test_ids:
            single = request.data.get("test_id") or request.data.get("test")
            test_ids = [single] if single else []
        if not test_ids:
            return error("At least one test is required.", errors={"tests": "Required."})

        urgency = request.data.get("urgency") or "routine"
        notes   = request.data.get("clinical_notes", "")

        branch_id = enc.appointment.branch_department.branch_id

        created_rows = []
        skipped = []
        for test_id in test_ids:
            try:
                test = LabTest.objects.using(db).get(pk=test_id, is_active=True)
            except LabTest.DoesNotExist:
                skipped.append(f"test {test_id} (not found or inactive)")
                continue
            # request_number: a real, sequential, quotable-at-the-counter
            request_number = None
            try:
                from apps.hospital_setup.models import NextNumber
                NextNumber.objects.using(db).get_or_create(
                    branch_id=branch_id, entity="lab_request",
                    defaults={"prefix": "LR-", "pad_length": 6, "last_number": 0},
                )
                request_number, _ = get_next_number(branch_id=branch_id, entity="lab_request", using=db)
            except Exception as e:
                logger.warning("Could not generate request_number for test_id=%s encounter=%s: %s", test_id, encounter_id, e)
            try:
                row = LabRequest.objects.using(db).create(
                    patient=patient, encounter=enc, appointment_id=enc.appointment_id,
                    test=test, requested_by_id=request.user.id, branch_id=branch_id,
                    urgency=urgency, clinical_notes=notes, request_number=request_number,
                )
            except Exception as exc:
                logger.exception("Failed to create LabRequest for test_id=%s encounter=%s", test_id, encounter_id)
                skipped.append(f"{test.name} ({exc.__class__.__name__})")
                continue
            created_rows.append(row)

        if not created_rows:
            detail = f" Reasons: {'; '.join(skipped)}." if skipped else ""
            return error(f"None of the requested tests could be ordered.{detail}")

        message = f"{len(created_rows)} test(s) ordered."
        if skipped:
            message += f" {len(skipped)} could not be ordered ({'; '.join(skipped)})."
        return created(data=LabRequestSerializer(created_rows, many=True, context={"db": db}).data, message=message)


class LabRequestLookupView(APIView):
    """GET /api/v1/lab/requests/lookup/?request_number=LR-000123"""
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def get(self, request):
        request_number = (request.query_params.get("request_number") or "").strip()
        if not request_number:
            return error("request_number is required.")

        db = request.hospital_db
        try:
            req = (LabRequest.objects.using(db)
                   .select_related("test", "patient")
                   .get(request_number__iexact=request_number))
        except LabRequest.DoesNotExist:
            return not_found("No lab request found for that number.")

        return success(data=LabRequestSerializer(req, context={"db": db}).data)


class LabRequestChoiceView(APIView):
    """PATCH /api/v1/lab/requests/{id}/choice/"""
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def patch(self, request, pk):
        db = request.hospital_db
        try:
            req = LabRequest.objects.using(db).get(pk=pk)
        except LabRequest.DoesNotExist:
            return not_found("Lab request not found.")

        s = LabRequestChoiceSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data

        req.patient_choice = d["patient_choice"]
        req.payment_preference = d.get("payment_preference", "")
        req.choice_made_by = "nurse"
        req.choice_made_at = timezone.now()
        if req.patient_choice == "in_house" and req.payment_preference == "pay_online":
            req.payment_status = "pending_online"
        req.save(using=db, update_fields=[
            "patient_choice", "payment_preference", "choice_made_by",
            "choice_made_at", "payment_status",
        ])
        return success(data=LabRequestSerializer(req, context={"db": db}).data, message="Choice updated.")


# Same ceiling as the patient portal's own upload — see
_MAX_DOC_BASE64_CHARS = 7_000_000  # ≈5MB raw file


class LabRequestAttachDocumentView(APIView):
    """POST /api/v1/lab/requests/{id}/attach-document/"""
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            req = LabRequest.objects.using(db).select_related("test", "patient").get(pk=pk)
        except LabRequest.DoesNotExist:
            return not_found("Lab request not found.")

        file_data = request.data.get("file_data") or ""
        if not file_data:
            return error("No file provided.", errors={"file_data": "Required."})
        if len(file_data) > _MAX_DOC_BASE64_CHARS:
            return error("File is too large. Please upload a smaller file (under ~5MB).")

        try:
            mime_type = validate_data_uri(file_data)
        except FileValidationError as exc:
            return error(str(exc), errors={"file_data": str(exc)})

        from apps.documents.models import CHOOSABLE_TYPES
        from apps.documents.models import MedicalDocument
        from apps.documents.lib_documents import create_issued_document, display_name, mime_of

        doc_type = request.data.get("doc_type") or "lab_report"
        if doc_type not in CHOOSABLE_TYPES:
            doc_type = "lab_report"
        title = (request.data.get("title") or "").strip() or f"{req.test.name} — outside report"

        patient = req.patient
        if not patient or not getattr(patient, "awpid", None):
            return error("This request has no patient/AWPID on file — cannot attach a document.")

        try:
            file_key = blob_storage.upload_data_uri(
                file_data, prefix=f"patients/{patient.awpid}/documents/outside-reports", mime_type=mime_type,
                category="patient-document",
            )
        except blob_storage.StorageError as exc:
            return error(str(exc), errors={"file_data": str(exc)})

        file_name = blob_storage.display_file_name(
            "patient-document", mime_type,
            detail=title, name=patient.get_patient_details()["full_name"], identifier=patient.awpid,
        )

        source_hospital_id = request.hospital_id

        doc = create_issued_document(
            awpid=patient.awpid, file_path=file_key, name=file_name, mime_type=mime_type,
            doc_type=doc_type, source_hospital_id=source_hospital_id,
            source_type=MedicalDocument.Source.LAB_REQUEST, source_id=f"{db}:{req.id}",
        )

        # Attaching an outside report only makes sense once the request is
        update_fields = []
        if req.patient_choice != "outside":
            req.patient_choice = "outside"
            req.choice_made_by = "nurse"
            req.choice_made_at = timezone.now()
            update_fields += ["patient_choice", "choice_made_by", "choice_made_at"]
        if update_fields:
            req.save(using=db, update_fields=update_fields)

        return created(data={
            "id": doc.id, "title": display_name(doc), "doc_type": doc.doc_classification,
            "file_name": display_name(doc), "mime_type": mime_of(doc),
            "source_ref": f"{doc.source_type}:{doc.source_id}" if doc.source_id else "", "created_at": doc.created_at,
        }, message="Report attached.")


class LabRequestStatusView(APIView):
    """PATCH /api/v1/lab/requests/{id}/status/ — lab tech moves a sample through the pipeline."""
    permission_classes = [IsAuthenticated, IsLabTech, RequireFeature("feat_lab")]

    def patch(self, request, pk):
        db = request.hospital_db
        try:
            req = LabRequest.objects.using(db).get(pk=pk)
        except LabRequest.DoesNotExist:
            return not_found("Lab request not found.")

        status_val = request.data.get("status")
        if status_val not in dict(LabRequest.STATUS_CHOICES):
            return error("Invalid status.", errors={"status": "Invalid choice."})

        req.status = status_val
        update_fields = ["status"]
        if status_val == "collected" and not req.collected_at:
            req.collected_at = timezone.now()
            update_fields.append("collected_at")
        req.save(using=db, update_fields=update_fields)
        return success(data=LabRequestSerializer(req, context={"db": db}).data, message="Status updated.")


def _bill_lab_request(req, db, user, hospital_id):
    """Create a real Invoice for this lab request, priced from LabTest.price —"""
    if req.invoice_id:
        return
    try:
        from decimal import Decimal
        from apps.billing.models import Invoice, InvoiceItem
        from apps.billing.services import recompute_invoice_totals, hospital_default_tax_rate

        price = req.test.price if req.test.price is not None else Decimal("0")
        tax_rate = hospital_default_tax_rate(hospital_id)
        invoice_number, _ = get_next_number(branch_id=req.branch_id, entity="invoice", using=db)
        invoice = Invoice.objects.using(db).create(
            patient=req.patient, branch_id=req.branch_id, invoice_number=invoice_number,
            status="draft", created_by_id=user.id,
            notes=f"Auto-generated for lab request {req.request_number or req.id}",
        )
        InvoiceItem.objects.using(db).create(
            invoice=invoice, description=req.test.name, quantity=1,
            unit_price=price, tax_rate=tax_rate, total=price,
        )
        recompute_invoice_totals(invoice, db)
        req.invoice = invoice
        req.save(using=db, update_fields=["invoice"])
        logger.info("Billed lab request %s: invoice=%s test=%s price=%s",
                    req.id, invoice.invoice_number, req.test.name, price)
    except Exception as e:
        logger.warning("Could not bill lab request %s: %s", req.id, e)


class LabReportUploadView(APIView):
    """POST /api/v1/lab/requests/{id}/report/"""
    permission_classes = [IsAuthenticated, IsLabTech, RequireFeature("feat_lab")]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            req = LabRequest.objects.using(db).get(pk=pk)
        except LabRequest.DoesNotExist:
            return not_found("Lab request not found.")

        report = LabReport.objects.using(db).filter(request=req).first()
        if not report:
            report_number, _ = get_next_number(branch_id=req.branch_id, entity="lab_report", using=db)
            report = LabReport(request=req, patient=req.patient, report_number=report_number)

        report.result_summary = request.data.get("result_summary", report.result_summary)
        if file_data := request.data.get("file_data"):
            # Verify the payload's real magic bytes match an allowed file
            try:
                verified_mime = validate_data_uri(file_data)
            except FileValidationError as exc:
                return error(str(exc), errors={"file_data": str(exc)})
            from apps.hospital_master.models import Hospital as _Hospital
            _hospital = _Hospital.objects.using("default").filter(pk=request.hospital_id).first()
            folder = blob_storage.hospital_folder(_hospital) if _hospital else db
            identity = blob_storage.identity_slug(name=req.patient.get_patient_details()["full_name"], identifier=req.patient.awpid)
            old_file_key = report.file_url
            try:
                report.file_url = blob_storage.upload_data_uri(
                    file_data, prefix=f"lab-reports/{folder}", mime_type=verified_mime,
                    category="lab-report", identity=identity,
                )
            except blob_storage.StorageError as exc:
                return error(str(exc), errors={"file_data": str(exc)})
            if old_file_key:
                blob_storage.delete(old_file_key)
            report.mime_type = verified_mime
            # Named after the specific test plus who it belongs to, not
            report.file_name = blob_storage.display_file_name(
                "lab-report", verified_mime,
                detail=req.test.name, name=req.patient.get_patient_details()["full_name"], identifier=req.patient.awpid,
            )
        report.performed_by_id = request.user.id

        deliver = bool(request.data.get("deliver"))
        if deliver:
            if not report.file_url:
                return error("Attach a report file before delivering — a summary alone can't be shared with the patient.",
                             errors={"file_data": "Required to deliver."})
            report.status = "delivered"
            report.delivered_at = timezone.now()

        report.save(using=db)

        items = request.data.get("items") or []
        if items:
            LabReportItem.objects.using(db).filter(report=report).delete()
            for it in items:
                LabReportItem.objects.using(db).create(
                    report=report,
                    parameter_name=it.get("parameter_name", ""),
                    result_value=it.get("result_value", ""),
                    unit=it.get("unit", ""),
                    reference_range=it.get("reference_range", ""),
                    is_abnormal=bool(it.get("is_abnormal")),
                )

        if deliver:
            req.status = "completed"
            req.save(using=db, update_fields=["status"])
            _bill_lab_request(req, db, request.user, request.hospital_id)

        return created(data=LabReportSerializer(report).data,
                       message="Report delivered." if deliver else "Report saved as draft.")
