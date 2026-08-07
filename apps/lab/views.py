import logging

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from core.response import success, created, error, not_found
from core.permissions import IsHospitalStaff, IsLabTech, IsDoctor
from core.permissions import RequireFeature
from core.utils.nntm import get_next_number
from core.pagination import paginate_queryset
from core.file_validation import validate_data_uri, FileValidationError
from .serializers import (
    LabTestSerializer, LabRequestSerializer, LabReportSerializer,
    LabRequestChoiceSerializer,
)
from .models import LabTest, LabRequest, LabReport, LabReportItem

logger = logging.getLogger(__name__)


class LabCatalogView(APIView):
    """
    GET  /api/v1/lab/catalog/  — active tests, for doctor/nurse/patient pickers.
                                  Pass ?include_inactive=1 (lab-tech catalog
                                  management screen) to also see deactivated ones.
    POST /api/v1/lab/catalog/  — lab tech adds a new test to the catalog.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def get(self, request):
        tests = LabTest.objects.using(request.tenant_db)
        if request.query_params.get("include_inactive") != "1":
            tests = tests.filter(is_active=True)
        return success(data=LabTestSerializer(tests, many=True).data)

    def post(self, request):
        s = LabTestSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        db = request.tenant_db
        validated = dict(s.validated_data)
        # Code is never typed by hand — NNTM assigns it, same as UHID/invoice/
        # lab report numbers, so codes stay unique and consistently formatted.
        if not validated.get("code"):
            validated["code"] = self._next_test_code(request, db)

        test = LabTest.objects.using(db).create(**validated)
        return created(data=LabTestSerializer(test).data, message="Test added to catalog.")

    def _next_test_code(self, request, db):
        from apps.org.models import NextNumber, Branch

        branch_id = getattr(request.user, "branch_id", None)
        if not branch_id:
            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            branch_id = branch.id if branch else None
        if not branch_id:
            return ""

        # Idempotent — covers branches created before "lab_test" existed as
        # an NNTM entity, so older tenants don't hit a missing-row DoesNotExist.
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
        try:
            test = LabTest.objects.using(request.tenant_db).get(pk=pk)
        except LabTest.DoesNotExist:
            return not_found("Test not found.")
        s = LabTestSerializer(test, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        s.save()
        return success(data=LabTestSerializer(test).data, message="Test updated.")


class LabRequestListCreateView(APIView):
    """
    GET  /api/v1/lab/requests/  — filter by encounter_id, appointment_id,
                                   patient_id, or status. Used by the doctor's
                                   consultation page, the nurse's lab-orders
                                   page, and the lab-tech queue alike.
    POST /api/v1/lab/requests/  — doctor orders one or more tests for an
                                   encounter: { encounter_id, tests: [id,...],
                                   urgency?, clinical_notes? }. Patient,
                                   branch, appointment and requested_by are
                                   all resolved server-side from the encounter
                                   — never trusted from the client.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def get(self, request):
        db = request.tenant_db
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
        return success(data={
            "results": LabRequestSerializer(page_items, many=True, context={"db": db}).data,
            "pagination": meta,
        })

    def post(self, request):
        from apps.opd.models import OPDEncounter

        db = request.tenant_db
        encounter_id = request.data.get("encounter_id")
        if not encounter_id:
            return error("encounter_id is required.", errors={"encounter_id": "Required."})
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=encounter_id)
        except OPDEncounter.DoesNotExist:
            return not_found("Encounter not found.")

        from apps.patients.models import Patient
        try:
            patient = Patient.objects.using(db).get(uuid=enc.patient_id)
        except Patient.DoesNotExist:
            return error("Patient record not found for this encounter.")

        test_ids = request.data.get("tests")
        if not test_ids:
            single = request.data.get("test_id") or request.data.get("test")
            test_ids = [single] if single else []
        if not test_ids:
            return error("At least one test is required.", errors={"tests": "Required."})

        urgency = request.data.get("urgency") or "routine"
        notes   = request.data.get("clinical_notes", "")

        # appointment.branch_id predates some rows (see Appointment model
        # comment) and patient.branch_id can be unset too — fall back to the
        # tenant's first active branch rather than trying to INSERT with a
        # NULL branch (LabRequest.branch is required, so that would 500).
        branch_id = enc.appointment.branch_id or patient.branch_id
        if not branch_id:
            from apps.org.models import Branch
            fallback_branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            branch_id = fallback_branch.id if fallback_branch else None
        if not branch_id:
            return error("Could not determine a branch for this order — no active branch is configured for this hospital.")

        created_rows = []
        skipped = []
        for test_id in test_ids:
            try:
                test = LabTest.objects.using(db).get(pk=test_id, is_active=True)
            except LabTest.DoesNotExist:
                skipped.append(f"test {test_id} (not found or inactive)")
                continue
            try:
                row = LabRequest.objects.using(db).create(
                    patient=patient, encounter=enc, appointment_id=enc.appointment_id,
                    test=test, requested_by_id=request.user.id, branch_id=branch_id,
                    urgency=urgency, clinical_notes=notes,
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


class LabRequestChoiceView(APIView):
    """
    PATCH /api/v1/lab/requests/{id}/choice/
    Staff-side override — a nurse sets in-house/outside on the patient's
    behalf when the patient can't decide via the portal themselves.
    (The patient's own version of this lives in the portal app, since
    patients authenticate with a different JWT and have no tenant context.)
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff, RequireFeature("feat_lab")]

    def patch(self, request, pk):
        db = request.tenant_db
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


class LabRequestStatusView(APIView):
    """PATCH /api/v1/lab/requests/{id}/status/ — lab tech moves a sample through the pipeline."""
    permission_classes = [IsAuthenticated, IsLabTech, RequireFeature("feat_lab")]

    def patch(self, request, pk):
        db = request.tenant_db
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


class LabReportUploadView(APIView):
    """
    POST /api/v1/lab/requests/{id}/report/
    Lab tech uploads the result (summary optional, file required) for an
    in-house test. Creates the LabReport if it doesn't exist yet; pass
    deliver:true to finalise in the same call (sets status=delivered, fires
    the HIE signal) instead of saving as a draft first. Delivering without a
    file is rejected — the file is what every other login (patient, nurse,
    doctor) actually opens, a text summary alone isn't enough to show them.
    """
    permission_classes = [IsAuthenticated, IsLabTech, RequireFeature("feat_lab")]

    def post(self, request, pk):
        db = request.tenant_db
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
            # type instead of trusting the client-supplied mime_type — a
            # mislabeled upload here would later get served back to a
            # patient's or doctor's browser under whatever content-type was
            # claimed at upload time.
            try:
                verified_mime = validate_data_uri(file_data)
            except FileValidationError as exc:
                return error(str(exc), errors={"file_data": str(exc)})
            report.file_url = file_data
            report.mime_type = verified_mime
        report.file_name = request.data.get("file_name", report.file_name)
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

        return created(data=LabReportSerializer(report).data,
                       message="Report delivered." if deliver else "Report saved as draft.")


class LabReportDeliverView(APIView):
    """POST /api/v1/lab/reports/{id}/deliver/ — deliver a previously-saved draft report."""
    permission_classes = [IsAuthenticated, IsLabTech, RequireFeature("feat_lab")]

    def post(self, request, pk):
        try:
            report = LabReport.objects.using(request.tenant_db).get(pk=pk)
        except LabReport.DoesNotExist:
            return not_found("Report not found.")
        if report.status == "delivered":
            return error("Report already delivered.")
        report.status       = "delivered"
        report.delivered_at = timezone.now()
        report.save(using=request.tenant_db, update_fields=["status", "delivered_at"])

        req = report.request
        req.status = "completed"
        req.save(using=request.tenant_db, update_fields=["status"])
        # Signal fires → SharedLabResult written to Registry DB
        return success(message="Report delivered.")
