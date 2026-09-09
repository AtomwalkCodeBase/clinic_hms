"""
apps/ipd/views.py
------------------
Phase 1 (admission intake) only. See models.py module docstring for the
two design decisions (separate type/source fields; front-desk-can-never-
originate enforcement) that shape every view below.
"""

from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.response import success, created, error, not_found
from core.permissions import IsDoctor, IsFrontDesk, IsHospitalStaff
from core.audit import log_action
from core.utils.nntm import get_next_number

from apps.billing.models import OptionList
from apps.billing.views import _DropdownListCreateView, _DropdownDetailView
from apps.org.models import StaffUser
from apps.patients.models import Patient
from apps.compliance.models import ConsentRecord

from .models import AdmissionReferral, Admission, AdmissionDeposit
from .serializers import (
    OptionListSerializer,
    RecommendAdmissionSerializer, AdmissionReferralSerializer,
    CompleteAdmissionSerializer, AdmissionSerializer,
    AdmissionDepositSerializer,
)


# ── Configurable catalogs — "make it configurable" ───────────────────────────
# Reuses billing's existing generic OptionList CRUD base classes untouched
# (see apps/billing/views.py) — same pattern already backing Drug Form /
# Payment Mode / Invoice Status / Service Category. A hospital admin manages
# these from the same "Dropdown Lists" settings surface, two more tabs.

class AdmissionTypeListCreateView(_DropdownListCreateView):
    list_type = OptionList.LIST_ADMISSION_TYPE
    serializer_class = OptionListSerializer


class AdmissionTypeDetailView(_DropdownDetailView):
    list_type = OptionList.LIST_ADMISSION_TYPE
    serializer_class = OptionListSerializer
    system_can_deactivate = False  # Emergency/Elective/etc. stay available even if deactivated attempts are made — same caution as InvoiceStatusOption


class AdmissionSourceListCreateView(_DropdownListCreateView):
    list_type = OptionList.LIST_ADMISSION_SOURCE
    serializer_class = OptionListSerializer


class AdmissionSourceDetailView(_DropdownDetailView):
    list_type = OptionList.LIST_ADMISSION_SOURCE
    serializer_class = OptionListSerializer
    system_can_deactivate = True  # a hospital genuinely may not use e.g. Medical Tourism/Ambulance-EMS — safe to let them turn these off


# ── Doctor-authored referral — the enforcement point ─────────────────────────

class RecommendAdmissionView(APIView):
    """The ONLY way an AdmissionReferral gets created. IsDoctor-gated;
    recommended_by is always request.user, never client-supplied."""
    permission_classes = [IsAuthenticated, IsDoctor]

    def post(self, request):
        s = RecommendAdmissionSerializer(data=request.data, context={"tenant_db": request.tenant_db})
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        v = s.validated_data

        referral = AdmissionReferral(
            patient_id=v["patient_id"],
            department_id=v["department_id"],
            admission_type=v["admission_type"],
            admission_source=v["admission_source"],
            reason_for_admission=v["reason_for_admission"],
            source_appointment_id=v.get("source_appointment_id"),
            source_encounter_id=v.get("source_encounter_id"),
            external_referring_doctor_name=v.get("external_referring_doctor_name", ""),
            external_referring_facility=v.get("external_referring_facility", ""),
            source_details=v.get("source_details", {}),
            is_mlc=v.get("is_mlc", False),
            guardian_consent_by=v.get("guardian_consent_by", ""),
            recommended_by_id=request.user.id,
        )
        referral.save(using=request.tenant_db)

        log_action(
            request, request.tenant_db, action="ipd.referral.recommend",
            resource_type="AdmissionReferral", resource_id=str(referral.id),
            patient_id=referral.patient_id,
            metadata={"admission_type": referral.admission_type, "admission_source": referral.admission_source},
        )
        return created(
            data=AdmissionReferralSerializer(referral).data,
            message="Admission referral recorded.",
        )


class AcceptExternalReferralView(APIView):
    """IsDoctor-gated countersign for a referral that arrived from outside
    this hospital (external referral / transfer-in / ambulance / medical
    tourism) — required before front desk can act on it. accepted_by is
    always request.user, never client-supplied."""
    permission_classes = [IsAuthenticated, IsDoctor]

    def post(self, request, pk):
        try:
            referral = AdmissionReferral.objects.using(request.tenant_db).get(pk=pk)
        except AdmissionReferral.DoesNotExist:
            return not_found("Referral not found.")

        if referral.status != AdmissionReferral.STATUS_PENDING:
            return error(f"Referral is already {referral.status}, cannot accept.")
        if not referral.requires_acceptance():
            return error("This admission source does not require doctor countersign.")

        from django.utils import timezone
        referral.accepted_by_id = request.user.id
        referral.accepted_at = timezone.now()
        referral.save(using=request.tenant_db, update_fields=["accepted_by_id", "accepted_at"])

        log_action(
            request, request.tenant_db, action="ipd.referral.accept",
            resource_type="AdmissionReferral", resource_id=str(referral.id),
            patient_id=referral.patient_id,
        )
        return success(data=AdmissionReferralSerializer(referral).data, message="Referral accepted.")


