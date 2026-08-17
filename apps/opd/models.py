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

    # Denormalized room/floor — resolved once at booking time from
    # org.RoomAssignment (doctor + day-of-week + time) and baked in here so
    # front desk/queue/patient screens can show "Room 204, Floor 2" without
    # a live lookup, and so the room shown never changes retroactively if
    # the hospital edits its room assignments later. Nullable: rooms are
    # opt-in — a hospital that hasn't set any up just gets no room shown,
    # nothing else breaks. Plain int/text, not a real FK — org.Room lives in
    # the same tenant DB but in a different app; matches this codebase's
    # existing convention of not adding cross-app FKs (see Tenant.
    # active_vaccination_schedule_id for the same reasoning).
    room_id = models.IntegerField(null=True, blank=True)
    room_name = models.CharField(max_length=100, blank=True)
    floor = models.CharField(max_length=30, blank=True)

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

    # Mirrors apps.lab.models.LabRequest's patient_choice/payment_preference/
    # payment_status/choice_made_by pattern — same shape, same portal-side
    # semantics, so a patient sees a consistent "buy in-house or take it
    # elsewhere" flow for both labs and prescriptions.
    CHOICE_PENDING = "pending"
    CHOICE_IN_HOUSE = "in_house"
    CHOICE_OUTSIDE = "outside"
    CHOICE_CHOICES = [
        (CHOICE_PENDING, "Pending"),
        (CHOICE_IN_HOUSE, "In-House"),
        (CHOICE_OUTSIDE, "Outside"),
    ]
    PAY_ONLINE = "pay_online"
    PAY_AT_PHARMACY = "pay_at_pharmacy"
    PAYMENT_PREFERENCE_CHOICES = [
        (PAY_ONLINE, "Pay Online"),
        (PAY_AT_PHARMACY, "Pay at Pharmacy"),
    ]
    PAY_UNPAID = "unpaid"
    PAY_PENDING_ONLINE = "pending_online"
    PAY_PAID = "paid"
    PAYMENT_STATUS_CHOICES = [
        (PAY_UNPAID, "Unpaid"),
        (PAY_PENDING_ONLINE, "Pending Online Payment"),
        (PAY_PAID, "Paid"),
    ]
    CHOICE_MADE_BY_CHOICES = [("patient", "Patient"), ("nurse", "Nurse")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.OneToOneField(OPDEncounter, on_delete=models.CASCADE, related_name="prescription")
    patient_id = models.UUIDField(db_index=True)
    doctor_user_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    notes = models.TextField(blank=True)
    dispensed_at = models.DateTimeField(null=True, blank=True)

    # Human-readable, sequential, quotable-over-the-counter token — NNTM
    # entity="prescription" (prefix "RX-", already seeded per branch, see
    # apps/org/views.py's NEXT_NUMBER_DEFAULTS). Generated once at creation
    # in PrescriptionCreateView. Blank on the very few rows that predate
    # this field; never reused/regenerated after that so it stays a stable
    # reference the patient can quote at the pharmacy counter.
    rx_number = models.CharField(max_length=30, unique=True, null=True, blank=True)

    patient_choice = models.CharField(max_length=10, choices=CHOICE_CHOICES, default=CHOICE_PENDING)
    payment_preference = models.CharField(max_length=15, choices=PAYMENT_PREFERENCE_CHOICES, blank=True)
    payment_status = models.CharField(max_length=15, choices=PAYMENT_STATUS_CHOICES, default=PAY_UNPAID)
    choice_made_by = models.CharField(max_length=10, choices=CHOICE_MADE_BY_CHOICES, blank=True)
    choice_made_at = models.DateTimeField(null=True, blank=True)

    # Set on first dispense against this prescription (see
    # apps/pharmacy/views.py::DispenseView) — every subsequent dispense of
    # another item on the same Rx adds line items to this same invoice
    # instead of creating a duplicate. Priced from Stock.mrp (sale price),
    # not Stock.unit_cost (purchase cost) — see InvoiceItem creation there.
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="+")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "opd"
        db_table = "opd_prescription"
        indexes = [models.Index(fields=["patient_id"]), models.Index(fields=["rx_number"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Rx {self.rx_number or self.id} — {self.status}"


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
    # Optional link back to the pharmacist-maintained catalog (apps.prescriptions.Drug).
    # Nullable — a doctor can still type a drug that isn't in the catalog yet.
    # SET_NULL rather than PROTECT: deactivating/removing a catalog entry must
    # never block or corrupt a prescription already written against it.
    drug = models.ForeignKey("prescriptions.Drug", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="+")
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
