"""
apps/patients/emergency_views.py
---------------------------------
The public half of the "Emergency QR" feature (see core/emergency_access.py
for the token mechanics and apps/patients/portal_views.py::PortalEmergencyTokenView
for how the token is minted and consented to).

This is the ONE deliberately public, unauthenticated, patient-data-returning
endpoint in the whole codebase — reached by literally scanning a QR code, no
app install or login. That is a large exception to how every other PHI
endpoint in this project works, so a few things are true by design:

  - Registry DB only, no tenant-DB fan-out. A per-tenant lookup across every
    hospital for an unauthenticated request would be both a performance
    problem (N tenant DB hits per scan) and a DoS surface (anyone can mint
    scan traffic without ever having an account). Everything returned here
    already lives in the registry DB's Shared* tables.
  - This is the patient's FULL cross-hospital shared history — diagnoses,
    vitals (including head circumference for a minor), allergies,
    prescriptions, lab reports, uploaded documents, vaccination records,
    birth history, and flagged developmental-milestone concerns (for a
    minor patient) — including viewable files — not a trimmed subset.
    That's a deliberate scope decision (the earlier, narrower version of
    this view only surfaced active allergies/diagnoses/latest prescription;
    the patient explicitly asked for everything). It's reused straight from
    apps.patients.services.PatientService.get_shared_history(), the same
    helper PatientHistoryView uses for a logged-in doctor with HIE consent
    — so a scanning doctor here sees exactly the same shape of data a
    consenting cross-hospital doctor would, just resolved by a token instead
    of a session.
  - Because that's a much bigger disclosure than the narrower version, the
    generation endpoint (PortalEmergencyTokenView) now requires the patient
    to explicitly confirm a consent prompt — listing everything this view
    will expose — before minting a token at all. This view itself has
    nothing further to gate: by the time a token exists, consent already
    happened.
  - No HIE-consent gate here — hie_consent_given governs *passive* ambient
    cross-hospital access (another hospital's staff browsing this patient's
    roadmap without the patient in front of them). This endpoint is the
    opposite: an explicit, patient-initiated, time-boxed disclosure to
    whichever doctor is physically in front of them right now.
"""

import logging
from datetime import date

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.response import success, error
from core import storage as blob_storage
from core.emergency_access import decode_emergency_token, EmergencyTokenError
from apps.registry.models import (
    PatientIdentity, PatientAccount, PatientRelationship,
    SharedDocument, SharedLabResult, SharedVaccination,
    EmergencyAccessLog,
)

logger = logging.getLogger(__name__)


from .age_utils import age_years_months as _age_years_months


def _resolve_emergency_contact(awpid):
    """
    Best-effort "who do we call" for this patient:
      1. Their own portal account's emergency contact fields, if set.
      2. Failing that (common for a dependent whose guardian never filled
         those fields in on the child's behalf, or a dependent with no
         portal account of their own at all), fall back to the guardian
         account that registered them — the guardian IS the practical
         emergency contact for a dependent, even with no explicit fields set.
    Returns None if neither resolves to anything (self-registered adult who
    never filled in an emergency contact, no guardian on file).
    """
    account = PatientAccount.objects.using("default").filter(awpid=awpid).first()
    if account and (account.emergency_contact_name or account.emergency_contact_phone):
        return {
            "name": account.emergency_contact_name,
            "phone": account.emergency_contact_phone,
            "relation": account.emergency_contact_relation or "Emergency contact",
        }

    rel = (
        PatientRelationship.objects.using("default").filter(dependent_awpid=awpid, is_primary=True).first()
        or PatientRelationship.objects.using("default").filter(dependent_awpid=awpid).first()
    )
    if rel:
        guardian = PatientAccount.objects.using("default").filter(awpid=rel.guardian_awpid).first()
        if guardian:
            return {
                "name": guardian.full_name,
                "phone": guardian.mobile,
                "relation": "Parent/Guardian",
            }
    return None


def _birth_history(awpid):
    """
    A child's birth history, if any hospital has captured it — written
    through from BirthHistoryView (see apps.patients.pediatric_views) into
    registry.SharedBirthHistory. Returns None (not an empty dict) when
    nothing's on file, so the frontend can tell "no birth history" apart
    from "not applicable" the same way it already does for emergency_contact.
    """
    from apps.registry.models import SharedBirthHistory
    bh = SharedBirthHistory.objects.using("default").filter(awpid=awpid).first()
    if not bh:
        return None
    return {
        "gestational_age_weeks": bh.gestational_age_weeks,
        "birth_weight_kg": bh.birth_weight_kg,
        "delivery_mode": bh.delivery_mode,
        "multiple_birth": bh.multiple_birth,
        "nicu_admission": bh.nicu_admission,
        "nicu_days": bh.nicu_days,
        "birth_complications": bh.birth_complications,
        "congenital_conditions": bh.congenital_conditions,
        "apgar_score_1min": bh.apgar_score_1min,
        "apgar_score_5min": bh.apgar_score_5min,
    }


