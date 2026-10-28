# Contents, in the order they appear:
#   1. Patient             HospitalPatient (the hospital's own row for a patient)
#   2. Visit record        Vitals
#   3. Events, documents   HospitalEvent, HospitalDocument (an event is what happened; its documents are the files about it)

from django.db import models
from django.utils import timezone
from apps.hospital_setup.models import BranchDepartment, StaffUser, hospital_folder

# ────────────────────────────────────────────────────────────────────────────
# PATIENT
# What this hospital keeps about a patient. Who the patient is (name, birth date, contact) is read from the shared record by get_patient_details().
# Everything else in this app and in opd, billing and hospital_setup points at this row as `patient`.
# ────────────────────────────────────────────────────────────────────────────

class HospitalPatient(models.Model):
    uhid          = models.CharField(max_length=30, unique=True)
    awpid         = models.CharField(max_length=30, unique=True)
    is_active     = models.BooleanField(default=True)
    created_by    = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="u_patients_registered")
    updated_by    = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="u_patients_updated")
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = "hospital_patients"

    def __str__(self):
        return f"{self.uhid} ({self.awpid})"

    def get_patient_details(self, batch=()):
        from apps.patients.services import load_patient_details
        load_patient_details([self, *batch])
        return self.__dict__["_patient_details"]


# ────────────────────────────────────────────────────────────────────────────
# VISIT RECORD
# Readings taken at a visit. The visit (appointment) already says which patient, so the patient is not repeated here.
# ────────────────────────────────────────────────────────────────────────────

class Vitals(models.Model):
    appointment           = models.OneToOneField("opd.Appointment", on_delete=models.PROTECT, related_name="a_vitals")
    recorded_by           = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="u_vitals_recorded")
    recorded_at           = models.DateTimeField(default=timezone.now, blank=True)
    systolic_bp           = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic_bp          = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse_rate            = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature           = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    spo2                  = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate      = models.PositiveSmallIntegerField(null=True, blank=True)
    blood_sugar_rbs       = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg             = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    height_cm             = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    head_circumference_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    nurse_notes           = models.TextField(blank=True)
    updated_at            = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hospital_vitals"
        constraints = [
            models.CheckConstraint(check=models.Q(spo2__isnull=True) | models.Q(spo2__lte=100), name="vitals_spo2_at_most_100"),
        ]
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"Vitals of appointment {self.appointment_id} at {self.recorded_at:%Y-%m-%d %H:%M}"


# ────────────────────────────────────────────────────────────────────────────
# EVENTS AND DOCUMENTS
# An event is one thing that happened to a patient at a branch department (a registration, a visit, a bill ...). It can have any number of
# documents, and a document exists only as part of an event, so the patient is read from the event.
# ────────────────────────────────────────────────────────────────────────────

class HospitalEvent(models.Model):
    TYPE_REGISTRATION = "registration"
    TYPE_APPOINTMENT  = "appointment"
    TYPE_VITALS       = "vitals"
    TYPE_CONSULTATION = "consultation"
    TYPE_PRESCRIPTION = "prescription"
    TYPE_LAB          = "lab"
    TYPE_BILLING      = "billing"
    TYPE_ADMISSION    = "admission"
    TYPE_CHOICES = [
        (TYPE_REGISTRATION, "Registration"),
        (TYPE_APPOINTMENT,  "Appointment"),
        (TYPE_VITALS,       "Vitals"),
        (TYPE_CONSULTATION, "Consultation"),
        (TYPE_PRESCRIPTION, "Prescription"),
        (TYPE_LAB,          "Lab"),
        (TYPE_BILLING,      "Billing"),
        (TYPE_ADMISSION,    "Admission"),
    ]

    patient           = models.ForeignKey(HospitalPatient, on_delete=models.PROTECT, related_name="p_events")
    event_type        = models.CharField(max_length=20, choices=TYPE_CHOICES)
    is_active         = models.BooleanField(default=True)
    branch_department = models.ForeignKey(BranchDepartment, on_delete=models.PROTECT, null=True, blank=True, related_name="bdp_events")
    created_by        = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="u_events_created")
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hospital_event"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.patient_id} {self.event_type} {self.created_at:%Y-%m-%d}"


def hospital_document_path(instance, filename):
    """hospital/<hospital database>/patients/<uhid>/<event>/<file>: the hospital's folder in the bucket, then the patient (by the hospital's own UHID)."""
    return f"{hospital_folder(instance)}/patients/{instance.event.patient.uhid}/{instance.event_id}/{filename}"


class HospitalDocument(models.Model):
    event      = models.ForeignKey(HospitalEvent, on_delete=models.PROTECT, related_name="ev_documents")
    file       = models.FileField(upload_to=hospital_document_path, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hospital_document"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file.name or self.pk} (event {self.event_id})"
