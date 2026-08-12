"""
apps/tenants/models.py
----------------------
Registry DB models for tenant provisioning and licensing.
These live in the "default" (Registry) database — never in tenant DBs.

Tables:
  Tenant        — one row per hospital/clinic
  Subscription  — licensing tier + feature gates + payment lifecycle
  NextNumber    — sequential ID generator per branch/entity (NNTM pattern)
"""

from django.db import models


class Tenant(models.Model):
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
    # description. Platform-admin-managed, not editable by tenant staff.
    accreditations = models.CharField(max_length=300, blank=True)
    about          = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    # Which VaccinationSchedule (apps.registry.models.VaccinationSchedule)
    # this hospital's staff-facing vaccination roadmap is built against.
    # Plain IntegerField, not a real Django FK — even though Tenant
    # (app_label "tenants") and VaccinationSchedule (app_label "registry")
    # both route to the "default" registry DB (see core/db_router.py:
    # REGISTRY_APPS includes both "tenants" and "registry"), this codebase's
    # established convention is to never put a real cross-app FK to/from
    # Tenant — every other cross-app reference to Tenant.id in this codebase
    # (StaffMobileIndex.tenant_id, PortalBooking.tenant_id, TenantAuditLog
    # uses a real FK only because it's declared *inside* the tenants app
    # itself) uses a plain mirrored IntegerField instead, to keep the
    # registry app and the tenants app decoupled from each other's model
    # imports. Matching that pattern here for consistency rather than
    # introducing the first cross-app FK. null=True: a tenant with no
    # schedule assigned yet (shouldn't normally happen post-migration, but
    # the field must tolerate it) falls back to the global "Default
    # Schedule" template at the call site.
    active_vaccination_schedule_id = models.IntegerField(null=True, blank=True)

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

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "tenants"
        db_table  = "tenant"

    def __str__(self):
        return f"{self.name} ({self.subdomain})"


class Subscription(models.Model):
    """
    Licensing tier and feature gates for a tenant.
    One row per tenant. The backend enforces features via license_tier;
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

    tenant           = models.OneToOneField(Tenant, on_delete=models.PROTECT,
                                            related_name="subscription")
    license_tier     = models.CharField(max_length=20, choices=TIER_CHOICES,
                                        default="starter")
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                        default="trial")
    trial_ends_on    = models.DateField(null=True, blank=True)
    current_period_start = models.DateField(null=True, blank=True)
    current_period_end   = models.DateField(null=True, blank=True)
    payment_lapse_since  = models.DateField(null=True, blank=True)

    # Feature gates (overridable per tenant by platform admin)
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
    # tenants that actually ask for a custom role pay the extra complexity.
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
        app_label = "tenants"
        db_table  = "subscription"

    def __str__(self):
        return f"{self.tenant.name} — {self.license_tier} ({self.status})"


class TenantAuditLog(models.Model):
    """
    Append-only trail of platform-admin actions taken on a tenant — tier
    changes, subscription-status changes, suspend/reactivate. Separate from
    org.AuditLog (which tracks per-tenant clinical/staff actions inside a
    hospital's own DB) since this lives in the registry DB alongside Tenant
    itself and is about platform-level administration, not patient care.

    Written by TenantDetailView.patch() — one row per changed field per
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

    tenant       = models.ForeignKey(Tenant, on_delete=models.CASCADE,
                                     related_name="audit_logs")
    action       = models.CharField(max_length=20, choices=ACTION_CHOICES)
    actor_email  = models.CharField(max_length=255, blank=True)
    before_value = models.CharField(max_length=100, blank=True)
    after_value  = models.CharField(max_length=100, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "tenants"
        db_table  = "tenant_audit_log"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.tenant.name}: {self.action} {self.before_value} → {self.after_value}"


class NextNumber(models.Model):
    """
    NNTM — Next Number Table Manager.
    One row per (branch, entity) pair. get_next_number() in core/utils/nntm.py
    uses SELECT FOR UPDATE inside an atomic transaction to guarantee uniqueness.

    entity examples: "UHID", "INV", "LAB", "RX", "QUEUE"
    """
    branch_id   = models.IntegerField(db_index=True)   # references org.Branch
    entity      = models.CharField(max_length=20)       # e.g. "UHID", "INV"
    prefix      = models.CharField(max_length=10, default="")
    last_number = models.PositiveBigIntegerField(default=0)
    pad_length  = models.PositiveSmallIntegerField(default=6)

    class Meta:
        app_label = "tenants"
        db_table  = "next_number"
        unique_together = [("branch_id", "entity")]

    def __str__(self):
        return f"{self.prefix}{str(self.last_number).zfill(self.pad_length)}"
