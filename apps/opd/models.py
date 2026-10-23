import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.functional import cached_property
from apps.hospital_setup.models import BranchDepartment, StaffBranchDepartment, StaffUser


class HospitalPatient(models.Model):
    uhid                    = models.CharField(max_length=20, unique=True)
    awpid                   = models.CharField(max_length=30, unique=True)
    dpdp_consent_captured   = models.BooleanField(default=False)
    dpdp_consent_at         = models.DateTimeField(null=True, blank=True)
    hie_consent_given       = models.BooleanField(default=False)
    hie_consent_at          = models.DateTimeField(null=True, blank=True)
    registered_at           = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "hospital_patients"
        constraints = [
            models.CheckConstraint(check=models.Q(dpdp_consent_captured=False) | models.Q(dpdp_consent_at__isnull=False), name="patient_dpdp_consent_is_dated"),
            models.CheckConstraint(check=models.Q(hie_consent_given=False) | models.Q(hie_consent_at__isnull=False), name="patient_hie_consent_is_dated"),
        ]

    def __str__(self):
        return f"{self.uhid} ({self.awpid})"

    def get_patient_details(self, batch=()):
        from apps.patients.services import load_patient_details
        load_patient_details([self, *batch])
        return self.__dict__["_patient_details"]


class PatientPayer(models.Model):
    PAYER_SELF = "self"
    PAYER_CHOICES = [(PAYER_SELF, "Self Pay"), ("insurance", "Insurance"), ("corporate", "Corporate")]

    patient                 = models.OneToOneField(HospitalPatient, on_delete=models.CASCADE, related_name="p_payer")
    payer_type              = models.CharField(max_length=20, choices=PAYER_CHOICES, default=PAYER_SELF)
    insurance_provider      = models.CharField(max_length=200, blank=True)
    policy_number           = models.CharField(max_length=100, blank=True)
    tpa_name                = models.CharField(max_length=200, blank=True)
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patient_payer"

    def __str__(self):
        return f"{self.patient_id} — {self.payer_type}"


