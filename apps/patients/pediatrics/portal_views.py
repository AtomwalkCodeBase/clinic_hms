"""
apps/patients/pediatrics/portal_views.py
----------------------------------------
The patient portal's pediatric endpoints, under /api/v1/portal/. They act for the logged-in account or one of its
family members (`?patient_awpid=`), and the portal never filters by consent: patients see all their own data.

  GET    growth/                       height / weight / head circumference over time, with WHO percentiles
  GET    vaccinations/                 vaccination roadmap (the default schedule, as the portal spans hospitals)
  POST   vaccinations/upload/          a parent reports a dose given elsewhere, with an optional certificate
  GET    vaccinations/<id>/file/       one certificate
  GET    milestones/                   milestone roadmap
  GET    family/ POST family/          list / add family members (children and others without a login)
  PATCH  family/<awpid>/ DELETE        edit / unlink a family member
"""
from rest_framework.views import APIView

from core import storage as blob_storage
from core.file_validation import validate_data_uri, FileValidationError
from core.permissions import IsPatient
from core.response import success, error, not_found

from apps.patients.age_utils import age_years_months
from apps.patients.pediatrics.common import growth_point, has_measurement, parse_date, text
from apps.patients.pediatrics.growth_reference import add_percentiles
from apps.patients.pediatrics.roadmap import rules_for
from apps.patients.portal_access import resolve_target_awpid_and_dob
from apps.patients.services import PatientService
from apps.registry.models import (
    PatientAccount, PatientIdentity, PatientRelationship, SharedVaccination, SharedVital)

_MAX_CERTIFICATE_CHARS = 15_500_000      # about 11 MB of base64, the same cap as document uploads


def _account(request):
    return PatientAccount.objects.using("default").get(pk=request.user.id)


# ── growth ────────────────────────────────────────────────────────────────────────────────────────────────────────
class PortalGrowthView(APIView):
    """Readings come from SharedVital (every hospital's visits), with source "clinic" or "home"."""
    permission_classes = [IsPatient]

    def get(self, request):
        awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        readings = SharedVital.objects.using("default").filter(awpid=awpid).order_by("recorded_at")
        series = [growth_point(v, v.source) for v in readings if has_measurement(v)]
        age = age_years_months(dob)
        is_minor = age is not None and age[0] < 18
        gender = getattr(PatientIdentity.objects.using("default").filter(awpid=awpid).first(), "gender", None)
        return success(data={
            "date_of_birth": dob,
            "age_years": age[0] if age else None,
            "age_months": age[1] if age else None,
            "is_minor": is_minor,
            "series": series,
            "latest": series[-1] if series else None,
            "percentile_available": is_minor and add_percentiles(series, gender, dob),
        })


# ── roadmaps ──────────────────────────────────────────────────────────────────────────────────────────────────────
class PortalVaccinationListView(APIView):
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.patients.pediatrics.vaccine_schedule import build_roadmap, summarize_roadmap

        awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        roadmap = build_roadmap(awpid, dob, rules_for("vaccination"))
        summary = summarize_roadmap(roadmap)
        return success(data={"date_of_birth": dob, "roadmap": roadmap, "completed_count": summary["completed_count"],
                             "total_count": summary["total_count"], "next_recommended": summary["next_recommended"],
                             "stats": summary["stats"]})


class PortalMilestoneListView(APIView):
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.patients.pediatrics.milestone_roadmap import build_roadmap, summarize_roadmap

        awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        roadmap = build_roadmap(awpid, dob, rules_for("milestone"))
        summary = summarize_roadmap(roadmap)
        return success(data={"date_of_birth": dob, "roadmap": roadmap, "achieved_count": summary["achieved_count"],
                             "total_count": summary["total_count"], "next_recommended": summary["next_recommended"],
                             "stats": summary["stats"]})


