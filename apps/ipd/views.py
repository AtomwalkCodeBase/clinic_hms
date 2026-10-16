"""apps/ipd/views.py"""

from django.db import transaction
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.api.response import success, created, error, not_found
from core.api.permissions import IsDoctor, IsFrontDesk, IsHospitalStaff
from core.utils.audit import log_action
from core.utils.nntm import get_next_number

from apps.billing.models import OptionList
from apps.billing.option_list_views import DropdownListCreateView, DropdownDetailView
from apps.billing.services import recompute_invoice_totals
from apps.hospital_setup.models import Bed
from apps.opd.models import HospitalPatient
from apps.hospital_setup.models import ConsentRecord

from apps.ipd.models import AdmissionReferral, Admission, AdmissionDeposit, PatientMovement
from apps.ipd.serializers import (
    OptionListSerializer,
    RecommendAdmissionSerializer,
    RegisterExternalReferralSerializer,
    AdmissionReferralSerializer,
    CompleteAdmissionSerializer,
    AdmissionSerializer,
    AdmissionUpdateSerializer,
    AdmissionDepositSerializer,
    AssignBedSerializer,
    ReserveBedSerializer,
    TransferBedSerializer,
    PatientMovementSerializer,
)


# ── Configurable catalogs — "make it configurable" ───────────────────────────

class AdmissionTypeListCreateView(DropdownListCreateView):
    list_type = OptionList.LIST_ADMISSION_TYPE
    serializer_class = OptionListSerializer
    # `value` (not `label`) is what Admission.admission_type actually stores
    identity_field = "value"
    model_field = "value"


class AdmissionTypeDetailView(DropdownDetailView):
    list_type = OptionList.LIST_ADMISSION_TYPE
    serializer_class = OptionListSerializer
    identity_field = "value"
    model_field = "value"
    system_can_deactivate = False


class AdmissionSourceListCreateView(DropdownListCreateView):
    list_type = OptionList.LIST_ADMISSION_SOURCE
    serializer_class = OptionListSerializer
    identity_field = "value"
    model_field = "value"


class AdmissionSourceDetailView(DropdownDetailView):
    list_type = OptionList.LIST_ADMISSION_SOURCE
    serializer_class = OptionListSerializer
    identity_field = "value"
    model_field = "value"
    system_can_deactivate = True


# ── Doctor-authored referral — the enforcement point ─────────────────────────

class RecommendAdmissionView(APIView):
    """The ONLY way an AdmissionReferral gets created. IsDoctor-gated;"""
    permission_classes = [IsAuthenticated, IsDoctor]

    def post(self, request):
        s = RecommendAdmissionSerializer(data=request.data, context={"hospital_db": request.hospital_db})
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
        referral.save(using=request.hospital_db)

        log_action(
            request, request.hospital_db, action="ipd.referral.recommend",
            resource_type="AdmissionReferral", resource_id=str(referral.id),
            patient_id=referral.patient_id,
            metadata={"admission_type": referral.admission_type, "admission_source": referral.admission_source},
        )
        return created(
            data=AdmissionReferralSerializer(referral).data,
            message="Admission referral recorded.",
        )


class AcceptExternalReferralView(APIView):
    """IsDoctor-gated countersign for a referral that arrived from outside"""
    permission_classes = [IsAuthenticated, IsDoctor]

    def post(self, request, pk):
        try:
            referral = AdmissionReferral.objects.using(request.hospital_db).get(pk=pk)
        except AdmissionReferral.DoesNotExist:
            return not_found("Referral not found.")

        if referral.status != AdmissionReferral.STATUS_PENDING:
            return error(f"Referral is already {referral.status}, cannot accept.")
        if not referral.requires_acceptance():
            return error("This admission source does not require doctor countersign.")

        from django.utils import timezone
        referral.accepted_by_id = request.user.id
        referral.accepted_at = timezone.now()
        referral.save(using=request.hospital_db, update_fields=["accepted_by_id", "accepted_at"])

        log_action(
            request, request.hospital_db, action="ipd.referral.accept",
            resource_type="AdmissionReferral", resource_id=str(referral.id),
            patient_id=referral.patient_id,
        )
        return success(data=AdmissionReferralSerializer(referral).data, message="Referral accepted.")


