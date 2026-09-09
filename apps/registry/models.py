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

import uuid

from django.db import models


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

    # Permanent "consultation scratchpad" QR token — a doctor mid-consult
    # shows this patient's QR, scans it on a phone, hand-writes a SOAP note
    # with a finger, and it's filed back against this patient as a PDF (see
    # apps/patients/consult_pad_views.py). Unlike the emergency token this
    # one never expires and is the SAME code every visit — one QR per
    # patient, so it can be printed on a card / stuck in a paper file.
    # null until a doctor first opens the QR for this patient; rotate it
    # (PatientConsultPadQRView ?rotate=1) to revoke a leaked code.
    consult_pad_token   = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    # The last hospital (Tenant.id) that opened this patient's pad QR. The
    # pad submission itself is unauthenticated (it's reached by scanning a
    # public QR), so it has no tenant context of its own — this is how a
    # submitted note gets stamped with "which hospital captured it", which
    # in turn is what lets that hospital always see its own consult notes in
    # the patient history even before the patient has consented to
    # cross-hospital record sharing.
    consult_pad_owner_tenant_id = models.IntegerField(null=True, blank=True)

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
        ("consult_note",       "Consultation Note"),
        ("other",              "Other"),
    ]
    # Doc types that are the hospital's own internal record — surfaced to
    # clinicians (patient-history sidebar) but NEVER in the patient portal.
    # Every patient-facing SharedDocument query must exclude these; the
    # handwritten internal note archived on encounter sign is the reason this
    # exists (apps.opd.views._store_handwriting_pdfs).
    STAFF_ONLY_DOC_TYPES = ("consult_note",)

    UPLOADED_BY_CHOICES = [
        ("patient", "Patient"),
        ("staff",   "Staff"),
    ]

    awpid            = models.CharField(max_length=30, db_index=True)
    title            = models.CharField(max_length=200)
    doc_type         = models.CharField(max_length=20, choices=DOC_TYPE_CHOICES, default="other")
    file_name        = models.CharField(max_length=255, blank=True)
    mime_type        = models.CharField(max_length=100, blank=True)
    file_data        = models.TextField()   # S3 object key (older rows: base64 data URI)
    uploaded_by      = models.CharField(max_length=10, choices=UPLOADED_BY_CHOICES, default="patient")
    source_tenant_id = models.IntegerField(null=True, blank=True)  # null when patient-uploaded
    # Links an "outside" upload back to the LabRequest that prompted it, e.g.
    # "labreq:aw_sunrise_clinic:42" — lets the doctor's order card show the
    # attached report inline instead of only in the generic documents list.
    source_ref       = models.CharField(max_length=120, blank=True, db_index=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    # ── My Reports pipeline (HMS-DOC) ─────────────────────────────────────
    # public_document_id: the quotable hospital id (rx_number / report_number)
    #   this row corresponds to. Set on the QR-verified path; blank for
    #   external uploads. Used together with content_hash for de-duplication.
    public_document_id = models.CharField(max_length=40, blank=True, db_index=True)
    # document_date: the date printed ON the document (extracted or entered),
    #   distinct from created_at (when it entered the vault).
    document_date      = models.DateField(null=True, blank=True)
    # content_hash: SHA-256 of the ORIGINAL uploaded bytes — exact-duplicate
    #   detection, stable across the PDF-normalisation step.
    content_hash       = models.CharField(max_length=64, blank=True, db_index=True)
    # how the doc_type was decided: qr | ocr_keyword | patient_confirmed | staff
    classification_method     = models.CharField(max_length=20, blank=True)
    classification_confidence = models.FloatField(null=True, blank=True)  # 0..1 for ocr_keyword
    # verified | unverified | needs_review | rejected
    verification_status = models.CharField(max_length=16, default="unverified")
    # filed | unsorted — 'unsorted' rows are excluded from the patient list's
    # normal view and from get_shared_history() until the patient confirms.
    review_state       = models.CharField(max_length=12, default="filed", db_index=True)
    batch              = models.ForeignKey(
        "registry.DocumentUploadBatch", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="documents",
    )
    is_duplicate_of    = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    # free-text lab/hospital and doctor for EXTERNAL uploads
    hospital_label     = models.CharField(max_length=120, blank=True)
    doctor_label       = models.CharField(max_length=120, blank=True)
    # soft links into the tenant DBs so the detail view can open structured data
    prescription_ref   = models.CharField(max_length=60, blank=True)  # "<tenant_db>:<uuid>"
    lab_report_ref     = models.CharField(max_length=60, blank=True)  # "<tenant_db>:<id>"
    # "hide from my documents" (hospital-generated rows) vs real delete (patient uploads)
    hidden_at          = models.DateTimeField(null=True, blank=True)
    deleted_at         = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_document"
        indexes = [
            models.Index(fields=["awpid", "review_state"], name="shared_doc_awpid_review_idx"),
            models.Index(fields=["awpid", "doc_type", "document_date"], name="shared_doc_awpid_type_date_idx"),
            models.Index(fields=["awpid", "content_hash"], name="shared_doc_awpid_hash_idx"),
        ]

    def __str__(self):
        return f"{self.awpid} — {self.title}"


class DocumentUploadBatch(models.Model):
    """
    One folder / multi-file upload from the patient portal. The client uploads
    every file straight to S3 (presigned PUT) and this row plus its
    DocumentUploadItem children track progress; the
    process_document_batches management command (cron) drains it.
    """
    STATUS_CHOICES = [
        ("pending", "Pending"), ("processing", "Processing"),
        ("done", "Done"), ("partial", "Partial"),
    ]
    METHOD_CHOICES = [
        ("folder", "Folder"), ("files", "Files"), ("photo", "Photo"), ("qr", "QR"),
    ]
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    awpid        = models.CharField(max_length=30, db_index=True)
    initiated_by = models.CharField(max_length=10, default="patient")  # patient | staff
    method       = models.CharField(max_length=12, choices=METHOD_CHOICES, default="files")
    total_files  = models.IntegerField(default=0)
    accepted     = models.IntegerField(default=0)   # filed as prescription / lab report
    unsorted     = models.IntegerField(default=0)   # parked for review
    ignored      = models.IntegerField(default=0)   # not medical / rejected
    failed       = models.IntegerField(default=0)   # validation / scan errors
    status       = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending", db_index=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    finished_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "registry"
        db_table  = "document_upload_batch"
        indexes = [models.Index(fields=["awpid", "status"], name="doc_batch_awpid_status_idx")]

    def __str__(self):
        return f"batch {self.id} [{self.status}] {self.awpid}"


class DocumentUploadItem(models.Model):
    """One file within a DocumentUploadBatch."""
    STATUS_CHOICES = [
        ("uploading", "Uploading"), ("scanning", "Scanning"),
        ("classified", "Classified"), ("filed", "Filed"), ("unsorted", "Unsorted"),
        ("ignored", "Ignored"), ("failed", "Failed"), ("duplicate", "Duplicate"),
    ]
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch             = models.ForeignKey(DocumentUploadBatch, on_delete=models.CASCADE, related_name="items")
    original_filename = models.CharField(max_length=255, blank=True)  # display only
    declared_size     = models.IntegerField(default=0)               # bytes, from the manifest
    content_hash      = models.CharField(max_length=64, blank=True)
    staging_key       = models.CharField(max_length=255, blank=True)  # S3 key under incoming/
    status            = models.CharField(max_length=14, choices=STATUS_CHOICES, default="uploading", db_index=True)
    reason            = models.CharField(max_length=160, blank=True)
    result_document   = models.ForeignKey(SharedDocument, null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name="+")
    classified_as     = models.CharField(max_length=20, blank=True)  # prescription | lab_report | not_medical
    processed_at      = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "registry"
        db_table  = "document_upload_item"
        indexes = [models.Index(fields=["batch", "status"], name="doc_item_batch_status_idx")]

    def __str__(self):
        return f"item {self.id} [{self.status}] {self.original_filename}"


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


class SharedVaccination(models.Model):
    """
    Vaccination record for a patient, visible across every hospital in the
    network — either administered by a hospital here (source="clinic",
    auto-verified since a clinician logged it directly), self-reported by
    the patient/parent with an uploaded certificate from outside the network
    (source="self_reported", starts as verification_status="pending_review"
    until a doctor or nurse at ANY hospital reviews the attached certificate
    and marks it verified or rejected — see PatientVaccinationVerifyView), or
    a doctor's ad-hoc clinical decision recorded before any administration
    happens (source="doctor_ordered" — see the state-machine note below).

    Deliberately NOT auto-verified just because it was uploaded — an
    unreviewed self-reported record must never render identically to a
    clinic-administered one in the UI; that distinction is the whole point
    of tracking verification_status separately from "does a record exist".

    file_data is a base64 data URI (same inline-storage pattern as
    SharedDocument) for the uploaded certificate image/PDF, when there is one.

    State-machine note (doctor order → nurse administers, or doctor
    declines): verification_status was originally a narrow "has this
    self-reported upload been reviewed" flag, but it's really the record's
    overall lifecycle status, so it's reused (not duplicated into a second
    field) for two more states instead of adding a parallel status column
    that would need to be kept in sync with it:
      - STATUS_ORDERED ("ordered"): a doctor recorded an ad-hoc vaccine
        recommendation (PatientVaccinationOrderView) that hasn't been given
        yet. administered_date is null until a nurse administers it
        (PatientVaccinationAdministerView), at which point the SAME row
        flips to source=SOURCE_CLINIC, verification_status=STATUS_VERIFIED,
        and administered_date is filled in — "ordered" never needed its own
        model, it's just an earlier point in one record's life.
      - STATUS_DECLINED ("declined"): a doctor marked a schedule slot as not
        clinically required for this patient (PatientVaccinationDeclineView).
        Also administered_date-less — nothing was given, nothing ever will
        be for this slot. build_roadmap() surfaces this as status="declined"
        (never "unknown", never "due_now") so the UI stops prompting for it.
    A dedicated "order status" field was considered and rejected: it would
    only ever be meaningful for source=SOURCE_DOCTOR_ORDERED rows, which is
    exactly the kind of confusing multi-purpose-field split the task brief
    warned against — verification_status already models "where is this
    record in its review/administration lifecycle" for every other source,
    so ordered/declined are just two more values of the same lifecycle.
    """
    SOURCE_CLINIC = "clinic"
    SOURCE_SELF_REPORTED = "self_reported"
    SOURCE_DOCTOR_ORDERED = "doctor_ordered"
    SOURCE_CHOICES = [
        (SOURCE_CLINIC, "Clinic administered"),
        (SOURCE_SELF_REPORTED, "Self reported"),
        (SOURCE_DOCTOR_ORDERED, "Doctor ordered"),
    ]

    STATUS_VERIFIED = "verified"
    STATUS_PENDING  = "pending_review"
    STATUS_REJECTED = "rejected"
    STATUS_ORDERED  = "ordered"
    STATUS_DECLINED = "declined"
    VERIFICATION_CHOICES = [
        (STATUS_VERIFIED, "Verified"),
        (STATUS_PENDING,  "Pending review"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_ORDERED,  "Ordered (not yet administered)"),
        (STATUS_DECLINED, "Declined / not required"),
    ]

    awpid               = models.CharField(max_length=30, db_index=True)
    vaccine_name        = models.CharField(max_length=100)
    # The default-schedule label this fulfills (e.g. "18 months"), blank if
    # it doesn't match a standard schedule slot (see vaccine_schedule.py).
    scheduled_label     = models.CharField(max_length=50, blank=True)
    # Null for an "ordered" (not yet given) or "declined" (never given)
    # record — those describe a clinical decision, not an administration
    # event, so there is no real date to store until/unless one happens.
    administered_date   = models.DateField(null=True, blank=True)
    # Only meaningful for source=SOURCE_DOCTOR_ORDERED / verification_status
    # in (STATUS_ORDERED, STATUS_DECLINED) — when the doctor recommends the
    # vaccine be given by, or blank if no target date was set.
    due_date             = models.DateField(null=True, blank=True)
    # Doctor's free-text clinical reason for an ad-hoc order or a decline —
    # e.g. "catch-up dose, missed at birth" or "contraindicated: egg allergy".
    reason               = models.TextField(blank=True)
    dose_number          = models.PositiveIntegerField(null=True, blank=True)

    source              = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_CLINIC)
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default=STATUS_VERIFIED, db_index=True)
    verified_by_name    = models.CharField(max_length=200, blank=True)  # snapshot — staff live in tenant DBs, no FK across DBs
    verified_at         = models.DateTimeField(null=True, blank=True)
    review_notes        = models.TextField(blank=True)

    file_name           = models.CharField(max_length=255, blank=True)
    mime_type            = models.CharField(max_length=100, blank=True)
    file_data            = models.TextField(blank=True)

    source_tenant_id    = models.IntegerField(null=True, blank=True)  # which hospital logged/verified this; null if purely self-reported and never reviewed
    recorded_by          = models.CharField(max_length=20, default="patient")  # "patient" or "staff"

    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "shared_vaccination"
        indexes = [models.Index(fields=["awpid", "verification_status"])]
        ordering  = ["administered_date"]

    def __str__(self):
        return f"{self.awpid} — {self.vaccine_name} ({self.verification_status})"


