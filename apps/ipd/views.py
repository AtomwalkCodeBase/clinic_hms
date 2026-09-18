"""
apps/ipd/views.py
------------------
Phase 1 (admission intake) only. See models.py module docstring for the
two design decisions (separate type/source fields; front-desk-can-never-
originate enforcement) that shape every view below.
"""

from django.db import transaction
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.response import success, created, error, not_found
from core.permissions import IsDoctor, IsFrontDesk, IsHospitalStaff
from core.audit import log_action
from core.utils.nntm import get_next_number

from apps.billing.models import OptionList
from apps.billing.views import _DropdownListCreateView, _DropdownDetailView
from apps.org.models import StaffUser, Bed
from apps.patients.models import Patient
from apps.compliance.models import ConsentRecord

from .models import AdmissionReferral, Admission, AdmissionDeposit, PatientMovement
from .serializers import (
    OptionListSerializer,
    RecommendAdmissionSerializer, RegisterExternalReferralSerializer, AdmissionReferralSerializer,
    CompleteAdmissionSerializer, AdmissionSerializer, AdmissionUpdateSerializer,
    AdmissionDepositSerializer, AssignBedSerializer,
    ReserveBedSerializer, TransferBedSerializer, PatientMovementSerializer,
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


class RegisterExternalReferralView(APIView):
    """POST /api/v1/ipd/referrals/register-external/
    IsFrontDesk-gated. Lets front desk log a referral the moment an
    external paper/PDF letter arrives, instead of waiting for a doctor to
    type it into RecommendAdmissionView first. Does NOT weaken "front desk
    can never single-handedly originate an admission" (see models.py
    module docstring, design decision 2) — it only changes WHO is allowed
    to log receipt of an externally-sourced referral. The row lands exactly
    where a doctor-recommended external referral would: status=PENDING,
    accepted_by=None — CompleteAdmissionView still refuses to act on it
    until one of this hospital's own doctors calls
    AcceptExternalReferralView. See RegisterExternalReferralSerializer.
    validate() for the source restriction that makes this safe."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request):
        s = RegisterExternalReferralSerializer(data=request.data, context={"tenant_db": request.tenant_db})
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        v = s.validated_data

        source_details = {}
        if v.get("referral_letter_date"):
            source_details["referral_letter_date"] = v["referral_letter_date"].isoformat()
        if v.get("referral_letter_reference"):
            source_details["referral_letter_reference"] = v["referral_letter_reference"]

        referral = AdmissionReferral(
            patient_id=v["patient_id"],
            department_id=v["department_id"],
            admission_type=v["admission_type"],
            admission_source=v["admission_source"],
            reason_for_admission=v["reason_for_admission"],
            external_referring_doctor_name=v["external_referring_doctor_name"],
            external_referring_facility=v.get("external_referring_facility", ""),
            source_details=source_details,
            is_mlc=v.get("is_mlc", False),
            guardian_consent_by=v.get("guardian_consent_by", ""),
            recommended_by_id=request.user.id,
            front_desk_logged=True,
        )
        referral.save(using=request.tenant_db)

        log_action(
            request, request.tenant_db, action="ipd.referral.register_external",
            resource_type="AdmissionReferral", resource_id=str(referral.id),
            patient_id=referral.patient_id,
            metadata={
                "admission_source": referral.admission_source,
                "external_referring_facility": referral.external_referring_facility,
            },
        )
        return created(
            data=AdmissionReferralSerializer(referral).data,
            message="External referral logged — awaiting a hospital doctor's countersign before it can be registered.",
        )


class PendingReferralsListView(APIView):
    """Worklist for referrals awaiting action — shared by two different
    audiences with two different queues:
      - Front desk (default) sees referrals by status (default: pending) —
        this is where CompleteAdmissionView's candidates come from.
        Deliberately no create/PUT here for front desk: front desk cannot
        originate an Admission itself, only log a referral for an
        externally-sourced case (see RegisterExternalReferralView).
      - A doctor hitting this same endpoint (and not also front desk — see
        the branch below) sees only externally-sourced referrals still
        awaiting THEIR countersign: status=pending, accepted_by is empty,
        and the source is one of AdmissionReferral.
        SOURCES_REQUIRING_ACCEPTANCE. That set is populated both by a
        colleague's own RecommendAdmissionView referral and by front desk's
        RegisterExternalReferralView — front_desk_logged on each row (see
        AdmissionReferralSerializer) is what lets the UI tell them apart.
    """
    permission_classes = [IsAuthenticated, (IsFrontDesk | IsDoctor)]

    def get(self, request):
        db = request.tenant_db
        if IsFrontDesk().has_permission(request, self):
            status_filter = request.query_params.get("status", AdmissionReferral.STATUS_PENDING)
            qs = AdmissionReferral.objects.using(db).filter(status=status_filter)
        else:
            qs = AdmissionReferral.objects.using(db).filter(
                status=AdmissionReferral.STATUS_PENDING,
                accepted_by__isnull=True,
                admission_source__in=AdmissionReferral.SOURCES_REQUIRING_ACCEPTANCE,
            )
        return success(data=AdmissionReferralSerializer(qs, many=True).data)


# ── Front desk — registration only ───────────────────────────────────────────

class CompleteAdmissionView(APIView):
    """Front desk's ONLY write path into Admission. Requires an existing,
    pending AdmissionReferral — there is no "create an Admission from
    scratch" endpoint. Everything clinical (type, source, doctor,
    department, reason) is copied from the referral; front desk supplies
    only registration data (attendant, payer, consent)."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request):
        s = CompleteAdmissionSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        v = s.validated_data
        db = request.tenant_db

        # NOTE: this used to be `@transaction.atomic` (no `using=`) on the
        # method itself, which silently wraps a transaction on the DEFAULT
        # alias only — never on the tenant DB alias this view actually
        # writes to. That went unnoticed because this view had never been
        # exercised against a real Postgres before (see the module-level
        # caveat on apps/opd/tests.py's DB-backed tests, which flags the
        # same "written without a live Postgres available" gap). The very
        # first real run of this endpoint against a live DB raised
        # `TransactionManagementError: select_for_update cannot be used
        # outside of a transaction` on the very next line — so this must be
        # an explicit `with transaction.atomic(using=db):` scoped to the
        # tenant alias, not the bare decorator.
        with transaction.atomic(using=db):
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
    """GET   /api/v1/ipd/admissions/{id}/ — full admission + its deposits,
             open to any hospital staff (same read-access level as the list).
    PATCH /api/v1/ipd/admissions/{id}/ — front-desk-only edit of the
             registration fields captured at intake (see
             AdmissionUpdateSerializer for exactly which ones and why)."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsFrontDesk()]

    def get(self, request, pk):
        try:
            admission = Admission.objects.using(request.tenant_db).get(pk=pk)
        except Admission.DoesNotExist:
            return not_found("Admission not found.")
        data = AdmissionSerializer(admission).data
        deposits = AdmissionDeposit.objects.using(request.tenant_db).filter(admission=admission)
        data["deposits"] = AdmissionDepositSerializer(deposits, many=True).data
        return success(data=data)

    def patch(self, request, pk):
        db = request.tenant_db
        try:
            admission = Admission.objects.using(db).get(pk=pk)
        except Admission.DoesNotExist:
            return not_found("Admission not found.")
        if admission.status in (Admission.STATUS_DISCHARGED, Admission.STATUS_CANCELLED):
            return error(f"Admission is {admission.get_status_display()} — nothing left to edit.")

        s = AdmissionUpdateSerializer(data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        if not s.validated_data:
            return error("Nothing to update.")

        update_fields = list(s.validated_data.keys())
        for attr, val in s.validated_data.items():
            setattr(admission, attr, val)
        admission.save(using=db, update_fields=update_fields + ["updated_at"])

        log_action(
            request, db, action="ipd.admission.update",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id,
            metadata={"fields": update_fields},
        )
        return success(data=AdmissionSerializer(admission).data, message="Admission updated.")


# ── Bed assignment — now or later ────────────────────────────────────────
# See docs/PENDING_IMPROVEMENTS.md item 3. Deliberately NOT part of
# CompleteAdmissionView: bed assignment is an independent fact that can
# happen at registration time or any time after, not a required step of
# completing the admission itself (Admission.status already reaches
# STATUS_ADMITTED with no bed at all — see models.py).

class AssignBedView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/assign-bed/
    Front desk assigns a specific bed to an admission — "now" (called right
    after CompleteAdmissionView, in the same screen) or "later" (called
    from the Awaiting Bed worklist, any time after). Same endpoint either
    way; only when it's called differs."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.tenant_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")

            if admission.status not in (Admission.STATUS_ADMITTED, Admission.STATUS_ACTIVE):
                return error(f"Admission is {admission.status} — cannot assign a bed.")
            if admission.bed_id:
                return error("This admission already has a bed assigned. Release it first to reassign.")

            s = AssignBedSerializer(data=request.data, context={"tenant_db": db, "admission_id": str(admission.id)})
            if not s.is_valid():
                return error("Validation error.", errors=s.errors)

            bed = Bed.objects.using(db).select_for_update().get(pk=s.validated_data["bed_id"])
            # AssignBedSerializer already confirmed this bed is either
            # AVAILABLE or RESERVED for this exact admission — nothing left
            # to check here beyond making the change.
            if bed.status != Bed.STATUS_AVAILABLE and bed.reserved_for_admission_id != admission.id:
                return error(f"That bed is currently {bed.get_status_display().lower()}, not available.")

            from django.utils import timezone
            bed.status = Bed.STATUS_OCCUPIED
            bed.reserved_for_admission_id = None
            bed.save(using=db, update_fields=["status", "reserved_for_admission_id", "updated_at"])

            admission.bed = bed
            admission.bed_assigned_at = timezone.now()
            update_fields = ["bed", "bed_assigned_at", "updated_at"]
            # ACTIVE has always meant "bed allocated" (see its STATUS_CHOICES
            # label) — this is the one place that becomes true, so it's the
            # one place that sets it.
            if admission.status == Admission.STATUS_ADMITTED:
                admission.status = Admission.STATUS_ACTIVE
                update_fields.append("status")
            admission.save(using=db, update_fields=update_fields)

            PatientMovement.objects.using(db).create(
                admission=admission, movement_type=PatientMovement.INITIAL_ASSIGNMENT,
                to_bed=bed, to_room_name=bed.room.name, to_bed_number=bed.bed_number,
                moved_by_id=request.user.id,
            )

        log_action(
            request, db, action="ipd.admission.assign_bed",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id,
            metadata={"bed_id": bed.id, "room": bed.room.name, "bed_number": bed.bed_number},
        )
        return success(data=AdmissionSerializer(admission).data, message="Bed assigned.")


class ReleaseBedView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/release-bed/
    Frees the bed back to available without discharging the admission —
    e.g. a bed was assigned in error, or the patient is being moved to a
    different bed (release then assign again)."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.tenant_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")
            if not admission.bed_id:
                return error("This admission has no bed assigned.")

            bed = Bed.objects.using(db).select_for_update().get(pk=admission.bed_id)
            old_room_name, old_bed_number = bed.room.name, bed.bed_number
            # Straight back to AVAILABLE, not CLEANING — this is the
            # "assigned in error, never actually used" undo path (see this
            # view's own docstring). A REAL patient move uses TransferBedView
            # below, which does route the vacated bed through CLEANING.
            bed.status = Bed.STATUS_AVAILABLE
            bed.save(using=db, update_fields=["status", "updated_at"])

            admission.bed = None
            admission.bed_assigned_at = None
            update_fields = ["bed", "bed_assigned_at", "updated_at"]
            # Mirror of the ADMITTED -> ACTIVE flip in AssignBedView — a bed
            # released without a discharge means the patient is still an
            # inpatient, just without a bed again, so they belong back on
            # the Awaiting Bed worklist (AwaitingBedListView filters on
            # REQUESTED/ADMITTED) rather than left stranded as ACTIVE.
            if admission.status == Admission.STATUS_ACTIVE:
                admission.status = Admission.STATUS_ADMITTED
                update_fields.append("status")
            admission.save(using=db, update_fields=update_fields)

            PatientMovement.objects.using(db).create(
                admission=admission, movement_type=PatientMovement.RELEASE,
                from_bed=bed, from_room_name=old_room_name, from_bed_number=old_bed_number,
                moved_by_id=request.user.id,
            )

        log_action(
            request, db, action="ipd.admission.release_bed",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id, metadata={"bed_id": bed.id},
        )
        return success(data=AdmissionSerializer(admission).data, message="Bed released.")


class ReserveBedView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/reserve-bed/  body: {"bed_id": ...}
    Hold a specific, currently-available bed against an admission that's
    ADMITTED (registered, awaiting bed) but not yet bedded — e.g. its
    current occupant is mid-discharge and will free it shortly, and front
    desk doesn't want another admission grabbing it first. The admission
    itself is NOT touched (still ADMITTED, still on the Awaiting Bed
    worklist) — only the bed moves to RESERVED. Confirming the hold once
    the bed is physically ready is AssignBedView, not this endpoint again;
    see AssignBedSerializer for how it accepts a bed reserved for this same
    admission."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.tenant_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")
            if admission.status != Admission.STATUS_ADMITTED:
                return error(f"Admission is {admission.get_status_display()} — only an admission awaiting a bed can reserve one.")
            if admission.bed_id:
                return error("This admission already has a bed assigned.")

            s = ReserveBedSerializer(data=request.data, context={"tenant_db": db})
            if not s.is_valid():
                return error("Validation error.", errors=s.errors)

            bed = Bed.objects.using(db).select_for_update().get(pk=s.validated_data["bed_id"])
            if bed.status != Bed.STATUS_AVAILABLE:
                return error(f"That bed is currently {bed.get_status_display().lower()}, not available.")

            bed.status = Bed.STATUS_RESERVED
            bed.reserved_for_admission_id = admission.id
            bed.save(using=db, update_fields=["status", "reserved_for_admission_id", "updated_at"])

        log_action(
            request, db, action="ipd.admission.reserve_bed",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id, metadata={"bed_id": bed.id},
        )
        return success(data=AdmissionSerializer(admission).data, message="Bed reserved.")


class CancelBedReservationView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/cancel-bed-reservation/
    Undo a ReserveBedView hold without ever having assigned it — the bed
    goes straight back to AVAILABLE for anyone else."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.tenant_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")

            bed = (
                Bed.objects.using(db).select_for_update()
                .filter(status=Bed.STATUS_RESERVED, reserved_for_admission_id=admission.id)
                .first()
            )
            if not bed:
                return error("This admission has no active bed reservation.")

            bed.status = Bed.STATUS_AVAILABLE
            bed.reserved_for_admission_id = None
            bed.save(using=db, update_fields=["status", "reserved_for_admission_id", "updated_at"])

        log_action(
            request, db, action="ipd.admission.cancel_bed_reservation",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id, metadata={"bed_id": bed.id},
        )
        return success(data=AdmissionSerializer(admission).data, message="Bed reservation cancelled.")


class TransferBedView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/transfer-bed/  body: {"to_bed_id": ...}
    Move an ACTIVE admission's patient straight from their current bed into
    a different available one, as one atomic action — replaces the
    error-prone "ReleaseBedView then AssignBedView" two-call sequence for a
    REAL patient move (a bed freed by an actual transfer needs cleaning
    before its next occupant, unlike ReleaseBedView's "never really used"
    undo case, so the vacated bed goes to CLEANING here, not AVAILABLE).
    Both beds are row-locked together with the admission so a concurrent
    request can never observe (or claim) a half-moved state."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.tenant_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")
            if admission.status != Admission.STATUS_ACTIVE:
                return error(f"Admission is {admission.get_status_display()} — only an Active admission (bed allocated) can be transferred.")
            if not admission.bed_id:
                return error("This admission has no current bed to transfer from.")

            s = TransferBedSerializer(data=request.data, context={"tenant_db": db})
            if not s.is_valid():
                return error("Validation error.", errors=s.errors)
            to_bed_id = s.validated_data["to_bed_id"]
            if to_bed_id == admission.bed_id:
                return error("That's already this admission's current bed.")

            from_bed = Bed.objects.using(db).select_for_update().get(pk=admission.bed_id)
            to_bed = Bed.objects.using(db).select_for_update().get(pk=to_bed_id)
            if to_bed.status != Bed.STATUS_AVAILABLE:
                return error(f"That bed is currently {to_bed.get_status_display().lower()}, not available.")

            from django.utils import timezone
            old_room_name, old_bed_number = from_bed.room.name, from_bed.bed_number

            from_bed.status = Bed.STATUS_CLEANING
            from_bed.save(using=db, update_fields=["status", "updated_at"])

            to_bed.status = Bed.STATUS_OCCUPIED
            to_bed.save(using=db, update_fields=["status", "updated_at"])

            admission.bed = to_bed
            admission.bed_assigned_at = timezone.now()
            admission.save(using=db, update_fields=["bed", "bed_assigned_at", "updated_at"])

            PatientMovement.objects.using(db).create(
                admission=admission, movement_type=PatientMovement.TRANSFER,
                from_bed=from_bed, from_room_name=old_room_name, from_bed_number=old_bed_number,
                to_bed=to_bed, to_room_name=to_bed.room.name, to_bed_number=to_bed.bed_number,
                moved_by_id=request.user.id,
            )

        log_action(
            request, db, action="ipd.admission.transfer_bed",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id,
            metadata={"from_bed_id": from_bed.id, "to_bed_id": to_bed.id},
        )
        return success(data=AdmissionSerializer(admission).data, message="Patient transferred.")


class DischargeAdmissionView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/discharge/
    Administrative discharge — front desk marks the stay complete, frees
    the bed, and stamps the real discharge timestamp. Requires the
    admission to currently be ACTIVE (bed allocated — see
    Admission.ALLOWED_TRANSITIONS and AssignBedView, which is what actually
    sets ACTIVE). expected_discharge_date is left untouched (it stays
    whatever was estimated at intake or later edited) — discharged_at is
    the separate, real "it actually happened now" fact. Does not touch the
    referral, deposits, or any invoice; billing is its own explicit step,
    see GenerateInvoiceView."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.tenant_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")

            if admission.status != Admission.STATUS_ACTIVE:
                return error(
                    f"Admission is {admission.get_status_display()} — only an Active admission "
                    "(bed allocated) can be discharged."
                )

            from django.utils import timezone
            admission.status = Admission.STATUS_DISCHARGED
            admission.discharged_at = timezone.now()
            admission.save(using=db, update_fields=["status", "discharged_at", "updated_at"])

            bed_id = admission.bed_id
            if bed_id:
                bed = Bed.objects.using(db).select_for_update().get(pk=bed_id)
                # -> CLEANING, not straight back to AVAILABLE — a discharged
                # bed needs a real housekeeping turn before its next
                # occupant (see org.views.BedMarkCleanView, the only place
                # that finishes this transition). This is the "Phase 2"
                # bed-turnover workflow org.Bed's own docstring anticipated.
                bed.status = Bed.STATUS_CLEANING
                bed.save(using=db, update_fields=["status", "updated_at"])
                # admission.bed is deliberately left set (unlike
                # ReleaseBedView, which clears it) — a discharge is the end
                # of the stay, not a mid-stay bed change, so which room/bed
                # the patient was actually in stays on the record for
                # history and billing (GenerateInvoiceView reads it).
                # org.BedSerializer.get_current_admission excludes
                # DISCHARGED admissions, so the bed still correctly stops
                # showing as "occupied by" them once this runs.
                PatientMovement.objects.using(db).create(
                    admission=admission, movement_type=PatientMovement.DISCHARGE,
                    from_bed=bed, from_room_name=bed.room.name, from_bed_number=bed.bed_number,
                    moved_by_id=request.user.id,
                )

        log_action(
            request, db, action="ipd.admission.discharge",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id, metadata={"bed_id": bed_id},
        )
        return success(data=AdmissionSerializer(admission).data, message="Patient discharged.")


class GenerateInvoiceView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/generate-invoice/
    Turns an admission's stay into a real billing.Invoice: one room-charge
    line item priced off the assigned room's Room Type daily_rate (set on
    the same Room Types catalog hospital-admin already manages — see
    billing.RoomTypeDetailView) × nights stayed, plus every not-yet-
    reconciled AdmissionDeposit folded in as a billing.Payment so it counts
    toward the invoice's paid_amount exactly like a payment collected
    directly against the invoice would.

    Safe to call more than once for the same admission — a reconciled
    deposit is skipped on a later call (see AdmissionDeposit.reconciled_invoice)
    — but each call creates a fresh invoice, so calling it twice bills the
    room charge twice; front desk is expected to call this once, typically
    at/after discharge (nights are counted up to discharged_at when set,
    otherwise up to now — an interim/mid-stay bill), not on a timer."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        import math
        from decimal import Decimal
        from django.utils import timezone
        from apps.billing.models import Invoice, InvoiceItem, Payment, OptionList as BillingOptionList
        from apps.billing.serializers import InvoiceSerializer
        from apps.billing.views import _recompute_invoice_totals

        db = request.tenant_db
        try:
            admission = Admission.objects.using(db).select_related("bed", "bed__room").get(pk=pk)
        except Admission.DoesNotExist:
            return not_found("Admission not found.")

        if not admission.bed_id:
            return error("This admission was never assigned a bed — nothing to bill for room charges.")

        room = admission.bed.room
        type_option = (
            BillingOptionList.objects.using(db)
            .filter(list_type=BillingOptionList.LIST_ROOM_TYPE, value=room.room_type, is_active=True)
            .first()
        )
        if not type_option or not type_option.daily_rate:
            return error(
                f'Room type "{room.room_type}" has no daily rate set — add one in '
                "Rooms & Floors → Room Types before generating a bill."
            )

        stay_end = admission.discharged_at or timezone.now()
        nights = 1
        if admission.bed_assigned_at:
            nights = max(1, math.ceil((stay_end - admission.bed_assigned_at).total_seconds() / 86400))

        inv_number, _ = get_next_number(branch_id=admission.branch_id, entity="invoice", using=db)
        invoice = Invoice.objects.using(db).create(
            patient_id=admission.patient_id,
            branch_id=admission.branch_id,
            invoice_number=inv_number,
            notes=f"IPD stay — {admission.admission_number}",
            created_by_id=request.user.id,
        )

        InvoiceItem.objects.using(db).create(
            invoice=invoice,
            description=f"Room charges — {room.name} ({type_option.label}) × {nights} night{'s' if nights != 1 else ''}",
            quantity=nights,
            unit_price=type_option.daily_rate,
            tax_rate=0,
            total=type_option.daily_rate * nights,
        )

        deposits = AdmissionDeposit.objects.using(db).filter(admission=admission, reconciled_invoice__isnull=True)
        for dep in deposits:
            Payment.objects.using(db).create(
                invoice=invoice, amount=dep.amount, payment_mode=dep.payment_mode,
                transaction_ref=dep.transaction_ref, recorded_by_id=dep.collected_by_id,
            )
            dep.reconciled_invoice = invoice
            dep.save(using=db, update_fields=["reconciled_invoice"])

        _recompute_invoice_totals(invoice, db)
        invoice.refresh_from_db(using=db)
        paid = sum((p.amount for p in invoice.payments.using(db).all()), Decimal("0"))
        if paid > 0:
            invoice.paid_amount = paid
            invoice.status = Invoice.STATUS_PAID if paid >= invoice.total_amount else Invoice.STATUS_PARTIALLY_PAID
            invoice.save(using=db, update_fields=["paid_amount", "status"])

        log_action(
            request, db, action="ipd.admission.generate_invoice",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id,
            metadata={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "nights": nights},
        )
        return created(data=InvoiceSerializer(invoice).data, message="Invoice generated.")


class AwaitingBedListView(APIView):
    """GET /api/v1/ipd/admissions/awaiting-bed/
    Front desk's deferred-bed worklist — every completed admission that
    has no bed yet. See docs/PENDING_IMPROVEMENTS.md item 3."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def get(self, request):
        qs = Admission.objects.using(request.tenant_db).filter(
            bed__isnull=True, status__in=[Admission.STATUS_REQUESTED, Admission.STATUS_ADMITTED],
        ).order_by("created_at")
        return success(data=AdmissionSerializer(qs, many=True).data)


