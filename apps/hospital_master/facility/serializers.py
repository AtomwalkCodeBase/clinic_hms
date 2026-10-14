import re

from rest_framework import serializers
from apps.hospital_master.facility.models import Branch, Department, Floor, Room, Bed


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
    # this is what "3 of 5 beds" is built from on the frontend; always 0 for
    # a non-bed-based (OPD) room.
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
        """Who this bed is being HELD for, while status=reserved — distinct
        from get_current_admission below (which only ever looks at ACTIVE
        occupancy). Same local-import exception as get_current_admission,
        for the same reason (apps.hospital_master.staff sits below apps.hospital_master.ipd)."""
        if obj.status != Bed.STATUS_RESERVED or not obj.reserved_for_admission_id:
            return None
        from apps.hospital_master.ipd.models import Admission

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
        """Who's actually in this bed right now, for the hospital-admin Beds
        table — a bed's `status` alone only says "occupied", not by whom or
        since when. `apps.hospital_master.ipd.Admission.bed` (related_name="admissions") is
        cleared back to null the moment ReleaseBedView frees a bed — but
        DischargeAdmissionView deliberately does NOT clear it (the record
        keeps which bed a discharged patient was actually in, for history
        and billing), so this reverse relation can hold a DISCHARGED
        admission alongside the live one; excluding CANCELLED/DISCHARGED/
        DISCHARGE_INITIATED is what actually narrows it down to "the"
        current occupant. Imported locally (not at module level) since
        apps.hospital_master.staff sits below apps.hospital_master.ipd in the app hierarchy — apps.hospital_master.ipd
        imports apps.hospital_master.staff.models, not the other way around — and this keeps
        that direction a runtime-only exception scoped to this one lookup
        rather than a module-level dependency.
        """
        from apps.hospital_master.ipd.models import Admission

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
