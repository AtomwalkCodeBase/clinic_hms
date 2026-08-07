"""
Tenant DB — OPD domain models.

Covers:
  - Appointment    : booking + queue state machine
  - OPDEncounter   : SOAP consultation notes
  - Prescription   : Rx header linked to encounter
  - PrescriptionItem: individual drug lines
  - PrescriptionFavourite: doctor's saved drug templates
  - Vitals         : recorded per encounter
"""

import uuid
from django.db import models


class Appointment(models.Model):
    STATUS_SCHEDULED    = "scheduled"
    STATUS_WAITING      = "waiting"
    STATUS_VITALS_DONE  = "vitals_done"
    STATUS_IN_PROGRESS  = "in_progress"
    STATUS_DONE         = "done"
    STATUS_CANCELLED    = "cancelled"
    STATUS_NO_SHOW      = "no_show"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED,   "Scheduled"),
        (STATUS_WAITING,     "Waiting"),
        (STATUS_VITALS_DONE, "Vitals Done"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_DONE,        "Done"),
        (STATUS_CANCELLED,   "Cancelled"),
        (STATUS_NO_SHOW,     "No Show"),
    ]

    TYPE_OPD = "opd"
    TYPE_FOLLOWUP = "followup"
    TYPE_EMERGENCY = "emergency"
    TYPE_CHOICES = [
        (TYPE_OPD, "OPD"),
        (TYPE_FOLLOWUP, "Follow-up"),
        (TYPE_EMERGENCY, "Emergency"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient_id = models.UUIDField(db_index=True)           # FK → patients.patient.id
    patient_awpid = models.CharField(max_length=30, db_index=True)
    doctor_user_id = models.UUIDField(db_index=True)       # registry_user.id
    doctor_name = models.CharField(max_length=255)
    # Nullable: existing rows predate this field. Multi-branch hospitals should
    # backfill from booked_by_user_id's branch before relying on this filter;
    # new bookings get it from the booking user automatically (see views.py).
    branch_id = models.IntegerField(null=True, blank=True, db_index=True)  # org.Branch.id (tenant DB)

    appointment_type = models.CharField(max_length=15, choices=TYPE_CHOICES, default=TYPE_OPD)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_SCHEDULED, db_index=True)

    scheduled_date = models.DateField(db_index=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    token_number = models.IntegerField(null=True, blank=True)

    # Timing
    checked_in_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    chief_complaint = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    booked_by_user_id = models.UUIDField(null=True, blank=True)

    # Captured at booking time (patient portal, or front desk on the patient's
    # behalf) so front desk knows whether to expect payment at check-in.
    # "pay_online" is not wired to a real payment gateway yet — see
    # PatientDoctorProfilePage.jsx; it's collected now so nothing needs to
    # migrate later once one exists.
    PAYMENT_PAY_AT_DESK = "pay_at_desk"
    PAYMENT_PAY_ONLINE  = "pay_online"
    PAYMENT_PREFERENCE_CHOICES = [
        (PAYMENT_PAY_AT_DESK, "Pay at Front Desk"),
        (PAYMENT_PAY_ONLINE,  "Pay Online"),
    ]
    payment_preference = models.CharField(
        max_length=15, choices=PAYMENT_PREFERENCE_CHOICES, default=PAYMENT_PAY_AT_DESK,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "opd"
        db_table = "appointment"
        indexes = [
            models.Index(fields=["scheduled_date", "doctor_user_id"]),
            models.Index(fields=["patient_id", "scheduled_date"]),
            models.Index(fields=["status", "scheduled_date"]),
        ]
        ordering = ["scheduled_date", "token_number"]

    def __str__(self):
        return f"Appt #{self.token_number} — {self.patient_awpid} ({self.status})"


class Vitals(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE, related_name="vitals")
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by_user_id = models.UUIDField(null=True, blank=True)

    # Core vitals
    systolic_bp      = models.IntegerField(null=True, blank=True)       # mmHg
    diastolic_bp     = models.IntegerField(null=True, blank=True)       # mmHg
    pulse_rate       = models.IntegerField(null=True, blank=True)       # bpm
    temperature      = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)  # °F
    spo2             = models.IntegerField(null=True, blank=True)        # %
    respiratory_rate = models.IntegerField(null=True, blank=True)       # /min
    weight_kg        = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    height_cm        = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    bmi              = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    blood_sugar_rbs  = models.IntegerField(null=True, blank=True)       # mg/dL random blood sugar
    nurse_notes      = models.TextField(blank=True)                     # nurse observations

    class Meta:
        app_label = "opd"
        db_table = "vitals"

    def save(self, *args, **kwargs):
        if self.weight_kg and self.height_cm and self.height_cm > 0:
            h_m = float(self.height_cm) / 100
            self.bmi = round(float(self.weight_kg) / (h_m ** 2), 1)
        super().save(*args, **kwargs)


class OPDEncounter(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SIGNED = "signed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SIGNED, "Signed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE, related_name="encounter")
    patient_id = models.UUIDField(db_index=True)
    doctor_user_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)

    # SOAP notes
    subjective = models.TextField(blank=True)    # Chief complaint + history
    objective = models.TextField(blank=True)     # Examination findings
    assessment = models.TextField(blank=True)    # Diagnosis / impression
    plan = models.TextField(blank=True)          # Treatment plan

    # ICD-10 diagnoses (list of {"code": "J06.9", "description": "Acute upper RTI"})
    diagnoses = models.JSONField(default=list, blank=True)

    # Investigations / orders
    investigations = models.TextField(blank=True)     # Free-text lab / radiology orders

    # Advice and follow-up
    advice_to_patient = models.TextField(blank=True)  # Discharge instructions
    follow_up_in_days = models.IntegerField(null=True, blank=True)  # Days until next visit

    # Referrals
    referred_to = models.CharField(max_length=255, blank=True)
    referral_notes = models.TextField(blank=True)

    # AI transcription (Phase 2)
    ai_transcript_job_id = models.CharField(max_length=100, blank=True)
    ai_transcript_text = models.TextField(blank=True)

    signed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "opd"
        db_table = "opd_encounter"
        indexes = [
            models.Index(fields=["patient_id"]),
            models.Index(fields=["doctor_user_id", "status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Encounter {self.id} [{self.status}]"

    def sign(self, using=None):
        from django.utils import timezone
        db = using or self._state.db
        self.status = self.STATUS_SIGNED
        self.signed_at = timezone.now()
        # Mark appointment as done
        self.appointment.status = Appointment.STATUS_DONE
        self.appointment.completed_at = timezone.now()
        self.appointment.save(using=db, update_fields=["status", "completed_at"])
        self.save(using=db)


class Prescription(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_DISPENSED = "dispensed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_DISPENSED, "Dispensed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.OneToOneField(OPDEncounter, on_delete=models.CASCADE, related_name="prescription")
    patient_id = models.UUIDField(db_index=True)
    doctor_user_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    notes = models.TextField(blank=True)
    dispensed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "opd"
        db_table = "opd_prescription"
        indexes = [models.Index(fields=["patient_id"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Rx {self.id} — {self.status}"


class PrescriptionItem(models.Model):
    FREQUENCY_CHOICES = [
        ("od", "Once Daily"),
        ("bd", "Twice Daily"),
        ("td", "Three Times Daily"),
        ("qid", "Four Times Daily"),
        ("sos", "As Needed"),
        ("stat", "Immediately"),
        ("nocte", "At Night"),
        ("mane", "In the Morning"),
    ]

    ROUTE_CHOICES = [
        ("oral", "Oral"),
        ("iv", "Intravenous"),
        ("im", "Intramuscular"),
        ("sc", "Subcutaneous"),
        ("topical", "Topical"),
        ("inhaled", "Inhaled"),
        ("rectal", "Rectal"),
        ("sublingual", "Sublingual"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    drug_name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255, blank=True)
    dosage = models.CharField(max_length=50)          # e.g. "500mg", "1 tablet"
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    route = models.CharField(max_length=15, choices=ROUTE_CHOICES, default="oral")
    duration_days = models.IntegerField(null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    instructions = models.TextField(blank=True)       # e.g. "Take after food"
    is_controlled = models.BooleanField(default=False)

    class Meta:
        app_label = "opd"
        db_table = "opd_prescription_item"

    def __str__(self):
        return f"{self.drug_name} {self.dosage} {self.frequency}"


class PrescriptionFavourite(models.Model):
    """Doctor's saved drug templates for quick Rx."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor_user_id = models.UUIDField(db_index=True)
    name = models.CharField(max_length=100)          # e.g. "Fever Bundle", "Diabetic Starter"
    items = models.JSONField(default=list)            # serialised PrescriptionItem fields
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "opd"
        db_table = "prescription_favourite"
        unique_together = [("doctor_user_id", "name")]
