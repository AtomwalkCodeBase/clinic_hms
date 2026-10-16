"""
apps/pharmacy/models.py
-----------------------
Tables: Stock, StockTransaction, Dispense, MedicationDoseLog
feat_pharmacy gate enforced at API view level.

Dispense.prescription_item points at apps.opd.PrescriptionItem — the live
model doctors actually write to during a consultation (apps.opd.Prescription
was previously never touched by Dispense, which pointed at the OLD/legacy
apps.pharmacy.Prescription instead; nothing in the live OPD flow ever
created rows there, so a prescription written by a doctor would never reach
the pharmacist's dispensing queue at all — see PendingPrescriptionsView).
"""

from django.db import models
from apps.staff.models import StaffUser
from apps.facility.models import Branch
from apps.hospital_patients.models import HospitalPatient
from apps.opd.models import PrescriptionItem


class Drug(models.Model):
    """
    Hospital drug catalog. Hospital-managed.
    drug_code is the internal code (not a standard code — optional).

    form is free text (validated against apps.billing.OptionList's
    list_type="drug_form" rows in the frontend/serializer layer, not a
    DB-level choices= constraint — see OptionList's docstring for why).
    """
    name        = models.CharField(max_length=200)
    generic_name= models.CharField(max_length=200, blank=True)
    drug_code   = models.CharField(max_length=50, blank=True)
    form        = models.CharField(max_length=50, default="Tablet")
    strength    = models.CharField(max_length=50, blank=True)   # e.g. "500mg"
    unit        = models.CharField(max_length=20, default="mg")
    # Reference selling price — pharmacy.Stock.mrp (set per received batch)
    # is what actually drives dispense billing, since real procurement price
    # can shift batch to batch. This is just the catalog-level default so
    # (a) the pharmacist can see "what does this drug cost" without digging
    # into Stock, and (b) the Receive Stock form can prefill from it instead
    # of relying on whoever's receiving stock to remember to type a price —
    # still overridable per batch.
    default_mrp = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "drug"
        ordering  = ["name"]

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
        unique_together = [("drug", "branch", "batch_number")]

    def __str__(self):
        return f"{self.drug.name} @ {self.branch.name} — qty:{self.quantity}"


class StockTransaction(models.Model):
    """
    Audit trail for every stock movement.
    quantity_change is positive (in) or negative (out).
    """
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
    reference_id    = models.IntegerField(null=True, blank=True)
    notes           = models.TextField(blank=True)
    recorded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True)
    recorded_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "stock_transaction"
        ordering  = ["-recorded_at"]


class Dispense(models.Model):
    """Drug dispensing record linked to a prescription item."""
    prescription_item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT,
                                          related_name="dispenses")
    stock           = models.ForeignKey(Stock, on_delete=models.PROTECT)
    quantity        = models.PositiveIntegerField()
    dispensed_by    = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True,
                                        limit_choices_to={"role": "pharmacist"})
    dispensed_at    = models.DateTimeField(auto_now_add=True)
    notes           = models.TextField(blank=True)

    class Meta:
        db_table  = "dispense"


class MedicationDoseLog(models.Model):
    """
    Inpatient medication dose administration log.
    Recorded by nursing staff per prescription item.
    """
    STATUS_CHOICES = [
        ("given",   "Given"),
        ("skipped", "Skipped"),
        ("refused", "Refused"),
    ]

    prescription_item = models.ForeignKey(PrescriptionItem, on_delete=models.PROTECT,
                                          related_name="dose_logs")
    patient         = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="given", db_index=True)
    administered_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True,
                                        limit_choices_to={"role": "nurse"})
    administered_at = models.DateTimeField()
    notes           = models.TextField(blank=True)

    class Meta:
        db_table  = "medication_dose_log"
        ordering  = ["-administered_at"]
