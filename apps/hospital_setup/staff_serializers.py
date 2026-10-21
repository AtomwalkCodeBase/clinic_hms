import re

from rest_framework import serializers
from core import storage as blob_storage
from apps.hospital_setup.models import (
    StaffUser,
    DoctorProfile,
    StaffProfile,
    StaffBranchMapping,
    Permission,
    Role,
    DoctorSchedule,
    DoctorAvailabilitySlot,
    RoomAssignment,
    NurseDoctorAssignment,
)


class RoomAssignmentSerializer(serializers.ModelSerializer):
    day_label   = serializers.CharField(source="get_day_of_week_display", read_only=True)
    room_name   = serializers.CharField(source="room.name", read_only=True)
    floor       = serializers.CharField(source="room.floor", read_only=True)
    doctor_name = serializers.SerializerMethodField()

    class Meta:
        model  = RoomAssignment
        fields = ["id", "room", "room_name", "floor", "doctor", "doctor_name",
                  "day_of_week", "day_label", "start_time", "end_time", "is_active"]
        read_only_fields = ["id", "day_label", "room_name", "floor", "doctor_name"]

    def get_doctor_name(self, obj):
        return obj.doctor.get_full_name()

    def validate(self, data):
        start = data.get("start_time", getattr(self.instance, "start_time", None))
        end   = data.get("end_time",   getattr(self.instance, "end_time",   None))
        if start is not None and end is not None and start >= end:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})
        return data


class DoctorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DoctorProfile
        fields = ["registration_no", "specialisation", "qualification",
                  "gender", "experience_years", "consultation_fee", "followup_fee",
                  "bio", "languages", "known_for"]


class DoctorSelfProfileSerializer(serializers.ModelSerializer):
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
        model  = DoctorProfile
        fields = ["registration_no", "specialisation", "qualification",
                  "gender", "experience_years", "consultation_fee", "followup_fee",
                  "digital_signature", "bio", "languages", "known_for"]
        read_only_fields = ["registration_no", "specialisation",
                             "qualification", "experience_years"]


# ── Doctor schedule serializers ───────────────────────────────────────────────

class DoctorAvailabilitySlotSerializer(serializers.ModelSerializer):
    day_label = serializers.CharField(source="get_day_of_week_display", read_only=True)

    class Meta:
        model  = DoctorAvailabilitySlot
        fields = ["id", "day_of_week", "day_label", "is_available", "start_time", "end_time"]
        read_only_fields = ["id", "day_label"]


class DoctorScheduleSerializer(serializers.ModelSerializer):
    days = DoctorAvailabilitySlotSerializer(many=True)

    class Meta:
        model  = DoctorSchedule
        fields = ["id", "slot_duration_minutes", "days"]
        read_only_fields = ["id"]

    def create(self, validated_data):
        days_data = validated_data.pop("days", [])
        schedule = DoctorSchedule.objects.using(self._db).create(**validated_data)
        for day in days_data:
            DoctorAvailabilitySlot.objects.using(self._db).create(schedule=schedule, **day)
        return schedule

    def update(self, instance, validated_data):
        days_data = validated_data.pop("days", None)
        instance.slot_duration_minutes = validated_data.get(
            "slot_duration_minutes", instance.slot_duration_minutes
        )
        instance.save(using=self._db)
        if days_data is not None:
            # Full replace — delete existing days and re-create
            instance.days.using(self._db).all().delete()
            for day in days_data:
                DoctorAvailabilitySlot.objects.using(self._db).create(schedule=instance, **day)
        return instance


class StaffProfileSerializer(serializers.ModelSerializer):
    """Admin-side view/edit of a non-doctor staff member's profile — mirrors DoctorProfileSerializer."""
    class Meta:
        model  = StaffProfile
        fields = ["registration_no", "council_name", "registration_expiry",
                  "qualification", "experience_years",
                  "gender", "bio", "languages", "extra"]


class StaffProfileSelfSerializer(serializers.ModelSerializer):
    """Self-service view/edit for a non-doctor staff member's own profile —"""
    class Meta:
        model  = StaffProfile
        fields = ["registration_no", "council_name", "registration_expiry",
                  "qualification", "experience_years",
                  "gender", "bio", "languages"]
        read_only_fields = ["registration_no", "council_name", "registration_expiry",
                             "qualification", "experience_years"]


class StaffMeSerializer(serializers.ModelSerializer):
    """Self-service view/edit for ANY logged-in staff member's own basic"""
    # photo stores an S3 object key (see core/storage.py), not a usable
    photo = serializers.SerializerMethodField()

    def get_photo(self, obj):
        return blob_storage.signed_url(obj.photo)

    class Meta:
        model  = StaffUser
        fields = ["id", "first_name", "last_name", "email", "role", "photo", "date_of_birth"]
        read_only_fields = ["id", "first_name", "last_name", "email", "role"]


