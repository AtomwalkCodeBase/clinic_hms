from rest_framework import serializers
from .models import Drug, Prescription, PrescriptionItem


class DrugSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Drug
        fields = ["id", "name", "generic_name", "drug_code", "form", "strength", "unit", "is_active"]
        read_only_fields = ["id"]


class PrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PrescriptionItem
        fields = ["id", "drug", "drug_name", "dose", "unit", "frequency",
                  "route", "duration_days", "instructions", "order"]
        read_only_fields = ["id"]


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model  = Prescription
        fields = ["id", "patient", "encounter", "prescribed_by", "rx_number",
                  "status", "notes", "finalized_at", "created_at", "items"]
        read_only_fields = ["id", "rx_number", "status", "finalized_at", "created_at"]
