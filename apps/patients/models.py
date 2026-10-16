import os
import uuid

from django.db import models

from core.storage import documents_storage
from core.utils.tokens import new_pad_token


def get_patient_photo_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"patients/{instance.awpid}/photo/{uuid.uuid4().hex}{ext}"


class Patient(models.Model):
    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]
    BLOOD_GROUP_CHOICES = [(g, g) for g in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")]

    awpid               = models.CharField(max_length=30, unique=True)
    full_name           = models.CharField(max_length=100)
    date_of_birth       = models.DateField(null=True, blank=True)
    gender              = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)

    mobile              = models.CharField(max_length=10, unique=True, null=True, blank=True)

    guardian_mobile     = models.CharField(max_length=15, blank=True, db_index=True)
    is_dependent        = models.BooleanField(default=False)
    email               = models.EmailField(blank=True)
    blood_group         = models.CharField(max_length=3, choices=BLOOD_GROUP_CHOICES, blank=True)
    preferred_language  = models.CharField(max_length=10, default="en")

    password      = models.CharField(max_length=128, blank=True)
    photo         = models.ImageField(storage=documents_storage, upload_to=get_patient_photo_path, blank=True)
    is_active     = models.BooleanField(default=True)
    last_login    = models.DateTimeField(null=True, blank=True)

    emergency_contact_name     = models.CharField(max_length=100, blank=True)
    emergency_contact_phone    = models.CharField(max_length=15, blank=True)
    emergency_contact_relation = models.CharField(max_length=30, blank=True)

    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "patient"


class PatientRelationship(models.Model):
    REL_CHOICES = [
        ("child", "Child"), ("parent", "Parent"), ("spouse", "Spouse"),
        ("sibling", "Sibling"), ("ward", "Ward"), ("other", "Other"),
    ]
    dependent       = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name="p_dependent")
    guardian        = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name="p_guardian")
    relationship    = models.CharField(max_length=20, choices=REL_CHOICES, default="other")
    is_primary      = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "patient_relationship"
        unique_together = [("dependent", "guardian")]


