from rest_framework import serializers
from .models import Stock, StockTransaction, Dispense


class StockSerializer(serializers.ModelSerializer):
    drug_name  = serializers.CharField(source="drug.name", read_only=True)
    is_low     = serializers.SerializerMethodField()

    class Meta:
        model  = Stock
        fields = ["id", "drug", "drug_name", "branch", "batch_number",
                  "expiry_date", "quantity", "reorder_level", "unit_cost", "mrp", "is_low"]
        read_only_fields = ["id"]

    def get_is_low(self, obj):
        return obj.quantity <= obj.reorder_level


# ── Pharmacist's dispensing queue ────────────────────────────────────────────
# Read-only views onto apps.prescriptions models (Prescription/PrescriptionItem
# live in that app, not this one) — kept here rather than added to
# prescriptions/serializers.py since they're shaped specifically for what the
# pharmacist screen needs (patient/doctor names resolved, per-item dispensed
# quantity) and PrescriptionListCreateView is doctor-only, so this is the only
# consumer of this particular shape.
class PharmacyPrescriptionItemSerializer(serializers.Serializer):
    id              = serializers.IntegerField()
    drug            = serializers.IntegerField(source="drug_id", allow_null=True)
    drug_name       = serializers.CharField()
    dose            = serializers.CharField()
    unit            = serializers.CharField()
    frequency       = serializers.CharField()
    route           = serializers.CharField()
    duration_days   = serializers.IntegerField(allow_null=True)
    instructions    = serializers.CharField()
    dispensed_qty   = serializers.IntegerField()


class PharmacyPrescriptionSerializer(serializers.Serializer):
    id            = serializers.IntegerField()
    rx_number     = serializers.CharField()
    status        = serializers.CharField()
    notes         = serializers.CharField()
    finalized_at  = serializers.DateTimeField(allow_null=True)
    created_at    = serializers.DateTimeField()
    patient       = serializers.IntegerField(source="patient_id")
    patient_name  = serializers.CharField()
    patient_uhid  = serializers.CharField()
    doctor_name   = serializers.CharField()
    items         = PharmacyPrescriptionItemSerializer(many=True)


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