class VaccinationSchedule(models.Model):
    """
    A named, ordered set of vaccination rules (VaccinationScheduleRule) that
    a hospital's roadmap is built against — replaces the single hardcoded
    DEFAULT_VACCINE_SCHEDULE list in vaccine_schedule.py with a configurable,
    per-hospital schedule.

    owner_tenant_id is null for system-level templates (e.g. the "Default
    Schedule" seeded by this app's data migration from the old hardcoded
    list) and set to a Tenant.id for a hospital's own editable copy. Plain
    IntegerField, not a real FK — see the comment on Tenant.
    active_vaccination_schedule_id in apps/tenants/models.py for why this
    codebase avoids cross-app FKs even when both sides live in the same DB.

    is_template marks a schedule meant to be cloned as a starting point
    (system templates, or a hospital's own saved variant) rather than
    edited in place by every tenant that points at it — primarily relevant
    for the null-owner system templates in v1.
    """
    name            = models.CharField(max_length=200)
    description     = models.TextField(blank=True)
    owner_tenant_id = models.IntegerField(null=True, blank=True)  # null = system-level template; mirrors Tenant.id, no FK across apps
    is_template     = models.BooleanField(default=False)
    active          = models.BooleanField(default=True)  # soft-disable instead of delete
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "registry"
        db_table  = "vaccination_schedule"

    def __str__(self):
        return self.name


