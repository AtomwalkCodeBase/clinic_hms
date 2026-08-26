"""
apps/patients/growth_vaccination_views.py
-------------------------------------------
Staff-facing growth chart + vaccination roadmap endpoints.

  GET  /api/v1/patients/<pk>/growth/                 — height/weight/BMI over time
  GET  /api/v1/patients/<pk>/vaccinations/            — roadmap (schedule + real records)
  POST /api/v1/patients/<pk>/vaccinations/            — log a clinic-administered vaccination
  PATCH /api/v1/patients/vaccinations/<id>/verify/    — verify/reject a self-reported upload
  POST /api/v1/patients/<pk>/vaccinations/order/      — doctor: ad-hoc vaccine order
  POST /api/v1/patients/<pk>/vaccinations/decline/    — doctor: mark a slot not required
  POST /api/v1/patients/<pk>/vaccinations/administer/ — nurse/doctor: mark administered

Mirrors PatientHistoryView's HIE-consent gating: this hospital's own local
data (Vitals recorded here) is always visible regardless of consent; a
patient's cross-hospital shared history (SharedVital / SharedVaccination
entries logged at OTHER hospitals) only surfaces once hie_consent_given.

See the state-machine note on apps.registry.models.SharedVaccination for how
"ordered" → "administered" and "declined" reuse verification_status instead
of a separate status field.
"""

import logging
from datetime import date

from django.utils import timezone
from rest_framework.views import APIView

from core.response import success, created, error, not_found
from core.permissions import IsHospitalStaff, IsDoctorOrNurse, IsDoctor
from core.file_validation import validate_data_uri, FileValidationError
from core import storage as blob_storage

from .models import Patient

logger = logging.getLogger(__name__)


def _age_years(dob):
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _handle_vaccination_file(patient, d, vaccine_name=""):
    """
    Optional certificate upload for a staff-logged vaccination — same S3
    fields (file_name/mime_type/file_data-as-key) a parent's self-reported
    upload sets via PortalVaccinationUploadView, just attached by the
    clinician instead. Most clinic-administered doses won't have a scanned
    certificate, so this is opt-in: returns ("", "", "", None) when the
    request carried no file_data at all.

    `vaccine_name`, when known at the call site, is baked into file_name
    alongside the patient's name/AWPID (see display_file_name()) — without
    it, every certificate for every patient would download as the same
    generic "Vaccination Certificate.png", indistinguishable once saved
    outside this app's own folder-organized S3 view.

    Returns (file_name, mime_type, file_key, error_response) — on any
    validation/upload failure the first three are None and error_response
    is a ready-to-return DRF response, matching the pattern every other
    upload call site in this codebase uses (see apps/lab/views.py,
    apps/patients/portal_views.py).
    """
    file_data = d.get("file_data") or ""
    if not file_data:
        return "", "", "", None
    try:
        mime_type = validate_data_uri(file_data)
    except FileValidationError as exc:
        return None, None, None, error(str(exc), errors={"file_data": str(exc)})
    identity = blob_storage.identity_slug(name=patient.full_name, identifier=patient.awpid)
    try:
        file_key = blob_storage.upload_data_uri(
            file_data, prefix="vaccination-certs", mime_type=mime_type,
            category="vaccination-certificate", identity=identity,
        )
    except blob_storage.StorageError as exc:
        return None, None, None, error(str(exc), errors={"file_data": str(exc)})
    # Named after what it is (the specific vaccine, not just "a vaccination
    # certificate") plus who it belongs to, not whatever the clinic's
    # scanner/phone called the file — same convention as every other
    # upload category.
    file_name = blob_storage.display_file_name(
        "vaccination-certificate", mime_type,
        detail=vaccine_name, name=patient.full_name, identifier=patient.awpid,
    )
    return file_name, mime_type, file_key, None


