from rest_framework import serializers
from .models import BillingService, Invoice, InvoiceItem, Payment


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

    class Meta:
        model  = Invoice
        fields = ["id", "patient", "encounter", "branch", "invoice_number", "status",
                  "subtotal", "tax_amount", "discount_amount", "total_amount", "paid_amount",
                  "notes", "issued_at", "created_at", "items", "payments"]
        read_only_fields = ["id", "invoice_number", "created_at"]