class StaffSerializer(serializers.ModelSerializer):
    doctor_profile = DoctorProfileSerializer(read_only=True)
    staff_profile  = StaffProfileSerializer(read_only=True)
    branch_name    = serializers.CharField(source="branch.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    # Only meaningful when role="custom" — the hospital-defined Role's own
    custom_role_name = serializers.CharField(source="custom_role.name", read_only=True, default=None)
    custom_role_acts_as = serializers.SerializerMethodField()

    def get_custom_role_acts_as(self, obj):
        return obj.custom_role.acts_as if obj.custom_role_id else []
    # Full branch assignment (usually just the one primary branch, mirrored
    branches = serializers.SerializerMethodField()

    # photo stores an S3 object key — signed fresh on every read, same
    photo = serializers.SerializerMethodField()

    def get_photo(self, obj):
        return blob_storage.signed_url(obj.photo)

    def get_branches(self, obj):
        mappings = (
            StaffBranchMapping.objects
            # .using() isn't available via this implicit manager call inside
            .filter(staff_id=obj.id)
            .select_related("branch")
            .order_by("-is_primary", "branch__name")
        )
        return [
            {"id": m.branch_id, "name": m.branch.name, "is_primary": m.is_primary}
            for m in mappings
        ]

    # Only meaningful for role="nurse" — which doctor(s) the hospital admin
    assigned_doctors = serializers.SerializerMethodField()

    def get_assigned_doctors(self, obj):
        if obj.role != "nurse":
            return []
        links = (
            NurseDoctorAssignment.objects
            .filter(nurse_id=obj.id)
            .select_related("doctor")
            .order_by("doctor__first_name", "doctor__last_name")
        )
        return [
            {"id": l.doctor_id, "name": l.doctor.get_full_name()}
            for l in links
        ]

    class Meta:
        model  = StaffUser
        fields = ["id", "email", "first_name", "last_name", "role",
                  "custom_role", "custom_role_name", "custom_role_acts_as",
                  "branch", "branch_name", "branches", "assigned_doctors",
                  "department", "department_name",
                  "phone", "employee_id", "date_of_birth", "is_active", "must_change_password", "photo",
                  "date_joined", "last_login", "doctor_profile", "staff_profile"]
        read_only_fields = ["id", "date_joined", "last_login",
                            "custom_role_name", "custom_role_acts_as",
                            "branch_name", "branches", "assigned_doctors", "department_name", "doctor_profile",
                            "staff_profile", "must_change_password"]


class StaffInviteSerializer(serializers.Serializer):
    """Input for inviting a new staff member. Mobile is the login identifier"""
    phone         = serializers.CharField(max_length=20)
    email         = serializers.EmailField(required=False, allow_blank=True)

    def validate_phone(self, value):
        if not re.match(r"^\d{10}$", value):
            raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
        return value

    # Employee ID is NOT accepted as input — it's auto-generated via NNTM
    first_name    = serializers.CharField(max_length=150)
    last_name     = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role          = serializers.ChoiceField(choices=[
        "hospital_admin", "doctor", "nurse", "front_desk", "lab_tech", "pharmacist", "custom"
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


# ── Table-driven RBAC (see apps.hospital_setup.rbac / docs/onboarding_auth_rbac_architecture.md 4.3) ──

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Permission
        fields = ["id", "code", "description"]


class RoleSerializer(serializers.ModelSerializer):
    permission_codes = serializers.SerializerMethodField()

    def get_permission_codes(self, obj):
        return list(obj.permissions.values_list("code", flat=True).order_by("code"))

    class Meta:
        model  = Role
        fields = ["id", "name", "description", "is_system_role", "system_role_key",
                  "permission_codes", "acts_as", "created_at"]
        read_only_fields = ["id", "is_system_role", "system_role_key", "created_at"]


class RoleWriteSerializer(serializers.Serializer):
    """Input for creating/editing a CUSTOM role (system roles are read-only)."""
    name              = serializers.CharField(max_length=100)
    description       = serializers.CharField(max_length=255, required=False, allow_blank=True)
    permission_codes  = serializers.ListField(child=serializers.CharField(), required=False, allow_empty=True)
    # Which system-role identities this custom role should be treated as
    acts_as           = serializers.ListField(child=serializers.CharField(), required=False, allow_empty=True)

    def validate_acts_as(self, value):
        from apps.hospital_setup.rbac import ACTS_AS_CHOICES
        invalid = set(value) - set(ACTS_AS_CHOICES)
        if invalid:
            raise serializers.ValidationError(f"Invalid acts_as value(s): {', '.join(sorted(invalid))}.")
        return value
