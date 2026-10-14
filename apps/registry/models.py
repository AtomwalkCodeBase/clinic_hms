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

import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone


# StaffEmailIndex was retired (v7 table-count redesign). It mapped
# email -> tenant DB before registration/login moved to mobile number (see
# StaffMobileIndex below). Checked before removal: it was still written by
# two demo/seed commands (add_cardiologist_cedar.py, seed_full_demo.py --
# now updated to stop), and it had no FK back to a specific StaffUser, so
# there was no well-defined way to migrate its historical rows into
# StaffMobileIndex.email (itself a live field for an unrelated feature).
# Historical rows were discarded rather than migrated -- nothing reads this
# table today, so nothing is lost functionally.


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
    # Optional second identifier — lets staff log in with email instead of
    # mobile, resolving to the same tenant DB. null=True (not blank string)
    # so multiple staff without an email don't collide against the unique
    # constraint. Kept on this same index table rather than a separate
    # StaffEmailIndex (see deprecated model above) to avoid fragmenting
    # cross-tenant identity resolution across two similar tables.
    email     = models.EmailField(max_length=254, unique=True, null=True, blank=True, db_index=True)
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

    # ── Portal login ────────────────────────────────────────────────────────────
    # A person who has signed up to the patient portal has these filled in (password != ""); a walk-in registered
    # by a front desk does not. This used to be a separate patient_account table keyed by the same AWPID. Login is
    # by mobile (or AWPID / email): the number typed is scrambled and matched on mobile_hash, so the plain number is
    # never stored here.
    password      = models.CharField(max_length=128, blank=True)
    photo         = models.TextField(blank=True)      # base64 data URI, same pattern as StaffUser.photo
    is_active     = models.BooleanField(default=True)
    last_login    = models.DateTimeField(null=True, blank=True)
    # Account-level emergency contact: asked once, applies at every hospital this person books at (unlike the
    # per-hospital Patient.emergency_contact_*).
    emergency_contact_name     = models.CharField(max_length=200, blank=True)
    emergency_contact_phone    = models.CharField(max_length=15, blank=True)
    emergency_contact_relation = models.CharField(max_length=30, blank=True)

    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "patient_identity"

    def set_password(self, raw):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw)

    def check_password(self, raw):
        from django.contrib.auth.hashers import check_password
        return check_password(raw, self.password)

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
    # Pediatric-only measurement, mirrors apps.opd.models.Vitals.head_circumference_cm
    # — only populated when the source Vitals row had it set (i.e. for minors).
    head_circumference_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
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


def mobile_hash_of(raw):
    """The scrambled form of a mobile number as typed: what hospitals and the login match on."""
    from core.utils.hashing import hash_mobile, normalize_mobile
    return hash_mobile(normalize_mobile(raw))


class _AccountQuerySet(models.QuerySet):
    def with_mobile(self, raw):
        """The accounts whose mobile number is the one typed (matched by its scrambled form); none if it isn't a phone number."""
        try:
            return self.filter(mobile_hash=mobile_hash_of(raw))
        except ValueError:
            return self.none()

    def create(self, **fields):
        """An account is a login on an identity: reuse the identity with this AWPID if there is one."""
        if "mobile" in fields:                                  # the number is kept only in scrambled form
            fields["mobile_hash"] = mobile_hash_of(fields.pop("mobile"))
        identity, _ = PatientIdentity._base_manager.using(self.db).get_or_create(
            awpid=fields["awpid"], defaults={"full_name": fields.get("full_name") or "Patient"})
        for name, value in fields.items():
            setattr(identity, name, value)
        identity.save(using=self.db)
        return self.get(pk=identity.pk)


class _AccountManager(models.Manager.from_queryset(_AccountQuerySet)):
    def get_queryset(self):
        return super().get_queryset().exclude(password="")


class PatientAccount(PatientIdentity):
    """
    A patient identity that can log in to the portal (password set). Same row and table as PatientIdentity
    (patient_identity); this class only narrows queries to people who have a login, so the portal and auth code
    keep saying "account". The row id is both the account id and the identity id.
    """
    objects = _AccountManager()

    class Meta:
        proxy = True
        app_label = "registry"