class RegisterExternalReferralView(APIView):
    """POST /api/v1/ipd/referrals/register-external/"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request):
        s = RegisterExternalReferralSerializer(data=request.data, context={"hospital_db": request.hospital_db})
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
        referral.save(using=request.hospital_db)

        log_action(
            request, request.hospital_db, action="ipd.referral.register_external",
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
    """Worklist for referrals awaiting action — shared by two different"""
    permission_classes = [IsAuthenticated, (IsFrontDesk | IsDoctor)]

    def get(self, request):
        db = request.hospital_db
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
    """Front desk's ONLY write path into Admission. Requires an existing,"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request):
        s = CompleteAdmissionSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        v = s.validated_data
        db = request.hospital_db

        # NOTE: this used to be `@transaction.atomic` (no `using=`) on the
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

            patient = HospitalPatient.objects.using(db).get(pk=referral.patient_id)

            # NNTM — same collision-free sequence mechanism as UHID/invoice/
            admission_number, _ = get_next_number(patient.branch_id, entity="admission", using=db)

            # Re-admission tracking — most recent non-cancelled prior admission
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
                status=Admission.STATUS_ADMITTED,
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
    """Records an advance/deposit. Deliberately does NOT block anything in"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        try:
            admission = Admission.objects.using(request.hospital_db).get(pk=pk)
        except Admission.DoesNotExist:
            return not_found("Admission not found.")

        s = AdmissionDepositSerializer(data=request.data, context={"hospital_db": request.hospital_db})
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        deposit = AdmissionDeposit(
            admission=admission,
            amount=s.validated_data["amount"],
            payment_mode=s.validated_data["payment_mode"],
            transaction_ref=s.validated_data.get("transaction_ref", ""),
            collected_by_id=request.user.id,
        )
        deposit.save(using=request.hospital_db)

        log_action(
            request, request.hospital_db, action="ipd.admission.deposit",
            resource_type="Admission", resource_id=str(admission.id),
            patient_id=admission.patient_id,
            metadata={"amount": str(deposit.amount), "payment_mode": deposit.payment_mode},
        )
        return created(data=AdmissionDepositSerializer(deposit).data, message="Deposit recorded.")


# ── Admission read views ──────────────────────────────────────────────────────

class AdmissionListView(APIView):
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        qs = Admission.objects.using(request.hospital_db).all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return success(data=AdmissionSerializer(qs, many=True).data)


class AdmissionDetailView(APIView):
    """GET   /api/v1/ipd/admissions/{id}/ — full admission + its deposits,"""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsFrontDesk()]

    def get(self, request, pk):
        try:
            admission = Admission.objects.using(request.hospital_db).get(pk=pk)
        except Admission.DoesNotExist:
            return not_found("Admission not found.")
        data = AdmissionSerializer(admission).data
        deposits = AdmissionDeposit.objects.using(request.hospital_db).filter(admission=admission)
        data["deposits"] = AdmissionDepositSerializer(deposits, many=True).data
        return success(data=data)

    def patch(self, request, pk):
        db = request.hospital_db
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

class AssignBedView(APIView):
    """POST /api/v1/ipd/admissions/<pk>/assign-bed/"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.hospital_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")

            if admission.status not in (Admission.STATUS_ADMITTED, Admission.STATUS_ACTIVE):
                return error(f"Admission is {admission.status} — cannot assign a bed.")
            if admission.bed_id:
                return error("This admission already has a bed assigned. Release it first to reassign.")

            s = AssignBedSerializer(data=request.data, context={"hospital_db": db, "admission_id": str(admission.id)})
            if not s.is_valid():
                return error("Validation error.", errors=s.errors)

            bed = Bed.objects.using(db).select_for_update().get(pk=s.validated_data["bed_id"])
            # AssignBedSerializer already confirmed this bed is either
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
    """POST /api/v1/ipd/admissions/<pk>/release-bed/"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.hospital_db
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
            bed.status = Bed.STATUS_AVAILABLE
            bed.save(using=db, update_fields=["status", "updated_at"])

            admission.bed = None
            admission.bed_assigned_at = None
            update_fields = ["bed", "bed_assigned_at", "updated_at"]
            # Mirror of the ADMITTED -> ACTIVE flip in AssignBedView — a bed
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
    """POST /api/v1/ipd/admissions/<pk>/reserve-bed/  body: {"bed_id": ...}"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.hospital_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")
            if admission.status != Admission.STATUS_ADMITTED:
                return error(f"Admission is {admission.get_status_display()} — only an admission awaiting a bed can reserve one.")
            if admission.bed_id:
                return error("This admission already has a bed assigned.")

            s = ReserveBedSerializer(data=request.data, context={"hospital_db": db})
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
    """POST /api/v1/ipd/admissions/<pk>/cancel-bed-reservation/"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.hospital_db
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
    """POST /api/v1/ipd/admissions/<pk>/transfer-bed/  body: {"to_bed_id": ...}"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.hospital_db
        with transaction.atomic(using=db):
            try:
                admission = Admission.objects.using(db).select_for_update().get(pk=pk)
            except Admission.DoesNotExist:
                return not_found("Admission not found.")
            if admission.status != Admission.STATUS_ACTIVE:
                return error(f"Admission is {admission.get_status_display()} — only an Active admission (bed allocated) can be transferred.")
            if not admission.bed_id:
                return error("This admission has no current bed to transfer from.")

            s = TransferBedSerializer(data=request.data, context={"hospital_db": db})
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
    """POST /api/v1/ipd/admissions/<pk>/discharge/"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.hospital_db
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
                bed.status = Bed.STATUS_CLEANING
                bed.save(using=db, update_fields=["status", "updated_at"])
                # admission.bed is deliberately left set (unlike
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
    """POST /api/v1/ipd/admissions/<pk>/generate-invoice/"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        import math
        from decimal import Decimal
        from django.utils import timezone
        from apps.billing.models import Invoice, InvoiceItem, Payment, OptionList as BillingOptionList
        from apps.billing.serializers import InvoiceSerializer

        db = request.hospital_db
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

        recompute_invoice_totals(invoice, db)
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
    """GET /api/v1/ipd/admissions/awaiting-bed/"""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def get(self, request):
        qs = Admission.objects.using(request.hospital_db).filter(
            bed__isnull=True, status__in=[Admission.STATUS_REQUESTED, Admission.STATUS_ADMITTED],
        ).order_by("created_at")
        return success(data=AdmissionSerializer(qs, many=True).data)


