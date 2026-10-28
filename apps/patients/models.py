from django.db import models
from apps.hospital_master.models import Hospital

def patient_photo_path(instance, filename):
    return f"patients/{instance.awpid}/photo/{filename}"


class Patient(models.Model):
    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]
    BLOOD_GROUP_CHOICES = [(g, g) for g in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")]
    CREATED_BY_CHOICES = [("patient", "Patient"), ("hospital", "Hospital")]

    awpid               = models.CharField(max_length=30, unique=True)
    full_name           = models.CharField(max_length=100)
    date_of_birth       = models.DateField(null=True, blank=True)
    gender              = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    mobile              = models.CharField(max_length=15, null=True, blank=True)
    guardian_mobile     = models.CharField(max_length=15, blank=True, null=True)
    is_dependent        = models.BooleanField(default=False)
    email               = models.EmailField(blank=True)
    blood_group         = models.CharField(max_length=3, choices=BLOOD_GROUP_CHOICES, blank=True)
    preferred_language  = models.CharField(max_length=10, default="en")
    password      = models.CharField(max_length=128, blank=True)
    photo         = models.ImageField(upload_to=patient_photo_path, blank=True, null=True)
    is_active     = models.BooleanField(default=True)
    last_login    = models.DateTimeField(null=True, blank=True)
    emergency_contact_name     = models.CharField(max_length=100, blank=True)
    emergency_contact_phone    = models.CharField(max_length=15, blank=True)
    emergency_contact_relation = models.CharField(max_length=30, blank=True)
    alternate_mobile           = models.CharField(max_length=15, blank=True, default="")
    address_line1              = models.CharField(max_length=255, blank=True, default="")
    city                       = models.CharField(max_length=100, blank=True, default="")
    state                      = models.CharField(max_length=100, blank=True, default="")
    pincode                    = models.CharField(max_length=10, blank=True, default="")
    marital_status             = models.CharField(max_length=20, blank=True, default="")
    nationality                = models.CharField(max_length=50, blank=True, default="Indian")
    occupation                 = models.CharField(max_length=100, blank=True, default="")
    source_hospital    = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_patients")
    created_by          = models.CharField(max_length=10, choices=CREATED_BY_CHOICES, default="patient")
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "patient"

    def __str__(self):
        return f"{self.full_name} ({self.awpid})"

# not reviewed
class PatientRelationship(models.Model):
    REL_CHOICES = [
        ("child", "Child"), ("parent", "Parent"), ("spouse", "Spouse"),
        ("sibling", "Sibling"), ("ward", "Ward"), ("other", "Other"),
    ]
    dependent       = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_dependent")
    guardian        = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_guardian")
    relationship    = models.CharField(max_length=20, choices=REL_CHOICES, default="other")
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "patient_relationship"
        constraints = [models.UniqueConstraint(fields=["dependent", "guardian"], name="uniq_relationship_dependent_guardian")]

    def __str__(self):
        return f"{self.guardian.awpid} -> {self.dependent.awpid} ({self.relationship})"


class PatientBooking(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"), ("waiting", "Waiting"), ("vitals_done", "Vitals done"),
        ("in_progress", "In progress"), ("done", "Done"), ("cancelled", "Cancelled"), ("no_show", "No show"),
    ]
    booked_by       = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.SET_NULL, related_name="p_bookings_made")
    patient         = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_bookings")
    hospital        = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_bookings")
    appointment_id  = models.UUIDField()
    doctor_name     = models.CharField(max_length=100, blank=True)
    scheduled_date  = models.DateField()
    chief_complaint = models.TextField(blank=True)
    status          = models.CharField(max_length=15, choices=STATUS_CHOICES, default="scheduled")
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "patient_booking"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"Booking {self.pk} for patient {self.patient_id} on {self.scheduled_date} - {self.status}"


class RecurrenceFlag(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="p_recurrence_flags")
    condition_group = models.CharField(max_length=40)
    label = models.CharField(max_length=255)
    triggered_on = models.DateField()
    rule = models.JSONField(default=dict)
    episodes_last_12m = models.PositiveIntegerField(default=0)
    clinical_hint = models.CharField(max_length=255, blank=True)
    acknowledged_by_id = models.IntegerField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "recurrence_flag"
        constraints = [models.UniqueConstraint(fields=["patient", "condition_group"], name="uniq_recurrence_per_patient_group")]

# not reviewed
class EmergencyAccessLog(models.Model):
    EVENT_GENERATED = "generated"
    EVENT_VIEWED    = "viewed"

    EVENT_PRIVACY   = "privacy"
    EVENT_CHOICES = [
        (EVENT_GENERATED, "QR code generated"),
        (EVENT_VIEWED,     "Summary viewed"),
        (EVENT_PRIVACY,    "Shared-records privacy changed"),
    ]

    patient    = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name="p_emergency_access_logs")
    event      = models.CharField(max_length=24, choices=EVENT_CHOICES)
    generated_by = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.SET_NULL, related_name="p_generated_access_logs")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "emergency_access_log"
        ordering  = ["-created_at"]

# not reviewed
class RecordsShareRequest(models.Model):
    STATUS_PENDING  = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED   = "denied"
    STATUS_ENDED    = "ended"
    STATUS_EXPIRED  = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING,  "Waiting for patient"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED,   "Denied by patient"),
        (STATUS_ENDED,    "Ended by patient"),
        (STATUS_EXPIRED,  "Expired"),
    ]

    WINDOW_HOURS = 2

    token       = models.CharField(max_length=32, unique=True)
    code        = models.CharField(max_length=8)
    requester_label = models.CharField(max_length=120, blank=True)
    opened_at   = models.DateTimeField(null=True, blank=True)
    device_hash = models.CharField(max_length=64, blank=True)
    pairing     = models.CharField(max_length=12, blank=True)
    patient     = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name="p_records_share_requests")
    status      = models.CharField(max_length=12, choices=STATUS_CHOICES,
                                   default=STATUS_PENDING)
    created_at  = models.DateTimeField(auto_now_add=True)
    decided_at  = models.DateTimeField(null=True, blank=True)
    expires_at  = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_ip  = models.GenericIPAddressField(null=True, blank=True)
    download_unlocked_ids = models.JSONField(default=list, blank=True)
    shown_private_ids = models.JSONField(default=list, blank=True)
    share_all   = models.BooleanField(default=False)
    pending_download_id = models.IntegerField(null=True, blank=True)
    code_attempts = models.PositiveSmallIntegerField(default=0)

    MAX_CODE_ATTEMPTS = 5

    PENDING_TTL_MINUTES = 20

    class Meta:
        db_table  = "records_share_request"
        ordering  = ["-created_at"]

# not reviewed
class RecordsPrivacy(models.Model):
    SECTIONS = ("summary", "vitals", "diagnoses", "vaccinations")

    patient           = models.OneToOneField(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name="p_records_privacy")
    hide_all          = models.BooleanField(default=False)
    hidden_doc_ids    = models.JSONField(default=list, blank=True)
    hidden_categories = models.JSONField(default=list, blank=True)
    hidden_kinds      = models.JSONField(default=list, blank=True)
    hidden_sections   = models.JSONField(default=list, blank=True)
    updated_at        = models.DateTimeField(auto_now=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "records_privacy"
