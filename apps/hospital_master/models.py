from django.db import models


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
    logo                     = models.TextField(blank=True)
    storage_folder           = models.CharField(max_length=60, blank=True)
    fee_ownership            = models.CharField(max_length=10, choices=FEE_OWNERSHIP_CHOICES, default=FEE_OWNERSHIP_DOCTOR)
    registration_fee_enabled = models.BooleanField(default=False)
    registration_fee_amount  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    default_tax_rate         = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    created_at               = models.DateTimeField(auto_now_add=True)
    updated_at               = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "hospital_parameters"


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
    trial_ends_on    = models.DateField(null=True, blank=True)
    current_period_start = models.DateField(null=True, blank=True)
    current_period_end   = models.DateField(null=True, blank=True)
    payment_lapse_since  = models.DateField(null=True, blank=True)

    feat_lab          = models.BooleanField(default=False)
    feat_pharmacy     = models.BooleanField(default=False)
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


class HospitalAuditLog(models.Model):
    ACTION_CHOICES = [
        ("created",          "Hospital Created"),
        ("tier_change",      "Tier Change"),
        ("status_change",    "Subscription Status Change"),
        ("active_change",    "Active/Suspended Toggle"),
        ("subdomain_change", "Hospital Code Change"),
    ]

    hospital       = models.ForeignKey(Hospital, on_delete=models.CASCADE)
    action       = models.CharField(max_length=20, choices=ACTION_CHOICES)
    actor_email  = models.CharField(max_length=255, blank=True)
    before_value = models.CharField(max_length=100, blank=True)
    after_value  = models.CharField(max_length=100, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table  = "hospital_audit_log"
        ordering  = ["-created_at"]