class PatientGrowthView(APIView):
    """GET /api/v1/patients/<pk>/growth/"""
    permission_classes = [IsDoctorOrNurse]

    def get(self, request, pk):
        from apps.opd.models import Appointment, Vitals

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        points = {}

        appt_ids = list(
            Appointment.objects.using(request.tenant_db)
            .filter(patient_id=patient.uuid).values_list("id", flat=True)
        )
        local_vitals = (
            Vitals.objects.using(request.tenant_db)
            .filter(appointment_id__in=appt_ids).order_by("recorded_at")
        )
        for v in local_vitals:
            if v.height_cm or v.weight_kg:
                d = v.recorded_at.date()
                points[d] = {
                    "date": str(d),
                    "height_cm": float(v.height_cm) if v.height_cm else None,
                    "weight_kg": float(v.weight_kg) if v.weight_kg else None,
                    "bmi": float(v.bmi) if v.bmi else None,
                    "source": "this_hospital",
                }

        if patient.hie_consent_given:
            from apps.registry.models import SharedVital
            shared = (
                SharedVital.objects.using("default")
                .filter(awpid=patient.awpid).order_by("recorded_at")
            )
            for v in shared:
                if v.height_cm or v.weight_kg:
                    d = v.recorded_at.date()
                    points.setdefault(d, {
                        "date": str(d),
                        "height_cm": float(v.height_cm) if v.height_cm else None,
                        "weight_kg": float(v.weight_kg) if v.weight_kg else None,
                        "bmi": None,
                        "source": "other_hospital",
                    })

        series = sorted(points.values(), key=lambda p: p["date"])
        age_years = _age_years(patient.date_of_birth)

        return success(data={
            "patient_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "age_years": age_years,
            "is_minor": age_years is not None and age_years < 18,
            "consent_given": patient.hie_consent_given,
            "series": series,
            # No percentile curves yet — plotting a made-up percentile band
            # would be worse than not showing one. Real WHO/IAP growth
            # reference tables are a follow-up, not something to fake here.
            "percentile_available": False,
        })


class PatientVaccinationListCreateView(APIView):
    """
    GET  /api/v1/patients/<pk>/vaccinations/  — roadmap (schedule + real records)
    POST /api/v1/patients/<pk>/vaccinations/  — log a clinic-administered vaccination
    """
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        from apps.registry.vaccine_schedule import build_roadmap
        from apps.registry.models import VaccinationSchedule, VaccinationScheduleRule
        from apps.tenants.models import Tenant

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        # Staff-facing requests already run within one hospital's context
        # (request.tenant_id), so there's no ambiguity about which schedule
        # applies — unlike the patient-portal's cross-hospital aggregated
        # views (see _portal_schedule_rules() in apps/patients/portal_views.py),
        # just resolve this tenant's own active_vaccination_schedule_id.
        # Falls back to the global "Default Schedule" system template if the
        # tenant hasn't been assigned one (shouldn't happen post-migration,
        # but new/edge-case tenants shouldn't lose the roadmap entirely).
        rules = []
        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        schedule_id = tenant.active_vaccination_schedule_id if tenant else None
        schedule = None
        if schedule_id:
            schedule = VaccinationSchedule.objects.using("default").filter(pk=schedule_id, active=True).first()
        if not schedule:
            schedule = (
                VaccinationSchedule.objects.using("default")
                .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
                .order_by("id")
                .first()
            )
        if schedule:
            rules = list(
                VaccinationScheduleRule.objects.using("default")
                .filter(schedule=schedule)
                .order_by("sort_order")
            )

        # HIE-consent gate — mirrors PatientHistoryView/PatientGrowthView:
        # without consent, other hospitals' vaccination records are hidden
        # from this hospital's staff (pending self-reports and this
        # hospital's own records stay visible regardless — see
        # build_roadmap()'s hie_consent docstring).
        roadmap = build_roadmap(
            patient.awpid, patient.date_of_birth, rules,
            viewer_tenant_id=request.tenant_id, hie_consent=patient.hie_consent_given,
        )
        return success(data={
            "patient_name": patient.full_name,
            "date_of_birth": patient.date_of_birth,
            "consent_given": patient.hie_consent_given,
            "roadmap": roadmap,
        })

    def post(self, request, pk):
        from apps.registry.models import SharedVaccination

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        d = request.data
        vaccine_name = (d.get("vaccine_name") or "").strip()
        administered_date = d.get("administered_date")
        scheduled_label = (d.get("scheduled_label") or "").strip()
        if not vaccine_name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not administered_date:
            return error("Administered date is required.", errors={"administered_date": "Required."})

        file_name, mime_type, file_key, err = _handle_vaccination_file(patient, d, vaccine_name)
        if err:
            return err

        staff_name = getattr(request.user, "full_name", None) or getattr(request.user, "email", "Staff")
        record = SharedVaccination.objects.using("default").create(
            awpid=patient.awpid,
            vaccine_name=vaccine_name,
            scheduled_label=scheduled_label,
            administered_date=administered_date,
            source=SharedVaccination.SOURCE_CLINIC,
            verification_status=SharedVaccination.STATUS_VERIFIED,
            verified_by_name=staff_name,
            verified_at=timezone.now(),
            source_tenant_id=request.tenant_id,
            recorded_by="staff",
            file_name=file_name,
            mime_type=mime_type,
            file_data=file_key,
        )
        return created(data={
            "id": record.id,
            "vaccine_name": record.vaccine_name,
            "administered_date": str(record.administered_date),
            "verification_status": record.verification_status,
            "has_certificate": bool(record.file_data),
        }, message="Vaccination logged.")