# ── vaccination uploads ───────────────────────────────────────────────────────────────────────────────────────────
class PortalVaccinationUploadView(APIView):
    """
    Body: {vaccine_name, administered_date, scheduled_label?, patient_awpid?, file_data?}.
    A parent reports a dose given outside the network, optionally with a certificate photo. It always lands as
    "pending_review": only a doctor or nurse verifying it (PatientVaccinationVerifyView) makes it count as verified.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        d = request.data
        name = text(d, "vaccine_name")
        if not name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not d.get("administered_date"):
            return error("Administered date is required.", errors={"administered_date": "Required."})
        given_on, err = parse_date(d["administered_date"], "administered_date", "Administered date")
        if err:
            return err

        file_name, mime_type, file_key = text(d, "file_name"), text(d, "mime_type"), d.get("file_data") or ""
        if file_key:
            if len(file_key) > _MAX_CERTIFICATE_CHARS:
                return error("File is too large. Please upload a smaller file (under ~11MB).")
            owner = PatientIdentity.objects.using("default").filter(awpid=awpid).first()
            owner_name = owner.full_name if owner else ""
            try:
                mime_type = validate_data_uri(file_key)
                file_key = blob_storage.upload_data_uri(
                    file_key, prefix="vaccination-certs", mime_type=mime_type, category="vaccination-certificate",
                    identity=blob_storage.identity_slug(name=owner_name, identifier=awpid))
            except (FileValidationError, blob_storage.StorageError) as exc:
                return error(str(exc), errors={"file_data": str(exc)})
            file_name = blob_storage.display_file_name("vaccination-certificate", mime_type, detail=name,
                                                       name=owner_name, identifier=awpid)

        record = SharedVaccination.objects.using("default").create(
            awpid=awpid, vaccine_name=name, scheduled_label=text(d, "scheduled_label"), administered_date=given_on,
            source=SharedVaccination.SOURCE_SELF_REPORTED, verification_status=SharedVaccination.STATUS_PENDING,
            file_name=file_name, mime_type=mime_type, file_data=file_key, recorded_by="patient")
        return success(data={"id": record.id, "vaccine_name": record.vaccine_name,
                             "administered_date": str(record.administered_date),
                             "verification_status": record.verification_status},
                       message="Submitted. This will show as pending review until a doctor confirms it.")


class PortalVaccinationFileView(APIView):
    """One certificate. The roadmap only says has_certificate; the file is fetched here, for the account or its family."""
    permission_classes = [IsPatient]

    def get(self, request, record_id):
        record = SharedVaccination.objects.using("default").filter(pk=record_id).first()
        if not record:
            return not_found("Vaccination record not found.")
        account = _account(request)
        if record.awpid != account.awpid and not PatientRelationship.objects.using("default").filter(
                guardian_awpid=account.awpid, dependent_awpid=record.awpid).exists():
            return error("This record does not belong to you.", status=403)
        if not record.file_data:
            return not_found("No certificate has been uploaded for this record.")
        return success(data={"file_data": blob_storage.signed_url(record.file_data),
                             "file_name": record.file_name, "mime_type": record.mime_type})


# ── family ────────────────────────────────────────────────────────────────────────────────────────────────────────
class PortalFamilyListCreateView(APIView):
    """
    POST body: {full_name, date_of_birth, gender?, relationship?}. A member added here and one added by a hospital's
    front desk under the same guardian resolve to the same AWPID (matched on name and date of birth).
    """
    permission_classes = [IsPatient]

    def get(self, request):
        return success(data={"results": PatientService.list_family_members(_account(request).awpid)})

    def post(self, request):
        account, d = _account(request), request.data
        try:
            member = PatientService.add_family_member(
                guardian_awpid=account.awpid, guardian_mobile_hash=account.mobile_hash,
                data={"full_name": text(d, "full_name"), "date_of_birth": d.get("date_of_birth"),
                      "gender": d.get("gender", ""), "relationship": d.get("relationship", "other")})
        except ValueError as exc:
            return error(str(exc))
        return success(data=member, message="Family member added." if member.get("created")
                       else "Reconnected — their existing records are linked again.")


class PortalFamilyDetailView(APIView):
    """Edit a family member, or unlink them from this account (their records stay). Only for members linked to the account."""
    permission_classes = [IsPatient]

    def patch(self, request, awpid):
        changes = {k: request.data.get(k) for k in ("full_name", "date_of_birth", "gender", "relationship") if k in request.data}
        try:
            member = PatientService.update_family_member(
                guardian_awpid=_account(request).awpid, dependent_awpid=awpid, data=changes)
        except ValueError as exc:
            return error(str(exc))
        return success(data=member, message="Family member updated.")

    def delete(self, request, awpid):
        try:
            PatientService.remove_family_member(guardian_awpid=_account(request).awpid, dependent_awpid=awpid)
        except ValueError as exc:
            return error(str(exc))
        return success(message="Family member removed.")
