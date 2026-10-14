"""
apps/hospital_patients/pediatrics/models.py
-------------------------------------------
The hospital-side birth history. The shared pediatric tables (vaccinations, milestones, schedules) live in apps/atomwalk/models.
"""
from django.db import models


class BirthHistory(models.Model):
    """
    A child's birth history, one row per patient. Front desk can capture it at registration and the pediatrician can add
    or correct it later. recorded_by / updated_by are StaffUser ids (plain numbers, not links).
    """
    DELIVERY_NORMAL   = "normal"
    DELIVERY_C_SECTION = "c_section"
    DELIVERY_ASSISTED  = "assisted"      # forceps / vacuum
    DELIVERY_UNKNOWN   = "unknown"
    DELIVERY_MODE_CHOICES = [
        (DELIVERY_NORMAL,    "Normal Vaginal Delivery"),
        (DELIVERY_C_SECTION, "C-Section"),
        (DELIVERY_ASSISTED,  "Assisted (Forceps/Vacuum)"),
        (DELIVERY_UNKNOWN,   "Unknown"),
    ]

    patient = models.OneToOneField("hospital_patients.HospitalPatient", on_delete=models.CASCADE,
                                   related_name="birth_history")

    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_weight_kg        = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    delivery_mode           = models.CharField(max_length=12, choices=DELIVERY_MODE_CHOICES, blank=True)
    multiple_birth          = models.CharField(max_length=50, blank=True)   # free text: "twin", "triplet A of 3"

    nicu_admission = models.BooleanField(default=False)
    nicu_days       = models.PositiveSmallIntegerField(null=True, blank=True)
    birth_complications = models.TextField(blank=True)  # e.g. jaundice, birth asphyxia
    congenital_conditions = models.TextField(blank=True)

    apgar_score_1min  = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_score_5min  = models.PositiveSmallIntegerField(null=True, blank=True)

    notes = models.TextField(blank=True)

    recorded_by = models.IntegerField(null=True, blank=True)  # StaffUser.id — who first captured this
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_by  = models.IntegerField(null=True, blank=True)  # StaffUser.id — who last edited this
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hospital_patients"
        db_table  = "birth_history"

    def __str__(self):
        return f"{self.patient.uhid} — birth history"
