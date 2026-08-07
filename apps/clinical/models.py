"""
apps/clinical/models.py
-----------------------
FHIR R4 aligned clinical models.

  Encounter      → FHIR Encounter
  Vital          → FHIR Observation (encounter nullable for home vitals)
  Diagnosis      → FHIR Condition (clinical_status added for R4 compliance)
  Allergy        → in apps/patients/models.py (owned by patient, not encounter)
  FollowUp       → referral/follow-up instructions
  ClinicalDocument → uploaded PDFs, scan reports, external records

On encounter.close() signal:
  - Vitals, Diagnoses written to registry shared HIE tables (sanitized, no tenant info)
"""

from django.db import models
from apps.org.models import StaffUser, Branch, Department
from apps.patients.models import Patient


class Encounter(models.Model):
    """
    One clinical visit. Maps to FHIR Encounter.
    Closing an encounter triggers the HIE write-through signal.
    """
    STATUS_CHOICES = [
        ("open",   "Open"),
        ("closed", "Closed"),
    ]

    patient         = models.ForeignKey(Patient, on_delete=models.PROTECT,
                                        related_name="encounters")
    doctor          = models.ForeignKey(StaffUser, on_delete=models.PROTECT,
                                        related_name="encounters",
                                        limit_choices_to={"role": "doctor"})
    branch          = models.ForeignKey(Branch, on_delete=models.PROTECT)
    department      = models.ForeignKey(Department, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    encounter_date  = models.DateField()
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open", db_index=True)
    chief_complaint = models.TextField(blank=True)
    history         = models.TextField(blank=True)   # history of presenting illness
    examination_notes = models.TextField(blank=True)
    advice          = models.TextField(blank=True)
    closed_at       = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "clinical"
        db_table  = "encounter"

    def __str__(self):
        return f"{self.patient.uhid} — {self.encounter_date} ({self.status})"


class Vital(models.Model):
    """
    Patient vitals. Maps to FHIR Observation.
    encounter is nullable to support home vitals (patient app).
    All numeric fields nullable — only measured values are set.
    source: clinic (nurse-recorded) or home (patient app).
    """
    SOURCE_CHOICES = [("clinic", "Clinic"), ("home", "Home")]

    patient         = models.ForeignKey(Patient, on_delete=models.PROTECT,
                                        related_name="vitals")
    encounter       = models.ForeignKey(Encounter, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="vitals")
    recorded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL,
                                        null=True, blank=True)
    source          = models.CharField(max_length=10, choices=SOURCE_CHOICES,
                                       default="clinic")
    recorded_at     = models.DateTimeField()

    # Vitals (LOINC aligned — see core/utils/fhir.py)
    bp_systolic     = models.SmallIntegerField(null=True, blank=True)   # mm[Hg]
    bp_diastolic    = models.SmallIntegerField(null=True, blank=True)   # mm[Hg]
    pulse_rate      = models.SmallIntegerField(null=True, blank=True)   # /min
    spo2            = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # %
    temperature     = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # Cel
    weight_kg       = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm       = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    resp_rate       = models.SmallIntegerField(null=True, blank=True)   # /min
    blood_sugar_mgdl= models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    notes           = models.TextField(blank=True)

    class Meta:
        app_label = "clinical"
        db_table  = "vital"
        ordering  = ["-recorded_at"]

    def __str__(self):
        return f"{self.patient.uhid} vitals @ {self.recorded_at}"


class Diagnosis(models.Model):
    """
    Clinical diagnosis. Maps to FHIR Condition.
    clinical_status is required by FHIR R4.
    """
    CLINICAL_STATUS_CHOICES = [
        ("active",   "Active"),
        ("resolved", "Resolved"),
        ("inactive", "Inactive"),
    ]

    encounter       = models.ForeignKey(Encounter, on_delete=models.CASCADE,
                                        related_name="diagnoses")
    icd10_code      = models.CharField(max_length=20, blank=True)
    description     = models.TextField()
    clinical_status = models.CharField(max_length=20, choices=CLINICAL_STATUS_CHOICES,
                                       default="active")
    is_primary      = models.BooleanField(default=False)
    onset_date      = models.DateField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "clinical"
        db_table  = "diagnosis"

    def __str__(self):
        return f"{self.icd10_code or 'No ICD'} — {self.description[:40]}"


class FollowUp(models.Model):
    """
    Follow-up or referral instruction from an encounter.
    """
    encounter       = models.ForeignKey(Encounter, on_delete=models.CASCADE,
                                        related_name="followups")
    follow_up_date  = models.DateField(null=True, blank=True)
    instructions    = models.TextField(blank=True)
    referral_to     = models.CharField(max_length=200, blank=True)  # department or specialist
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "clinical"
        db_table  = "follow_up"


class ClinicalDocument(models.Model):
    """
    Uploaded clinical document — external report, scan, discharge summary, etc.
    file_url is the stored file path or S3 key; access is scoped to this tenant.
    """
    TYPE_CHOICES = [
        ("report",    "Report"),
        ("scan",      "Scan / Imaging"),
        ("discharge", "Discharge Summary"),
        ("referral",  "Referral Letter"),
        ("other",     "Other"),
    ]

    patient         = models.ForeignKey(Patient, on_delete=models.PROTECT,
                                        related_name="documents")
    encounter       = models.ForeignKey(Encounter, on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name="documents")
    document_type   = models.CharField(max_length=20, choices=TYPE_CHOICES, default="other")
    title           = models.CharField(max_length=200)
    file_url        = models.TextField()    # S3 key or local path
    uploaded_by     = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True)
    uploaded_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "clinical"
        db_table  = "clinical_document"

    def __str__(self):
        return f"{self.patient.uhid} — {self.title}"
