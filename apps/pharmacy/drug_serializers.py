from rest_framework import serializers
from apps.billing.models import OptionList
from apps.pharmacy.models import Drug


class DrugSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Drug
        fields = ["id", "name", "generic_name", "drug_code", "form", "strength", "unit", "default_mrp", "is_active"]
        read_only_fields = ["id"]


class DrugFormTypeSerializer(serializers.ModelSerializer):
    # `name` kept as the external field name (source="label") so the
    name = serializers.CharField(source="label")

    class Meta:
        model  = OptionList
        fields = ["id", "name", "is_active"]
        read_only_fields = ["id"]
