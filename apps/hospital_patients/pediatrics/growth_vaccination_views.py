"""
apps/hospital_patients/pediatrics/growth_vaccination_views.py
----------------------------------------------------
Staff growth chart and vaccination endpoints, all under /api/v1/patients/:

  GET   <pk>/growth/                     height / weight / head circumference over time, with WHO percentiles
  GET   <pk>/vaccinations/               the roadmap: this hospital's schedule laid over the child's real records
  POST  <pk>/vaccinations/               log a dose given at this clinic
  PATCH vaccinations/<id>/verify/        verify or reject a parent's uploaded certificate
  POST  <pk>/vaccinations/order/         doctor: recommend a vaccine
  POST  <pk>/vaccinations/decline/       doctor: mark a slot not required
  POST  <pk>/vaccinations/administer/    nurse or doctor: mark a dose given (closes a doctor's order, or logs a new dose)

Data from OTHER hospitals (growth_measurement, vitals, immunization_record) only shows once the patient has consented to sharing
(hie_consent_given); what this hospital recorded always shows.
A vaccination's state is its `verification_status`: "ordered" (doctor asked for it) becomes "verified" once given, or
"declined" if not needed; a parent's upload starts "pending_review".
"""
from datetime import date

from django.utils import timezone
from rest_framework.views import APIView

from core import storage as blob_storage
from core.file_validation import validate_data_uri, FileValidationError
from core.permissions import IsHospitalStaff, IsDoctorOrNurse, IsDoctor
from core.response import success, created, error, not_found

from apps.hospital_patients.age_utils import age_years_months
from apps.hospital_patients.pediatrics.common import (
    PATIENT_NOT_FOUND, get_patient, parse_date, staff_name as _staff_name, text as _text)
from apps.hospital_patients.pediatrics.growth_reference import add_percentiles
from apps.hospital_patients.pediatrics.roadmap import rules_for
from apps.atomwalk.models import ImmunizationRecord, Patient
from apps.atomwalk.vitals import growth_points

V = ImmunizationRecord


def _given(request):
    """The fields that make a record a verified dose given at this clinic."""
    return {"source": V.SOURCE_CLINIC, "verification_status": V.STATUS_VERIFIED,
            "verified_by_name": _staff_name(request), "verified_at": timezone.now()}


def _new_record(request, patient, **fields):
    return V.objects.using("default").create(
        patient=Patient.objects.using("default").filter(awpid=patient.awpid).first(),
        source_hospital_id=request.hospital_id, **fields)


def _already_recorded(patient, name, given_on, dose_number):
    """The same dose (vaccine, date and dose number) is already on this child's record."""
    return V.objects.using("default").filter(
        patient__awpid=patient.awpid, vaccine_name__iexact=name, administered_date=given_on, dose_number=dose_number).exists()


_DUPLICATE = "This dose is already recorded for this patient."


def _given_json(record):
    return {"id": record.id, "vaccine_name": record.vaccine_name, "administered_date": str(record.administered_date),
            "verification_status": record.verification_status, "has_certificate": bool(record.file_data)}


def _certificate(patient, data, vaccine_name):
    """
    The optional scanned certificate sent with a dose: (file_name, mime_type, stored_key, error_response).
    No file sent -> three empty strings. A bad file -> error_response is ready to return.
    """
    file_data = data.get("file_data") or ""
    if not file_data:
        return "", "", "", None
    try:
        mime_type = validate_data_uri(file_data)
        key = blob_storage.upload_data_uri(
            file_data, prefix="vaccination-certs", mime_type=mime_type, category="vaccination-certificate",
            identity=blob_storage.identity_slug(name=patient.full_name, identifier=patient.awpid))
    except (FileValidationError, blob_storage.StorageError) as exc:
        return None, None, None, error(str(exc), errors={"file_data": str(exc)})
    name = blob_storage.display_file_name("vaccination-certificate", mime_type, detail=vaccine_name,
                                          name=patient.full_name, identifier=patient.awpid)
    return name, mime_type, key, None


