from rest_framework import serializers
from .models import (
    BillingService, Invoice, InvoiceItem, Payment, OptionList,
)


class ServiceCategorySerializer(serializers.ModelSerializer):
    # `name` is kept as the external field name (source="label") so the
    # /billing/service-categories/ response shape is byte-for-byte
    # unchanged from the pre-merge ServiceCategory table.
    name = serializers.CharField(source="label")

    class Meta:
        model  = OptionList
        fields = ["id", "name", "is_active", "is_system", "sort_order"]
        read_only_fields = ["id", "is_system"]


class PaymentModeOptionSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="label")

    class Meta:
        model  = OptionList
        fields = ["id", "name", "is_active", "is_system", "sort_order"]
        read_only_fields = ["id", "is_system"]


class InvoiceStatusOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = OptionList
        fields = ["id", "value", "label", "is_active", "is_system", "sort_order"]
        read_only_fields = ["id", "is_system"]


class RoomTypeOptionSerializer(serializers.ModelSerializer):
    # Same value+label shape as InvoiceStatusOptionSerializer (not the
    # name-mirrors-label shape ServiceCategory/PaymentMode use) — Room.room_type
    # stores this row's machine `value`, while `label` is what the Room
    # form's dropdown displays, matching how the field already worked
    # before it became hospital-configurable (was a fixed choices= list on org.models.Room).
    #
    # category/is_bed_based are what let this one catalog serve both OPD
    # rooms (Consultation, Procedure — category="opd"/"procedure",
    # is_bed_based=False) and bed-based IPD rooms (General Ward, Private,
    # ICU, … — category="ipd", is_bed_based=True) since the v8 unification
    # folded org.Ward's old, separate ward_type catalog in here. See
    # billing.OptionList's own docstring.
    class Meta:
        model  = OptionList
        fields = ["id", "value", "label", "is_active", "is_system", "sort_order",
                  "category", "is_bed_based", "daily_rate"]
        read_only_fields = ["id", "is_system"]


class BillingServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = BillingService
        fields = ["id", "name", "code", "category", "unit_price", "tax_rate", "is_active"]
        read_only_fields = ["id"]


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InvoiceItem
        fields = ["id", "service", "description", "quantity", "unit_price", "tax_rate", "total"]
        read_only_fields = ["id"]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Payment
        fields = ["id", "invoice", "amount", "payment_mode", "transaction_ref", "paid_at"]
        read_only_fields = ["id", "paid_at"]


class InvoiceSerializer(serializers.ModelSerializer):
    items    = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    # `patient` on its own is just a FK id — front desk's billing list needs
    # a name to search/scan by, same as every other patient-facing list in
    # this app. `patient` is a real same-DB ForeignKey (not cross-tenant),
    # so `.full_name`/`.uhid` are free reads off the already-fetched row.
    patient_name = serializers.SerializerMethodField()
    patient_uhid = serializers.SerializerMethodField()

    class Meta:
        model  = Invoice
        fields = ["id", "patient", "patient_name", "patient_uhid", "branch", "invoice_number", "status",
                  "subtotal", "tax_amount", "discount_amount", "total_amount", "paid_amount",
                  "notes", "issued_at", "created_at", "items", "payments"]
        read_only_fields = ["id", "invoice_number", "created_at"]

    def get_patient_name(self, obj):
        return obj.patient.full_name if obj.patient_id else None

    def get_patient_uhid(self, obj):
        return obj.patient.uhid if obj.patient_id else None