class PatientVaccinationVerifyView(APIView):
    """
    PATCH /api/v1/patients/vaccinations/<id>/verify/
    Body: { action: "verify" | "reject", review_notes? }
    Staff reviews a self-reported (parent-uploaded) vaccination certificate.
    Any hospital's doctor/nurse can review one — the record isn't scoped to
    a particular tenant until reviewed, since a self-reported entry may
    never have been logged by any hospital in the first place.
    """
    permission_classes = [IsDoctorOrNurse]

    def patch(self, request, pk):
        from apps.registry.models import SharedVaccination

        try:
            record = SharedVaccination.objects.using("default").get(pk=pk)
        except SharedVaccination.DoesNotExist:
            return not_found("Vaccination record not found.")

        action = (request.data.get("action") or "").strip()
        if action not in ("verify", "reject"):
            return error("action must be 'verify' or 'reject'.", errors={"action": "Invalid."})

        staff_name = getattr(request.user, "full_name", None) or getattr(request.user, "email", "Staff")
        record.verification_status = (
            SharedVaccination.STATUS_VERIFIED if action == "verify" else SharedVaccination.STATUS_REJECTED
        )
        record.verified_by_name = staff_name
        record.verified_at = timezone.now()
        record.review_notes = (request.data.get("review_notes") or "").strip()
        if record.source_tenant_id is None:
            record.source_tenant_id = request.tenant_id
        record.save(using="default", update_fields=[
            "verification_status", "verified_by_name", "verified_at", "review_notes", "source_tenant_id",
        ])
        return success(data={
            "id": record.id,
            "verification_status": record.verification_status,
        }, message=f"Vaccination record {action}d.")


