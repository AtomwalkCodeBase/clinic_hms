import re

from rest_framework import serializers
from .models import (
    Branch, Department, StaffUser, DoctorProfile, StaffProfile, StaffBranchMapping,
    Permission, Role, UserRole, DoctorSchedule, DoctorAvailabilitySlot,
)


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Branch
        fields = ["id", "name", "address", "city", "state", "pincode",
                  "phone", "lat", "lng", "is_active"]
        read_only_fields = ["id"]

    def validate_phone(self, value):
        # Branch.phone is optional (blank=True) — only enforce the format
        # when something was actually entered, same 10-digit convention used
        # for every other phone field in the app (patient mobile, staff
        # mobile, etc.). A plain RegexValidator on the model field would
        # also fire on an empty string, which is why this is a method
        # validator instead.
        if value and not re.match(r"^\d{10}$", value):
            raise serializers.ValidationError("Enter a valid 10-digit phone number.")
        return value


class DepartmentSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model  = Department
        fields = ["id", "branch", "branch_name", "name", "is_active"]
        read_only_fields = ["id", "branch_name"]


class DoctorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DoctorProfile
        fields = ["registration_no", "specialisation", "qualification",
                  "gender", "experience_years", "consultation_fee",
                  "bio", "photo_url", "languages", "known_for"]


