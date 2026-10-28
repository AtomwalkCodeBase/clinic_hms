import uuid

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.functional import cached_property
from apps.hospital_patients.models import HospitalPatient
from core.utils import new_pad_token
from apps.hospital_setup.models import BranchDepartment, StaffBranchAssignment, StaffUser, hospital_folder


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

    appointment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
        place = self.branch_department
        if not StaffBranchAssignment.objects.using(db).filter(
                staff_id=self.doctor_id, branch_id=place.branch_id, staff__department_id=place.department_id).exists():
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
        from apps.hospital_patients.vitals_service import visit_vitals
        return visit_vitals(self.pk, self._state.db)


class OPDEncounter(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SIGNED = "signed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SIGNED, "Signed"),
    ]

    opd_encounter_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
        constraints = [
            models.CheckConstraint(check=~models.Q(status="signed") | models.Q(signed_at__isnull=False), name="encounter_signed_is_dated"),
            models.CheckConstraint(check=models.Q(follow_up_in_days__isnull=True) | models.Q(follow_up_in_days__gt=0), name="encounter_follow_up_positive"),
            models.CheckConstraint(check=models.Q(followup_nurse_booked=False) | models.Q(followup_ask_nurse=True), name="encounter_nurse_follow_up_was_asked"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Encounter {self.pk} [{self.status}]"

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


class Prescription(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_EXPIRED, "Expired"),
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

    opd_prescription_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter          = models.OneToOneField(OPDEncounter, on_delete=models.PROTECT, related_name="e_prescription")
    status             = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes              = models.TextField(blank=True)
    rx_number          = models.CharField(max_length=30, unique=True, null=True, blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opd_prescription"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Rx {self.rx_number or self.pk} — {self.status}"


class PrescriptionItem(models.Model):
    opd_prescription_item_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prescription  = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="rx_items")
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


def consult_note_path(instance, filename):
    return f"{hospital_folder(instance)}/patients/{instance.encounter.appointment.patient.uhid}/{instance.encounter.appointment_id}/{filename}"


class ConsultSession(models.Model):
    """A doctor's handwritten-pad session for one encounter: the pages written, what was read from them, and the signed note. The patient and the
    doctor are those of the encounter's appointment."""
    STATUS_OPEN    = "open"
    STATUS_SIGNED  = "signed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_OPEN,    "Open"),
        (STATUS_SIGNED,  "Signed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    encounter       = models.ForeignKey(OPDEncounter, on_delete=models.CASCADE, related_name="e_consult_sessions")
    token           = models.CharField(max_length=64, unique=True, default=new_pad_token)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    rx_pages        = models.JSONField(default=list, blank=True)
    rx_recognised   = models.JSONField(null=True, blank=True)
    note_pages      = models.JSONField(default=list, blank=True)
    note_recognised = models.JSONField(null=True, blank=True)
    note_pdf        = models.FileField(upload_to=consult_note_path, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    expires_at      = models.DateTimeField(null=True, blank=True)
    signed_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "consult_session"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Consult session {self.pk} of encounter {self.encounter_id} [{self.status}]"