# ── growth ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _growth_series(patient, hospital_id):
    """One point per day: this hospital's readings, plus other hospitals' on days we have none (if consented)."""
    return growth_points(patient.awpid, hospital_id=hospital_id, include_other=patient.hie_consent_given)


class PatientGrowthView(APIView):
    permission_classes = [IsDoctorOrNurse]

    def get(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        series = _growth_series(patient, request.hospital_id)
        age = age_years_months(patient.date_of_birth)
        is_minor = age is not None and age[0] < 18
        return success(data={
            "patient_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age_years": age[0] if age else None,
            "age_months": age[1] if age else None,
            "is_minor": is_minor,
            "consent_given": patient.hie_consent_given,
            "series": series,
            "percentile_available": is_minor and add_percentiles(
                series, patient.gender, patient.date_of_birth, only_source="this_hospital"),
        })


# ── vaccinations ──────────────────────────────────────────────────────────────────────────────────────────────────
class PatientVaccinationListCreateView(APIView):
    def get_permissions(self):
        return [IsHospitalStaff() if self.request.method == "GET" else IsDoctorOrNurse()]

    def get(self, request, pk):
        from apps.hospital_patients.pediatrics.vaccine_schedule import build_roadmap

        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        roadmap = build_roadmap(patient.awpid, patient.date_of_birth, rules_for("vaccination", request.hospital_id),
                                viewer_hospital_id=request.hospital_id, hie_consent=patient.hie_consent_given)
        return success(data={"patient_name": patient.full_name, "date_of_birth": patient.date_of_birth,
                             "consent_given": patient.hie_consent_given, "roadmap": roadmap})

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        name = _text(d, "vaccine_name")
        if not name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not d.get("administered_date"):
            return error("Administered date is required.", errors={"administered_date": "Required."})
        given_on, err = parse_date(d["administered_date"], "administered_date", "Administered date")
        if err:
            return err
        if _already_recorded(patient, name, given_on, d.get("dose_number") or None):
            return error(_DUPLICATE, status=409)
        file_name, mime_type, key, err = _certificate(patient, d, name)
        if err:
            return err
        record = _new_record(request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"),
                             administered_date=given_on, dose_number=d.get("dose_number") or None, file_name=file_name, mime_type=mime_type,
                             file_data=key, **_given(request))
        return created(data=_given_json(record), message="Vaccination logged.")


class PatientVaccinationVerifyView(APIView):
    """Body: {action: "verify" | "reject", review_notes?}. Any hospital's doctor or nurse can review a parent's upload."""
    permission_classes = [IsDoctorOrNurse]

    def patch(self, request, pk):
        record = V.objects.using("default").filter(pk=pk).first()
        if not record:
            return not_found("Vaccination record not found.")
        action = _text(request.data, "action")
        if action not in ("verify", "reject"):
            return error("action must be 'verify' or 'reject'.", errors={"action": "Invalid."})
        record.verification_status = V.STATUS_VERIFIED if action == "verify" else V.STATUS_REJECTED
        record.verified_by_name = _staff_name(request)
        record.verified_at = timezone.now()
        record.review_notes = _text(request.data, "review_notes")
        record.source_hospital_id = record.source_hospital_id or request.hospital_id      # first hospital to review claims it
        record.save(using="default", update_fields=[
            "verification_status", "verified_by_name", "verified_at", "review_notes", "source_hospital_id"])
        return success(data={"id": record.id, "verification_status": record.verification_status},
                       message=f"Vaccination record {action}d.")


class PatientVaccinationOrderView(APIView):
    """Doctor recommends a vaccine that isn't given yet. Body: {vaccine_name, reason, due_date?, scheduled_label?, dose_number?}"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        name, reason = _text(d, "vaccine_name"), _text(d, "reason")
        if not name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not reason:
            return error("A clinical reason is required for an ad-hoc order.", errors={"reason": "Required."})
        due_on, err = parse_date(d.get("due_date"), "due_date", "Due date", allow_future=True)
        if err:
            return err
        record = _new_record(
            request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"), reason=reason,
            due_date=due_on, dose_number=d.get("dose_number") or None, administered_date=None,
            source=V.SOURCE_DOCTOR_ORDERED, verification_status=V.STATUS_ORDERED,
            verified_by_name=_staff_name(request, "Doctor"))
        return created(data={"id": record.id, "vaccine_name": record.vaccine_name, "reason": record.reason,
                             "due_date": str(record.due_date) if record.due_date else None,
                             "verification_status": record.verification_status}, message="Vaccine order recorded.")


class PatientVaccinationDeclineView(APIView):
    """Doctor marks a slot not required. Body: {record_id?} for an existing record, else {vaccine_name, scheduled_label?}; reason?"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        if d.get("record_id"):
            record = V.objects.using("default").filter(pk=d["record_id"], patient__awpid=patient.awpid).first()
            if not record:
                return not_found("Vaccination record not found for this patient.")
        else:
            name = _text(d, "vaccine_name")
            if not name:
                return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
            record = _new_record(request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"),
                                 administered_date=None, source=V.SOURCE_DOCTOR_ORDERED,
                                 verification_status=V.STATUS_DECLINED)
        reason = _text(d, "reason")
        record.verification_status = V.STATUS_DECLINED
        record.reason = reason or record.reason
        record.review_notes = reason or record.review_notes
        record.verified_by_name = _staff_name(request, "Doctor")
        record.verified_at = timezone.now()
        record.source_hospital_id = record.source_hospital_id or request.hospital_id
        record.save(using="default", update_fields=[
            "verification_status", "reason", "review_notes", "verified_by_name", "verified_at", "source_hospital_id"])
        return success(data={"id": record.id, "vaccine_name": record.vaccine_name,
                             "verification_status": record.verification_status}, message="Vaccine marked as not required.")


class PatientVaccinationAdministerView(APIView):
    """
    Nurse or doctor marks a dose given today (or on administered_date).
    Body: {record_id?} to close an existing record (typically a doctor's order) in place, else {vaccine_name,
    scheduled_label?} to log a new one; administered_date?, dose_number?, file_data?.
    """
    permission_classes = [IsDoctorOrNurse]

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        record = None
        if d.get("record_id"):
            record = V.objects.using("default").filter(pk=d["record_id"], patient__awpid=patient.awpid).first()
            if not record:
                return not_found("Vaccination record not found for this patient.")
        name = record.vaccine_name if record else _text(d, "vaccine_name")
        if not name:
            return error("vaccine_name or record_id is required.", errors={"vaccine_name": "Required."})

        given_on, err = parse_date(d.get("administered_date"), "administered_date", "Administered date")
        if err:
            return err
        given_on = given_on or date.today()
        if record is None and _already_recorded(patient, name, given_on, d.get("dose_number") or None):
            return error(_DUPLICATE, status=409)
        file_name, mime_type, key, err = _certificate(patient, d, name)
        if err:
            return err
        fields = {"administered_date": given_on, "dose_number": d.get("dose_number") or None, **_given(request)}
        if key:
            fields.update(file_name=file_name, mime_type=mime_type, file_data=key)

        if record is None:
            record = _new_record(request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"), **fields)
        else:
            old_key = record.file_data
            if not fields["dose_number"]:
                del fields["dose_number"]                                   # keep the dose the order already had
            fields.update(source_hospital_id=record.source_hospital_id or request.hospital_id)
            for field, value in fields.items():
                setattr(record, field, value)
            record.save(using="default", update_fields=list(fields))
            if key and old_key:
                blob_storage.delete(old_key)                                # the new certificate replaces the old file
        return success(data=_given_json(record), message="Vaccination recorded as administered.")