class PatientVaccinationOrderView(APIView):
    """
    POST /api/v1/patients/<pk>/vaccinations/order/
    Body: { vaccine_name, reason, due_date?, scheduled_label?, dose_number? }

    Doctor-only. Records an ad-hoc vaccine recommendation that hasn't been
    administered yet — a new SharedVaccination row with
    source="doctor_ordered", verification_status="ordered", and no
    administered_date. A nurse (or the doctor) later closes the loop with
    PatientVaccinationAdministerView, which flips this SAME row to
    source="clinic"/verification_status="verified" and fills in
    administered_date — see the state-machine note on SharedVaccination.
    """
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        from apps.registry.models import SharedVaccination

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        d = request.data
        vaccine_name = (d.get("vaccine_name") or "").strip()
        reason = (d.get("reason") or "").strip()
        scheduled_label = (d.get("scheduled_label") or "").strip()
        due_date = d.get("due_date") or None
        dose_number = d.get("dose_number") or None

        if not vaccine_name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not reason:
            return error("A clinical reason is required for an ad-hoc order.", errors={"reason": "Required."})

        doctor_name = getattr(request.user, "full_name", None) or getattr(request.user, "email", "Doctor")
        record = SharedVaccination.objects.using("default").create(
            awpid=patient.awpid,
            vaccine_name=vaccine_name,
            scheduled_label=scheduled_label,
            administered_date=None,
            due_date=due_date,
            reason=reason,
            dose_number=dose_number,
            source=SharedVaccination.SOURCE_DOCTOR_ORDERED,
            verification_status=SharedVaccination.STATUS_ORDERED,
            verified_by_name=doctor_name,
            source_tenant_id=request.tenant_id,
            recorded_by="staff",
        )
        return created(data={
            "id": record.id,
            "vaccine_name": record.vaccine_name,
            "due_date": str(record.due_date) if record.due_date else None,
            "reason": record.reason,
            "verification_status": record.verification_status,
        }, message="Vaccine order recorded.")


class PatientVaccinationDeclineView(APIView):
    """
    POST /api/v1/patients/<pk>/vaccinations/decline/
    Body: { vaccine_name, scheduled_label?, reason?, record_id? }

    Doctor-only. Marks a roadmap slot as not clinically required for this
    patient. There may be no existing record for that slot yet (a roadmap
    slot with status "unknown" has none) — this action creates one if
    needed so there's a row to carry the "declined" status, or updates
    record_id if one is passed (e.g. declining a prior doctor-ordered
    record that's no longer wanted).
    """
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        from apps.registry.models import SharedVaccination

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        d = request.data
        reason = (d.get("reason") or "").strip()
        doctor_name = getattr(request.user, "full_name", None) or getattr(request.user, "email", "Doctor")
        record_id = d.get("record_id")

        if record_id:
            record = SharedVaccination.objects.using("default").filter(pk=record_id, awpid=patient.awpid).first()
            if not record:
                return not_found("Vaccination record not found for this patient.")
        else:
            vaccine_name = (d.get("vaccine_name") or "").strip()
            scheduled_label = (d.get("scheduled_label") or "").strip()
            if not vaccine_name:
                return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
            record = SharedVaccination.objects.using("default").create(
                awpid=patient.awpid,
                vaccine_name=vaccine_name,
                scheduled_label=scheduled_label,
                administered_date=None,
                source=SharedVaccination.SOURCE_DOCTOR_ORDERED,
                verification_status=SharedVaccination.STATUS_DECLINED,
                source_tenant_id=request.tenant_id,
                recorded_by="staff",
            )

        record.verification_status = SharedVaccination.STATUS_DECLINED
        record.reason = reason or record.reason
        record.review_notes = reason or record.review_notes
        record.verified_by_name = doctor_name
        record.verified_at = timezone.now()
        if record.source_tenant_id is None:
            record.source_tenant_id = request.tenant_id
        record.save(using="default", update_fields=[
            "verification_status", "reason", "review_notes", "verified_by_name",
            "verified_at", "source_tenant_id",
        ])
        return success(data={
            "id": record.id,
            "vaccine_name": record.vaccine_name,
            "verification_status": record.verification_status,
        }, message="Vaccine marked as not required.")