class AdmissionMovementsView(APIView):
    """GET /api/v1/ipd/admissions/<pk>/movements/
    Full bed-history timeline for one admission — every initial assignment,
    transfer, release, and the final discharge, oldest first. Read-only,
    open to any hospital staff (same level as AdmissionDetailView's GET) —
    this is history, not an action."""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        db = request.tenant_db
        if not Admission.objects.using(db).filter(pk=pk).exists():
            return not_found("Admission not found.")
        qs = PatientMovement.objects.using(db).filter(admission_id=pk).order_by("moved_at")
        return success(data=PatientMovementSerializer(qs, many=True).data)


# ── Doctor-facing IPD views ──────────────────────────────────────────────────
# Added so a doctor has a persistent place to find/track IPD work instead of
# "Recommend Admission" only existing as a button inside an active
# encounter, with no way afterward to see what happened to that referral or
# which of their patients are currently inpatients.

class MyReferralsListView(APIView):
    """GET /api/v1/ipd/referrals/mine/?status=
    Every referral this doctor has personally recommended OR accepted
    (countersigned), any status — unlike PendingReferralsListView (an
    action worklist: front desk's pending queue, or a doctor's own
    still-awaiting-countersign queue), this is a doctor's own history/
    tracking view: "what happened to the admission I recommended?"."""
    permission_classes = [IsAuthenticated, IsDoctor]

    def get(self, request):
        db = request.tenant_db
        qs = AdmissionReferral.objects.using(db).filter(
            Q(recommended_by_id=request.user.id) | Q(accepted_by_id=request.user.id)
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return success(data=AdmissionReferralSerializer(qs, many=True).data)


class MyAdmittedPatientsView(APIView):
    """GET /api/v1/ipd/admissions/mine/?include_discharged=1
    This doctor's own inpatients — Admission.ordering_doctor is set at
    CompleteAdmissionView from the referral's accepted_by/recommended_by
    (see views.py), so this is "who am I responsible for right now",
    defaulting to currently-admitted (admitted/active) only."""
    permission_classes = [IsAuthenticated, IsDoctor]

    def get(self, request):
        db = request.tenant_db
        qs = Admission.objects.using(db).filter(ordering_doctor_id=request.user.id)
        if request.query_params.get("include_discharged") != "1":
            qs = qs.filter(status__in=[Admission.STATUS_REQUESTED, Admission.STATUS_ADMITTED, Admission.STATUS_ACTIVE])
        return success(data=AdmissionSerializer(qs, many=True).data)
