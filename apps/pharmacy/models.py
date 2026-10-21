"""apps/pharmacy/models.py"""

from django.db import models
from apps.hospital_setup.models import StaffUser
from apps.hospital_setup.models import Branch
from apps.opd.models import HospitalPatient
from apps.opd.models import PrescriptionItem


class Drug(models.Model):
    """Hospital drug catalog. Hospital-managed."""
    name        = models.CharField(max_length=200)
    generic_name= models.CharField(max_length=200, blank=True)
    drug_code   = models.CharField(max_length=50, blank=True)
    form        = models.CharField(max_length=50, default="Tablet")
    strength    = models.CharField(max_length=50, blank=True)   # e.g. "500mg"
    unit        = models.CharField(max_length=20, default="mg")
    # Reference selling price — pharmacy.Stock.mrp (set per received batch)
    default_mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "drug"
        ordering  = ["name"]
        constraints = [models.UniqueConstraint(fields=["drug_code"], condition=~models.Q(drug_code=""), name="uniq_drug_code")]

    def __str__(self):
        return f"{self.name} {self.strength}"


class Stock(models.Model):
    """Current inventory for a drug at a branch."""
    drug            = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name="stocks")
    branch          = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="stocks")
    batch_number    = models.CharField(max_length=50, blank=True)
    expiry_date     = models.DateField(null=True, blank=True)
    quantity        = models.IntegerField(default=0)   # current quantity
    reorder_level   = models.PositiveIntegerField(default=10)
    unit_cost       = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    mrp             = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "stock"
        constraints = [
            models.UniqueConstraint(fields=["drug", "branch", "batch_number"], name="uniq_stock_drug_branch_batch"),
            models.CheckConstraint(check=models.Q(quantity__gte=0), name="stock_quantity_not_negative"),
        ]

    def __str__(self):
        return f"{self.drug.name} @ {self.branch.name} — qty:{self.quantity}"


class StockTransaction(models.Model):
    """Audit trail for every stock movement."""
    TXN_TYPE_CHOICES = [
        ("purchase",  "Purchase"),
        ("dispense",  "Dispense"),
        ("return",    "Return"),
        ("expiry",    "Expiry Write-off"),
        ("adjustment","Adjustment"),
    ]

    stock           = models.ForeignKey(Stock, on_delete=models.PROTECT,
                                        related_name="transactions")
    txn_type        = models.CharField(max_length=20, choices=TXN_TYPE_CHOICES)
    quantity_change = models.IntegerField()   # + for in, - for out
    quantity_before = models.IntegerField()
    quantity_after  = models.IntegerField()
    reference_type  = models.CharField(max_length=50, blank=True)   # "Dispense", "Purchase", etc.
    notes           = models.TextField(blank=True)
    recorded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_transactions")
    recorded_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "stock_transaction"
        ordering  = ["-recorded_at"]
        constraints = [
            models.CheckConstraint(check=models.Q(quantity_after=models.F("quantity_before") + models.F("quantity_change")),
                                   name="stock_transaction_adds_up"),
        ]


class Dispense(models.Model):
    """Drug dispensing record linked to a prescription item."""
    prescription_item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT,
                                          related_name="dispenses")
    stock           = models.ForeignKey(Stock, on_delete=models.PROTECT, related_name="dispenses")
    quantity        = models.PositiveIntegerField()
    dispensed_by    = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="dispenses_made", limit_choices_to={"role": "pharmacist"})
    dispensed_at    = models.DateTimeField(auto_now_add=True)
    notes           = models.TextField(blank=True)

    class Meta:
        db_table  = "dispense"
        constraints = [models.CheckConstraint(check=models.Q(quantity__gt=0), name="dispense_quantity_positive")]


class MedicationDoseLog(models.Model):
    """Inpatient medication dose administration log."""
    STATUS_CHOICES = [
        ("given",   "Given"),
        ("skipped", "Skipped"),
        ("refused", "Refused"),
    ]

    prescription_item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT,
                                          related_name="dose_logs")
    patient         = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT, related_name="dose_logs")
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="given")
    administered_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="doses_administered", limit_choices_to={"role": "nurse"})
    administered_at = models.DateTimeField()
    notes           = models.TextField(blank=True)

    class Meta:
        db_table  = "medication_dose_log"
        ordering  = ["-administered_at"]
