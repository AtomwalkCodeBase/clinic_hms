"""
apps/ipd/models.py
-------------------
IPD Admission — PHASE 1 ONLY (admission intake). Bed/ward allocation,
inpatient nursing, rounds/eMAR, OT, transfers, and discharge are explicitly
out of scope here — see IPD_Admission_Feature_Documentation_v2.docx's own
Scope section, and the knowledge-map's §17.0/§17.1 contradiction notes.

Two design decisions worth understanding before touching this file:

1. admission_type and admission_source are DELIBERATELY two separate
   fields, not one. Checking this against real-world hospital practice
   (not just the handover spec, which conflated them into one
   admission_type enum) showed these answer two different questions:
   "how urgent" (Emergency/Urgent/Elective/Day-care/Newborn) vs. "how did
   they arrive" (OPD Consultation/External Referral/Walk-in/Direct Order/
   Transfer-in/Ambulance/TPA-coordinated/Medical Tourism/Telemedicine/
   Involuntary-MLC). Both are free-text values validated against
   billing.OptionList — the same tenant-configurable-dropdown mechanism
   already backing Drug.form / Invoice.status / Payment.payment_mode — so
   a hospital can add or retire values without a code deploy. See
   apps/billing/models.py's OptionList docstring, and this app's
   migrations/0002_seed_admission_option_lists.py for the seeded defaults.

2. Front desk can NEVER originate an admission — only a doctor's own
   authenticated action can. AdmissionReferral is the artifact that makes
   this enforceable: it is created only by RecommendAdmissionView (IsDoctor,
   stamps recommended_by from request.user, never from client input), and
   for a referral that arrives from outside this hospital, it additionally
   requires accepted_by to be set by AcceptExternalReferralView (also
   IsDoctor) before front desk can act on it. CompleteAdmissionView (the
   only way an Admission row gets created) requires an existing, pending
   AdmissionReferral — there is no "create an Admission from scratch"
   endpoint at all, by design.
"""

import uuid
from django.db import models

from apps.org.models import StaffUser, Department, Branch
from apps.patients.models import Patient
from apps.opd.models import OPDEncounter, Appointment


