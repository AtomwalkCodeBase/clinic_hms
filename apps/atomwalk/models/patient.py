"""The people: patient (one row per person, with the portal login on it), who looks after whom, and their portal bookings."""

from django.db import models


class Patient(models.Model):
    """
    Single source of truth for patient identity across all hospitals.
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
        app_label = "atomwalk"
        db_table  = "patient"

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

    Deliberately keyed by AWPID, not a DB foreign key — Patient rows
    are the only cross-hospital-safe identity reference; relationships are a
    atomwalk-level (not per-hospital) fact, same scope as Patient.
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
        app_label = "atomwalk"
        db_table  = "patient_relationship"
        unique_together = [("dependent_awpid", "guardian_awpid")]

    def __str__(self):
        return f"{self.dependent_awpid} ({self.relationship} of {self.guardian_awpid})"


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
        identity, _ = Patient._base_manager.using(self.db).get_or_create(
            awpid=fields["awpid"], defaults={"full_name": fields.get("full_name") or "Patient"})
        for name, value in fields.items():
            setattr(identity, name, value)
        identity.save(using=self.db)
        return self.get(pk=identity.pk)


class _AccountManager(models.Manager.from_queryset(_AccountQuerySet)):
    def get_queryset(self):
        return super().get_queryset().exclude(password="")


class PatientAccount(Patient):
    """
    A patient identity that can log in to the portal (password set). Same row and table as Patient
    (patient); this class only narrows queries to people who have a login, so the portal and auth code
    keep saying "account". The row id is both the account id and the identity id.
    """
    objects = _AccountManager()

    class Meta:
        proxy = True
        app_label = "atomwalk"


class PatientBooking(models.Model):
    """
    Atomwalk-side record of a booking made via the patient portal.
    The authoritative appointment lives in the hospital DB; this row lets the
    patient list their bookings across hospitals without scanning every hospital.
    """
    account         = models.ForeignKey(Patient, on_delete=models.CASCADE,
                                        related_name="bookings")
    hospital_id       = models.IntegerField(db_index=True)
    db_name         = models.CharField(max_length=100, db_index=True)
    hospital_name   = models.CharField(max_length=200)
    appointment_id  = models.UUIDField()
    doctor_name     = models.CharField(max_length=255, blank=True)
    # Which patient this booking is actually for: the account owner by default
    # (empty), or a linked family member (see PatientRelationship).
    patient         = models.ForeignKey(Patient, null=True, blank=True, on_delete=models.CASCADE, related_name="bookings_for")
    patient_name    = models.CharField(max_length=200, blank=True)
    scheduled_date  = models.DateField()
    chief_complaint = models.TextField(blank=True)
    status          = models.CharField(max_length=15, default="scheduled", db_index=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "atomwalk"
        db_table  = "patient_booking"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"{self.account.email} @ {self.hospital_name} on {self.scheduled_date}"
