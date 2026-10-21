"""apps/billing/models.py"""

from django.db import models
from django.utils import timezone
from apps.hospital_setup.models import StaffUser
from apps.hospital_setup.models import Branch
from apps.opd.models import HospitalPatient


class OptionList(models.Model):
    """Hospital-managed dropdown lists, merged across billing + pharmacy setup screens."""
    LIST_SERVICE_CATEGORY = "service_category"
    LIST_PAYMENT_MODE     = "payment_mode"
    LIST_INVOICE_STATUS   = "invoice_status"
    LIST_DRUG_FORM        = "drug_form"
    # Added for apps.ipd (Phase 1 admission intake) — admission_type and
    LIST_ADMISSION_TYPE   = "admission_type"
    LIST_ADMISSION_SOURCE = "admission_source"
    # Added so org.Room.room_type stops being a fixed 3-value choices= list
    LIST_ROOM_TYPE        = "room_type"
    # Added to stop LabTest.sample_type (blood/urine/stool/sputum/swab/other)
    LIST_SAMPLE_TYPE      = "sample_type"
    LIST_APPOINTMENT_TYPE = "appointment_type"
    LIST_TYPE_CHOICES = [
        (LIST_SERVICE_CATEGORY, "Service Category"),
        (LIST_PAYMENT_MODE, "Payment Mode"),
        (LIST_INVOICE_STATUS, "Invoice Status"),
        (LIST_DRUG_FORM, "Drug Form"),
        (LIST_ADMISSION_TYPE, "Admission Type"),
        (LIST_ADMISSION_SOURCE, "Admission Source"),
        (LIST_ROOM_TYPE, "Room Type"),
        (LIST_SAMPLE_TYPE, "Sample Type"),
        (LIST_APPOINTMENT_TYPE, "Appointment Type"),
    ]

    # Meaningful only for list_type="room_type" rows (every other list_type
    CATEGORY_OPD       = "opd"
    CATEGORY_IPD       = "ipd"
    CATEGORY_PROCEDURE = "procedure"
    CATEGORY_OTHER     = "other"
    CATEGORY_CHOICES = [
        (CATEGORY_OPD, "OPD"),
        (CATEGORY_IPD, "IPD"),
        (CATEGORY_PROCEDURE, "Procedure"),
        (CATEGORY_OTHER, "Other"),
    ]

    list_type   = models.CharField(max_length=20, choices=LIST_TYPE_CHOICES)
    value       = models.CharField(max_length=20)   # what's actually stored/matched against
    label       = models.CharField(max_length=50)   # what's shown in the UI
    is_active   = models.BooleanField(default=True)
    is_system   = models.BooleanField(default=False)  # seeded default — can't be deleted
    sort_order  = models.PositiveSmallIntegerField(default=0)
    category      = models.CharField(max_length=12, choices=CATEGORY_CHOICES, blank=True)
    is_bed_based  = models.BooleanField(default=False)
    # Meaningful only for list_type="room_type" rows where is_bed_based=True
    daily_rate  = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "option_list"
        ordering  = ["list_type", "sort_order", "label"]
        constraints = [
            models.UniqueConstraint(fields=["list_type", "value"], name="uniq_option_list_type_value"),
        ]

    def __str__(self):
        return f"{self.list_type}:{self.label}"


class BillingService(models.Model):
    """Hospital-configured price list for services, procedures, etc."""
    name        = models.CharField(max_length=200)
    code        = models.CharField(max_length=50, blank=True)
    category    = models.CharField(max_length=50, default="Other")
    unit_price  = models.DecimalField(max_digits=10, decimal_places=2)
    tax_rate    = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "billing_service"
        ordering  = ["name"]

    def __str__(self):
        return f"{self.name} (₹{self.unit_price})"


class Invoice(models.Model):
    # Kept as plain constants (not a `choices=` list) for internal logic to
    STATUS_DRAFT          = "draft"
    STATUS_ISSUED         = "issued"
    STATUS_PAID           = "paid"
    STATUS_PARTIALLY_PAID = "partially_paid"
    STATUS_CANCELLED      = "cancelled"

    patient         = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT,
                                        related_name="invoices")
    # `encounter` (FK to apps.clinical.Encounter) was removed (HMS-07c-1) —
    branch          = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="invoices")
    invoice_number  = models.CharField(max_length=30, unique=True)
    status          = models.CharField(max_length=20, default=STATUS_DRAFT, db_index=True)  # validated against OptionList(list_type="invoice_status")
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes           = models.TextField(blank=True)
    created_by      = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="invoices_created")
    issued_at       = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "invoice"
        constraints = [
            models.CheckConstraint(
                check=models.Q(subtotal__gte=0, tax_amount__gte=0, discount_amount__gte=0, total_amount__gte=0, paid_amount__gte=0),
                name="invoice_amounts_not_negative"),
        ]

    def __str__(self):
        return f"{self.invoice_number} — {self.patient.uhid} (₹{self.total_amount})"


class InvoiceItem(models.Model):
    invoice         = models.ForeignKey(Invoice, on_delete=models.CASCADE,
                                        related_name="items")
    service         = models.ForeignKey(BillingService, on_delete=models.PROTECT,
                                        null=True, blank=True, related_name="invoice_items")
    description     = models.CharField(max_length=200)  # denormalized
    quantity        = models.PositiveSmallIntegerField(default=1)
    unit_price      = models.DecimalField(max_digits=10, decimal_places=2)
    tax_rate        = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total           = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table  = "invoice_item"
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0, unit_price__gte=0, total__gte=0), name="invoice_item_values_valid"),
        ]


class Payment(models.Model):
    """Payment record against an invoice. Multiple payments allowed (partial payments)."""
    invoice         = models.ForeignKey(Invoice, on_delete=models.PROTECT,
                                        related_name="payments")
    amount          = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode    = models.CharField(max_length=50)
    transaction_ref = models.CharField(max_length=100, blank=True)
    recorded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments_recorded")
    paid_at         = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table  = "payment"
        constraints = [
            models.CheckConstraint(check=models.Q(amount__gt=0), name="payment_amount_positive"),
            models.UniqueConstraint(fields=["invoice", "transaction_ref"], condition=~models.Q(transaction_ref=""),
                                    name="uniq_payment_reference_per_invoice"),
        ]

    def __str__(self):
        return f"₹{self.amount} via {self.payment_mode} for {self.invoice.invoice_number}"
