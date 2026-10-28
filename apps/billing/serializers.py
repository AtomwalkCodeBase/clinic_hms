from decimal import Decimal

from rest_framework import serializers
from core.api.serializers import PkModelSerializer
from apps.billing.models import BillingItem, Invoice
from apps.hospital_setup.models import OptionList


class ServiceCategorySerializer(PkModelSerializer):
    # `name` is kept as the external field name (source="label") so the
    name = serializers.CharField(source="label")

    class Meta:
        model  = OptionList
        fields = ["option_list_id", "name", "is_active", "is_system", "sort_order"]
        read_only_fields = ["option_list_id", "is_system"]


class PaymentModeOptionSerializer(PkModelSerializer):
    name = serializers.CharField(source="label")

    class Meta:
        model  = OptionList
        fields = ["option_list_id", "name", "is_active", "is_system", "sort_order"]
        read_only_fields = ["option_list_id", "is_system"]


class InvoiceStatusOptionSerializer(PkModelSerializer):
    class Meta:
        model  = OptionList
        fields = ["option_list_id", "value", "label", "is_active", "is_system", "sort_order"]
        read_only_fields = ["option_list_id", "is_system"]


class RoomTypeOptionSerializer(PkModelSerializer):
    class Meta:
        model  = OptionList
        fields = ["option_list_id", "value", "label", "is_active", "is_system", "sort_order"]
        read_only_fields = ["option_list_id", "is_system"]


class BillingServiceSerializer(PkModelSerializer):
    class Meta:
        model  = BillingItem
        fields = ["billing_item_id", "name", "code", "category", "unit_price", "tax_rate", "tax_inclusive", "is_price_editable", "is_active"]
        read_only_fields = ["billing_item_id"]


class InvoiceItemSerializer(serializers.Serializer):
    """One line on an invoice, as sent when adding it."""
    service     = serializers.PrimaryKeyRelatedField(queryset=BillingItem.objects.none(), required=False, allow_null=True)
    description = serializers.CharField(max_length=200, required=False, allow_blank=True)
    quantity    = serializers.IntegerField(min_value=1, default=1)
    unit_price  = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0"), required=False)
    tax_rate    = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    tax_inclusive = serializers.BooleanField(required=False)

    def __init__(self, *args, db=None, **kwargs):
        super().__init__(*args, **kwargs)
        if db:
            self.fields["service"].queryset = BillingItem.objects.using(db)


class PaymentSerializer(serializers.Serializer):
    """A payment as sent when recording it."""
    invoice         = serializers.PrimaryKeyRelatedField(queryset=Invoice.objects.none())
    amount          = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    payment_mode    = serializers.CharField(max_length=50)
    transaction_ref = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def __init__(self, *args, db=None, **kwargs):
        super().__init__(*args, **kwargs)
        if db:
            self.fields["invoice"].queryset = Invoice.objects.using(db)


class InvoiceSerializer(PkModelSerializer):
    items    = serializers.JSONField(read_only=True, source="lines")
    payments = serializers.JSONField(read_only=True)
    patient_name = serializers.SerializerMethodField()
    patient_uhid = serializers.SerializerMethodField()

    class Meta:
        model  = Invoice
        fields = ["invoice_id", "patient", "patient_name", "patient_uhid", "branch", "invoice_number", "status",
                  "subtotal", "tax_amount", "discount_amount", "total_amount", "paid_amount",
                  "notes", "issued_at", "created_at", "items", "payments"]
        read_only_fields = ["invoice_id", "invoice_number", "created_at"]

    def get_patient_name(self, obj):
        return obj.patient.get_patient_details()["full_name"] if obj.patient_id else None

    def get_patient_uhid(self, obj):
        return obj.patient.uhid if obj.patient_id else None
