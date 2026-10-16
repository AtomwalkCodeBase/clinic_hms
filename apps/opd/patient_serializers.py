"""apps/hospital_patients/serializers.py"""

from django.core.validators import RegexValidator
from rest_framework import serializers
from apps.documents.models import BirthHistory
from apps.opd.models import HospitalPatient, Allergy

# Consent is never withheld from an emergency patient because a reason
DEFAULT_EMERGENCY_CONSENT_DEFERRED_REASON = (
    "DPDP/HIE consent deferred — patient unable to consent and no guardian "
    "present at registration (emergency-treatment doctrine)."
)

# Central format check for every mobile-number field below — exactly 10
mobile_validator = RegexValidator(
    regex=r"^\d{10}$",
    message="Enter a valid 10-digit mobile number.",
)


class PatientRegisterSerializer(serializers.Serializer):
    """Input serializer for patient registration."""
    # Required
    full_name       = serializers.CharField(max_length=200)
    # Not required outright — a dependent (child, or anyone with no mobile
    mobile          = serializers.CharField(max_length=15, required=False, allow_blank=True,
                                            validators=[mobile_validator])
    branch_id       = serializers.IntegerField()
    dpdp_consent    = serializers.BooleanField()

    # Dependent / guardian — set when registering someone via a guardian's
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


class PatientEmergencyRegisterSerializer(serializers.Serializer):
    """Input serializer for the emergency/unidentified-patient registration"""
    branch_id          = serializers.IntegerField()
    placeholder_label  = serializers.CharField(max_length=200, required=False, allow_blank=True)
    full_name          = serializers.CharField(max_length=200, required=False, allow_blank=True)
    gender             = serializers.ChoiceField(
        choices=["male", "female", "other", "prefer_not_to_say", "M", "F", "O"],
        required=False, allow_blank=True,
    )
    date_of_birth      = serializers.DateField(required=False, allow_null=True)
    is_mlc             = serializers.BooleanField(required=False, default=False)
    arrival_channel    = serializers.ChoiceField(
        choices=[c[0] for c in HospitalPatient.ARRIVAL_CHANNEL_CHOICES], required=False, allow_blank=True,
    )
    # Whatever is known about the patient at intake, best-effort — none of
    mobile             = serializers.CharField(max_length=15, required=False, allow_blank=True,
                                               validators=[mobile_validator])
    guardian_name      = serializers.CharField(max_length=200, required=False, allow_blank=True)
    guardian_mobile     = serializers.CharField(max_length=15, required=False, allow_blank=True,
                                                validators=[mobile_validator])
    consent_deferred_reason = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate(self, data):
        if not data.get("placeholder_label", "").strip() and not data.get("full_name", "").strip():
            raise serializers.ValidationError({
                "placeholder_label": "Either a name or a placeholder label (e.g. \"Unknown Male, approx. 30yrs\") is required."
            })
        return data


class PatientDetailSerializer(serializers.ModelSerializer):
    """Full patient detail. Never exposes internal IDs from other hospitals."""

    class Meta:
        model  = HospitalPatient
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
            "identity_status", "is_mlc", "arrival_channel", "placeholder_label", "consent_deferred_reason",
        ]
        read_only_fields = ["id", "awpid", "uhid", "registered_at", "dpdp_consent_captured"]


class PatientSearchSerializer(serializers.ModelSerializer):
    """Lightweight result for patient search (name/mobile/UHID/AWPID)."""
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")

    class Meta:
        model  = HospitalPatient
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


class BirthHistorySerializer(serializers.ModelSerializer):
    """CRUD serializer for BirthHistory — mirrors AllergySerializer's shape."""
    delivery_mode_display = serializers.CharField(source="get_delivery_mode_display", read_only=True)

    class Meta:
        model  = BirthHistory
        fields = [
            "id", "patient", "gestational_age_weeks", "birth_weight_kg",
            "delivery_mode", "delivery_mode_display", "multiple_birth",
            "nicu_admission", "nicu_days", "birth_complications",
            "congenital_conditions",
            "notes", "created_at",
        ]
        read_only_fields = ["id", "patient", "created_at"]
