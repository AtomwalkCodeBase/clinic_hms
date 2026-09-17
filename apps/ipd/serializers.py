"""
apps/ipd/serializers.py
------------------------
admission_type / admission_source are validated against
billing.OptionList (is_active rows for the tenant DB the request is
already scoped to — request.tenant_db) rather than a hardcoded choices=
list, matching how Drug.form / Invoice.status / Payment.payment_mode are
already validated (see apps/billing/views.py's dropdown base classes).

Every serializer here expects `context={"tenant_db": request.tenant_db}`
from the view — OptionList rows are tenant-scoped and there is no other
reliable way for a serializer to know which tenant DB to check against.
"""

from rest_framework import serializers

from apps.billing.models import OptionList
from apps.org.models import StaffUser, Department, Bed
from apps.patients.models import Patient
from .models import AdmissionReferral, Admission, AdmissionDeposit, PatientMovement


def _option_exists(tenant_db, list_type, value):
    if not value:
        return False
    return OptionList.objects.using(tenant_db).filter(
        list_type=list_type, value=value, is_active=True,
    ).exists()


class OptionListSerializer(serializers.ModelSerializer):
    """Generic read/write serializer for the two new configurable
    catalogs — admission_type and admission_source. Mirrors the shape
    billing's own OptionList-backed dropdowns already expose."""
    class Meta:
        model = OptionList
        fields = ["id", "list_type", "value", "label", "is_active", "is_system", "sort_order"]
        read_only_fields = ["id", "list_type", "is_system"]


class RecommendAdmissionSerializer(serializers.Serializer):
    """POST body for RecommendAdmissionView. recommended_by is intentionally
    NOT a field here — it is set by the view from request.user, never from
    client input (see models.AdmissionReferral module docstring)."""
    patient_id             = serializers.IntegerField()
    department_id          = serializers.IntegerField()
    admission_type         = serializers.CharField(max_length=30)
    admission_source       = serializers.CharField(max_length=30)
    reason_for_admission   = serializers.CharField()
    source_appointment_id  = serializers.UUIDField(required=False, allow_null=True)
    source_encounter_id    = serializers.UUIDField(required=False, allow_null=True)
    external_referring_doctor_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    external_referring_facility    = serializers.CharField(max_length=200, required=False, allow_blank=True)
    source_details          = serializers.JSONField(required=False)
    is_mlc                  = serializers.BooleanField(required=False, default=False)
    guardian_consent_by     = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs):
        tenant_db = self.context["tenant_db"]
        if not _option_exists(tenant_db, OptionList.LIST_ADMISSION_TYPE, attrs["admission_type"]):
            raise serializers.ValidationError({"admission_type": "Not a configured admission type for this hospital."})
        if not _option_exists(tenant_db, OptionList.LIST_ADMISSION_SOURCE, attrs["admission_source"]):
            raise serializers.ValidationError({"admission_source": "Not a configured admission source for this hospital."})
        if not Patient.objects.using(tenant_db).filter(pk=attrs["patient_id"]).exists():
            raise serializers.ValidationError({"patient_id": "Patient not found."})
        if not Department.objects.using(tenant_db).filter(pk=attrs["department_id"]).exists():
            raise serializers.ValidationError({"department_id": "Department not found."})
        return attrs


