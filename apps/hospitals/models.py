"""
apps/hospitals/models.py
----------------------
Atomwalk DB models for hospital provisioning and licensing.
These live in the "default" (Atomwalk) database — never in hospital DBs.

Tables:
  Hospital        — one row per hospital/clinic
  Subscription  — licensing tier + feature gates + payment lifecycle
"""

from django.db import models


class Hospital(models.Model):
    """
    Represents one hospital or clinic registered on the platform.
    Atomwalk platform admin creates and manages these records.
    """
    name        = models.CharField(max_length=200)
    subdomain   = models.CharField(max_length=100, unique=True)
    db_name     = models.CharField(max_length=100, unique=True)   # PostgreSQL DB alias
    city        = models.CharField(max_length=100, blank=True)
    state       = models.CharField(max_length=100, blank=True)
    gstin       = models.CharField(max_length=20,  blank=True)
    # Shown on the patient portal's hospital cards/profile — comma-separated
    # accreditation names (e.g. "NABH, ISO 9001") and a short public-facing
    # description. Platform-admin-managed, not editable by hospital staff.
    accreditations = models.CharField(max_length=300, blank=True)
    about          = models.TextField(blank=True)
    # Set once by platform admin (Hospital profile → Edit), same
    # provenance as accreditations/about above — patient app never writes
    # these. Powers "hospitals near me" (apps.hospital_patients.portal_views) via a
    # plain haversine distance calc (core.geo.haversine_km); null until an
    # admin fills them in, so a hospital missing coordinates just sorts to
    # the end of a distance-ranked list instead of breaking it.
    latitude    = models.FloatField(null=True, blank=True)
    longitude   = models.FloatField(null=True, blank=True)
    is_active   = models.BooleanField(default=True)
    # The schedules this hospital's staff-facing vaccination and milestone roadmaps are built from: a platform template or the
    # hospital's own copy. Empty = the platform's default template (decided where the roadmap is built).
    active_vaccination_schedule = models.ForeignKey("atomwalk.Schedule", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    active_milestone_schedule = models.ForeignKey("atomwalk.Schedule", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    # Who controls the consultation fee for doctors at this hospital.
    #   "doctor"   — each doctor sets their own fee from their profile.
    #   "hospital" — the hospital admin sets the fee at registration and
    #                can edit it later; the field is read-only for doctors.
    FEE_OWNERSHIP_DOCTOR   = "doctor"
    FEE_OWNERSHIP_HOSPITAL = "hospital"
    FEE_OWNERSHIP_CHOICES  = [
        (FEE_OWNERSHIP_DOCTOR,   "Doctor self-configures"),
        (FEE_OWNERSHIP_HOSPITAL, "Hospital controls"),
    ]
    fee_ownership = models.CharField(
        max_length=10,
        choices=FEE_OWNERSHIP_CHOICES,
        default=FEE_OWNERSHIP_DOCTOR,
    )

    # ── Billing config — hospital admin editable via /org/settings/ ────────
    # Off by default: a hospital that's never touched billing setup gets no
    # surprise registration charge on their first patient.
    registration_fee_enabled = models.BooleanField(default=False)
    registration_fee_amount  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # % applied to a billing line item that doesn't specify its own tax_rate
    # (e.g. the auto-generated consultation/registration invoices) — a
    # per-BillingService tax_rate still overrides this when one is set.
    default_tax_rate         = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Hospital's own logo, uploaded by their hospital admin (Settings page) —
    # stores an S3 object key, not a usable URL (see core/storage.py); read
    # sites sign it fresh on every request. Shown in the staff AppShell
    # topbar (replacing the deterministic monogram fallback) across every
    # role at this hospital, and on the patient portal's hospital/doctor
    # cards. Blank until the hospital uploads one.
    logo = models.TextField(blank=True)

    # Human-friendly S3 folder name for this clinic's uploads (staff photos,
    # doctor signatures, lab reports, the logo above) — e.g. "sunrise-clinic"
    # instead of the auto-generated db_name ("aw_sunrise_clinic_7f2a"). Set
    # by the hospital admin via /org/settings/ (core.storage.sanitize_folder
    # enforces lowercase/hyphen-only on save so it's always a safe S3 key
    # segment). Blank means "use db_name" — see
    # core.storage.hospital_folder(hospital), the single place this fallback is
    # resolved, so every upload call site stays in sync automatically.
    # Changing this only affects NEW uploads; files already in S3 under the
    # old folder name aren't moved.
    storage_folder = models.CharField(max_length=60, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hospitals"
        db_table  = "hospitals"

    def __str__(self):
        return f"{self.name} ({self.subdomain})"


class Subscription(models.Model):
    """
    Licensing tier and feature gates for a hospital.
    One row per hospital. The backend enforces features via license_tier;
    boolean feat_* fields are cached from tier config but can be overridden
    by platform admin for custom deals.
    """
    TIER_CHOICES = [
        ("starter",    "Starter"),
        ("growth",     "Growth"),
        ("pro",        "Pro"),
        ("enterprise", "Enterprise"),
    ]

    STATUS_CHOICES = [
        ("trial",     "Trial"),
        ("active",    "Active"),
        ("grace",     "Grace Period"),       # payment lapsed, day 1–7
        ("read_only", "Read Only"),           # day 8–30
        ("frozen",    "Frozen"),              # day 31–90
        ("suspended", "Suspended"),           # platform admin review
    ]

    hospital           = models.OneToOneField(Hospital, on_delete=models.PROTECT,
                                            related_name="subscription")
    license_tier     = models.CharField(max_length=20, choices=TIER_CHOICES,
                                        default="starter")
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                        default="trial")
    trial_ends_on    = models.DateField(null=True, blank=True)
    current_period_start = models.DateField(null=True, blank=True)
    current_period_end   = models.DateField(null=True, blank=True)
    payment_lapse_since  = models.DateField(null=True, blank=True)

    # Feature gates (overridable per hospital by platform admin)
    feat_lab          = models.BooleanField(default=False)
    feat_pharmacy     = models.BooleanField(default=False)
    feat_whatsapp     = models.BooleanField(default=False)
    feat_multi_branch = models.BooleanField(default=False)
    feat_ai_voice     = models.BooleanField(default=False)
    feat_patient_app  = models.BooleanField(default=False)
    feat_analytics    = models.BooleanField(default=False)
    feat_video        = models.BooleanField(default=False)
    feat_face_recog   = models.BooleanField(default=False)
    # Table-driven RBAC (custom roles beyond the 6 system defaults) — see
    # docs/onboarding_auth_rbac_architecture.md 4.3. Gated to enterprise
    # tier: the 6 hardcoded system roles cover 95%+ of hospitals, so only
    # hospitals that actually ask for a custom role pay the extra complexity.
    feat_custom_roles = models.BooleanField(default=False)

    # Soft limits (0 = unlimited). max_staff caps everyone EXCEPT doctors
    # (nurse/front_desk/lab_tech/pharmacist/hospital_admin combined) — doctors
    # have their own dedicated cap since they're the primary billed seat.
    max_doctors       = models.PositiveIntegerField(default=3)
    max_branches      = models.PositiveIntegerField(default=1)
    max_staff         = models.PositiveIntegerField(default=5)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hospitals"
        db_table  = "subscription"

    def __str__(self):
        return f"{self.hospital.name} — {self.license_tier} ({self.status})"


class HospitalAuditLog(models.Model):
    """
    Append-only trail of platform-admin actions taken on a hospital — tier
    changes, subscription-status changes, suspend/reactivate. Separate from
    org.AuditLog (which tracks per-hospital clinical/staff actions inside a
    hospital's own DB) since this lives in the atomwalk DB alongside Hospital
    itself and is about platform-level administration, not patient care.

    Written by HospitalDetailView.patch() — one row per changed field per
    request, so multi-field PATCHes produce multiple rows with the same
    created_at.
    """
    ACTION_CHOICES = [
        ("created",          "Hospital Created"),
        ("tier_change",      "Tier Change"),
        ("status_change",    "Subscription Status Change"),
        ("active_change",    "Active/Suspended Toggle"),
        ("subdomain_change", "Hospital Code Change"),
    ]

    hospital       = models.ForeignKey(Hospital, on_delete=models.CASCADE,
                                     related_name="audit_logs")
    action       = models.CharField(max_length=20, choices=ACTION_CHOICES)
    actor_email  = models.CharField(max_length=255, blank=True)
    before_value = models.CharField(max_length=100, blank=True)
    after_value  = models.CharField(max_length=100, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "hospitals"
        db_table  = "hospital_audit_log"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.hospital.name}: {self.action} {self.before_value} → {self.after_value}"
