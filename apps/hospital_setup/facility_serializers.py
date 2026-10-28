import re

from rest_framework import serializers
from core.api.serializers import PkModelSerializer
from apps.hospital_setup.models import Branch, BranchDepartment, Department, Floor, Room


class BranchSerializer(PkModelSerializer):
    class Meta:
        model  = Branch
        fields = ["branch_id", "name", "address", "city", "state", "pincode",
                  "phone", "lat", "lng", "is_active"]
        read_only_fields = ["branch_id"]

    def validate_phone(self, value):
        # Branch.phone is optional (blank=True) — only enforce the format
        if value and not re.match(r"^\d{10}$", value):
            raise serializers.ValidationError("Enter a valid 10-digit phone number.")
        return value


class DepartmentSerializer(PkModelSerializer):
    """A department of the hospital, with the branches that offer it."""
    branches = serializers.SerializerMethodField()

    class Meta:
        model  = Department
        fields = ["department_id", "name", "is_active", "branches"]
        read_only_fields = ["department_id", "branches"]

    def get_branches(self, obj):
        return [{"branch": place.branch_id, "branch_name": place.branch.name, "branch_department_id": place.pk,
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


class BranchDepartmentSerializer(PkModelSerializer):
    """A department as one branch offers it. `department_id` is the department's id, so lists by branch read like the department list."""
    department_id   = serializers.IntegerField(read_only=True)
    name            = serializers.CharField(source="department.name", read_only=True)
    branch_name     = serializers.CharField(source="branch.name", read_only=True)
    floor_name      = serializers.CharField(source="floor.name", read_only=True, default="")
    
    class Meta:
        model  = BranchDepartment
        fields = ["department_id", "name", "branch", "branch_name", "branch_department_id", "floor", "floor_name", "is_active"]
        read_only_fields = ["branch"]

    def validate_floor(self, value):
        branch_id = self.instance.branch_id if self.instance is not None else self.initial_data.get("branch")
        if value is not None and str(value.branch_id) != str(branch_id):
            raise serializers.ValidationError("That floor belongs to a different branch.")
        return value


class FloorSerializer(PkModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model  = Floor
        fields = ["floor_id", "branch", "branch_name", "name", "level", "is_active"]
        read_only_fields = ["floor_id", "branch_name"]


class RoomSerializer(PkModelSerializer):
    """A room. Its branch is its floor's branch; `department` is a department id that the floor's branch must offer."""
    branch          = serializers.IntegerField(source="floor.branch_id", read_only=True)
    branch_name     = serializers.CharField(source="floor.branch.name", read_only=True)
    floor_name      = serializers.CharField(source="floor.name", read_only=True)
    floor_obj       = serializers.PrimaryKeyRelatedField(source="floor", queryset=Floor.objects.all())
    floor           = serializers.CharField(source="floor.name", read_only=True)
    department      = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), required=False, allow_null=True)
    department_name = serializers.SerializerMethodField()

    class Meta:
        model  = Room
        fields = ["room_id", "branch", "branch_name", "floor", "floor_obj", "floor_name",
                  "department", "department_name", "name", "room_type",
                  "is_active"]
        read_only_fields = ["room_id", "branch", "branch_name", "floor", "floor_name", "department_name"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["department"] = instance.branch_department.department_id if instance.branch_department_id else None
        return data

    def get_department_name(self, obj):
        return obj.branch_department.department.name if obj.branch_department_id else ""
