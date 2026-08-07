"""
apps/registry/models.py
-----------------------
Registry DB models: patient identity hub + shared HIE (Health Information Exchange) tables.

PatientIdentity — global patient record; one row per unique patient on the platform.
SharedXxx tables — sanitized clinical copies written by tenant-side signals.
                   Hospital B reads these. source_tenant_id is NEVER returned
                   in API responses to other tenants (enforced at serializer level).

DPDP Act compliance:
  - No plain mobile numbers stored in this DB.
  - mobile_hash = SHA-256(normalize(+91XXXXXXXXXX)) — 64 hex chars.
  - AWPID is the platform's cross-provider patient identifier.
"""

from django.db import models


class StaffEmailIndex(models.Model):
    """
    DEPRECATED — registration/login moved to mobile number (see
    StaffMobileIndex below). Kept only so existing rows aren't destroyed by
    a destructive migration; nothing in the codebase writes or reads this
    table anymore. Do not use in new code.
    """
    email     = models.EmailField(unique=True, db_index=True)
    tenant_id = models.IntegerField()          # mirrors Tenant.id — no FK across DBs
    db_name   = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "staff_email_index"

    def __str__(self):
        return f"{self.email} → {self.db_name}"


class StaffMobileIndex(models.Model):
    """
    Registry-level lookup table: mobile number → tenant database.

    Written atomically when a StaffUser is created (via invite or provisioning).
    Read by StaffLoginView to route login to the correct tenant DB without
    requiring the user to know or type their hospital subdomain. Replaces
    StaffEmailIndex — staff registration/login is mobile-based, not email-based.

    Architecture note (from design spec):
      Request → Authenticated User → Profile → Hospital → DB Name → Tenant DB
      No subdomain in login form. No DNS records needed. DB name is immutable.

    Rules:
      - mobile is globally unique across the platform (one staff mobile = one hospital)
      - db_name must NOT be editable after creation
      - Deleted only if the staff account is permanently removed (medical records law: never)
    """
    mobile    = models.CharField(max_length=15, unique=True, db_index=True)
    tenant_id = models.IntegerField()          # mirrors Tenant.id — no FK across DBs
    db_name   = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "staff_mobile_index"

    def __str__(self):
        return f"{self.mobile} → {self.db_name}"


class PatientIdentity(models.Model):
    """
    Single source of truth for patient identity across all tenants.
    Created on first registration; reused on subsequent registrations at any hospital.

    Dependent patients (children, or anyone registered without their own
    mobile number) do NOT get a mobile_hash — a patient record must exist
    independently of whether that person has a login/mobile of their own.
    Their identity is instead deduplicated via guardian_mobile_hash + a
    PatientRelationship row to whichever adult identity registered them, so
    the same child doesn't get a second, disconnected AWPID the next time a
    different hospital's front desk adds them under the same guardian.
    """
    awpid               = models.CharField(max_length=30, unique=True, db_index=True)
    full_name           = models.CharField(max_length=200)
    date_of_birth       = models.DateField(null=True, blank=True)
    gender              = models.CharField(max_length=10, blank=True)  # M/F/O
    # Null (not blank-string) for dependents with no mobile of their own —
    # Postgres allows multiple NULLs under a unique constraint, so this
    # still prevents two *adults* from colliding while never forcing a
    # dependent into a fake shared hash.
    mobile_hash         = models.CharField(max_length=64, unique=True, db_index=True, null=True, blank=True)
    # Set only for dependents — hash of the guardian's mobile at the time of
    # registration, so "who are this guardian's family members" can be
    # answered without a second contact table (DPDP: no plain mobile stored
    # here either, same as mobile_hash above).
    guardian_mobile_hash = models.CharField(max_length=64, blank=True, db_index=True)
    is_dependent        = models.BooleanField(default=False)
    email               = models.EmailField(blank=True)
    blood_group         = models.CharField(max_length=5, blank=True)
    preferred_language  = models.CharField(max_length=10, default="en")
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "patient_identity"

    def __str__(self):
        return f"{self.awpid} — {self.full_name}"


class PatientRelationship(models.Model):
    """
    Links a dependent patient identity to the guardian identity who
    registered them — the cross-hospital fact "Ananya is Ramesh's daughter"
    that lets a second hospital find and reuse Ananya's existing AWPID
    instead of creating a disconnected duplicate, the same way mobile-based
    dedup works for adults.

    Deliberately keyed by AWPID, not a DB foreign key — PatientIdentity rows
    are the only cross-tenant-safe identity reference; relationships are a
    registry-level (not per-hospital) fact, same scope as PatientIdentity.
    """
    REL_CHOICES = [
        ("child", "Child"), ("parent", "Parent"), ("spouse", "Spouse"),
        ("sibling", "Sibling"), ("ward", "Ward"), ("other", "Other"),
    ]
    dependent_awpid = models.CharField(max_length=30, db_index=True)
    guardian_awpid  = models.CharField(max_length=30, db_index=True)
    relationship    = models.CharField(max_length=20, choices=REL_CHOICES, default="other")
    is_primary      = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "patient_relationship"
        unique_together = [("dependent_awpid", "guardian_awpid")]

    def __str__(self):
        return f"{self.dependent_awpid} ({self.relationship} of {self.guardian_awpid})"