def _milestone_concerns(awpid):
    """
    Developmental-milestone records flagged "concern" by a doctor/nurse —
    the only milestone information an ER doctor treating an unfamiliar
    child actually needs in an emergency (a full achieved/not-yet roadmap is
    a well-child-visit concern, not an acute-care one; see
    apps.registry.milestone_roadmap for that fuller view, used by the
    doctor's own consultation screen and the parent's portal). Sourced
    straight from SharedMilestoneRecord — no schedule merge needed here,
    just "what has a clinician actually flagged."
    """
    from apps.registry.models import SharedMilestoneRecord
    records = (
        SharedMilestoneRecord.objects.using("default")
        .filter(awpid=awpid, status=SharedMilestoneRecord.STATUS_CONCERN)
        .order_by("-assessed_date")[:20]
    )
    return [{
        "domain": r.domain,
        "milestone": r.milestone,
        "assessed_date": r.assessed_date,
        "notes": r.notes,
        "recorded_by_name": r.recorded_by_name,
    } for r in records]


def _vaccination_history(awpid):
    """
    Every vaccination record on file, clinic-administered or self-reported —
    including ones still pending review, clearly labeled, so the scanning
    doctor sees the full picture rather than a silently trimmed one. Mirrors
    the file-access pattern below: certificate images are resolved to a
    signed URL here, not returned as raw base64.
    """
    records = (
        SharedVaccination.objects.using("default")
        .filter(awpid=awpid)
        .exclude(verification_status=SharedVaccination.STATUS_DECLINED)
        .order_by("-administered_date", "-created_at")[:50]
    )
    out = []
    for v in records:
        out.append({
            "vaccine_name": v.vaccine_name,
            "administered_date": v.administered_date,
            "dose_number": v.dose_number,
            "source": v.source,
            "verification_status": v.verification_status,
            "certificate_url": blob_storage.signed_url(v.file_data),
        })
    return out


class EmergencySummaryView(APIView):
    """
    GET /api/v1/emergency/<token>/

    No auth. Decodes the short-lived token, resolves the awpid it grants
    access to, and returns the patient's full shared clinical history plus
    an emergency contact. Any expired/invalid/malformed token returns a
    plain 400 with a patient-safe message — never a stack trace, since this
    endpoint is reachable by anyone with a camera.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "emergency"

    def get(self, request, token):
        try:
            awpid = decode_emergency_token(token)
        except EmergencyTokenError as exc:
            return error(message=str(exc), status=400)

        identity = PatientIdentity.objects.using("default").filter(awpid=awpid).first()
        if not identity:
            # Token was validly signed but the identity it points to is gone
            # — shouldn't happen outside of manual DB tampering, but fail
            # safe rather than 500.
            return error(message="This emergency code is no longer valid.", status=404)

        from apps.patients.services import PatientService
        history = PatientService.get_shared_history(awpid=awpid)

        # get_shared_history() keeps lab results/documents lightweight (an id
        # + metadata, no file content) so the same helper stays cheap for
        # PatientHistoryView's list view. This endpoint has nowhere further
        # for a doctor to click through to (no login to fetch the detail
        # endpoints with), so resolve every file to a signed URL right here.
        lab_result_ids = [r["id"] for r in history["lab_results"] if r.get("has_file")]
        lab_files = {
            r.id: blob_storage.signed_url(r.file_data)
            for r in SharedLabResult.objects.using("default").filter(id__in=lab_result_ids)
        }
        for r in history["lab_results"]:
            r["file_url"] = lab_files.get(r["id"], "")

        doc_ids = [d["id"] for d in history["documents"]]
        doc_files = {
            d.id: blob_storage.signed_url(d.file_data)
            for d in SharedDocument.objects.using("default").filter(id__in=doc_ids)
        }
        for d in history["documents"]:
            d["file_url"] = doc_files.get(d["id"], "")

        contact = _resolve_emergency_contact(awpid)
        vaccinations = _vaccination_history(awpid)
        # Newest additions to this endpoint — wrapped defensively so a
        # problem here (e.g. a deploy where this migration hasn't landed on
        # every environment yet) degrades to "not available" rather than
        # taking down the whole summary. Everything above this line is the
        # long-standing, load-bearing part of the page and deliberately
        # isn't wrapped the same way — a real failure there should surface
        # loudly, not be silently swallowed on a safety-critical screen.
        try:
            birth_history = _birth_history(awpid)
        except Exception:
            logger.exception("Emergency summary: birth history lookup failed for awpid=%s", awpid)
            birth_history = None
        try:
            milestone_concerns = _milestone_concerns(awpid)
        except Exception:
            logger.exception("Emergency summary: milestone concerns lookup failed for awpid=%s", awpid)
            milestone_concerns = []

        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        ip_address = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
        try:
            EmergencyAccessLog.objects.using("default").create(
                awpid=awpid, event=EmergencyAccessLog.EVENT_VIEWED, ip_address=ip_address,
            )
        except Exception:
            logger.exception("EmergencyAccessLog write failed (viewed) for awpid=%s", awpid)

        return success(data={
            "full_name": identity.full_name,
            "age_years": (_age_years_months(identity.date_of_birth) or (None,))[0],
            "age_months": (_age_years_months(identity.date_of_birth) or (None, None))[1],
            "date_of_birth": identity.date_of_birth,
            "gender": identity.gender,
            "blood_group": identity.blood_group,
            "allergies": history["allergies"],
            "diagnoses": history["diagnoses"],
            "vitals": history["vitals"],
            "prescriptions": history["prescriptions"],
            "lab_results": history["lab_results"],
            "documents": history["documents"],
            "vaccinations": vaccinations,
            "birth_history": birth_history,
            "milestone_concerns": milestone_concerns,
            "emergency_contact": contact,
        })
