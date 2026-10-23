"""apps/ipd/models.py"""

import uuid
from django.conf import settings
from django.db import models

from apps.hospital_setup.models import StaffUser
from apps.hospital_setup.models import Department, Branch
from apps.opd.models import HospitalPatient
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
    SOURCES_REQUIRING_ACCEPTANCE = {
        "external_referral", "transfer_in", "ambulance_ems", "medical_tourism",
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    patient    = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT, related_name="p_admission_referrals")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="d_admission_referrals")

    # Validated against billing.OptionList(list_type="admission_type" /
    admission_type   = models.CharField(max_length=30)
    admission_source = models.CharField(max_length=30)

    reason_for_admission = models.TextField()

    # Populated when this referral originates inside this hospital's own
    source_appointment = models.ForeignKey(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="a_admission_referrals",
    )
    source_encounter = models.ForeignKey(
        OPDEncounter, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="e_admission_referrals",
    )

    # Set only by RecommendAdmissionView from request.user — never accepted
    recommended_by = models.ForeignKey(
        StaffUser, on_delete=models.PROTECT, related_name="u_admission_referrals_made",
    )
    recommended_at = models.DateTimeField(auto_now_add=True)

    # External-origin referrals only (admission_source in
    external_referring_doctor_name = models.CharField(max_length=200, blank=True)
    external_referring_facility    = models.CharField(max_length=200, blank=True)

    # Set only by AcceptExternalReferralView from request.user of THIS
    accepted_by = models.ForeignKey(
        StaffUser, on_delete=models.PROTECT, null=True, blank=True,
        related_name="u_admission_referrals_accepted",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Channel-specific extra data that doesn't earn its own column (e.g.
    source_details = models.JSONField(default=dict, blank=True)

    # Two open policy questions per the IPD spec docs themselves — present
    is_mlc               = models.BooleanField(default=False)
    guardian_consent_by  = models.CharField(max_length=200, blank=True)

    # True when RegisterExternalReferralView (front desk, logging a paper/
    front_desk_logged = models.BooleanField(default=False)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)

    class Meta:
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

    OPEN_STATUSES = (STATUS_REQUESTED, STATUS_ADMITTED, STATUS_ACTIVE, STATUS_DISCHARGE_INITIATED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    admission_number = models.CharField(max_length=20, unique=True)  # NNTM, entity="admission"
    branch           = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="b_admissions")

    referral   = models.OneToOneField(AdmissionReferral, on_delete=models.PROTECT, related_name="ar_admission")
    patient    = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT, related_name="p_admissions")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="d_admissions")

    # Denormalized off the referral at creation (same rationale as
    admission_type   = models.CharField(max_length=30)
    admission_source = models.CharField(max_length=30)

    ordering_doctor = models.ForeignKey(StaffUser, on_delete=models.PROTECT, related_name="u_admissions_ordered")
    logged_by_staff = models.ForeignKey(StaffUser, on_delete=models.PROTECT, related_name="u_admissions_logged")

    reason_for_admission    = models.TextField()
    expected_discharge_date = models.DateField(null=True, blank=True)

    # Registration data captured by front desk at intake — distinct from
    attendant_name     = models.CharField(max_length=200, blank=True)
    attendant_phone     = models.CharField(max_length=15, blank=True)
    payer_type          = models.CharField(max_length=20, blank=True)     # copied from Patient.payer_type at intake
    insurance_provider  = models.CharField(max_length=200, blank=True)    # copied from Patient.insurance_provider at intake

    # Re-admission tracking — a self-FK rather than a boolean, so
    previous_admission = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="ad_readmissions",
    )

    # Bed assignment — deliberately optional and independent of `status`.
    bed = models.ForeignKey(
        "hospital_setup.Bed", on_delete=models.SET_NULL, null=True, blank=True, related_name="bd_admissions",
    )
    bed_assigned_at = models.DateTimeField(null=True, blank=True)

    # Set once, by views.DischargeAdmissionView, the moment a discharge is
    discharged_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=22, choices=STATUS_CHOICES, default=STATUS_REQUESTED)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "admission"
        ordering  = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "branch"]),
            models.Index(fields=["patient", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["patient"], condition=models.Q(status__in=("requested", "admitted", "active", "discharge_initiated")),
                                    name="one_open_admission_per_patient"),
            models.UniqueConstraint(fields=["bed"], condition=models.Q(bed__isnull=False, status__in=("requested", "admitted", "active", "discharge_initiated")),
                                    name="one_open_admission_per_bed"),
        ]

    def __str__(self):
        return f"{self.admission_number} — {self.patient.uhid} ({self.status})"


class AdmissionDeposit(models.Model):
    """Advance/deposit collected against an Admission, independent of any"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission       = models.ForeignKey(Admission, on_delete=models.PROTECT, related_name="ad_deposits")
    amount          = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode    = models.CharField(max_length=50)
    transaction_ref = models.CharField(max_length=100, blank=True)
    collected_by    = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="u_deposits_collected")
    collected_at    = models.DateTimeField(auto_now_add=True)

    # The reconciliation this docstring used to describe as "Phase 2, not
    reconciled_invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="i_reconciled_ipd_deposits",
    )

    class Meta:
        db_table  = "admission_deposit"
        ordering  = ["-collected_at"]
        constraints = [models.CheckConstraint(check=models.Q(amount__gt=0), name="deposit_amount_positive")]

    def __str__(self):
        return f"{settings.CURRENCY_SYMBOL}{self.amount} advance for {self.admission.admission_number}"


class PatientMovement(models.Model):
    """Append-only history of every bed change during an Admission's stay —"""
    INITIAL_ASSIGNMENT = "initial_assignment"
    TRANSFER           = "transfer"
    RELEASE            = "release"
    DISCHARGE          = "discharge"
    MOVEMENT_CHOICES = [
        (INITIAL_ASSIGNMENT, "Initial Bed Assignment"),
        (TRANSFER, "Bed Transfer"),
        (RELEASE, "Bed Released (no discharge)"),
        (DISCHARGE, "Discharge"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admission     = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name="ad_movements")
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES)
    from_bed      = models.ForeignKey("hospital_setup.Bed", on_delete=models.SET_NULL, null=True, blank=True, related_name="bd_movements_from")
    to_bed        = models.ForeignKey("hospital_setup.Bed", on_delete=models.SET_NULL, null=True, blank=True, related_name="bd_movements_to")
    # Denormalized at write time (same rationale as Admission.admission_type/
    from_room_name = models.CharField(max_length=100, blank=True)
    from_bed_number = models.CharField(max_length=20, blank=True)
    to_room_name   = models.CharField(max_length=100, blank=True)
    to_bed_number  = models.CharField(max_length=20, blank=True)
    moved_by  = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, related_name="u_patient_movements_recorded")
    notes     = models.CharField(max_length=255, blank=True)
    moved_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "patient_movement"
        ordering  = ["-moved_at"]

    def __str__(self):
        return f"{self.admission.admission_number}: {self.get_movement_type_display()}"