class SharedDiagnosis(models.Model):
    """
    Sanitized diagnosis copy written from any tenant on encounter close.
    What is shared: clinical content (what + when).
    What is NEVER shared: source_tenant_id, doctor identity, hospital name.
    """
    awpid           = models.CharField(max_length=30, db_index=True)
    icd10_code      = models.CharField(max_length=20, blank=True)
    description     = models.TextField(blank=True)
    clinical_status = models.CharField(max_length=20, default="active")  # FHIR R4
    onset_date      = models.DateField(null=True, blank=True)
    source_tenant_id= models.IntegerField()   # stored internally, NEVER returned to other tenants
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_diagnosis"


class SharedPrescription(models.Model):
    """
    One row per finalized prescription (header). Items are stored in SharedPrescriptionItem.
    """
    awpid            = models.CharField(max_length=30, db_index=True)
    prescribed_on    = models.DateField()
    source_tenant_id = models.IntegerField()
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_prescription"


class SharedPrescriptionItem(models.Model):
    """Drug line item for a SharedPrescription."""
    prescription     = models.ForeignKey(SharedPrescription, on_delete=models.CASCADE,
                                         related_name="items")
    drug_name        = models.CharField(max_length=200)
    dose             = models.CharField(max_length=50, blank=True)
    unit             = models.CharField(max_length=20, blank=True)
    frequency        = models.CharField(max_length=50, blank=True)
    route            = models.CharField(max_length=50, blank=True)
    duration_days    = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_prescription_item"


class SharedLabResult(models.Model):
    """
    Sanitized lab report copy written when a report is delivered.
    result_summary is free text / structured JSON; file_url is optional.

    file_data/mime_type hold the actual result file as a base64 data URI —
    file_url is a URLField (200-char, URL-validated) so it can't hold one;
    added alongside rather than repurposed, since nothing currently populates
    file_url and there's no reason to risk breaking it.
    """
    awpid            = models.CharField(max_length=30, db_index=True)
    test_name        = models.CharField(max_length=200)
    result_summary   = models.TextField(blank=True)
    file_url         = models.URLField(blank=True)
    file_data        = models.TextField(blank=True)
    mime_type        = models.CharField(max_length=100, blank=True)
    delivered_at     = models.DateTimeField()
    source_tenant_id = models.IntegerField()
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_lab_result"


class SharedAllergy(models.Model):
    """Written when an allergy is recorded or updated."""
    awpid             = models.CharField(max_length=30, db_index=True)
    substance         = models.CharField(max_length=200)
    reaction          = models.TextField(blank=True)
    severity          = models.CharField(max_length=20, blank=True)  # mild/moderate/severe
    is_active         = models.BooleanField(default=True)
    source_tenant_id  = models.IntegerField()
    recorded_at       = models.DateTimeField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_allergy"