class AdmissionReferralSerializer(serializers.ModelSerializer):
    patient_name   = serializers.CharField(source="patient.full_name", read_only=True)
    patient_uhid   = serializers.CharField(source="patient.uhid", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    recommended_by_name = serializers.SerializerMethodField()
    accepted_by_name     = serializers.SerializerMethodField()
    requires_acceptance   = serializers.SerializerMethodField()

    class Meta:
        model = AdmissionReferral
        fields = [
            "id", "patient", "patient_name", "patient_uhid",
            "department", "department_name",
            "admission_type", "admission_source", "reason_for_admission",
            "source_appointment", "source_encounter",
            "recommended_by", "recommended_by_name", "recommended_at",
            "external_referring_doctor_name", "external_referring_facility",
            "accepted_by", "accepted_by_name", "accepted_at",
            "source_details", "is_mlc", "guardian_consent_by",
            "front_desk_logged", "status", "requires_acceptance",
        ]
        read_only_fields = fields

    def get_recommended_by_name(self, obj):
        return f"{obj.recommended_by.first_name} {obj.recommended_by.last_name}".strip()

    def get_accepted_by_name(self, obj):
        if not obj.accepted_by:
            return None
        return f"{obj.accepted_by.first_name} {obj.accepted_by.last_name}".strip()

    def get_requires_acceptance(self, obj):
        return obj.requires_acceptance()


class RegisterExternalReferralSerializer(serializers.Serializer):
    """POST body for RegisterExternalReferralView — front desk logging a
    referral straight from an external paper/PDF letter the moment it
    arrives, instead of waiting for an in-app doctor to type it into
    RecommendAdmissionSerializer first. recommended_by is still never a
    field here — the view stamps it from request.user, same discipline as
    RecommendAdmissionSerializer; it's just a front-desk StaffUser doing
    the logging this time, not a doctor (see models.AdmissionReferral
    module docstring, design decision 2).

    Deliberately narrower than RecommendAdmissionSerializer in two ways
    that keep this from being a backdoor around "front desk can never
    single-handedly originate an admission":
      - admission_source must be one of AdmissionReferral.
        SOURCES_REQUIRING_ACCEPTANCE (validate() below) — a source that
        doesn't need a doctor's countersign anyway (OPD Consultation,
        Walk-in, ...) still can only come from a doctor's own Recommend
        Admission action.
      - external_referring_doctor_name / external_referring_facility are
        REQUIRED here (optional on the doctor path) — this endpoint's
        entire premise is a named outside doctor's letter in hand.
    """
    patient_id             = serializers.IntegerField()
    department_id          = serializers.IntegerField()
    admission_type         = serializers.CharField(max_length=30)
    admission_source       = serializers.CharField(max_length=30)
    reason_for_admission   = serializers.CharField()
    external_referring_doctor_name = serializers.CharField(max_length=200)
    external_referring_facility    = serializers.CharField(max_length=200)
    # Letter paperwork detail, folded into AdmissionReferral.source_details
    # by the view — doesn't earn its own column (same JSON-for-variant-
    # detail pattern the model already uses, see models.py).
    referral_letter_date      = serializers.DateField(required=False, allow_null=True)
    referral_letter_reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    is_mlc                  = serializers.BooleanField(required=False, default=False)
    guardian_consent_by     = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs):
        tenant_db = self.context["tenant_db"]
        if not _option_exists(tenant_db, OptionList.LIST_ADMISSION_TYPE, attrs["admission_type"]):
            raise serializers.ValidationError({"admission_type": "Not a configured admission type for this hospital."})
        if not _option_exists(tenant_db, OptionList.LIST_ADMISSION_SOURCE, attrs["admission_source"]):
            raise serializers.ValidationError({"admission_source": "Not a configured admission source for this hospital."})
        if attrs["admission_source"] not in AdmissionReferral.SOURCES_REQUIRING_ACCEPTANCE:
            raise serializers.ValidationError({
                "admission_source": (
                    "Front desk can only log a referral here for a source that arrives from outside the "
                    "hospital (external referral, transfer-in, ambulance/EMS, or medical tourism). Any other "
                    "source must come from a doctor's own Recommend Admission action."
                ),
            })
        if not attrs["external_referring_doctor_name"].strip():
            raise serializers.ValidationError({"external_referring_doctor_name": "Required — this is who the letter is being logged from."})
        if not Patient.objects.using(tenant_db).filter(pk=attrs["patient_id"]).exists():
            raise serializers.ValidationError({"patient_id": "Patient not found."})
        if not Department.objects.using(tenant_db).filter(pk=attrs["department_id"]).exists():
            raise serializers.ValidationError({"department_id": "Department not found."})
        return attrs


