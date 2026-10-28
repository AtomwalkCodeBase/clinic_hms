import re

from rest_framework import serializers
from core.api.serializers import PkModelSerializer
from core import storage as blob_storage
from apps.hospital_setup.models import (
    Room,
    StaffUser,
    StaffBranchAssignment,
)
from apps.hospital_setup.rbac import api_role, resolve_acts_as
from apps.hospital_setup.branch_utils import get_staff_places, primary_branch_id, primary_department_id, primary_place
from apps.hospital_setup.staff_services import last_logins


class RoomAssignmentSerializer(serializers.Serializer):
    """Input for a room block (a doctor in a room on a weekday between two times); the output is room_utils.block_json."""
    room        = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all())
    doctor      = serializers.PrimaryKeyRelatedField(queryset=StaffUser.objects.all())
    day_of_week = serializers.ChoiceField(choices=StaffBranchAssignment.DAY_CHOICES)
    start_time  = serializers.TimeField()
    end_time    = serializers.TimeField()
    is_active   = serializers.BooleanField(required=False)

    def validate(self, data):
        start = data.get("start_time", getattr(self.instance, "start_time", None))
        end   = data.get("end_time",   getattr(self.instance, "end_time",   None))
        if start is not None and end is not None and start >= end:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})
        return data


class DoctorProfileSerializer(PkModelSerializer):
    class Meta:
        model  = StaffUser
        fields = ["registration_no", "specialisation", "qualification",
                  "gender", "experience_years", "consultation_fee", "followup_fee",
                  "bio", "languages", "known_for"]


class DoctorSelfProfileSerializer(PkModelSerializer):
    """Self-service view/edit for the logged-in doctor's own profile."""
    # digital_signature stores an S3 object key (see core/storage.py), not a
    digital_signature = serializers.SerializerMethodField()

    def get_digital_signature(self, obj):
        return blob_storage.signed_url(obj.digital_signature)

    def get_fields(self):
        fields = super().get_fields()
        if not self.context.get("fee_editable", False):
            fields["consultation_fee"].read_only = True
            fields["followup_fee"].read_only = True
        return fields

    class Meta:
        model  = StaffUser
        fields = ["registration_no", "specialisation", "qualification",
                  "gender", "experience_years", "consultation_fee", "followup_fee",
                  "digital_signature", "bio", "languages", "known_for"]
        read_only_fields = ["registration_no", "specialisation",
                             "qualification", "experience_years"]


# ── Doctor schedule serializers ───────────────────────────────────────────────

class DoctorDaySerializer(serializers.Serializer):
    day_of_week  = serializers.ChoiceField(choices=StaffBranchAssignment.DAY_CHOICES)
    is_available = serializers.BooleanField(default=True)
    start_time   = serializers.TimeField()
    end_time     = serializers.TimeField()

    def validate(self, data):
        if data["is_available"] and data["end_time"] <= data["start_time"]:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})
        return data


class DoctorScheduleSerializer(serializers.Serializer):
    """Input for a doctor's working hours: the slot length and up to one window per weekday. Stored by room_utils.set_hours."""
    slot_duration_minutes = serializers.IntegerField(min_value=1, required=False, default=15)
    days = DoctorDaySerializer(many=True)

    def validate_days(self, days):
        seen = [d["day_of_week"] for d in days]
        if len(seen) != len(set(seen)):
            raise serializers.ValidationError("Each day can appear only once.")
        return days


class StaffProfileSerializer(PkModelSerializer):
    """Admin-side view/edit of a non-doctor staff member's profile — mirrors DoctorProfileSerializer."""
    class Meta:
        model  = StaffUser
        fields = ["registration_no", "council_name", "registration_expiry",
                  "qualification", "experience_years",
                  "gender", "bio", "languages"]


class StaffProfileSelfSerializer(PkModelSerializer):
    """Self-service view/edit for a non-doctor staff member's own profile —"""
    class Meta:
        model  = StaffUser
        fields = ["registration_no", "council_name", "registration_expiry",
                  "qualification", "experience_years",
                  "gender", "bio", "languages"]
        read_only_fields = ["registration_no", "council_name", "registration_expiry",
                             "qualification", "experience_years"]


class StaffMeSerializer(PkModelSerializer):
    """Self-service view/edit for ANY logged-in staff member's own basic"""
    # photo stores an S3 object key (see core/storage.py), not a usable
    photo = serializers.SerializerMethodField()

    def get_photo(self, obj):
        return blob_storage.signed_url(obj.photo)

    class Meta:
        model  = StaffUser
        fields = ["staff_user_id", "first_name", "last_name", "email", "role", "photo", "date_of_birth"]
        read_only_fields = ["staff_user_id", "first_name", "last_name", "email", "role"]

    role = serializers.SerializerMethodField()

    def get_role(self, obj):
        return api_role(obj)