class SharedDocument(models.Model):
    """
    Patient-attached document — old lab reports, scans, discharge summaries,
    prescriptions from elsewhere — uploaded by the patient via the portal (no
    tenant context) or by staff during a visit. Stored here (not per-tenant)
    so it's visible to any hospital's doctor via the shared-history sidebar,
    same as SharedLabResult etc.

    file_data is a base64 data URI — this project has no object storage
    configured yet, so binary content is stored inline like StaffUser.photo.
    Kept out of get_shared_history()'s summary list (fetched separately by id)
    to keep that payload light.
    """
    DOC_TYPE_CHOICES = [
        ("lab_report",         "Lab Report"),
        ("prescription",       "Prescription"),
        ("scan",               "Scan / Imaging"),
        ("discharge_summary",  "Discharge Summary"),
        ("other",              "Other"),
    ]
    UPLOADED_BY_CHOICES = [
        ("patient", "Patient"),
        ("staff",   "Staff"),
    ]

    awpid            = models.CharField(max_length=30, db_index=True)
    title            = models.CharField(max_length=200)
    doc_type         = models.CharField(max_length=20, choices=DOC_TYPE_CHOICES, default="other")
    file_name        = models.CharField(max_length=255, blank=True)
    mime_type        = models.CharField(max_length=100, blank=True)
    file_data        = models.TextField()   # base64 data URI
    uploaded_by      = models.CharField(max_length=10, choices=UPLOADED_BY_CHOICES, default="patient")
    source_tenant_id = models.IntegerField(null=True, blank=True)  # null when patient-uploaded
    # Links an "outside" upload back to the LabRequest that prompted it, e.g.
    # "labreq:aw_sunrise_clinic:42" — lets the doctor's order card show the
    # attached report inline instead of only in the generic documents list.
    source_ref       = models.CharField(max_length=120, blank=True, db_index=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_document"

    def __str__(self):
        return f"{self.awpid} — {self.title}"


class SharedVital(models.Model):
    """
    Sanitized vital snapshot written on finalization.
    All numeric fields are nullable — only measured fields are populated.
    """
    awpid             = models.CharField(max_length=30, db_index=True)
    recorded_at       = models.DateTimeField()
    source            = models.CharField(max_length=20, default="clinic")  # clinic / home
    bp_systolic       = models.SmallIntegerField(null=True, blank=True)
    bp_diastolic      = models.SmallIntegerField(null=True, blank=True)
    pulse_rate        = models.SmallIntegerField(null=True, blank=True)
    spo2              = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    temperature       = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    weight_kg         = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    height_cm         = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    resp_rate         = models.SmallIntegerField(null=True, blank=True)
    blood_sugar_mgdl  = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    source_tenant_id  = models.IntegerField()
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_vital"


class BlacklistedToken(models.Model):
    """
    JWT revocation list. Populated on logout (or admin-forced revocation).
    Checked on every authenticated request by core.authentication —
    this is what makes "log out" actually invalidate a still-unexpired token.
    Rows are safe to prune once expires_at has passed.
    """
    jti        = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "blacklisted_token"

    def __str__(self):
        return self.jti


class PatientAccount(models.Model):
    """
    Patient portal login account (registry DB — global, cross-tenant).
    Password hashed with Django's hashers. Linked to PatientIdentity via awpid.

    Login identifier is mobile (or awpid), not email — email is kept as an
    optional field (still shown/editable on My Profile, useful for
    notifications) but is no longer unique-enforced as a login key, and
    registration no longer requires it.
    """
    awpid         = models.CharField(max_length=30, unique=True, db_index=True)
    full_name     = models.CharField(max_length=200)
    # Optional now — mobile is the login identifier. null=True (not just
    # blank=True) so multiple accounts with no email don't collide under the
    # unique constraint (Postgres allows many NULLs, not many '').
    email         = models.EmailField(unique=True, db_index=True, blank=True, null=True)
    mobile        = models.CharField(max_length=15, unique=True, db_index=True)
    password      = models.CharField(max_length=128)
    gender        = models.CharField(max_length=1, blank=True)   # M/F/O
    date_of_birth = models.DateField(null=True, blank=True)
    # Base64 data URI, same storage pattern as StaffUser.photo — no object
    # storage configured yet, fine for avatar-sized images.
    photo         = models.TextField(blank=True)
    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    last_login    = models.DateTimeField(null=True, blank=True)
    # Account-level emergency contact — asked once, applies across every
    # hospital this account books at (unlike Patient.emergency_contact_*,
    # which is per-tenant and only exists once a local Patient row is
    # created). Kept here so it's visible/editable from My Profile even
    # before the patient's first booking anywhere.
    emergency_contact_name     = models.CharField(max_length=200, blank=True)
    emergency_contact_phone    = models.CharField(max_length=15, blank=True)
    emergency_contact_relation = models.CharField(max_length=30, blank=True)

    class Meta:
        app_label = "registry"
        db_table  = "patient_account"

    def set_password(self, raw):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw)

    def check_password(self, raw):
        from django.contrib.auth.hashers import check_password
        return check_password(raw, self.password)

    def __str__(self):
        return f"{self.email} ({self.awpid})"


class PortalBooking(models.Model):
    """
    Registry-side record of a booking made via the patient portal.
    The authoritative appointment lives in the tenant DB; this row lets the
    patient list their bookings across hospitals without scanning every tenant.
    """
    account         = models.ForeignKey(PatientAccount, on_delete=models.CASCADE,
                                        related_name="bookings")
    tenant_id       = models.IntegerField(db_index=True)
    db_name         = models.CharField(max_length=100, db_index=True)
    hospital_name   = models.CharField(max_length=200)
    appointment_id  = models.UUIDField()
    doctor_name     = models.CharField(max_length=255, blank=True)
    # Which patient this booking is actually for — the account owner by
    # default, or a linked family member (see PatientRelationship). Blank
    # patient_awpid on older rows means "the account owner" (back-compat).
    patient_awpid   = models.CharField(max_length=30, blank=True)
    patient_name    = models.CharField(max_length=200, blank=True)
    scheduled_date  = models.DateField()
    chief_complaint = models.TextField(blank=True)
    status          = models.CharField(max_length=15, default="scheduled", db_index=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "portal_booking"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.account.email} @ {self.hospital_name} on {self.scheduled_date}"
