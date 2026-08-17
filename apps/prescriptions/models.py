"""
apps/prescriptions/models.py
----------------------------
Tables: Drug (catalog), DrugFormType (configurable form list)

Prescription/PrescriptionItem used to live here too, but the live
doctor-consultation flow has only ever written prescriptions to
apps.opd.Prescription/PrescriptionItem (see apps/opd/views.py
PrescriptionCreateView) — these two were dead scaffolding with a routed
API nothing called (confirmed: zero references in frontend/src, and the
pharmacy dispensing-queue bug fixed earlier this session was caused by
pharmacy code pointing at these instead of the live opd models). Retired
as part of HMS-07c-1; see apps.clinical's module docstring for the sibling
Encounter/Vital/Diagnosis/FollowUp/ClinicalDocument retirement.
"""

from django.db import models


class DrugFormType(models.Model):
    """
    Configurable list of drug forms (Tablet, Capsule, Syrup, ...) — was
    previously a hardcoded Python FORM_CHOICES list on Drug itself, which
    meant a hospital could never add a form the original list didn't happen
    to include. Tenant-managed via the pharmacist's "Drug Form Setup"
    screen, same pattern as the Drug catalog itself.

    Drug.form stays a plain CharField (not a ForeignKey here) storing this
    row's `name` directly — avoids a data migration on existing Drug rows
    and keeps PrescriptionItem/serializers untouched; this table exists to
    drive the pick-list, not to enforce referential integrity on it.
    """
    name        = models.CharField(max_length=50, unique=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "prescriptions"
        db_table  = "drug_form_type"
        ordering  = ["name"]

    def __str__(self):
        return self.name


class Drug(models.Model):
    """
    Hospital drug catalog. Tenant-managed.
    drug_code is the internal code (not a standard code — optional).

    form is free text (validated against DrugFormType's configurable list
    in the frontend/serializer layer, not a DB-level choices= constraint —
    see DrugFormType's docstring for why).
    """
    name        = models.CharField(max_length=200)
    generic_name= models.CharField(max_length=200, blank=True)
    drug_code   = models.CharField(max_length=50, blank=True)
    form        = models.CharField(max_length=50, default="Tablet")
    strength    = models.CharField(max_length=50, blank=True)   # e.g. "500mg"
    unit        = models.CharField(max_length=20, default="mg")
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "prescriptions"
        db_table  = "drug"
        ordering  = ["name"]

    def __str__(self):
        return f"{self.name} {self.strength}"