class AdmissionMovementsView(APIView):
    """GET /api/v1/ipd/admissions/<pk>/movements/"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        db = request.hospital_db
        if not Admission.objects.using(db).filter(pk=pk).exists():
            return not_found("Admission not found.")
        qs = PatientMovement.objects.using(db).filter(admission_id=pk).order_by("moved_at")
        return success(data=PatientMovementSerializer(qs, many=True).data)


# ── Doctor-facing IPD views ──────────────────────────────────────────────────

class MyReferralsListView(APIView):
    """GET /api/v1/ipd/referrals/mine/?status="""
    permission_classes = [IsAuthenticated, IsDoctor]

    def get(self, request):
        db = request.hospital_db
        qs = AdmissionReferral.objects.using(db).filter(
            Q(recommended_by_id=request.user.id) | Q(accepted_by_id=request.user.id)
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return success(data=AdmissionReferralSerializer(qs, many=True).data)


class MyAdmittedPatientsView(APIView):
    """GET /api/v1/ipd/admissions/mine/?include_discharged=1"""
    permission_classes = [IsAuthenticated, IsDoctor]

    def get(self, request):
        db = request.hospital_db
        qs = Admission.objects.using(db).filter(ordering_doctor_id=request.user.id)
        if request.query_params.get("include_discharged") != "1":
            qs = qs.filter(status__in=[Admission.STATUS_REQUESTED, Admission.STATUS_ADMITTED, Admission.STATUS_ACTIVE])
        return success(data=AdmissionSerializer(qs, many=True).data)
