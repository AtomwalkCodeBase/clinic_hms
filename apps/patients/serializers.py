"""
apps/patients/serializers.py
----------------------------
Serializers for Patient registration, lookup, and cross-tenant HIE read.

PatientRegisterSerializer — validates + creates PatientIdentity (Registry) + Patient (tenant)
PatientDetailSerializer   — full patient detail for authenticated staff
PatientSearchSerializer   — lightweight result for search responses
AllergySerializer         — CRUD serializer for Allergy
SharedRecordSerializer    — read-only: clinical records from HIE (cross-tenant safe)
"""

from django.core.validators import RegexValidator
from rest_framework import serializers
from .models import Patient, Allergy

# Central format check for every mobile-number field below — exactly 10
# digits, no country code / spaces / punctuation. Applied via `validators=`
# so it's skipped for blank optional fields (DRF short-circuits blank
# CharFields before running validators) but always enforced once a value
# is actually supplied, regardless of which frontend form sent it.
mobile_validator = RegexValidator(
    regex=r"^\d{10}$",
    message="Enter a valid 10-digit mobile number.",
)


class PatientRegisterSerializer(serializers.Serializer):
    """
    Input serializer for patient registration.
    Accepts both frontend field names and maps them to model fields.
    """
    # Required
    full_name       = serializers.CharField(max_length=200)
    # Not required outright — a dependent (child, or anyone with no mobile
    # of their own) has none. validate() enforces: mobile required unless
    # is_dependent is set, in which case guardian_awpid + date_of_birth are
    # required instead. A patient record must not depend on the person
    # having their own contact number.
    mobile          = serializers.CharField(max_length=15, required=False, allow_blank=True,
                                            validators=[mobile_validator])
    branch_id       = serializers.IntegerField()
    dpdp_consent    = serializers.BooleanField()

    # Dependent / guardian — set when registering someone via a guardian's
    # existing record (see PatientLookupView's family_members) rather than
    # their own mobile number.
    is_dependent    = serializers.BooleanField(required=False, default=False)
    guardian_awpid  = serializers.CharField(max_length=30, required=False, allow_blank=True)
    guardian_name   = serializers.CharField(max_length=200, required=False, allow_blank=True)
    guardian_mobile = serializers.CharField(max_length=15, required=False, allow_blank=True,
                                            validators=[mobile_validator])
    relationship    = serializers.ChoiceField(
        choices=["child", "parent", "spouse", "sibling", "ward", "other"],
        required=False, default="other",
    )
    # Separate from dpdp_consent — specifically governs whether THIS hospital's
    # staff may see the patient's shared cross-hospital history (HIE). Not
    # required (a patient may be brand new to the network, nothing to share
    # yet), but if not given, get_shared_history() will not return anything
    # for this hospital's Patient record — see PatientHistoryView.
    hie_consent     = serializers.BooleanField(required=False, default=False)

    # Personal
    date_of_birth   = serializers.DateField(required=False, allow_null=True)
    gender          = serializers.ChoiceField(
        choices=["male", "female", "other", "prefer_not_to_say", "M", "F", "O"],
        required=False, allow_blank=True
    )
    blood_group     = serializers.CharField(max_length=5,   required=False, allow_blank=True)
    marital_status  = serializers.CharField(max_length=20,  required=False, allow_blank=True)
    nationality     = serializers.CharField(max_length=50,  required=False, allow_blank=True)
    occupation      = serializers.CharField(max_length=100, required=False, allow_blank=True)

    # Contact
    alternate_mobile = serializers.CharField(max_length=15,  required=False, allow_blank=True,
                                             validators=[mobile_validator])
    email            = serializers.EmailField(required=False, allow_blank=True)
    address_line1    = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city             = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state            = serializers.CharField(max_length=100, required=False, allow_blank=True)
    pincode          = serializers.CharField(max_length=10,  required=False, allow_blank=True)

    # Emergency contact — frontend sends emergency_name / emergency_phone
    emergency_name     = serializers.CharField(max_length=100, required=False, allow_blank=True)
    emergency_phone    = serializers.CharField(max_length=15,  required=False, allow_blank=True,
                                               validators=[mobile_validator])
    emergency_relation = serializers.CharField(max_length=50,  required=False, allow_blank=True)

    # Insurance
    payer_type         = serializers.ChoiceField(
        choices=["self", "insurance", "corporate"], default="self"
    )
    insurance_provider = serializers.CharField(max_length=200, required=False, allow_blank=True)
    policy_number      = serializers.CharField(max_length=100, required=False, allow_blank=True)
    tpa_name           = serializers.CharField(max_length=200, required=False, allow_blank=True)

    preferred_language = serializers.CharField(max_length=10, default="en")

    def validate(self, data):
        if data.get("is_dependent"):
            if not data.get("guardian_awpid", "").strip():
                raise serializers.ValidationError({
                    "guardian_awpid": "Select the guardian this dependent is being registered under."
                })
            if not data.get("date_of_birth"):
                raise serializers.ValidationError({
                    "date_of_birth": "Date of birth is required to identify a dependent patient across hospitals."
                })
        elif not data.get("mobile", "").strip():
            raise serializers.ValidationError({
                "mobile": "Mobile number is required unless registering as a dependent."
            })
        return data


