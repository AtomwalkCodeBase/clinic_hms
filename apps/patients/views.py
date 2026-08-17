"""
apps/patients/views.py
-----------------------
Thin view layer — delegates all logic to PatientService.
Views only: validate input, call service, return standardised response.
"""

import logging

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.response import success, created, error, not_found
from core.pagination import paginate_queryset

logger = logging.getLogger(__name__)
from core.permissions import IsHospitalStaff, IsDoctorOrNurse, IsFrontDesk

from .serializers import (
    PatientRegisterSerializer,
    PatientDetailSerializer,
    PatientSearchSerializer,
    AllergySerializer,
    SharedDiagnosisSerializer,
    SharedVitalSerializer,
    SharedAllergySerializer,
    SharedLabResultSerializer,
    SharedPrescriptionSerializer,
)
from .services import PatientService
from .models import Patient, Allergy


def _maybe_charge_registration_fee(patient, tenant_id, db, user):
    """
    If this hospital has registration_fee_enabled (Hospital Admin → Settings,
    off by default), auto-create a small draft invoice for it — same
    best-effort/non-blocking pattern as apps.opd's consultation auto-invoice:
    registration already succeeded either way, so a billing hiccup here
    shouldn't turn into a failed registration.
    """
    try:
        from apps.tenants.models import Tenant
        from apps.billing.models import Invoice, InvoiceItem
        from apps.billing.views import _recompute_invoice_totals
        from core.utils.nntm import get_next_number

        tenant = Tenant.objects.using("default").get(pk=tenant_id)
        if not tenant.registration_fee_enabled or not tenant.registration_fee_amount:
            return
        if not getattr(patient, "branch_id", None):
            return  # Invoice.branch is required — nothing sensible to bill against

        invoice_number, _ = get_next_number(branch_id=patient.branch_id, entity="invoice", using=db)
        invoice = Invoice.objects.using(db).create(
            patient=patient,
            branch_id=patient.branch_id,
            invoice_number=invoice_number,
            status="draft",
            created_by_id=getattr(user, "id", None),
            notes="Auto-generated registration fee",
        )
        InvoiceItem.objects.using(db).create(
            invoice=invoice,
            description="Registration Fee",
            quantity=1,
            unit_price=tenant.registration_fee_amount,
            tax_rate=tenant.default_tax_rate,
            total=tenant.registration_fee_amount,
        )
        _recompute_invoice_totals(invoice, db)
    except Exception as exc:
        logger.warning("Could not auto-generate registration fee invoice: %s", exc)


class PatientRegisterView(APIView):
    """POST /api/v1/patients/register/"""
    permission_classes = [IsAuthenticated, IsFrontDesk | IsHospitalStaff]

    def post(self, request):
        serializer = PatientRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        try:
            patient = PatientService.register(
                data=serializer.validated_data,
                tenant_id=request.tenant_id,
                db_name=request.tenant_db,
                request=request,
            )
        except ValueError as exc:
            return error(message=str(exc))
        except Exception as exc:
            logger.exception("Patient registration failed: %s", exc)
            return error(
                message=f"Registration failed: {exc}",
                status=500,
            )
        _maybe_charge_registration_fee(patient, request.tenant_id, request.tenant_db, request.user)

        from core.audit import log_action
        log_action(request, request.tenant_db, action="patient.register",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)

        return created(
            data=PatientDetailSerializer(patient).data,
            message="Patient registered successfully.",
        )


class PatientLookupView(APIView):
    """
    GET /api/v1/patients/lookup/?mobile=
    Called live as front desk types a mobile number during registration —
    tells them whether this patient already exists in the Atomwalk network
    (and whether they're already registered at THIS hospital specifically),
    so front desk never creates a disconnected duplicate. Never reveals
    which other hospital a patient has visited.
    """
    permission_classes = [IsAuthenticated, IsFrontDesk | IsHospitalStaff]

    def get(self, request):
        mobile = (request.query_params.get("mobile") or "").strip()
        if len(mobile) < 6:
            return success(data={"exists_in_network": False, "already_registered_here": False})
        result = PatientService.lookup_by_mobile(mobile_raw=mobile, db_name=request.tenant_db)
        return success(data=result)


