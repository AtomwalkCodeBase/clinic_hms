"""Hospital database: the price list (billing_item) and invoices (invoice) with their lines and payments kept on the invoice row as JSON.

Same conventions as hospital_setup/models.py. Deliberate exceptions: Invoice.status and BillingItem.category are plain text checked against OptionList, because each hospital edits those lists; an invoice is never deleted once it exists (PROTECT on its patient and branch).

Invoice.lines   [{"item_id", "description", "quantity", "unit_price", "tax_rate", "tax_inclusive", "total"}]   amounts as strings
Invoice.payments [{"payment_id", "amount", "payment_mode", "transaction_ref", "recorded_by_id", "paid_at"}]  payment_id counts 1, 2, 3 within the invoice
"""

from django.conf import settings
from django.db import models
from apps.hospital_setup.models import StaffUser
from apps.hospital_setup.models import Branch, BranchDepartment
from apps.hospital_patients.models import HospitalPatient



class Invoice(models.Model):
    """A bill for one patient at one branch, with its lines, payments and totals."""
    # Kept as plain constants (not a `choices=` list) for internal logic to
    STATUS_DRAFT          = "draft"
    STATUS_ISSUED         = "issued"
    STATUS_PAID           = "paid"
    STATUS_PARTIALLY_PAID = "partially_paid"
    STATUS_CANCELLED      = "cancelled"

    invoice_number  = models.CharField(max_length=30, unique=True)
    patient         = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT,
                                        related_name="p_invoices")
    branch          = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="b_invoices")
    status          = models.CharField(max_length=20, default=STATUS_DRAFT)  # validated against OptionList(list_type="invoice_status")
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    lines           = models.JSONField(default=list, blank=True)
    payments        = models.JSONField(default=list, blank=True)
    notes           = models.TextField(blank=True)
    created_by      = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="u_invoices_created")
    issued_at       = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    tax_inclusive    = models.BooleanField(default=False)    # unit_price already contains tax_rate; False adds it on top
        
    class Meta:
        db_table  = "invoice"
        constraints = [
            models.CheckConstraint(
                check=models.Q(subtotal__gte=0, tax_amount__gte=0, discount_amount__gte=0, total_amount__gte=0, paid_amount__gte=0),
                name="invoice_amounts_not_negative"),
        ]

    def __str__(self):
        return f"{self.invoice_number} — {self.patient.uhid} ({settings.CURRENCY_SYMBOL}{self.total_amount})"


class BillingItem(models.Model):
    """Hospital-configured price list for services, procedures, etc."""
    bill          = models.ForeignKey(Invoice, on_delete=models.CASCADE, null=True, blank=True, related_name="i_items")    # set: a line on that invoice; empty: a price-list entry
    name          = models.CharField(max_length=200)
    code          = models.CharField(max_length=30, blank=True)
    category      = models.CharField(max_length=50, blank=True)    # validated against OptionList(list_type="service_category")
    description   = models.CharField(max_length=100, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    tax_rate   = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_inclusive = models.BooleanField(default=False)
    is_price_editable = models.BooleanField(default=True)    # False: the invoice line must use unit_price as listed
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "billing_item"
        ordering  = ["name"]
        constraints = [models.UniqueConstraint(fields=["code"], condition=~models.Q(code="") & models.Q(bill__isnull=True), name="uniq_billing_item_code")]

    def __str__(self):
        return f"{self.name} ({settings.CURRENCY_SYMBOL}{self.unit_price})"