class AdmissionReferral(models.Model):
    """The doctor-authored order behind an Admission. See module docstring."""

    STATUS_PENDING   = "pending"     # awaiting front-desk registration
    STATUS_CONVERTED = "converted"   # an Admission has been created from this
    STATUS_WITHDRAWN = "withdrawn"   # doctor / ordering party withdrew it before use
    STATUS_CHOICES = [
        (STATUS_PENDING,   "Pending"),
        (STATUS_CONVERTED, "Converted"),
        (STATUS_WITHDRAWN, "Withdrawn"),
    ]

    # Sources that arrive with someone else's clinical decision already
    # attached — these require a hospital doctor's own accept action
    # (accepted_by) before CompleteAdmissionView will act on the referral.
    # Kept here (not in OptionList) because it's enforcement logic, not
    # configurable master data — a hospital shouldn't be able to switch off
    # the doctor-countersign requirement for an externally-sourced patient.
    SOURCES_REQUIRING_ACCEPTANCE = {
        "external_referral", "transfer_in", "ambulance_ems", "medical_tourism",
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    patient    = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="admission_referrals")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="admission_referrals")

    # Validated against billing.OptionList(list_type="admission_type" /
    # "admission_source") at the serializer layer — see AdmissionReferralSerializer.
    admission_type   = models.CharField(max_length=30)
    admission_source = models.CharField(max_length=30)

    reason_for_admission = models.TextField()

    # Populated when this referral originates inside this hospital's own
    # OPD flow. Both nullable — a walk-in/ER case may have neither, since
    # whether ER visits get their own OPDEncounter row is still an open
    # question (not assumed either way here).
    source_appointment = models.ForeignKey(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="admission_referrals",
    )
    source_encounter = models.ForeignKey(
        OPDEncounter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="admission_referrals",
    )

    # Set only by RecommendAdmissionView from request.user — never accepted
    # as client input, by design (this is the actual enforcement point).
    recommended_by = models.ForeignKey(
        StaffUser, on_delete=models.PROTECT, related_name="admission_referrals_made",
    )
    recommended_at = models.DateTimeField(auto_now_add=True)

    # External-origin referrals only (admission_source in
    # SOURCES_REQUIRING_ACCEPTANCE). Free text because the referring party
    # doesn't exist in this hospital's StaffUser table.
    external_referring_doctor_name = models.CharField(max_length=200, blank=True)
    external_referring_facility    = models.CharField(max_length=200, blank=True)

    # Set only by AcceptExternalReferralView from request.user of THIS
    # hospital's own doctor — never client input. Distinct from
    # recommended_by: recommended_by is whoever logged receipt of the
    # referral; accepted_by is who actually took clinical responsibility.
    accepted_by = models.ForeignKey(
        StaffUser, on_delete=models.PROTECT, null=True, blank=True,
        related_name="admission_referrals_accepted",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Channel-specific extra data that doesn't earn its own column (e.g.
    # transferring facility, EMS run number, TPA pre-authorization number).
    # Same JSON-for-variant-detail pattern as OPDEncounter.diagnoses.
    source_details = models.JSONField(default=dict, blank=True)

    # Two open policy questions per the IPD spec docs themselves — present
    # on the schema now, unenforced, so a later policy decision doesn't
    # need a breaking migration. See knowledge-map §17.9.
    is_mlc               = models.BooleanField(default=False)
    guardian_consent_by  = models.CharField(max_length=200, blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)

    class Meta:
        app_label = "ipd"
        db_table  = "admission_referral"
        ordering  = ["-recommended_at"]

    def __str__(self):
        return f"Referral for {self.patient.uhid} — {self.admission_type} ({self.status})"

    def requires_acceptance(self) -> bool:
        return self.admission_source in self.SOURCES_REQUIRING_ACCEPTANCE


class Admission(models.Model):
    STATUS_REQUESTED           = "requested"
    STATUS_ADMITTED            = "admitted"              # awaiting bed
    STATUS_ACTIVE              = "active"                # bed allocated — Phase 2, not built here
    STATUS_DISCHARGE_INITIATED = "discharge_initiated"
    STATUS_DISCHARGED          = "discharged"
    STATUS_CANCELLED           = "cancelled"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_ADMITTED, "Admitted (awaiting bed)"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_DISCHARGE_INITIATED, "Discharge Initiated"),
        (STATUS_DISCHARGED, "Discharged"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    # Same enforced-state-machine pattern as
    # apps.opd.views.AppointmentStatusView.ALLOWED_TRANSITIONS. Phase 1's
    # API only ever creates a row directly at STATUS_ADMITTED (see
    # views.CompleteAdmissionView) — the rest of this map is modeled now so
    # Phase 2 (bed allocation onward) doesn't need a schema change, but
    # nothing in this app transitions into ACTIVE or beyond yet.
    ALLOWED_TRANSITIONS = {
        STATUS_REQUESTED: [STATUS_ADMITTED, STATUS_CANCELLED],
        STATUS_ADMITTED:  [STATUS_ACTIVE, STATUS_CANCELLED],
        STATUS_ACTIVE:    [STATUS_DISCHARGE_INITIATED],
        STATUS_DISCHARGE_INITIATED: [STATUS_DISCHARGED],
        STATUS_DISCHARGED: [],
        STATUS_CANCELLED: [],
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    admission_number = models.CharField(max_length=20, unique=True)  # NNTM, entity="admission"
    branch           = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="admissions")

    referral   = models.OneToOneField(AdmissionReferral, on_delete=models.PROTECT, related_name="admission")
    patient    = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="admissions")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="admissions")

    # Denormalized off the referral at creation (same rationale as
    # Appointment baking in room/floor at booking time): the referral never
    # changes after conversion, but a report over Admission alone shouldn't
    # need a join for its two most commonly filtered fields.
    admission_type   = models.CharField(max_length=30)
    admission_source = models.CharField(max_length=30)

    ordering_doctor = models.ForeignKey(StaffUser, on_delete=models.PROTECT, related_name="admissions_ordered")
    logged_by_staff = models.ForeignKey(StaffUser, on_delete=models.PROTECT, related_name="admissions_logged")

    reason_for_admission    = models.TextField()
    expected_discharge_date = models.DateField(null=True, blank=True)

    # Registration data captured by front desk at intake — distinct from
    # the clinical data on the referral above.
    attendant_name     = models.CharField(max_length=200, blank=True)
    attendant_phone     = models.CharField(max_length=15, blank=True)
    payer_type          = models.CharField(max_length=20, blank=True)     # copied from Patient.payer_type at intake
    insurance_provider  = models.CharField(max_length=200, blank=True)    # copied from Patient.insurance_provider at intake

    # Re-admission tracking — a self-FK rather than a boolean, so
    # "readmitted within 30 days of discharge" is a real join, not a guess.
    previous_admission = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="readmissions",
    )

    status = models.CharField(max_length=22, choices=STATUS_CHOICES, default=STATUS_REQUESTED, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ipd"
        db_table  = "admission"
        ordering  = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "branch"]),
            models.Index(fields=["patient", "status"]),
        ]

    def __str__(self):
        return f"{self.admission_number} — {self.patient.uhid} ({self.status})"


class AdmissionDeposit(models.Model):
    """
    Advance/deposit collected against an Admission, independent of any
    Invoice — billing.Payment has a mandatory (non-nullable) FK to an
    already-existing Invoice, and a deposit is collected before there is
    anything to invoice yet (often before a bed is even assigned).
    Reconciled as a credit line against the real Invoice at discharge —
    that reconciliation is Phase 2, not built here.

    Deliberately unenforced as a blocking gate anywhere in this Phase 1 API:
    Indian law (Clinical Establishments Act 2010; NMC Professional Conduct
    Regulations 2023; Paschim Banga Khet Mazdoor Samity v. State of West
    Bengal, 1996, on Article 21) prohibits conditioning emergency
    stabilization on advance payment. This model exists to RECORD deposits,
    not to gate anything — a "must collect X before bed allocation" policy
    (for non-emergency admission types only) is Phase 2 scope, and even
    then the Emergency exemption must stay hardcoded, never a
    hospital-configurable toggle.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission       = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="deposits")
    amount          = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode    = models.CharField(max_length=50)  # validated against OptionList(list_type="payment_mode") — same catalog billing.Payment already uses
    transaction_ref = models.CharField(max_length=100, blank=True)
    collected_by    = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True)
    collected_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ipd"
        db_table  = "admission_deposit"
        ordering  = ["-collected_at"]

    def __str__(self):
        return f"₹{self.amount} advance for {self.admission.admission_number}"