class CompleteAdmissionSerializer(serializers.Serializer):
    """POST body for CompleteAdmissionView — front desk's ONLY write path
    into this app. There is no field here for admission_type, source,
    ordering doctor, department, or reason — all of that comes from the
    referral the view looks up, never from this request (see
    views.CompleteAdmissionView)."""
    referral_id        = serializers.UUIDField()
    attendant_name      = serializers.CharField(max_length=200, required=False, allow_blank=True)
    attendant_phone      = serializers.CharField(max_length=15, required=False, allow_blank=True)
    payer_type           = serializers.CharField(max_length=20, required=False, allow_blank=True)
    insurance_provider   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    expected_discharge_date = serializers.DateField(required=False, allow_null=True)
    consent_given        = serializers.BooleanField()

    def validate_consent_given(self, value):
        if not value:
            raise serializers.ValidationError(
                "Admission consent must be captured before registration can be completed."
            )
        return value


class AdmissionSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_uhid = serializers.CharField(source="patient.uhid", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    ordering_doctor_name = serializers.SerializerMethodField()
    bed_number = serializers.CharField(source="bed.bed_number", read_only=True, default=None)
    room_name = serializers.CharField(source="bed.room.name", read_only=True, default=None)
    awaiting_bed = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Admission
        fields = [
            "id", "admission_number", "branch",
            "referral", "patient", "patient_name", "patient_uhid",
            "department", "department_name",
            "admission_type", "admission_source",
            "ordering_doctor", "ordering_doctor_name", "logged_by_staff",
            "reason_for_admission", "expected_discharge_date",
            "attendant_name", "attendant_phone", "payer_type", "insurance_provider",
            "previous_admission", "status", "status_display",
            "bed", "bed_number", "room_name", "bed_assigned_at", "discharged_at", "awaiting_bed",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    # Bug fix: these two SerializerMethodField backers (ordering_doctor_name,
    # awaiting_bed declared above) were previously defined on the WRONG class
    # (AdmissionUpdateSerializer below, which has no such fields at all) —
    # every response returning Admission data (CompleteAdmissionView,
    # AssignBedView, ReleaseBedView, DischargeAdmissionView, AdmissionListView,
    # AdmissionDetailView, AwaitingBedListView, ...) raised
    # AttributeError: 'AdmissionSerializer' object has no attribute
    # 'get_ordering_doctor_name' the moment it was actually exercised against
    # a live DB. Confirmed via direct end-to-end testing while building the
    # bed-turnover/reserve/transfer feature (never caught before because, per
    # this codebase's own recurring caution elsewhere, these views "had never
    # been exercised against a real Postgres before").
    def get_ordering_doctor_name(self, obj):
        return f"{obj.ordering_doctor.first_name} {obj.ordering_doctor.last_name}".strip()

    def get_awaiting_bed(self, obj):
        """True while the admission is registered but has no bed yet — the
        "assign later" outcome front desk can pick at completion time."""
        return obj.bed_id is None and obj.status in (Admission.STATUS_REQUESTED, Admission.STATUS_ADMITTED)


class AdmissionUpdateSerializer(serializers.Serializer):
    """PATCH body for AdmissionDetailView — front desk's only path to
    change an admission after it's been registered. Deliberately as narrow
    as CompleteAdmissionSerializer's own write surface: registration data
    only (the same four fields front desk supplies at intake, plus the
    discharge-date estimate), never the clinical fields (patient,
    admission_type/source, ordering_doctor, department, reason) — those
    come from the referral and stay fixed, same reasoning as
    CompleteAdmissionSerializer's own docstring. `partial`-style: every
    field optional, only what's present in the request changes."""
    attendant_name           = serializers.CharField(max_length=200, required=False, allow_blank=True)
    attendant_phone          = serializers.CharField(max_length=15, required=False, allow_blank=True)
    payer_type               = serializers.CharField(max_length=20, required=False, allow_blank=True)
    insurance_provider       = serializers.CharField(max_length=200, required=False, allow_blank=True)
    expected_discharge_date  = serializers.DateField(required=False, allow_null=True)


class AssignBedSerializer(serializers.Serializer):
    """POST body for AssignBedView — front desk assigning a bed to an
    already-completed admission, either right away or later off the
    Awaiting Bed worklist. Both are the same action; only the timing
    differs (see docs/PENDING_IMPROVEMENTS.md item 3).

    A bed reserved (Bed.STATUS_RESERVED) for THIS SAME admission is also
    acceptable here — confirming a reservation is just "assign," the same
    endpoint, not a separate action (see views.ReserveBedView). A bed
    reserved for a DIFFERENT admission is refused exactly like an occupied
    one — the whole point of reserving it was to stop that."""
    bed_id = serializers.IntegerField()

    def validate_bed_id(self, value):
        tenant_db = self.context["tenant_db"]
        admission_id = self.context.get("admission_id")
        try:
            bed = Bed.objects.using(tenant_db).get(pk=value, is_active=True)
        except Bed.DoesNotExist:
            raise serializers.ValidationError("Bed not found.")
        if bed.status == Bed.STATUS_RESERVED:
            if str(bed.reserved_for_admission_id) != str(admission_id):
                raise serializers.ValidationError("That bed is reserved for a different admission.")
        elif bed.status != Bed.STATUS_AVAILABLE:
            raise serializers.ValidationError(f"That bed is currently {bed.get_status_display().lower()}, not available.")
        return value


class ReserveBedSerializer(serializers.Serializer):
    """POST body for ReserveBedView — hold a specific available bed against
    an admission that's ADMITTED (completed, awaiting bed) but not yet
    bedded, e.g. while its current occupant is still being discharged/
    cleaned out. Confirming the hold later is AssignBedView, not this
    endpoint again."""
    bed_id = serializers.IntegerField()

    def validate_bed_id(self, value):
        tenant_db = self.context["tenant_db"]
        try:
            bed = Bed.objects.using(tenant_db).get(pk=value, is_active=True)
        except Bed.DoesNotExist:
            raise serializers.ValidationError("Bed not found.")
        if bed.status != Bed.STATUS_AVAILABLE:
            raise serializers.ValidationError(f"That bed is currently {bed.get_status_display().lower()}, not available to reserve.")
        return value


class TransferBedSerializer(serializers.Serializer):
    """POST body for TransferBedView — move an ACTIVE admission's patient
    from their current bed straight into a different one, atomically. The
    target must be genuinely free (available) — you can't transfer into a
    bed someone else has reserved or is occupying."""
    to_bed_id = serializers.IntegerField()

    def validate_to_bed_id(self, value):
        tenant_db = self.context["tenant_db"]
        try:
            bed = Bed.objects.using(tenant_db).get(pk=value, is_active=True)
        except Bed.DoesNotExist:
            raise serializers.ValidationError("Bed not found.")
        if bed.status != Bed.STATUS_AVAILABLE:
            raise serializers.ValidationError(f"That bed is currently {bed.get_status_display().lower()}, not available.")
        return value


class PatientMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(source="get_movement_type_display", read_only=True)
    moved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PatientMovement
        fields = [
            "id", "admission", "movement_type", "movement_type_display",
            "from_bed", "from_room_name", "from_bed_number",
            "to_bed", "to_room_name", "to_bed_number",
            "moved_by", "moved_by_name", "notes", "moved_at",
        ]
        read_only_fields = fields

    def get_moved_by_name(self, obj):
        if not obj.moved_by:
            return None
        return f"{obj.moved_by.first_name} {obj.moved_by.last_name}".strip()


class AdmissionDepositSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmissionDeposit
        fields = ["id", "admission", "amount", "payment_mode", "transaction_ref", "collected_by",
                  "collected_at", "reconciled_invoice"]
        read_only_fields = ["id", "admission", "collected_by", "collected_at", "reconciled_invoice"]

    def validate_payment_mode(self, value):
        tenant_db = self.context["tenant_db"]
        if not _option_exists(tenant_db, OptionList.LIST_PAYMENT_MODE, value):
            raise serializers.ValidationError("Not a configured payment mode for this hospital.")
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value