class PatientEmergencyIntake(models.Model):
    IDENTITY_CONFIRMED = "confirmed"
    IDENTITY_PROVISIONAL = "provisional"
    IDENTITY_STATUS_CHOICES = [(IDENTITY_CONFIRMED, "Confirmed"), (IDENTITY_PROVISIONAL, "Provisional")]

    ARRIVAL_CHANNEL_CHOICES = [
        ("ambulance", "Ambulance"),
        ("brought_in", "Brought in"),
        ("police_case", "Police case"),
        ("walk_in_unresponsive", "Walk-in, unresponsive"),
        ("other", "Other"),
    ]

    patient                 = models.OneToOneField(HospitalPatient, on_delete=models.PROTECT, related_name="p_emergency_intake")
    identity_status         = models.CharField(max_length=12, choices=IDENTITY_STATUS_CHOICES, default=IDENTITY_CONFIRMED)
    is_mlc                  = models.BooleanField(default=False)
    arrival_channel         = models.CharField(max_length=25, choices=ARRIVAL_CHANNEL_CHOICES, blank=True)
    placeholder_label       = models.CharField(max_length=200, blank=True)
    consent_deferred_reason = models.CharField(max_length=255, blank=True)
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patient_emergency_intake"

    def __str__(self):
        return f"{self.patient_id} — {self.identity_status}"


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
    TYPE_CHOICES = [(TYPE_OPD, "OPD"), (TYPE_FOLLOWUP, "Follow-up"), (TYPE_EMERGENCY, "Emergency")]

    PAYMENT_PAY_AT_DESK = "pay_at_desk"
    PAYMENT_PAY_ONLINE  = "pay_online"
    PAYMENT_PREFERENCE_CHOICES = [
        (PAYMENT_PAY_AT_DESK, "Pay at Front Desk"),
        (PAYMENT_PAY_ONLINE,  "Pay Online"),
    ]

    id                 = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient            = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT, related_name="p_appointments")
    doctor             = models.ForeignKey(StaffUser, on_delete=models.PROTECT, related_name="u_appointments")
    # The place the visit happened and the queue it belongs to. Kept on the visit, not read from the doctor's current assignment, because the
    # doctor may later move or leave that department while the visit's place must not change; clean() checks the doctor worked there.
    branch_department  = models.ForeignKey(BranchDepartment, on_delete=models.PROTECT, related_name="bdp_appointments")
    appointment_type   = models.CharField(max_length=15, choices=TYPE_CHOICES, default=TYPE_OPD)
    status             = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    scheduled_date     = models.DateField()
    scheduled_time     = models.TimeField(null=True, blank=True)
    token_number       = models.IntegerField(null=True, blank=True)
    room               = models.ForeignKey("hospital_setup.Room", on_delete=models.PROTECT, null=True, blank=True, related_name="r_appointments")
    started_at         = models.DateTimeField(null=True, blank=True)
    completed_at       = models.DateTimeField(null=True, blank=True)
    chief_complaint    = models.TextField(blank=True)
    notes              = models.TextField(blank=True)
    payment_preference = models.CharField(max_length=15, choices=PAYMENT_PREFERENCE_CHOICES, default=PAYMENT_PAY_AT_DESK)
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "appointment"
        indexes = [
            models.Index(fields=["scheduled_date", "doctor"]),
            models.Index(fields=["scheduled_date", "branch_department"]),
            models.Index(fields=["patient", "scheduled_date"]),
            models.Index(fields=["status", "scheduled_date"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["branch_department", "scheduled_date", "token_number"], condition=models.Q(token_number__isnull=False),
                                    name="uniq_appt_queue_token_per_dept_day"),
            models.CheckConstraint(check=models.Q(token_number__isnull=True) | models.Q(token_number__gt=0), name="appointment_token_positive"),
            models.CheckConstraint(check=~models.Q(status="done") | models.Q(completed_at__isnull=False), name="appointment_done_is_dated"),
        ]
        ordering = ["scheduled_date", "token_number"]

    def __str__(self):
        return f"Appt #{self.token_number} — {self.patient_id} ({self.status})"

    def clean(self):
        db = self._state.db
        if not StaffBranchDepartment.objects.using(db).filter(staff_id=self.doctor_id, branch_department_id=self.branch_department_id).exists():
            raise ValidationError({"doctor": "The doctor does not work at this branch and department."})
        if self.room_id and self.room.branch_id != self.branch_department.branch_id:
            raise ValidationError({"room": "The room is at a different branch."})

    @classmethod
    def next_token(cls, branch_department_id, scheduled_date, using):
        """The next queue number for a department on a day. Locks the department row, so call it in the same transaction that creates the appointment."""
        with transaction.atomic(using=using):
            BranchDepartment.objects.using(using).select_for_update().get(pk=branch_department_id)
            last = cls.objects.using(using).filter(branch_department_id=branch_department_id, scheduled_date=scheduled_date) \
                              .aggregate(last=models.Max("token_number"))["last"]
            return (last or 0) + 1

    @cached_property
    def vitals(self):
        from apps.documents.lib_vitals import visit_vitals
        return visit_vitals(self.id)


class OPDEncounter(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SIGNED = "signed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SIGNED, "Signed"),
    ]

    id                          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment                 = models.OneToOneField(Appointment, on_delete=models.PROTECT, related_name="a_encounter")
    status                      = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    subjective                  = models.TextField(blank=True)
    objective                   = models.TextField(blank=True)
    assessment                  = models.TextField(blank=True)
    plan                        = models.TextField(blank=True)

    diagnoses                   = models.JSONField(default=list, blank=True)

    investigations              = models.TextField(blank=True)

    advice_to_patient           = models.TextField(blank=True)
    follow_up_in_days           = models.IntegerField(null=True, blank=True)

    followup_ask_nurse          = models.BooleanField(default=False)
    followup_nurse_note         = models.CharField(max_length=255, blank=True)
    followup_nurse_requested_at = models.DateTimeField(null=True, blank=True)
    followup_nurse_booked       = models.BooleanField(default=False)
    followup_nurse_booked_at    = models.DateTimeField(null=True, blank=True)

    referred_to                 = models.CharField(max_length=255, blank=True)
    referral_notes              = models.TextField(blank=True)

    signed_at                   = models.DateTimeField(null=True, blank=True)
    created_at                  = models.DateTimeField(auto_now_add=True)
    updated_at                  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opd_encounter"
        indexes = [models.Index(fields=["status"])]
        constraints = [
            models.CheckConstraint(check=~models.Q(status="signed") | models.Q(signed_at__isnull=False), name="encounter_signed_is_dated"),
            models.CheckConstraint(check=models.Q(follow_up_in_days__isnull=True) | models.Q(follow_up_in_days__gt=0), name="encounter_follow_up_positive"),
            models.CheckConstraint(check=models.Q(followup_nurse_booked=False) | models.Q(followup_ask_nurse=True), name="encounter_nurse_follow_up_was_asked"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Encounter {self.id} [{self.status}]"

    def sign(self, using=None):
        db = using or self._state.db
        now = timezone.now()
        with transaction.atomic(using=db):
            self.status = self.STATUS_SIGNED
            self.signed_at = now
            self.appointment.status = Appointment.STATUS_DONE
            self.appointment.completed_at = now
            self.appointment.save(using=db, update_fields=["status", "completed_at"])
            self.save(using=db)


class PatientChoiceFields(models.Model):
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

    id                 = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter          = models.OneToOneField(OPDEncounter, on_delete=models.PROTECT, related_name="e_prescription")
    status             = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes              = models.TextField(blank=True)
    rx_number          = models.CharField(max_length=30, unique=True, null=True, blank=True)
    payment_preference = models.CharField(max_length=15, choices=PAYMENT_PREFERENCE_CHOICES, blank=True)
    invoice            = models.ForeignKey("billing.Invoice", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opd_prescription"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Rx {self.rx_number or self.id} — {self.status}"


class PrescriptionItem(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prescription  = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="rx_items")
    drug          = models.ForeignKey("pharmacy.Drug", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    drug_name     = models.CharField(max_length=255)
    generic_name  = models.CharField(max_length=255, blank=True)
    dosage        = models.CharField(max_length=50)
    frequency     = models.CharField(max_length=10, choices=Prescription.FREQUENCY_CHOICES)
    route         = models.CharField(max_length=15, choices=Prescription.ROUTE_CHOICES, default="oral")
    duration_days = models.IntegerField(null=True, blank=True)
    quantity      = models.IntegerField(null=True, blank=True)
    instructions  = models.TextField(blank=True)

    class Meta:
        db_table = "opd_prescription_item"
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__isnull=True) | models.Q(quantity__gt=0), name="rx_item_quantity_positive"),
            models.CheckConstraint(check=models.Q(duration_days__isnull=True) | models.Q(duration_days__gt=0), name="rx_item_duration_positive"),
        ]

    def __str__(self):
        return f"{self.drug_name} {self.dosage} {self.frequency}"


class Allergy(models.Model):
    SEVERITY_CHOICES = [
        ("mild",     "Mild"),
        ("moderate", "Moderate"),
        ("severe",   "Severe"),
    ]

    patient     = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT, related_name="p_allergies")
    substance   = models.CharField(max_length=200)
    reaction    = models.TextField(blank=True)
    severity    = models.CharField(max_length=20, choices=SEVERITY_CHOICES, blank=True)
    is_active   = models.BooleanField(default=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    recorded_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="u_allergies_recorded")

    class Meta:
        db_table  = "allergy"

    def __str__(self):
        return f"{self.patient_id} — {self.substance}"