class PendingReferralsListView(APIView):
    """Front desk's worklist — the only thing front desk sees to act on.
    Deliberately no create/PUT here: front desk cannot originate a row in
    this table at all."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def get(self, request):
        status_filter = request.query_params.get("status", AdmissionReferral.STATUS_PENDING)
        qs = AdmissionReferral.objects.using(request.tenant_db).filter(status=status_filter)
        return success(data=AdmissionReferralSerializer(qs, many=True).data)


# ── Front desk — registration only ───────────────────────────────────────────

class CompleteAdmissionView(APIView):
    """Front desk's ONLY write path into Admission. Requires an existing,
    pending AdmissionReferral — there is no "create an Admission from
    scratch" endpoint. Everything clinical (type, source, doctor,
    department, reason) is copied from the referral; front desk supplies
    only registration data (attendant, payer, consent)."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    @transaction.atomic
    def post(self, request):
        s = CompleteAdmissionSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        v = s.validated_data
        db = request.tenant_db

        try:
            referral = AdmissionReferral.objects.using(db).select_for_update().get(pk=v["referral_id"])
        except AdmissionReferral.DoesNotExist:
            return not_found("Referral not found.")

        if referral.status != AdmissionReferral.STATUS_PENDING:
            return error(f"Referral is already {referral.status} — cannot register against it again.")
        if referral.requires_acceptance() and not referral.accepted_by_id:
            return error(
                "This referral came from outside the hospital and has not yet been "
                "countersigned by one of this hospital's own doctors."
            )

        patient = Patient.objects.using(db).get(pk=referral.patient_id)

        # NNTM — same collision-free sequence mechanism as UHID/invoice/
        # lab/Rx/queue numbers. entity="admission" (see core/utils/nntm.py).
        admission_number, _ = get_next_number(patient.branch_id, entity="admission", using=db)

        # Re-admission tracking — most recent non-cancelled prior admission
        # for this patient, if any (see models.Admission.previous_admission).
        previous = (
            Admission.objects.using(db)
            .filter(patient_id=referral.patient_id)
            .exclude(status=Admission.STATUS_CANCELLED)
            .order_by("-created_at")
            .first()
        )

        admission = Admission(
            admission_number=admission_number,
            branch_id=patient.branch_id,
            referral=referral,
            patient_id=referral.patient_id,
            department_id=referral.department_id,
            admission_type=referral.admission_type,
            admission_source=referral.admission_source,
            ordering_doctor_id=(referral.accepted_by_id or referral.recommended_by_id),
            logged_by_staff_id=request.user.id,
            reason_for_admission=referral.reason_for_admission,
            expected_discharge_date=v.get("expected_discharge_date"),
            attendant_name=v.get("attendant_name", ""),
            attendant_phone=v.get("attendant_phone", ""),
            payer_type=v.get("payer_type") or patient.payer_type,
            insurance_provider=v.get("insurance_provider") or patient.insurance_provider,
            previous_admission=previous,
            status=Admission.STATUS_ADMITTED,  # Phase 1 goes straight from referral to "admitted (awaiting bed)"
        )
        admission.save(using=db)

        referral.status = AdmissionReferral.STATUS_CONVERTED
        referral.save(using=db, update_fields=["status"])

        ConsentRecord.objects.using(db).create(
            patient=patient,
            consent_type=ConsentRecord.CONSENT_ADMISSION_TREATMENT,
            granted=True,
            source=ConsentRecord.SOURCE_FRONT_DESK,
            recorded_by_id=request.user.id,
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        log_action(
            request, db, action="ipd.admission.register",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id,
            metadata={"admission_number": admission_number, "referral_id": str(referral.id)},
        )

        return created(data=AdmissionSerializer(admission).data, message="Admission completed — awaiting bed.")


class AdmissionDepositView(APIView):
    """Records an advance/deposit. Deliberately does NOT block anything in
    this phase — see models.AdmissionDeposit docstring for why an
    advance-payment gate must never apply to Emergency admissions, and why
    that exemption is not a hospital-configurable toggle."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        try:
            admission = Admission.objects.using(request.tenant_db).get(pk=pk)
        except Admission.DoesNotExist:
            return not_found("Admission not found.")

        s = AdmissionDepositSerializer(data=request.data, context={"tenant_db": request.tenant_db})
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        deposit = AdmissionDeposit(
            admission=admission,
            amount=s.validated_data["amount"],
            payment_mode=s.validated_data["payment_mode"],
            transaction_ref=s.validated_data.get("transaction_ref", ""),
            collected_by_id=request.user.id,
        )
        deposit.save(using=request.tenant_db)

        log_action(
            request, request.tenant_db, action="ipd.admission.deposit",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id,
            metadata={"amount": str(deposit.amount), "payment_mode": deposit.payment_mode},
        )
        return created(data=AdmissionDepositSerializer(deposit).data, message="Deposit recorded.")


# ── Admission read views ──────────────────────────────────────────────────────

class AdmissionListView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        qs = Admission.objects.using(request.tenant_db).all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return success(data=AdmissionSerializer(qs, many=True).data)


class AdmissionDetailView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        try:
            admission = Admission.objects.using(request.tenant_db).get(pk=pk)
        except Admission.DoesNotExist:
            return not_found("Admission not found.")
        data = AdmissionSerializer(admission).data
        deposits = AdmissionDeposit.objects.using(request.tenant_db).filter(admission=admission)
        data["deposits"] = AdmissionDepositSerializer(deposits, many=True).data
        return success(data=data)
