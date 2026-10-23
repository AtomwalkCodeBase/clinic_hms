import re

from rest_framework import serializers
from apps.hospital_setup.models import Branch, BranchDepartment, Department, Floor, Room, Bed


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Branch
        fields = ["id", "name", "address", "city", "state", "pincode",
                  "phone", "lat", "lng", "is_active"]
        read_only_fields = ["id"]

    def validate_phone(self, value):
        # Branch.phone is optional (blank=True) — only enforce the format
        if value and not re.match(r"^\d{10}$", value):
            raise serializers.ValidationError("Enter a valid 10-digit phone number.")
        return value


class DepartmentSerializer(serializers.ModelSerializer):
    """A department of the hospital, with the branches that offer it."""
    branches = serializers.SerializerMethodField()

    class Meta:
        model  = Department
        fields = ["id", "name", "is_active", "branches"]
        read_only_fields = ["id", "branches"]

    def get_branches(self, obj):
        return [{"branch": place.branch_id, "branch_name": place.branch.name, "branch_department_id": place.id,
                 "floor": place.floor_id, "floor_name": place.floor.name if place.floor_id else "", "is_active": place.is_active}
                for place in obj.d_branches.select_related("branch", "floor").order_by("branch__name")]

    def validate_name(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Enter a name.")
        clash = Department.objects.filter(name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A department with this name already exists.")
        return value


class BranchDepartmentSerializer(serializers.ModelSerializer):
    """A department as one branch offers it. `id` is the department's id, so lists by branch read like the department list."""
    id              = serializers.IntegerField(source="department_id", read_only=True)
    name            = serializers.CharField(source="department.name", read_only=True)
    branch_name     = serializers.CharField(source="branch.name", read_only=True)
    floor_name      = serializers.CharField(source="floor.name", read_only=True, default="")
    branch_department_id = serializers.IntegerField(source="id", read_only=True)

    class Meta:
        model  = BranchDepartment
        fields = ["id", "name", "branch", "branch_name", "branch_department_id", "floor", "floor_name", "is_active"]
        read_only_fields = ["branch"]

    def validate_floor(self, value):
        branch_id = self.instance.branch_id if self.instance is not None else self.initial_data.get("branch")
        if value is not None and str(value.branch_id) != str(branch_id):
            raise serializers.ValidationError("That floor belongs to a different branch.")
        return value


class FloorSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model  = Floor
        fields = ["id", "branch", "branch_name", "name", "level", "is_active"]
        read_only_fields = ["id", "branch_name"]


class RoomSerializer(serializers.ModelSerializer):
    """A room. Its branch is its floor's branch; `department` is a department id that the floor's branch must offer."""
    branch          = serializers.IntegerField(source="floor.branch_id", read_only=True)
    branch_name     = serializers.CharField(source="floor.branch.name", read_only=True)
    floor_name      = serializers.CharField(source="floor.name", read_only=True)
    floor_obj       = serializers.PrimaryKeyRelatedField(source="floor", queryset=Floor.objects.all())
    floor           = serializers.CharField(source="floor.name", read_only=True)
    department      = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), required=False, allow_null=True)
    department_name = serializers.SerializerMethodField()
    # Live count of active beds under this room — for a bed-based room type
    bed_count       = serializers.SerializerMethodField()

    class Meta:
        model  = Room
        fields = ["id", "branch", "branch_name", "floor", "floor_obj", "floor_name",
                  "department", "department_name", "name", "room_type", "capacity",
                  "is_active", "bed_count"]
        read_only_fields = ["id", "branch", "branch_name", "floor", "floor_name", "department_name", "bed_count"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["department"] = instance.branch_department.department_id if instance.branch_department_id else None
        return data

    def get_department_name(self, obj):
        return obj.branch_department.department.name if obj.branch_department_id else ""

    def get_bed_count(self, obj):
        return obj.r_beds.filter(is_active=True).count()


class BedSerializer(serializers.ModelSerializer):
    room_name   = serializers.CharField(source="room.name", read_only=True)
    branch_id   = serializers.IntegerField(source="room.floor.branch_id", read_only=True)
    floor_id    = serializers.IntegerField(source="room.floor_id", read_only=True)
    floor_name  = serializers.CharField(source="room.floor.name", read_only=True)
    current_admission = serializers.SerializerMethodField()
    reservation = serializers.SerializerMethodField()

    class Meta:
        model  = Bed
        fields = ["id", "room", "room_name", "branch_id", "floor_id", "floor_name", "bed_number", "status",
                  "is_active", "current_admission", "reservation"]
        read_only_fields = ["id", "room_name", "branch_id", "floor_id", "floor_name", "current_admission", "reservation"]

    def get_reservation(self, obj):
        """Who this bed is being HELD for, while status=reserved — distinct"""
        if obj.status != Bed.STATUS_RESERVED or not obj.reserved_for_admission_id:
            return None
        from apps.ipd.models import Admission

        try:
            admission = Admission.objects.db_manager(obj._state.db).select_related("patient").get(
                pk=obj.reserved_for_admission_id,
            )
        except Admission.DoesNotExist:
            return None
        return {
            "admission_id": str(admission.id),
            "admission_number": admission.admission_number,
            "patient_name": admission.patient.get_patient_details()["full_name"],
            "patient_uhid": admission.patient.uhid,
        }

    def get_current_admission(self, obj):
        """Who's actually in this bed right now, for the hospital-admin Beds"""
        from apps.ipd.models import Admission

        admission = (
            obj.bd_admissions
            .exclude(status__in=[
                Admission.STATUS_CANCELLED,
                Admission.STATUS_DISCHARGE_INITIATED,
                Admission.STATUS_DISCHARGED,
            ])
            .select_related("patient")
            .order_by("-bed_assigned_at")
            .first()
        )
        if not admission:
            return None
        return {
            "admission_id": str(admission.id),
            "admission_number": admission.admission_number,
            "patient_name": admission.patient.get_patient_details()["full_name"],
            "patient_uhid": admission.patient.uhid,
            "admitted_at": admission.bed_assigned_at,
            "expected_discharge_date": admission.expected_discharge_date,
        }