class VaccinationScheduleRule(models.Model):
    """
    One vaccine/dose slot within a VaccinationSchedule — e.g. "BCG, dose 1,
    Birth, min_age_days=0". build_roadmap() iterates a schedule's rules
    (ordered by sort_order) the same way it used to iterate the hardcoded
    DEFAULT_VACCINE_SCHEDULE list.

    min_age_days/max_age_days describe the recommended age window — used
    only to compute the informational "timing" (upcoming vs due_now) on a
    roadmap slot with no matching record. They are NOT used to fabricate an
    "overdue" verdict; see vaccine_schedule.py's status-semantics comment.
    """
    schedule         = models.ForeignKey(VaccinationSchedule, on_delete=models.CASCADE, related_name="rules")
    vaccine_name     = models.CharField(max_length=100)
    dose_number      = models.PositiveIntegerField(default=1)
    scheduled_label  = models.CharField(max_length=50)  # human milestone label, e.g. "Birth", "6 weeks", "9 months"
    min_age_days     = models.PositiveIntegerField()
    max_age_days     = models.PositiveIntegerField(null=True, blank=True)
    mandatory        = models.BooleanField(default=True)
    sort_order       = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "registry"
        db_table  = "vaccination_schedule_rule"
        ordering  = ["sort_order"]

    def __str__(self):
        return f"{self.schedule.name} — {self.vaccine_name} ({self.scheduled_label})"


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
        _make_invite_token pattern already used for staff invites
        (apps.auth_app.views) rather than inventing a second convention.
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
    EVENT_CHOICES = [
        (EVENT_GENERATED, "QR code generated"),
        (EVENT_VIEWED,     "Summary viewed"),
    ]

    awpid      = models.CharField(max_length=30, db_index=True)
    event      = models.CharField(max_length=10, choices=EVENT_CHOICES)
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


class ConsultSession(models.Model):
    """
    A live handwriting session for ONE consultation. The doctor opens it from
    an encounter (EncounterConsultSessionView), scans the patient's permanent
    QR, and writes on a phone across two tabs — Prescription and Internal Note
    — with every stroke autosaved here. It stays `open`, surviving the pad
    being closed and re-scanned, until the encounter is signed.

    Registry DB (like SharedDocument / the retired ConsultPadSubmission) so
    the public, tenant-context-free phone endpoint can read/write it via a
    plain `.using("default")`. Scoped by no-FK id fields, this codebase's
    cross-DB convention:
      encounter_id  → the tenant-DB OPDEncounter this belongs to
      tenant_id     → which hospital (also how the phone endpoint routes,
                      via PatientIdentity.consult_pad_owner_tenant_id)

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