class PatientDetailSerializer(serializers.ModelSerializer):
    """Full patient detail. Never exposes internal IDs from other tenants."""

    class Meta:
        model  = Patient
        fields = [
            "id", "uuid", "awpid", "uhid", "branch",
            "full_name", "date_of_birth", "gender", "blood_group",
            "marital_status", "nationality", "occupation",
            "mobile", "alternate_mobile", "email",
            "address_line1", "city", "state", "pincode",
            "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
            "payer_type", "insurance_provider", "policy_number", "tpa_name",
            "is_dependent", "guardian_name", "guardian_mobile", "guardian_relation", "guardian_awpid",
            "dpdp_consent_captured", "preferred_language", "registered_at",
        ]
        read_only_fields = ["id", "awpid", "uhid", "registered_at", "dpdp_consent_captured"]


class PatientSearchSerializer(serializers.ModelSerializer):
    """Lightweight result for patient search (name/mobile/UHID/AWPID)."""
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")

    class Meta:
        model  = Patient
        fields = [
            "id", "uuid", "awpid", "uhid", "full_name", "mobile", "date_of_birth", "gender", "blood_group",
            "is_dependent", "guardian_name", "guardian_relation", "branch_name", "registered_at",
        ]


class AllergySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Allergy
        fields = [
            "id", "patient", "substance", "reaction", "severity",
            "is_active", "recorded_at", "updated_at",
        ]
        read_only_fields = ["id", "patient", "recorded_at", "updated_at"]


class SharedDiagnosisSerializer(serializers.Serializer):
    """Read-only serializer for shared HIE diagnosis — source_tenant_id excluded."""
    icd10_code      = serializers.CharField()
    description     = serializers.CharField()
    clinical_status = serializers.CharField()
    onset_date      = serializers.DateField(allow_null=True)
    created_at      = serializers.DateTimeField()


class SharedVitalSerializer(serializers.Serializer):
    """Read-only serializer for shared HIE vital — source_tenant_id excluded."""
    recorded_at     = serializers.DateTimeField()
    source          = serializers.CharField()
    bp_systolic     = serializers.IntegerField(allow_null=True)
    bp_diastolic    = serializers.IntegerField(allow_null=True)
    pulse_rate      = serializers.IntegerField(allow_null=True)
    spo2            = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    temperature     = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    weight_kg       = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    height_cm       = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    resp_rate       = serializers.IntegerField(allow_null=True)
    blood_sugar_mgdl= serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)


class SharedAllergySerializer(serializers.Serializer):
    """Read-only serializer for shared HIE allergy — source_tenant_id excluded."""
    substance   = serializers.CharField()
    reaction    = serializers.CharField()
    severity    = serializers.CharField()
    is_active   = serializers.BooleanField()
    recorded_at = serializers.DateTimeField()


class SharedLabResultSerializer(serializers.Serializer):
    """Read-only serializer for shared HIE lab result — source_tenant_id excluded."""
    test_name       = serializers.CharField()
    result_summary  = serializers.CharField()
    delivered_at    = serializers.DateTimeField()


class SharedPrescriptionItemSerializer(serializers.Serializer):
    drug_name    = serializers.CharField()
    dose         = serializers.CharField()
    unit         = serializers.CharField()
    frequency    = serializers.CharField()
    route        = serializers.CharField()
    duration_days= serializers.IntegerField(allow_null=True)


class SharedPrescriptionSerializer(serializers.Serializer):
    prescribed_on = serializers.DateField()
    items         = SharedPrescriptionItemSerializer(many=True)