class DoctorSelfProfileSerializer(serializers.ModelSerializer):
    """
    Self-service view/edit for the logged-in doctor's own profile.

    admin_fields (registration_no, specialisation, qualification,
    experience_years) are always read-only here — set by the hospital admin
    at onboarding, changeable only via DoctorProfileView.

    consultation_fee is conditionally read-only: when the hospital's
    fee_ownership == "hospital" the field is locked for doctors; when
    fee_ownership == "doctor" they can edit it freely.  The view
    (MyDoctorProfileView) passes fee_editable=True/False as context so this
    serializer doesn't need to query the Tenant itself.
    """
    def get_fields(self):
        fields = super().get_fields()
        if not self.context.get("fee_editable", False):
            fields["consultation_fee"].read_only = True
        return fields

    class Meta:
        model  = DoctorProfile
        fields = ["registration_no", "specialisation", "qualification",
                  "gender", "experience_years", "consultation_fee",
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
    """
    Self-service view/edit for a non-doctor staff member's own profile —
    mirrors DoctorSelfProfileSerializer. registration_no / council_name /
    registration_expiry / qualification / experience_years were set by the
    hospital admin at onboarding and are read-only here; gender / bio /
    languages the staff member owns.
    """
    class Meta:
        model  = StaffProfile
        fields = ["registration_no", "council_name", "registration_expiry",
                  "qualification", "experience_years",
                  "gender", "bio", "languages"]
        read_only_fields = ["registration_no", "council_name", "registration_expiry",
                             "qualification", "experience_years"]


class StaffMeSerializer(serializers.ModelSerializer):
    """
    Self-service view/edit for ANY logged-in staff member's own basic
    profile — currently just the photo. Shared by every role (doctor,
    nurse, front desk, lab tech, pharmacist, hospital admin) via
    MyStaffProfileView, scoped to request.user's own row.
    """
    class Meta:
        model  = StaffUser
        fields = ["id", "first_name", "last_name", "email", "role", "photo", "date_of_birth"]
        read_only_fields = ["id", "first_name", "last_name", "email", "role"]


class StaffSerializer(serializers.ModelSerializer):
    doctor_profile = DoctorProfileSerializer(read_only=True)
    staff_profile  = StaffProfileSerializer(read_only=True)
    branch_name    = serializers.CharField(source="branch.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    # Full branch assignment (usually just the one primary branch, mirrored
    # from `branch`/`branch_name` above for backward compat — more than one
    # entry means this person, almost always a doctor, works multiple
    # branches; see apps.org.branch_utils).
    branches = serializers.SerializerMethodField()

    def get_branches(self, obj):
        mappings = (
            StaffBranchMapping.objects
            # .using() isn't available via this implicit manager call inside
            # a serializer method — the queryset passed to the serializer's
            # instance list already resolved `obj` from the right tenant DB,
            # and StaffBranchMapping shares that same tenant DB (both live
            # in apps.org, routed together), so plain .filter() here is safe.
            .filter(staff_id=obj.id)
            .select_related("branch")
            .order_by("-is_primary", "branch__name")
        )
        return [
            {"id": m.branch_id, "name": m.branch.name, "is_primary": m.is_primary}
            for m in mappings
        ]

    class Meta:
        model  = StaffUser
        fields = ["id", "email", "first_name", "last_name", "role",
                  "branch", "branch_name", "branches", "department", "department_name",
                  "phone", "employee_id", "date_of_birth", "is_active", "must_change_password", "photo",
                  "date_joined", "last_login", "doctor_profile", "staff_profile"]
        read_only_fields = ["id", "date_joined", "last_login",
                            "branch_name", "branches", "department_name", "doctor_profile",
                            "staff_profile", "must_change_password"]


class StaffInviteSerializer(serializers.Serializer):
    """Input for inviting a new staff member. Mobile is the login identifier
    (see registry.StaffMobileIndex) — email is optional/informational only."""
    phone         = serializers.CharField(max_length=20)
    email         = serializers.EmailField(required=False, allow_blank=True)

    def validate_phone(self, value):
        if not re.match(r"^\d{10}$", value):
            raise serializers.ValidationError("Enter a valid 10-digit mobile number.")
        return value

    # Employee ID is NOT accepted as input — it's auto-generated via NNTM
    # (see apps.org.views._next_employee_id), same as UHID/invoice/etc.
    # Never manually typed in, so it isn't part of this input contract.
    first_name    = serializers.CharField(max_length=150)
    last_name     = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role          = serializers.ChoiceField(choices=[
        "hospital_admin", "doctor", "nurse", "front_desk", "lab_tech", "pharmacist"
    ])
    branch_id     = serializers.IntegerField(required=False, allow_null=True)
    department_id = serializers.IntegerField(required=False, allow_null=True)
    # Extra branches beyond branch_id (the primary) — meaningful for doctor
    # role only in practice, harmless to accept for any role. If provided,
    # branch_id (if also given) is folded in as the primary automatically —
    # see apps.org.branch_utils.set_staff_branches.
    branch_ids    = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)

    # ── Professional basics — admin enters these at creation for EVERY role,
    #    not just doctor, so nobody ends up with a blank profile (nursing/
    #    pharmacy council registration is legally required before those
    #    accounts should even be treated as active). specialisation only
    #    applies to doctor; council_name / registration_expiry mainly matter
    #    for nurse and pharmacist but are harmless to leave blank for others.
    #    Everything else (gender, bio, languages, photo, signature) is
    #    self-service — see MyDoctorProfileView / MyStaffProfileDetailsView.
    registration_no     = serializers.CharField(max_length=50, required=False, allow_blank=True)
    council_name        = serializers.CharField(max_length=150, required=False, allow_blank=True)
    registration_expiry = serializers.DateField(required=False, allow_null=True)
    specialisation       = serializers.CharField(max_length=100, required=False, allow_blank=True)
    qualification        = serializers.CharField(max_length=200, required=False, allow_blank=True)
    experience_years     = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    # ── Doctor-only fields — ignored for non-doctor roles ────────────────────
    # consultation_fee: accepted here when the hospital's fee_ownership is
    # "hospital" — the view checks the tenant setting and writes it to
    # DoctorProfile.consultation_fee; ignored silently for non-doctor roles.
    consultation_fee = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, allow_null=True
    )
    # Working-hours schedule: list of up to 7 day objects.  Optional at
    # registration — can also be set later via /staff/<pk>/schedule/.
    schedule = DoctorScheduleSerializer(required=False, allow_null=True)


# ── Table-driven RBAC (see apps.org.rbac / docs/onboarding_auth_rbac_architecture.md 4.3) ──

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
                  "permission_codes", "created_at"]
        read_only_fields = ["id", "is_system_role", "system_role_key", "created_at"]


class RoleWriteSerializer(serializers.Serializer):
    """Input for creating/editing a CUSTOM role (system roles are read-only)."""
    name              = serializers.CharField(max_length=100)
    description       = serializers.CharField(max_length=255, required=False, allow_blank=True)
    permission_codes  = serializers.ListField(child=serializers.CharField(), required=False, allow_empty=True)
