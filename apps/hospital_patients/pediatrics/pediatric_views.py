"""
apps/hospital_patients/pediatrics/pediatric_views.py
-------------------------------------------
Staff birth history and developmental milestones, under /api/v1/patients/<pk>/:

  GET    birth-history/    any hospital staff
  POST   birth-history/    front desk or doctor, once per child
  PATCH  birth-history/    front desk or doctor
  GET    milestones/       the roadmap: this hospital's schedule laid over the child's real assessments
  POST   milestones/       doctor or nurse records an assessment

The screens only offer these for under-18s, but the backend doesn't block an adult's record.
"""
import logging
from datetime import date

from rest_framework.views import APIView

from core.audit import log_action
from core.permissions import IsHospitalStaff, IsDoctorOrFrontDesk, IsDoctorOrNurse
from core.response import success, created, error, not_found

from apps.hospital_patients.pediatrics.common import PATIENT_NOT_FOUND, get_patient, parse_date, staff_name, text
from apps.hospital_patients.pediatrics.roadmap import rules_for
from apps.hospital_patients.serializers import BirthHistorySerializer
from apps.atomwalk.models import BirthHistory, MilestoneRecord, Patient

logger = logging.getLogger(__name__)

def _shared_patient(patient):
    """The patient's row in Atomwalk, where the birth history is kept for every hospital."""
    return Patient.objects.using("default").filter(awpid=patient.awpid).first()


class BirthHistoryView(APIView):
    def get_permissions(self):
        return [IsHospitalStaff() if self.request.method == "GET" else IsDoctorOrFrontDesk()]

    def get(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        bh = BirthHistory.objects.using("default").filter(patient__awpid=patient.awpid).first()
        if not bh:
            return success(data=None, message="No birth history recorded yet.")
        return success(data=BirthHistorySerializer(bh).data)

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        shared = _shared_patient(patient)
        if not shared:
            return error("This patient has no shared identity yet, so a birth history can't be kept for them.", status=400)
        if BirthHistory.objects.using("default").filter(patient=shared).exists():
            return error("Birth history already exists for this patient — use PATCH to edit it.", status=400)
        serializer = BirthHistorySerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        bh = BirthHistory.objects.using("default").create(
            patient=shared, recorded_by=request.user.id, source_hospital_id=request.hospital_id, **serializer.validated_data)
        log_action(request, request.hospital_db, "birth_history.create", resource_type="BirthHistory",
                   resource_id=bh.id, patient_id=patient.uuid, metadata={"replaced_other_hospitals_copy": None})
        return created(data=BirthHistorySerializer(bh).data, message="Birth history recorded.")

    def patch(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        bh = BirthHistory.objects.using("default").filter(patient__awpid=patient.awpid).first()
        if not bh:
            return not_found("No birth history recorded yet for this patient — use POST to create it.")
        serializer = BirthHistorySerializer(bh, data=request.data, partial=True)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        before = {f: getattr(bh, f) for f in serializer.validated_data}
        previous_hospital = bh.source_hospital_id
        serializer.save(updated_by=request.user.id, source_hospital_id=request.hospital_id)
        changed = {f: [str(old), str(getattr(bh, f))] for f, old in before.items() if getattr(bh, f) != old}
        replaced = previous_hospital if previous_hospital not in (None, request.hospital_id) else None
        log_action(request, request.hospital_db, "birth_history.update", resource_type="BirthHistory",
                   resource_id=bh.id, patient_id=patient.uuid,
                   metadata={"changed": changed, "replaced_other_hospitals_copy": replaced})
        return success(data=BirthHistorySerializer(bh).data, message="Birth history updated.")


class PatientMilestoneListCreateView(APIView):
    """POST body: {domain, milestone, status ("achieved" | "not_yet" | "concern"), scheduled_label?, achieved_date?, assessed_date?, notes?}"""
    permission_classes = [IsDoctorOrNurse]

    def get(self, request, pk):
        from apps.hospital_patients.pediatrics.milestone_roadmap import build_roadmap

        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        roadmap = build_roadmap(patient.awpid, patient.date_of_birth, rules_for("milestone", request.hospital_id),
                                viewer_hospital_id=request.hospital_id, hie_consent=patient.hie_consent_given)
        return success(data={"patient_name": patient.full_name, "date_of_birth": patient.date_of_birth,
                             "consent_given": patient.hie_consent_given, "roadmap": roadmap})

    def post(self, request, pk):
        M = MilestoneRecord
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        domain, milestone = text(d, "domain"), text(d, "milestone")
        status = text(d, "status") or M.STATUS_ACHIEVED
        if domain not in dict(M._meta.get_field("domain").choices):
            return error("A valid domain is required.", errors={"domain": "Required/invalid."})
        if not milestone:
            return error("Milestone is required.", errors={"milestone": "Required."})
        if status not in dict(M.STATUS_CHOICES):
            return error("Invalid status.", errors={"status": "Invalid."})

        achieved_on, err = parse_date(d.get("achieved_date"), "achieved_date", "Achieved date")
        if err:
            return err
        assessed_on, err = parse_date(d.get("assessed_date"), "assessed_date", "Assessed date")
        if err:
            return err
        # only an achieved milestone has an achieved date (today unless one is given)
        achieved = (achieved_on or date.today()) if status == M.STATUS_ACHIEVED else None
        record = M.objects.using("default").create(
            patient=_shared_patient(patient), domain=domain, milestone=milestone, scheduled_label=text(d, "scheduled_label"),
            status=status, achieved_date=achieved, assessed_date=assessed_on or date.today(),
            notes=text(d, "notes"), recorded_by_name=staff_name(request), source_hospital_id=request.hospital_id)
        return created(data={
            "id": record.id, "domain": record.domain, "milestone": record.milestone, "status": record.status,
            "achieved_date": str(record.achieved_date) if record.achieved_date else None,
            "assessed_date": str(record.assessed_date) if record.assessed_date else None,
        }, message="Milestone assessment recorded.")