class StaffSerializer(PkModelSerializer):
    doctor_profile = serializers.SerializerMethodField()
    staff_profile  = serializers.SerializerMethodField()
    role            = serializers.SerializerMethodField()
    group           = serializers.IntegerField(source="user_group_id", read_only=True)
    group_name      = serializers.CharField(source="user_group.name", read_only=True)
    branch          = serializers.SerializerMethodField()
    branch_name     = serializers.SerializerMethodField()
    department      = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    branch_department = serializers.SerializerMethodField()
    # Only meaningful when role="custom" — the hospital-defined Role's own
    custom_role      = serializers.SerializerMethodField()
    custom_role_name = serializers.SerializerMethodField()
    custom_role_acts_as = serializers.SerializerMethodField()
    # Every place they work: their own branch_department first, then the additional ones
    branches = serializers.SerializerMethodField()

    # photo stores an S3 object key — signed fresh on every read, same
    photo = serializers.SerializerMethodField()

    def get_photo(self, obj):
        return blob_storage.signed_url(obj.photo)

    def get_doctor_profile(self, obj):
        return DoctorProfileSerializer(obj).data if "doctor" in resolve_acts_as(obj) else None

    def get_staff_profile(self, obj):
        return StaffProfileSerializer(obj).data if "doctor" not in resolve_acts_as(obj) else None

    def get_branch(self, obj):
        return primary_branch_id(obj)

    def get_branch_name(self, obj):
        place = primary_place(obj)
        return place.branch.name if place else None

    def get_department(self, obj):
        return primary_department_id(obj)

    def get_department_name(self, obj):
        place = primary_place(obj)
        return place.department.name if place else None

    def get_branch_department(self, obj):
        place = primary_place(obj)
        return place.pk if place else None

    def get_role(self, obj):
        return api_role(obj)

    last_login = serializers.SerializerMethodField()

    def get_last_login(self, obj):
        logins = self.context.get("logins")
        if logins is None:
            logins = last_logins([obj])
        return logins.get(obj.user_id)

    def get_custom_role(self, obj):
        return None

    def get_custom_role_name(self, obj):
        return None

    def get_custom_role_acts_as(self, obj):
        return []

    def get_branches(self, obj):
        db = obj._state.db or "default"
        primary = primary_place(obj, db)
        return [
            {"branch_id": place.branch_id, "name": place.branch.name, "is_primary": primary is not None and place.pk == primary.pk,
             "branch_department_id": place.pk, "department_id": place.department_id, "department_name": place.department.name}
            for place in get_staff_places(obj, db)
        ]

    class Meta:
        model  = StaffUser
        fields = ["staff_user_id", "email", "first_name", "last_name", "role", "group", "group_name",
                  "custom_role", "custom_role_name", "custom_role_acts_as",
                  "branch", "branch_name", "branches",
                  "department", "department_name", "branch_department",
                  "phone", "employee_id", "date_of_birth", "is_active", "must_change_password", "photo",
                  "date_joined", "last_login", "doctor_profile", "staff_profile"]
        read_only_fields = ["staff_user_id", "date_joined", "last_login", "group", "group_name", "branch_department",
                            "custom_role_name", "custom_role_acts_as",
                            "branch_name", "branches", "department_name", "doctor_profile",
                            "staff_profile", "must_change_password"]


class StaffInviteSerializer(serializers.Serializer):
    """Input for inviting a new staff member. Mobile is the login identifier"""
    phone         = serializers.CharField(max_length=20)
    email         = serializers.EmailField(required=False, allow_blank=True)

    def validate_phone(self, value):
        if not re.match(r"^\d{10}$", value):
            raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
        return value

    # Employee ID is NOT accepted as input — it's auto-generated via NextNumber
    first_name    = serializers.CharField(max_length=150)
    last_name     = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role          = serializers.ChoiceField(choices=[
        "hospital_admin", "doctor", "nurse", "front_desk", "custom"
    ])
    # Required (and validated further in the view, which needs request.hospital_db
    custom_role_id = serializers.IntegerField(required=False, allow_null=True)
    branch_id     = serializers.IntegerField(required=False, allow_null=True)
    department_id = serializers.IntegerField(required=False, allow_null=True)
    # Extra branches beyond branch_id (the primary) — meaningful for doctor
    branch_ids    = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)

    # ── Professional basics — admin enters these at creation for EVERY role,
    registration_no     = serializers.CharField(max_length=50, required=False, allow_blank=True)
    council_name        = serializers.CharField(max_length=150, required=False, allow_blank=True)
    registration_expiry = serializers.DateField(required=False, allow_null=True)
    specialisation       = serializers.CharField(max_length=100, required=False, allow_blank=True)
    qualification        = serializers.CharField(max_length=200, required=False, allow_blank=True)
    experience_years     = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    # ── Doctor-only fields — ignored for non-doctor roles ────────────────────
    consultation_fee = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True
    )
    followup_fee = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True
    )
    # Working-hours schedule: list of up to 7 day objects.  Optional at
    schedule = DoctorScheduleSerializer(required=False, allow_null=True)
