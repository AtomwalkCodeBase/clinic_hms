from rest_framework import serializers
from .models import Stock, StockTransaction, Dispense


class StockSerializer(serializers.ModelSerializer):
    drug_name  = serializers.CharField(source="drug.name", read_only=True)

    class Meta:
        model  = Stock
        fields = ["id", "drug", "drug_name", "branch", "batch_number",
                  "expiry_date", "quantity", "reorder_level", "mrp"]
        read_only_fields = ["id"]


class StockTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = StockTransaction
        fields = ["id", "stock", "txn_type", "quantity_change",
                  "quantity_before", "quantity_after", "notes", "recorded_at"]
        read_only_fields = ["id", "quantity_before", "quantity_after", "recorded_at"]


class DispenseSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Dispense
        fields = ["id", "prescription_item", "stock", "quantity", "dispensed_at"]
        read_only_fields = ["id", "dispensed_at"]
