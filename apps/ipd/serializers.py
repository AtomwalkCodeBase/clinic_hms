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
from apps.org.models import StaffUser, Department
from apps.patients.models import Patient
from .models import AdmissionReferral, Admission, AdmissionDeposit


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
            "status", "requires_acceptance",
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
            "previous_admission", "status", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_ordering_doctor_name(self, obj):
        return f"{obj.ordering_doctor.first_name} {obj.ordering_doctor.last_name}".strip()


class AdmissionDepositSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdmissionDeposit
        fields = ["id", "admission", "amount", "payment_mode", "transaction_ref", "collected_by", "collected_at"]
        read_only_fields = ["id", "admission", "collected_by", "collected_at"]

    def validate_payment_mode(self, value):
        tenant_db = self.context["tenant_db"]
        if not _option_exists(tenant_db, OptionList.LIST_PAYMENT_MODE, value):
            raise serializers.ValidationError("Not a configured payment mode for this hospital.")
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value
