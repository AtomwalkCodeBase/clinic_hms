"""apps/hospital_patients/serializers.py"""

from django.core.validators import RegexValidator
from rest_framework import serializers
from core.api.serializers import PkModelSerializer
from apps.documents.models import BirthHistory

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


class PatientDetailSerializer(serializers.BaseSerializer):
    """Full patient detail, read-only: the hospital's own row plus everything from `patient.get_patient_details()`.
    Never exposes internal IDs from other hospitals."""
    FROM_DETAILS = [
        "full_name", "date_of_birth", "gender", "blood_group", "marital_status", "nationality", "occupation",
        "mobile", "alternate_mobile", "email", "address_line1", "city", "state", "pincode",
        "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
        "is_dependent", "guardian_name", "guardian_mobile", "guardian_relation", "guardian_awpid", "preferred_language",
    ]

    def to_representation(self, patient):
        row = {
            "patient_id": patient.pk, "awpid": patient.awpid, "uhid": patient.uhid,
            "registered_at": patient.registered_at,
        }
        details = patient.get_patient_details()
        return {**row, **{name: details[name] for name in self.FROM_DETAILS}}


class PatientSearchSerializer(serializers.BaseSerializer):
    """Lightweight result for patient search (name/mobile/UHID/AWPID)."""
    FROM_DETAILS = ["full_name", "mobile", "date_of_birth", "gender", "blood_group", "is_dependent", "guardian_name", "guardian_relation"]

    def to_representation(self, patient):
        row = {
            "patient_id": patient.pk, "awpid": patient.awpid, "uhid": patient.uhid, "registered_at": patient.registered_at,
        }
        details = patient.get_patient_details()
        return {**row, **{name: details[name] for name in self.FROM_DETAILS}}


class BirthHistorySerializer(PkModelSerializer):
    """CRUD serializer for BirthHistory — ."""
    delivery_mode_display = serializers.CharField(source="get_delivery_mode_display", read_only=True)

    class Meta:
        model  = BirthHistory
        fields = [
            "birth_history_id", "patient", "gestational_age_weeks", "birth_weight_kg",
            "delivery_mode", "delivery_mode_display", "multiple_birth",
            "nicu_admission", "nicu_days", "birth_complications",
            "congenital_conditions",
            "notes", "created_at",
        ]
        read_only_fields = ["birth_history_id", "patient", "created_at"]
