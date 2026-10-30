from django.contrib.auth.models import User
from django.db import models


def get_hospital_logo_path(instance, filename):
    return f"hospitals/{instance.hospital.hospital_code}/logo/{filename}"


class Hospital(models.Model):
    hospital_code = models.CharField(max_length=20, unique=True)
    name        = models.CharField(max_length=200)
    db_name     = models.CharField(max_length=100, unique=True)
    city        = models.CharField(max_length=100, blank=True)
    state       = models.CharField(max_length=100, blank=True)
    gstin       = models.CharField(max_length=20,  blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "hospitals"

    def __str__(self):
        return f"{self.name} ({self.hospital_code})"


class HospitalParameters(models.Model):
    FEE_OWNERSHIP_DOCTOR   = "doctor"
    FEE_OWNERSHIP_HOSPITAL = "hospital"
    FEE_OWNERSHIP_CHOICES  = [
        (FEE_OWNERSHIP_DOCTOR,   "Doctor self-configures"),
        (FEE_OWNERSHIP_HOSPITAL, "Hospital controls"),
    ]

    hospital                 = models.OneToOneField(Hospital, on_delete=models.CASCADE, related_name="h_parameters")
    accreditations           = models.CharField(max_length=300, blank=True)
    about                    = models.TextField(blank=True)
    latitude                 = models.FloatField(null=True, blank=True)
    longitude                = models.FloatField(null=True, blank=True)
    logo                     = models.ImageField(upload_to=get_hospital_logo_path, blank=True, null=True)
    fee_ownership            = models.CharField(max_length=10, choices=FEE_OWNERSHIP_CHOICES, default=FEE_OWNERSHIP_DOCTOR)
    registration_fee_enabled = models.BooleanField(default=False)
    registration_fee_amount  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    default_tax_rate         = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        db_table  = "hospital_parameters"

# not reviewed
class Subscription(models.Model):
    TIER_CHOICES = [
        ("starter",    "Starter"),
        ("growth",     "Growth"),
        ("pro",        "Pro"),
        ("enterprise", "Enterprise"),
    ]

    STATUS_CHOICES = [
        ("trial",     "Trial"),
        ("active",    "Active"),
        ("grace",     "Grace Period"),
        ("read_only", "Read Only"),
        ("frozen",    "Frozen"),
        ("suspended", "Suspended"),
    ]

    hospital           = models.OneToOneField(Hospital, on_delete=models.PROTECT,
                                            related_name="h_subscription")
    license_tier     = models.CharField(max_length=20, choices=TIER_CHOICES,
                                        default="starter")
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                        default="trial")
    feat_whatsapp     = models.BooleanField(default=False)
    feat_multi_branch = models.BooleanField(default=False)
    feat_ai_voice     = models.BooleanField(default=False)
    feat_patient_app  = models.BooleanField(default=False)
    feat_analytics    = models.BooleanField(default=False)
    feat_video        = models.BooleanField(default=False)
    feat_face_recog   = models.BooleanField(default=False)

    feat_custom_roles = models.BooleanField(default=False)

    max_doctors       = models.PositiveIntegerField(default=3)
    max_branches      = models.PositiveIntegerField(default=1)
    max_staff         = models.PositiveIntegerField(default=5)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "subscription"

# not reviewed
class HospitalAuditLog(models.Model):
    ACTION_CHOICES = [
        ("created",          "Hospital Created"),
        ("tier_change",      "Tier Change"),
        ("status_change",    "Subscription Status Change"),
        ("active_change",    "Active/Suspended Toggle"),
        ("code_change",      "Hospital Code Change"),
    ]

    hospital       = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.SET_NULL, related_name="h_audit_logs")
    action       = models.CharField(max_length=20, choices=ACTION_CHOICES)
    actor_email  = models.CharField(max_length=255, blank=True)
    before_value = models.CharField(max_length=100, blank=True)
    after_value  = models.CharField(max_length=100, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "hospital_audit_log"
        ordering  = ["-created_at"]


class GlobalStaffUserIndexCatalog(models.Model):
    mobile         = models.CharField(max_length=15, unique=True)
    email          = models.EmailField(max_length=254, unique=True, null=True, blank=True)
    hospital       = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="h_staff_index")
    user           = models.ForeignKey(User, on_delete=models.CASCADE, related_name="staff_index_entries")
    is_doctor      = models.BooleanField(default=False)
    doctor_details = models.JSONField(default=dict, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "global_staff_user_index_catalog"
        constraints = [models.UniqueConstraint(fields=["user"], name="uniq_global_staff_user")]

    def __str__(self):
        return f"{self.mobile} -> {self.hospital_id}"


# not reviewed
class Schedule(models.Model):
    KIND_VACCINATION = "vaccination"
    KIND_CHOICES = [(KIND_VACCINATION, "Vaccination")]

    kind           = models.CharField(max_length=15, choices=KIND_CHOICES)
    name           = models.CharField(max_length=200)
    description    = models.TextField(blank=True)
    owner_hospital = models.ForeignKey(Hospital, null=True, blank=True, on_delete=models.CASCADE, related_name="h_schedules")
    is_template    = models.BooleanField(default=False)
    active         = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "immunization_schedules"

    def __str__(self):
        return f"{self.name} ({self.kind})"


# not reviewed
class ScheduleRule(models.Model):
    schedule        = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="s_rules")
    item            = models.CharField(max_length=200)
    dose_number     = models.PositiveSmallIntegerField(default=1)
    scheduled_label = models.CharField(max_length=50)
    min_age_days    = models.PositiveIntegerField()
    max_age_days    = models.PositiveIntegerField(null=True, blank=True)
    mandatory       = models.BooleanField(default=True)
    sort_order      = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "immunization_schedule_rules"
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(fields=["schedule", "item", "dose_number"], name="uniq_schedule_rule_item_dose"),
            models.CheckConstraint(check=models.Q(max_age_days__isnull=True) | models.Q(max_age_days__gte=models.F("min_age_days")), name="schedule_rule_age_range"),
        ]

    def __str__(self):
        return f"{self.item} dose {self.dose_number} ({self.scheduled_label})"
