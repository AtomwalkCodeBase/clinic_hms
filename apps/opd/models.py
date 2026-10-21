"""Hospital DB — OPD domain models."""

import uuid
from django.db import models
from apps.hospital_setup.models import Branch
from django.utils.functional import cached_property


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

    # Was a fixed choices= list — now hospital-configurable via
    TYPE_OPD = "opd"
    TYPE_FOLLOWUP = "followup"
    TYPE_EMERGENCY = "emergency"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The hospital's own patient (by its uuid; the code reads and writes it as patient_id). The awpid is the person across hospitals:
    patient = models.ForeignKey("opd.HospitalPatient", to_field="uuid", db_column="patient_id",
                                on_delete=models.CASCADE, related_name="appointments")
    patient_awpid = models.CharField(max_length=30, db_index=True)
    doctor_user_id = models.UUIDField(db_index=True)       # atomwalk_user.id
    doctor_name = models.CharField(max_length=255)
    # Nullable: existing rows predate this field. Multi-branch hospitals should
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="appointments")

    appointment_type = models.CharField(max_length=15, default=TYPE_OPD)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)

    scheduled_date = models.DateField()
    scheduled_time = models.TimeField(null=True, blank=True)
    token_number = models.IntegerField(null=True, blank=True)

    # Denormalized room/floor — resolved once at booking time from
    room = models.ForeignKey("hospital_setup.Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="appointments")
    room_name = models.CharField(max_length=100, blank=True)
    floor = models.CharField(max_length=30, blank=True)

    # Timing
    checked_in_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    chief_complaint = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Captured at booking time (patient portal, or front desk on the patient's
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
        db_table = "appointment"
        indexes = [
            models.Index(fields=["scheduled_date", "doctor_user_id"]),
            models.Index(fields=["patient_id", "scheduled_date"]),
            models.Index(fields=["status", "scheduled_date"]),
        ]
        ordering = ["scheduled_date", "token_number"]

    def __str__(self):
        return f"Appt #{self.token_number} — {self.patient_awpid} ({self.status})"

    @cached_property
    def vitals(self):
        """This visit's vitals (apps/vitals.py), or None. A list of appointments loads them in one go with attach_vitals()."""
        from apps.documents.lib_vitals import visit_vitals
        return visit_vitals(self.id)


class OPDEncounter(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SIGNED = "signed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SIGNED, "Signed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE, related_name="encounter")
    patient = models.ForeignKey("opd.HospitalPatient", to_field="uuid", db_column="patient_id",
                                on_delete=models.PROTECT, related_name="encounters")
    doctor_user_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)

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

    # Nurse-mediated follow-up booking — a doctor deciding "book this
    followup_ask_nurse = models.BooleanField(default=False)
    followup_nurse_note = models.CharField(max_length=255, blank=True)
    followup_nurse_requested_at = models.DateTimeField(null=True, blank=True)
    followup_nurse_booked = models.BooleanField(default=False)
    followup_nurse_booked_at = models.DateTimeField(null=True, blank=True)

    # Referrals
    referred_to = models.CharField(max_length=255, blank=True)
    referral_notes = models.TextField(blank=True)

    signed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opd_encounter"
        indexes = [models.Index(fields=["doctor_user_id", "status"])]
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


class PatientChoiceFields(models.Model):
    """Where the patient gets a prescribed item done (in the hospital or outside) and how it is paid: shared by prescriptions and lab requests."""
    CHOICE_PENDING = "pending"
    CHOICE_IN_HOUSE = "in_house"
    CHOICE_OUTSIDE = "outside"
    CHOICE_CHOICES = [
        (CHOICE_PENDING, "Pending"),
        (CHOICE_IN_HOUSE, "In-House"),
        (CHOICE_OUTSIDE, "Outside"),
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

    patient_choice = models.CharField(max_length=10, choices=CHOICE_CHOICES, default=CHOICE_PENDING)
    payment_status = models.CharField(max_length=15, choices=PAYMENT_STATUS_CHOICES, default=PAY_UNPAID)
    choice_made_by = models.CharField(max_length=10, choices=CHOICE_MADE_BY_CHOICES, blank=True)
    choice_made_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class Prescription(PatientChoiceFields):
    STATUS_ACTIVE = "active"
    STATUS_DISPENSED = "dispensed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_DISPENSED, "Dispensed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    PAY_ONLINE = "pay_online"
    PAY_AT_PHARMACY = "pay_at_pharmacy"
    PAYMENT_PREFERENCE_CHOICES = [
        (PAY_ONLINE, "Pay Online"),
        (PAY_AT_PHARMACY, "Pay at Pharmacy"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.OneToOneField(OPDEncounter, on_delete=models.CASCADE, related_name="prescription")
    patient = models.ForeignKey("opd.HospitalPatient", to_field="uuid", db_column="patient_id",
                                on_delete=models.PROTECT, related_name="prescriptions")
    doctor_user_id = models.UUIDField(db_index=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.TextField(blank=True)
    dispensed_at = models.DateTimeField(null=True, blank=True)

    # Human-readable, sequential, quotable-over-the-counter token — NNTM
    rx_number = models.CharField(max_length=30, unique=True, null=True, blank=True)

    payment_preference = models.CharField(max_length=15, choices=PAYMENT_PREFERENCE_CHOICES, blank=True)

    # Set on first dispense against this prescription (see
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="+")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opd_prescription"
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
    # Optional link back to the pharmacist-maintained catalog (apps.pharmacy.Drug).
    drug = models.ForeignKey("pharmacy.Drug", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="+")
    drug_name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255, blank=True)
    dosage = models.CharField(max_length=50)          # e.g. "500mg", "1 tablet"
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    route = models.CharField(max_length=15, choices=ROUTE_CHOICES, default="oral")
    duration_days = models.IntegerField(null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    instructions = models.TextField(blank=True)       # e.g. "Take after food"

    class Meta:
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
        db_table = "prescription_favourite"
        constraints = [models.UniqueConstraint(fields=["doctor_user_id", "name"], name="uniq_favourite_doctor_name")]


# Hospital patients: the hospital's own record of a patient, and the allergies noted here

class HospitalPatient(models.Model):
    """Per-hospital patient record."""
    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]
    PAYER_CHOICES  = [("self", "Self Pay"), ("insurance", "Insurance"), ("corporate", "Corporate")]

    uuid            = models.UUIDField(default=uuid.uuid4, unique=True)
    awpid           = models.CharField(max_length=30, unique=True)
    uhid            = models.CharField(max_length=20, unique=True)  # e.g. APL-000123
    branch          = models.ForeignKey(Branch, on_delete=models.PROTECT,
                                        related_name="patients")
    # Personal
    full_name       = models.CharField(max_length=200)
    date_of_birth   = models.DateField(null=True, blank=True)
    gender          = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    BLOOD_GROUP_CHOICES = [(g, g) for g in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")]
    blood_group     = models.CharField(max_length=5, choices=BLOOD_GROUP_CHOICES, blank=True)
    marital_status  = models.CharField(max_length=20, blank=True)
    nationality     = models.CharField(max_length=50, blank=True, default="Indian")
    occupation      = models.CharField(max_length=100, blank=True)

    # Contact
    mobile          = models.CharField(max_length=15, blank=True)  # plain per-hospital (DPDP: no plain mobile in Atomwalk)
    alternate_mobile= models.CharField(max_length=15, blank=True)
    email           = models.EmailField(blank=True)
    address_line1   = models.CharField(max_length=255, blank=True)
    city            = models.CharField(max_length=100, blank=True)
    state           = models.CharField(max_length=100, blank=True)
    pincode         = models.CharField(max_length=10, blank=True)

    # Dependent patients (children, or anyone with no mobile of their own). WHO the guardian is and how they are
    is_dependent        = models.BooleanField(default=False)
    guardian_name        = models.CharField(max_length=200, blank=True)
    guardian_mobile       = models.CharField(max_length=15, blank=True)

    # Emergency contact
    emergency_contact_name     = models.CharField(max_length=100, blank=True)
    emergency_contact_phone    = models.CharField(max_length=15, blank=True)
    emergency_contact_relation = models.CharField(max_length=50, blank=True)

    # Insurance / payment
    payer_type         = models.CharField(max_length=20, choices=PAYER_CHOICES, default="self")
    insurance_provider = models.CharField(max_length=200, blank=True)
    policy_number      = models.CharField(max_length=100, blank=True)
    tpa_name           = models.CharField(max_length=200, blank=True)

    # DPDP consent (Digital Personal Data Protection Act 2023) — consent to
    dpdp_consent_captured = models.BooleanField(default=False)
    dpdp_consent_at       = models.DateTimeField(null=True, blank=True)

    # HIE consent — separate from the above: specifically, the patient
    hie_consent_given = models.BooleanField(default=False)
    hie_consent_at    = models.DateTimeField(null=True, blank=True)

    preferred_language = models.CharField(max_length=10, default="en")
    registered_at   = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    # ── Emergency / unidentified patient intake ──────────────────────────
    IDENTITY_CONFIRMED   = "confirmed"
    IDENTITY_PROVISIONAL = "provisional"
    IDENTITY_STATUS_CHOICES = [
        (IDENTITY_CONFIRMED, "Confirmed"),
        (IDENTITY_PROVISIONAL, "Provisional"),
    ]
    ARRIVAL_AMBULANCE   = "ambulance"
    ARRIVAL_BROUGHT_IN  = "brought_in"
    ARRIVAL_POLICE_CASE = "police_case"
    ARRIVAL_WALK_IN_UNRESPONSIVE = "walk_in_unresponsive"
    ARRIVAL_OTHER       = "other"
    ARRIVAL_CHANNEL_CHOICES = [
        (ARRIVAL_AMBULANCE, "Ambulance"),
        (ARRIVAL_BROUGHT_IN, "Brought in"),
        (ARRIVAL_POLICE_CASE, "Police case"),
        (ARRIVAL_WALK_IN_UNRESPONSIVE, "Walk-in, unresponsive"),
        (ARRIVAL_OTHER, "Other"),
    ]

    identity_status = models.CharField(max_length=12, choices=IDENTITY_STATUS_CHOICES, default=IDENTITY_CONFIRMED)
    # Mirrors ipd.AdmissionReferral.is_mlc, but at the patient level — an
    is_mlc          = models.BooleanField(default=False)
    arrival_channel = models.CharField(max_length=25, choices=ARRIVAL_CHANNEL_CHOICES, blank=True)
    # e.g. "Unknown Male, approx. 30yrs" — shown instead of full_name until
    placeholder_label = models.CharField(max_length=200, blank=True)
    # Auto-logged reason when DPDP/HIE consent is skipped under the
    consent_deferred_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table  = "hospital_patients"

    @property
    def guardian_link(self):
        """The atomwalk's PatientRelationship for this dependent (their primary guardian), or None."""
        if not self.is_dependent:
            return None
        if not hasattr(self, "_guardian_link"):
            from apps.patients.models import PatientRelationship
            self._guardian_link = (PatientRelationship.objects.using("default").select_related("guardian")
                                   .filter(dependent__awpid=self.awpid).order_by("id").first())
        return self._guardian_link

    @property
    def guardian_awpid(self):
        return self.guardian_link.guardian.awpid if self.guardian_link else ""

    @property
    def guardian_relation(self):
        return self.guardian_link.relationship if self.guardian_link else ""

    def __str__(self):
        return f"{self.uhid} — {self.full_name}"


class Allergy(models.Model):
    """Patient allergy record. On create/update a Django signal writes a"""
    SEVERITY_CHOICES = [
        ("mild",     "Mild"),
        ("moderate", "Moderate"),
        ("severe",   "Severe"),
    ]

    patient     = models.ForeignKey(HospitalPatient, on_delete=models.CASCADE,
                                    related_name="allergies")
    substance   = models.CharField(max_length=200)
    reaction    = models.TextField(blank=True)
    severity    = models.CharField(max_length=20, choices=SEVERITY_CHOICES, blank=True)
    is_active   = models.BooleanField(default=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey("hospital_setup.StaffUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="allergies_recorded")

    class Meta:
        db_table  = "allergy"

    def __str__(self):
        return f"{self.patient.uhid} — {self.substance}"