class PatientVaccinationAdministerView(APIView):
    """
    POST /api/v1/patients/<pk>/vaccinations/administer/
    Body: { record_id? , vaccine_name?, scheduled_label?, administered_date?, dose_number? }

    Nurse (or doctor) marks a vaccine as administered today. If record_id
    is given (typically a prior doctor-ordered row, verification_status
    "ordered"), that same row is updated in place — source flips to
    "clinic", verification_status to "verified", administered_date is
    filled in. Otherwise a fresh clinic-administered row is created (same
    auto-verified pattern as PatientVaccinationListCreateView.post —
    clinic-administered records don't need review).
    """
    permission_classes = [IsDoctorOrNurse]

    def post(self, request, pk):
        from apps.registry.models import SharedVaccination

        try:
            patient = Patient.objects.using(request.tenant_db).get(pk=pk)
        except Patient.DoesNotExist:
            return not_found("Patient not found.")

        d = request.data
        administered_date = d.get("administered_date") or date.today().isoformat()
        dose_number = d.get("dose_number") or None
        staff_name = getattr(request.user, "full_name", None) or getattr(request.user, "email", "Staff")
        record_id = d.get("record_id")

        # Resolve which vaccine this is BEFORE handling any attached file —
        # _handle_vaccination_file() bakes the vaccine name into file_name
        # (see display_file_name()), so for the record_id path that means
        # fetching the record first rather than after, purely to know its
        # vaccine_name in time for naming the file.
        record = None
        if record_id:
            record = SharedVaccination.objects.using("default").filter(pk=record_id, awpid=patient.awpid).first()
            if not record:
                return not_found("Vaccination record not found for this patient.")
            vaccine_name_for_file = record.vaccine_name
        else:
            vaccine_name_for_file = (d.get("vaccine_name") or "").strip()

        file_name, mime_type, file_key, err = _handle_vaccination_file(patient, d, vaccine_name_for_file)
        if err:
            return err
        has_file = bool(file_key)

        if record_id:
            # Replacing whatever certificate (if any) was already on file —
            # e.g. a doctor-ordered row administered here had none, or a
            # rejected self-reported upload is being corrected — so clean up
            # the old S3 object first, same replace-on-write pattern used
            # everywhere else a stored file can be overwritten.
            old_file_key = record.file_data
            record.administered_date = administered_date
            record.source = SharedVaccination.SOURCE_CLINIC
            record.verification_status = SharedVaccination.STATUS_VERIFIED
            record.verified_by_name = staff_name
            record.verified_at = timezone.now()
            if dose_number:
                record.dose_number = dose_number
            if record.source_tenant_id is None:
                record.source_tenant_id = request.tenant_id
            record.recorded_by = "staff"
            update_fields = [
                "administered_date", "source", "verification_status", "verified_by_name",
                "verified_at", "dose_number", "source_tenant_id", "recorded_by",
            ]
            if has_file:
                record.file_name = file_name
                record.mime_type = mime_type
                record.file_data = file_key
                update_fields += ["file_name", "mime_type", "file_data"]
            record.save(using="default", update_fields=update_fields)
            if has_file and old_file_key:
                blob_storage.delete(old_file_key)
        else:
            vaccine_name = (d.get("vaccine_name") or "").strip()
            if not vaccine_name:
                return error("vaccine_name or record_id is required.", errors={"vaccine_name": "Required."})
            scheduled_label = (d.get("scheduled_label") or "").strip()
            record = SharedVaccination.objects.using("default").create(
                awpid=patient.awpid,
                vaccine_name=vaccine_name,
                scheduled_label=scheduled_label,
                administered_date=administered_date,
                dose_number=dose_number,
                source=SharedVaccination.SOURCE_CLINIC,
                verification_status=SharedVaccination.STATUS_VERIFIED,
                verified_by_name=staff_name,
                verified_at=timezone.now(),
                source_tenant_id=request.tenant_id,
                recorded_by="staff",
                file_name=file_name,
                mime_type=mime_type,
                file_data=file_key,
            )

        return success(data={
            "id": record.id,
            "vaccine_name": record.vaccine_name,
            "administered_date": str(record.administered_date),
            "verification_status": record.verification_status,
            "has_certificate": bool(record.file_data),
        }, message="Vaccination recorded as administered.")
