from rest_framework import serializers
from .models import Drug, DrugFormType


class DrugSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Drug
        fields = ["id", "name", "generic_name", "drug_code", "form", "strength", "unit", "is_active"]
        read_only_fields = ["id"]


class DrugFormTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DrugFormType
        fields = ["id", "name", "is_active"]
        read_only_fields = ["id"]