class OTPCode(models.Model):
    """
    One-time-password codes for every OTP flow in the system — staff and
    patient password reset, patient self-registration verification,
    day-to-day passwordless patient login, and re-verification before a
    patient changes their registered mobile number.

    Lives in the registry ('default') DB rather than a tenant DB — the same
    reason BlacklistedToken and StaffMobileIndex live here: OTP requests
    happen before a tenant is resolved (or, for patients, there is never a
    tenant at all), so a per-tenant table can't be the source of truth here.

    A single generic model (rather than one table per flow) because every
    flow needs the exact same shape — identifier, channel, hashed code,
    expiry, attempt counter — and the only thing that differs is *what
    happens once verified*, which is encoded in `purpose` and resolved by
    the calling view, not by this model.

    Security notes:
      - code_hash stores SHA-256(code + OTP_HASH_PEPPER), never the raw
        code — see core/otp.py. A leaked DB row can't be used to log in.
      - attempts is capped (core.otp.MAX_VERIFY_ATTEMPTS) so a code can't be
        brute-forced within its validity window.
      - is_used is set the moment a code is successfully verified, so the
        same code can never be replayed even before it expires.
      - Verifying a code does NOT by itself complete the action (reset a
        password, create an account, log in) — verify_otp() hands back a
        short-lived signed JWT ("action token", see core.otp.make_action_token)
        that the next-step endpoint must present. This mirrors the
        signed-JWT "token_type" convention the staff setup-password token
        uses (apps.auth_app.views.SetupPasswordView) rather than inventing a
        second one.
    """
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
    # The mobile number or email address the code was actually sent to —
    # for password_reset_staff this is the staff member's phone (their
    # login identifier, always present); for the rest it's whatever the
    # caller supplied (mobile or email, auto-detected by "@").
    identifier  = models.CharField(max_length=254, db_index=True)
    channel     = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    code_hash   = models.CharField(max_length=64)

    # Who this code resolves to, once verified — resolved at request-otp
    # time so verify-otp doesn't need to re-run the (purpose-specific)
    # lookup logic. Blank/null for registration_patient, where there is no
    # existing user yet.
    target_type = models.CharField(max_length=10, blank=True)   # "staff" / "patient" / ""
    target_id   = models.IntegerField(null=True, blank=True)
    # Tenant db_name — only meaningful for target_type="staff" (a StaffUser
    # id alone is ambiguous across tenant databases).
    target_db   = models.CharField(max_length=100, blank=True)

    attempts    = models.PositiveSmallIntegerField(default=0)
    is_used     = models.BooleanField(default=False)
    expires_at  = models.DateTimeField(db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "otp_code"
        indexes = [models.Index(fields=["identifier", "purpose", "-created_at"])]

    def __str__(self):
        return f"{self.purpose} → {self.identifier} ({'used' if self.is_used else 'active'})"


class PortalBooking(models.Model):
    """
    Registry-side record of a booking made via the patient portal.
    The authoritative appointment lives in the tenant DB; this row lets the
    patient list their bookings across hospitals without scanning every tenant.
    """
    account         = models.ForeignKey(PatientIdentity, on_delete=models.CASCADE,
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


class EmergencyAccessLog(models.Model):
    """
    Audit trail for the "Emergency QR" feature (see core/emergency_access.py)
    — every time a patient generates an emergency QR code, and every time
    someone actually opens the resulting link, gets one row here. Lives in
    the registry DB (not a tenant DB) because the whole point of this
    feature is it has NO tenant context: it can be scanned by a doctor at a
    hospital that isn't even on this platform.

    Two event types, not two models — a "generated" row and its later
    "viewed" row(s) share every other field, and a patient's own "how many
    times has this been looked at" view (if ever surfaced) wants both kinds
    interleaved by time, not queried separately.
    """
    EVENT_GENERATED = "generated"
    EVENT_VIEWED    = "viewed"
    # Reused by Share Records for a breadcrumb whenever the patient changes
    # their shared-records privacy or reveals a private record for one visit
    # (see apps/patients/records_share_views.py). Kept here rather than a new
    # table so a patient's "who has looked at what" view stays one query.
    EVENT_PRIVACY   = "privacy"
    EVENT_CHOICES = [
        (EVENT_GENERATED, "QR code generated"),
        (EVENT_VIEWED,     "Summary viewed"),
        (EVENT_PRIVACY,    "Shared-records privacy changed"),
    ]

    awpid      = models.CharField(max_length=30, db_index=True)
    event      = models.CharField(max_length=24, choices=EVENT_CHOICES)
    # Which account actually triggered generation — blank for "viewed" rows,
    # since a scan is by definition someone without an account here.
    generated_by_account_id = models.IntegerField(null=True, blank=True)
    # True only for EVENT_GENERATED rows — durable proof the account holder
    # explicitly confirmed the consent prompt (see PortalEmergencyTokenView)
    # before this specific token was minted, not just a standing preference.
    # Meaningless/always False on EVENT_VIEWED rows (a scan has no consent
    # step of its own — consent already happened at generation time).
    consent_confirmed = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "emergency_access_log"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.awpid} — {self.event} @ {self.created_at}"


def new_pad_token():
    return secrets.token_urlsafe(32)


class ConsultSession(models.Model):
    """
    A live handwriting session for ONE consultation. The doctor opens it from
    an encounter (EncounterConsultSessionView), scans this session's QR (its
    own `token`), and writes on a phone across two tabs — Prescription and Internal Note
    — with every stroke autosaved here. It stays `open`, surviving the pad
    being closed and re-scanned, until the encounter is signed.

    Registry DB (like SharedDocument / the retired ConsultPadSubmission) so
    the public, tenant-context-free phone endpoint can read/write it via a
    plain `.using("default")`. Scoped by no-FK id fields, this codebase's
    cross-DB convention:
      encounter_id  → the tenant-DB OPDEncounter this belongs to
      tenant_id     → which hospital

    `*_pages` hold the raw canvas as "data:image/png;base64,..." strings —
    session scratch, discarded when status flips to signed/expired. The
    permanent record is the encounter's SOAP fields + the Prescription (+ its
    stored PDF). `*_recognised` hold the vision-LLM output the web pulls in
    via "Load handwritten note".
    """
    STATUS_OPEN    = "open"
    STATUS_SIGNED  = "signed"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_OPEN,    "Open"),
        (STATUS_SIGNED,  "Signed"),
        (STATUS_EXPIRED, "Expired"),
    ]

    # The secret in the QR / link the phone opens (no login). One per consultation, so it also says which hospital and
    # which patient the phone is writing for.
    token           = models.CharField(max_length=64, unique=True, db_index=True, default=new_pad_token)
    awpid           = models.CharField(max_length=30, db_index=True)
    tenant_id       = models.IntegerField(db_index=True)
    encounter_id    = models.UUIDField(db_index=True)
    doctor_user_id  = models.UUIDField(null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_OPEN, db_index=True)

    # Prescription tab
    rx_pages      = models.JSONField(default=list, blank=True)
    # { items:[{drug_name,dosage,frequency,route,duration_days,instructions}],
    #   raw_text, status: idle|pending|done|failed, error, at }
    rx_recognised = models.JSONField(null=True, blank=True)

    # Internal Note tab
    note_pages      = models.JSONField(default=list, blank=True)
    # { subjective,objective,assessment,plan, diagnoses:[{code,description}],
    #   investigations, advice, follow_up_days, raw_text,
    #   status: idle|pending|done|failed, error, at }
    note_recognised = models.JSONField(null=True, blank=True)
    # S3 key of the Internal Note's handwriting, archived as a PDF when the encounter is signed. Doctor-only:
    # it is kept here, on the consult pad, and is never a patient document (apps.records knows nothing of it).
    note_pdf = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    signed_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "registry"
        db_table  = "consult_session"
        ordering  = ["-created_at"]
        indexes = [
            models.Index(fields=["encounter_id", "status"]),
            models.Index(fields=["awpid", "tenant_id", "status"]),
        ]

    def __str__(self):
        return f"ConsultSession {self.id} enc={self.encounter_id} [{self.status}]"


