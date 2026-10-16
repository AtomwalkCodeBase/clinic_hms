import re

from rest_framework import serializers
from apps.hospital_setup.models import Branch, Department, Floor, Room, Bed


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
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model  = Department
        fields = ["id", "branch", "branch_name", "name", "is_active"]
        read_only_fields = ["id", "branch_name"]


class FloorSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model  = Floor
        fields = ["id", "branch", "branch_name", "name", "level", "is_active"]
        read_only_fields = ["id", "branch_name"]


class RoomSerializer(serializers.ModelSerializer):
    branch_name     = serializers.CharField(source="branch.name", read_only=True)
    floor_name      = serializers.CharField(source="floor_obj.name", read_only=True, default="")
    department_name = serializers.CharField(source="department.name", read_only=True, default="")
    # Live count of active beds under this room — for a bed-based room type
    bed_count       = serializers.SerializerMethodField()

    class Meta:
        model  = Room
        fields = ["id", "branch", "branch_name", "floor", "floor_obj", "floor_name",
                  "department", "department_name", "name", "room_type", "capacity",
                  "is_active", "bed_count"]
        read_only_fields = ["id", "branch_name", "floor", "floor_name", "department_name", "bed_count"]

    def get_bed_count(self, obj):
        return obj.beds.filter(is_active=True).count()


class BedSerializer(serializers.ModelSerializer):
    room_name   = serializers.CharField(source="room.name", read_only=True)
    branch_id   = serializers.IntegerField(source="room.branch_id", read_only=True)
    floor_id    = serializers.IntegerField(source="room.floor_obj_id", read_only=True, default=None)
    floor_name  = serializers.CharField(source="room.floor_obj.name", read_only=True, default="")
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
            "patient_name": admission.patient.full_name,
            "patient_uhid": admission.patient.uhid,
        }

    def get_current_admission(self, obj):
        """Who's actually in this bed right now, for the hospital-admin Beds"""
        from apps.ipd.models import Admission

        admission = (
            obj.admissions
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
            "patient_name": admission.patient.full_name,
            "patient_uhid": admission.patient.uhid,
            "admitted_at": admission.bed_assigned_at,
            "expected_discharge_date": admission.expected_discharge_date,
        }