class PatientBooking(models.Model):
    booked_by       = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name="p_bookings_made")
    patient         = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE)
    hospital        = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.CASCADE)
    appointment_id  = models.UUIDField()

    doctor_name     = models.CharField(max_length=255, blank=True)
    scheduled_date  = models.DateField()
    chief_complaint = models.TextField(blank=True)
    status          = models.CharField(max_length=15, default="scheduled", db_index=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "patient_booking"
        ordering  = ["-created_at"]


class BlacklistedToken(models.Model):
    jti        = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "blacklisted_token"


class OTPCode(models.Model):
    PURPOSE_PASSWORD_RESET_STAFF   = "password_reset_staff"
    PURPOSE_PASSWORD_RESET_PATIENT = "password_reset_patient"
    PURPOSE_REGISTRATION_PATIENT   = "registration_patient"
    PURPOSE_LOGIN_PATIENT          = "login_patient"
    PURPOSE_CONTACT_CHANGE_PATIENT = "contact_change_patient"
    PURPOSE_CHOICES = [
        (PURPOSE_PASSWORD_RESET_STAFF,   "Staff password reset"),
        (PURPOSE_PASSWORD_RESET_PATIENT, "Patient password reset"),
        (PURPOSE_REGISTRATION_PATIENT,   "Patient registration"),
        (PURPOSE_LOGIN_PATIENT,          "Patient OTP login"),
        (PURPOSE_CONTACT_CHANGE_PATIENT, "Patient mobile-number change"),
    ]

    CHANNEL_SMS   = "sms"
    CHANNEL_EMAIL = "email"
    CHANNEL_CHOICES = [(CHANNEL_SMS, "SMS"), (CHANNEL_EMAIL, "Email")]

    purpose     = models.CharField(max_length=30, choices=PURPOSE_CHOICES, db_index=True)

    identifier  = models.CharField(max_length=254, db_index=True)
    channel     = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    code_hash   = models.CharField(max_length=64)

    target_type = models.CharField(max_length=10, blank=True)
    target_id   = models.IntegerField(null=True, blank=True)

    hospital    = models.ForeignKey("hospital_master.Hospital", null=True, blank=True, on_delete=models.CASCADE)

    attempts    = models.PositiveSmallIntegerField(default=0)
    is_used     = models.BooleanField(default=False)
    expires_at  = models.DateTimeField(db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "otp_code"
        indexes = [models.Index(fields=["identifier", "purpose", "-created_at"])]


class EmergencyAccessLog(models.Model):
    EVENT_GENERATED = "generated"
    EVENT_VIEWED    = "viewed"

    EVENT_PRIVACY   = "privacy"
    EVENT_CHOICES = [
        (EVENT_GENERATED, "QR code generated"),
        (EVENT_VIEWED,     "Summary viewed"),
        (EVENT_PRIVACY,    "Shared-records privacy changed"),
    ]

    patient    = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    event      = models.CharField(max_length=24, choices=EVENT_CHOICES)

    generated_by = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.SET_NULL, related_name="p_generated_access_logs")

    consent_confirmed = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "emergency_access_log"
        ordering  = ["-created_at"]


class ConsultSession(models.Model):
    STATUS_OPEN    = "open"
    STATUS_SIGNED  = "signed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_OPEN,    "Open"),
        (STATUS_SIGNED,  "Signed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    token           = models.CharField(max_length=64, unique=True, db_index=True, default=new_pad_token)
    patient         = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    hospital          = models.ForeignKey("hospital_master.Hospital", on_delete=models.CASCADE)
    encounter_id    = models.UUIDField(db_index=True)
    doctor_user_id  = models.UUIDField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_OPEN, db_index=True)

    rx_pages      = models.JSONField(default=list, blank=True)

    rx_recognised = models.JSONField(null=True, blank=True)

    note_pages      = models.JSONField(default=list, blank=True)

    note_recognised = models.JSONField(null=True, blank=True)

    note_pdf = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    signed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table  = "consult_session"
        ordering  = ["-created_at"]
        indexes = [
            models.Index(fields=["encounter_id", "status"]),
            models.Index(fields=["patient", "hospital", "status"]),
        ]


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

    token       = models.CharField(max_length=32, unique=True, db_index=True)

    code        = models.CharField(max_length=8, db_index=True)

    requester_label = models.CharField(max_length=120, blank=True)

    opened_at   = models.DateTimeField(null=True, blank=True)

    device_hash = models.CharField(max_length=64, blank=True)

    pairing     = models.CharField(max_length=12, blank=True)

    patient     = models.ForeignKey("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    status      = models.CharField(max_length=12, choices=STATUS_CHOICES,
                                   default=STATUS_PENDING, db_index=True)

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
        indexes = [
            models.Index(fields=["patient", "status"]),
        ]


class RecordsPrivacy(models.Model):
    SECTIONS = ("summary", "vitals", "diagnoses", "vaccinations")

    patient           = models.OneToOneField("patients.Patient", null=True, blank=True, on_delete=models.CASCADE)
    hide_all          = models.BooleanField(default=False)
    hidden_doc_ids    = models.JSONField(default=list, blank=True)
    hidden_categories = models.JSONField(default=list, blank=True)
    hidden_kinds      = models.JSONField(default=list, blank=True)
    hidden_sections   = models.JSONField(default=list, blank=True)
    updated_at        = models.DateTimeField(auto_now=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "records_privacy"


class StaffMobileIndex(models.Model):
    mobile    = models.CharField(max_length=15, unique=True, db_index=True)

    email     = models.EmailField(max_length=254, unique=True, null=True, blank=True, db_index=True)
    hospital = models.ForeignKey("hospital_master.Hospital", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "staff_mobile_index"