class RecordsShareRequest(models.Model):
    """
    "Records Access" — the doctor-has-a-laptop half of break-glass record
    sharing. Distinct from the "Emergency QR" flow (EmergencyAccessLog /
    core.emergency_access), which is stateless: there the *patient's* phone
    shows a signed-JWT QR and any camera opens a read-only page.

    This flow is the inverse and therefore stateful:
      1. A doctor opens the public /records-access page on a laptop. A row is
         created here (status=pending) with a random `token` (in the QR/URL)
         and a short numeric `code` fallback.
      2. The patient scans the QR with their phone, sees who is asking, and
         approves — binding their `awpid` and starting a 2-hour window
         (`expires_at`). Until then the token grants nothing.
      3. The laptop polls `token` and, once approved, renders the patient's
         navigable shared history + Rx & Reports vault, read-only.
      4. The patient can end it early (status=ended); it otherwise lapses at
         `expires_at` (status flips lazily on the next read).

    Downloads are gated one file at a time: the doctor asking to download a
    document sets `pending_download_id`; the patient allows it on their phone,
    moving that id into `download_unlocked_ids`.

    Registry DB, like SharedDocument / ConsultSession — the public endpoints
    read/write it with a plain `.using("default")`, no tenant context.
    """
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
    # The 6-digit "front door" the patient reads out to the doctor. The doctor
    # types it at clinic.atomwalk.com/s to load this pending session on their
    # laptop. It only ever resolves a still-pending grant — it locates the
    # session, it is not the approval check (see `pairing`).
    code        = models.CharField(max_length=8, db_index=True)
    # What the doctor typed on the start screen — "Dr. Rao, City Clinic".
    # Free text, shown to the patient in the approval prompt. Optional.
    requester_label = models.CharField(max_length=120, blank=True)

    # ── laptop binding ────────────────────────────────────────────────────
    # Set the first time a browser "claims" this session (RecordsShareClaimView)
    # — either by typing `code` at /s or by opening a full link directly.
    opened_at   = models.DateTimeField(null=True, blank=True)
    # sha256 of the random device token handed to the claiming browser. Once
    # set, every public /records-share/<token>/… read must carry that token in
    # the X-Share-Device header — so a leaked link/QR alone reads nothing.
    device_hash = models.CharField(max_length=64, blank=True)
    # 6-char code minted at claim time, shown on the doctor's screen (inside
    # the QR as ?p=… and as text beneath it). The patient's app lifts it off
    # that screen — by scanning, or the patient types it — and sends it with
    # the approval, proving they are looking at the doctor's screen. Replaces
    # the old "type the numeric code" step.
    pairing     = models.CharField(max_length=12, blank=True)

    # Empty until a patient approves; then it's the awpid whose records this
    # grant exposes. A grant only ever covers the approving patient (no
    # family-member targeting in v1).
    awpid       = models.CharField(max_length=30, blank=True, db_index=True)
    status      = models.CharField(max_length=12, choices=STATUS_CHOICES,
                                   default=STATUS_PENDING, db_index=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    decided_at  = models.DateTimeField(null=True, blank=True)
    expires_at  = models.DateTimeField(null=True, blank=True)
    # Doctor-side poll heartbeat — lets the patient's "who has access" view
    # show whether the doctor is actively looking right now.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_ip  = models.GenericIPAddressField(null=True, blank=True)

    # SharedDocument ids the patient has released for download on this grant.
    download_unlocked_ids = models.JSONField(default=list, blank=True)
    # SharedDocument ids the patient has revealed for THIS visit only — a
    # per-session override of their standing RecordsPrivacy. Cleared when the
    # grant ends, so the next share starts from full standing privacy again.
    shown_private_ids = models.JSONField(default=list, blank=True)
    # A bulk, session-scoped alternative to shown_private_ids: chosen once at
    # approval time (RecordsShareDecisionView) instead of revealing records
    # one at a time. True means "skip standing RecordsPrivacy entirely for
    # this grant" — this specific doctor sees everything, including private
    # records, for this visit only. Doesn't touch RecordsPrivacy itself, so
    # every future share (with anyone else) still starts from the patient's
    # normal standing privacy, same as before this field existed.
    share_all   = models.BooleanField(default=False)
    # A single SharedDocument id the doctor has asked to download, awaiting
    # the patient's decision. Cleared once decided.
    pending_download_id = models.IntegerField(null=True, blank=True)
    # Wrong-`code` tries at approval time. The patient reads the 6-digit code
    # off the doctor's screen after scanning; too many misses locks the
    # session (someone guessing without seeing that screen).
    code_attempts = models.PositiveSmallIntegerField(default=0)

    MAX_CODE_ATTEMPTS = 5
    # A pending session the doctor never opens is only useful for a few
    # minutes — after this it can't be claimed, which keeps the 6-digit
    # front-door code from being worth guessing and sweeps up abandoned rows.
    PENDING_TTL_MINUTES = 20

    @property
    def pending_stale(self):
        return (
            self.status == self.STATUS_PENDING
            and timezone.now() - self.created_at
            > timedelta(minutes=self.PENDING_TTL_MINUTES)
        )

    def device_matches(self, raw_token):
        """True when `raw_token` is the device token this session was claimed
        with. Vacuously true until the session has been claimed at all."""
        if not self.device_hash:
            return True
        if not raw_token:
            return False
        import hashlib
        return hashlib.sha256(raw_token.encode()).hexdigest() == self.device_hash

    class Meta:
        app_label = "registry"
        db_table  = "records_share_request"
        ordering  = ["-created_at"]
        indexes = [
            models.Index(fields=["awpid", "status"]),
        ]

    def __str__(self):
        return f"RecordsShareRequest {self.code} [{self.status}] awpid={self.awpid or '—'}"

    @property
    def is_live(self):
        """Approved and still inside the 2-hour window."""
        return (
            self.status == self.STATUS_APPROVED
            and self.expires_at is not None
            and timezone.now() < self.expires_at
        )

    def lapse_if_due(self):
        """Flip an approved-but-past-window grant to expired. Returns True if it changed."""
        if (
            self.status == self.STATUS_APPROVED
            and self.expires_at is not None
            and timezone.now() >= self.expires_at
        ):
            self.status = self.STATUS_EXPIRED
            self.save(using="default", update_fields=["status"])
            return True
        return False

    def seconds_left(self):
        if not self.expires_at:
            return 0
        return max(0, int((self.expires_at - timezone.now()).total_seconds()))


class RecordsPrivacy(models.Model):
    """
    Patient-controlled privacy over what a doctor sees when records are shared
    (Share Records / RecordsShareRequest). One lazily-created row per awpid,
    read by every share session.

    "Private" is sticky: once hidden here, a record or a whole category stays
    hidden in *every* future share until the patient un-hides it. The only way
    a private record reaches a doctor is a per-visit reveal on the live grant
    (RecordsShareRequest.shown_private_ids), which clears when that visit ends.

    hidden_categories / hidden_kinds are LIVE rules — a matching document that
    arrives next month is hidden too, automatically.

    Registry DB, keyed by awpid, like the Shared* HIE tables.
    """
    SECTIONS = ("summary", "vitals", "diagnoses", "vaccinations")

    awpid             = models.CharField(max_length=30, unique=True, db_index=True)
    hide_all          = models.BooleanField(default=False)
    hidden_doc_ids    = models.JSONField(default=list, blank=True)   # SharedDocument ids
    hidden_categories = models.JSONField(default=list, blank=True)   # report_categories slugs
    hidden_kinds      = models.JSONField(default=list, blank=True)   # SharedDocument.doc_type values
    hidden_sections   = models.JSONField(default=list, blank=True)   # subset of SECTIONS
    updated_at        = models.DateTimeField(auto_now=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "registry"
        db_table  = "records_privacy"

    def __str__(self):
        return f"RecordsPrivacy awpid={self.awpid} hide_all={self.hide_all}"

    @classmethod
    def for_awpid(cls, awpid):
        obj, _ = cls.objects.using("default").get_or_create(awpid=awpid)
        return obj


# The pediatric models (birth history, vaccinations, schedules, milestones) are defined in apps/patients/pediatrics/models.py
# and keep app_label "registry"; imported here so `from apps.registry.models import ...` keeps working.
from apps.patients.pediatrics.models import (  # noqa: E402,F401
    Schedule, ScheduleRule, SharedBirthHistory, SharedMilestoneRecord, SharedVaccination,
    VaccinationSchedule, VaccinationScheduleRule, MilestoneSchedule, MilestoneScheduleRule,
)