class PatientSearchView(APIView):
    """
    GET /api/v1/patients/search/?q=&branch_id=
    GET /api/v1/patients/search/?page=&page_size=  (full paginated list — see below)

    Empty/missing q browses the most recently registered patients at this
    hospital instead of erroring — lets front desk scan a short list to
    pick from when they don't have an exact name/UHID/mobile to search yet.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        query     = request.query_params.get("q", "").strip()
        branch_id = request.query_params.get("branch_id")
        if query and len(query) < 2:
            return error(message="Search query must be at least 2 characters.")
        qs = PatientService.search(
            query=query,
            branch_id=int(branch_id) if branch_id else None,
            db_name=request.tenant_db,
        )

        # Two callers share this endpoint:
        #   1. Typeahead search boxes (register/appointments patient picker)
        #      — no ?page=, capped at 50 with a truncated/total_matches hint
        #      instead of page controls, which would be an odd UX for a
        #      live-search dropdown.
        #   2. A full "All Patients" list screen — passes ?page= explicitly
        #      and gets real page/page_size/total_pages controls back, same
        #      shape as AppointmentListCreateView's pagination.
        if "page" in request.query_params:
            page_items, meta = paginate_queryset(request, qs)
            return success(data={
                "results": PatientSearchSerializer(page_items, many=True).data,
                "pagination": meta,
                "is_browse": not query,
            })

        total_matches = qs.count()
        limit = 50
        return success(data={
            "results": PatientSearchSerializer(qs[:limit], many=True).data,
            "total_matches": total_matches,
            "truncated": total_matches > limit,
            "is_browse": not query,
        })


class PatientDetailView(APIView):
    """GET /api/v1/patients/<id>/"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        from core.audit import log_action
        log_action(request, request.tenant_db, action="patient.view",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)

        return success(data=PatientDetailSerializer(patient).data)


class PatientHistoryView(APIView):
    """
    GET /api/v1/patients/<id>/history/
    Returns cross-tenant shared clinical records from Registry HIE.
    source_tenant_id is NEVER included in the response.

    Gated on patient.hie_consent_given — a Patient record only carries this
    flag as True if the patient (or front desk registering them in person)
    explicitly agreed to cross-hospital sharing. Portal bookings always set
    it via the consent modal; front-desk registration sets it from its own
    consent checkbox. If neither ran (e.g. an older record from before this
    flag existed, or consent was declined), no shared data is exposed here
    — this hospital's staff only see what this hospital itself recorded.
    """
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, pk):
        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        if not patient.hie_consent_given:
            from core.audit import log_action
            log_action(request, request.tenant_db, action="patient.history.view_blocked_no_consent",
                        resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)
            return success(data={
                "awpid": patient.awpid, "consent_given": False,
                "diagnoses": [], "vitals": [], "allergies": [],
                "lab_results": [], "prescriptions": [], "documents": [],
            })

        history = PatientService.get_shared_history(awpid=patient.awpid)
        history["consent_given"] = True

        from core.audit import log_action
        log_action(request, request.tenant_db, action="patient.history.view",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)

        return success(data=history)


class PatientDocumentDetailView(APIView):
    """
    GET /api/v1/patients/documents/<doc_id>/
    Full content (including file_data) for one document referenced from the
    lightweight list inside get_shared_history(). Split out into its own
    endpoint so the history payload itself stays small — a doctor only pays
    for the full base64 file when they actually open one.
    """
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, doc_id):
        from apps.registry.models import SharedDocument
        try:
            doc = SharedDocument.objects.using("default").get(pk=doc_id)
        except SharedDocument.DoesNotExist:
            return not_found("Document not found.")

        from core.audit import log_action
        log_action(request, request.tenant_db, action="patient.document.view",
                    resource_type="SharedDocument", resource_id=doc.id)

        return success(data={
            "id": doc.id, "title": doc.title, "doc_type": doc.doc_type,
            "file_name": doc.file_name, "mime_type": doc.mime_type,
            "file_data": doc.file_data, "created_at": doc.created_at,
        })


class PatientLabResultDetailView(APIView):
    """
    GET /api/v1/patients/lab-results/<result_id>/
    Full content (including file_data) for one cross-tenant shared lab
    result, referenced from the lightweight list inside get_shared_history().
    Mirrors PatientDocumentDetailView — same reasoning for keeping this split
    out of the summary payload.
    """
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, result_id):
        from apps.registry.models import SharedLabResult
        try:
            r = SharedLabResult.objects.using("default").get(pk=result_id)
        except SharedLabResult.DoesNotExist:
            return not_found("Lab result not found.")

        from core.audit import log_action
        log_action(request, request.tenant_db, action="patient.lab_result.view",
                    resource_type="SharedLabResult", resource_id=r.id)

        return success(data={
            "id": r.id, "test_name": r.test_name, "result_summary": r.result_summary,
            "mime_type": r.mime_type, "file_data": r.file_data, "delivered_at": r.delivered_at,
        })


class PatientAllergyListCreateView(APIView):
    """GET + POST /api/v1/patients/<id>/allergies/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, pk):
        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")
        allergies = Allergy.objects.using(request.tenant_db).filter(patient=patient)
        return success(data=AllergySerializer(allergies, many=True).data)

    def post(self, request, pk):
        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")
        serializer = AllergySerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        allergy = Allergy.objects.using(request.tenant_db).create(
            patient=patient,
            recorded_by=request.user.id,
            **serializer.validated_data,
        )
        return created(data=AllergySerializer(allergy).data)
