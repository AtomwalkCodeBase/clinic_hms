"""Hospital database: the price list (billing_item) and invoices (invoice) with their lines and payments kept on the invoice row as JSON.

Same conventions as hospital_setup/models.py. Deliberate exceptions: Invoice.status and BillingItem.category are plain text checked against OptionList, because each hospital edits those lists; an invoice is never deleted once it exists (PROTECT on its patient and branch).

Invoice lines are BillingItem rows with `bill` set (related name i_items); a BillingItem with no `bill` is a price-list entry. `Invoice.lines` reads
and writes them as the list of dicts the API shows: [{"item_id", "description", "quantity", "unit_price", "tax_rate", "tax_inclusive", "total"}],
where item_id is the price-list entry the line came from.
Invoice.payments [{"payment_id", "amount", "payment_mode", "transaction_ref", "recorded_by_id", "paid_at"}]  payment_id counts 1, 2, 3 within the invoice
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from apps.hospital_setup.models import StaffUser
from apps.hospital_setup.models import Branch
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

    _pending_lines = None

    @property
    def lines(self):
        """The invoice's lines as dicts (see the module text). Lines set but not yet saved are returned as they were set."""
        if self._pending_lines is not None:
            return list(self._pending_lines)
        if self.pk is None:
            return []
        return [item.as_line() for item in self.i_items.all()]

    @lines.setter
    def lines(self, value):
        self._pending_lines = list(value)

    def save(self, *args, **kwargs):
        """Lines set on the invoice are written as BillingItem rows with it (replacing the old ones), also when `update_fields` names "lines"."""
        fields = kwargs.get("update_fields")
        if fields is not None:
            kwargs["update_fields"] = [f for f in fields if f != "lines"]
        super().save(*args, **kwargs)
        if self._pending_lines is not None:
            db = kwargs.get("using") or self._state.db
            BillingItem.objects.using(db).filter(bill=self).delete()
            BillingItem.objects.using(db).bulk_create([BillingItem.from_line(self, line) for line in self._pending_lines])
            self._pending_lines = None
            if hasattr(self, "_prefetched_objects_cache"):
                self._prefetched_objects_cache.pop("i_items", None)


class BillingItem(models.Model):
    """Hospital-configured price list for services, procedures, etc."""
    bill          = models.ForeignKey(Invoice, on_delete=models.CASCADE, null=True, blank=True, related_name="i_items")    # set: a line on that invoice; empty: a price-list entry
    name          = models.CharField(max_length=200)
    code          = models.CharField(max_length=30, blank=True)
    category      = models.CharField(max_length=50, blank=True)    # validated against OptionList(list_type="service_category")
    description   = models.CharField(max_length=100, blank=True)
    price_list_item = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="used_on_lines")    # a line: the entry it was priced from
    quantity      = models.PositiveIntegerField(default=1)    # a line's quantity; 1 on a price-list entry
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

    def as_line(self):
        """This row as an invoice line dict (see the module text)."""
        return {"item_id": self.price_list_item_id, "description": self.name, "quantity": self.quantity, "unit_price": str(self.unit_price),
                "tax_rate": str(self.tax_rate), "tax_inclusive": self.tax_inclusive, "total": str(self.unit_price * self.quantity)}

    @classmethod
    def from_line(cls, invoice, line):
        """An unsaved row for one invoice line dict."""
        return cls(bill=invoice, price_list_item_id=line.get("item_id"), name=(line.get("description") or "")[:200], quantity=int(line.get("quantity", 1)),
                   unit_price=Decimal(str(line.get("unit_price") or 0)), tax_rate=Decimal(str(line.get("tax_rate") or 0)),
                   tax_inclusive=bool(line.get("tax_inclusive", False)), is_price_editable=False)

