"""
apps/patients/portal_access.py
------------------------------
Which patient (the caller, or a linked family member) a patient-portal request is about.
Used by the portal views and by records.UploadView; moved out of portal_views.py, where
records had to import an underscore-prefixed view helper.
"""

from apps.registry.models import PatientAccount, PatientIdentity
from core.response import error


def resolve_target_awpid_and_dob(request):
    """
    Shared helper — resolves which patient (self or a linked family member)
    a portal request is about, and returns (awpid, date_of_birth, error_response).
    Mirrors the ownership check already used by PortalMyRecordsView /
    PortalHealthSummaryView: a family member's AWPID is only valid here if
    PatientRelationship actually links it to this account.
    """
    acct = PatientAccount.objects.using("default").get(pk=request.user.id)
    target_awpid = (request.query_params.get("patient_awpid") or request.data.get("patient_awpid") or "").strip() or acct.awpid

    if target_awpid == acct.awpid:
        return target_awpid, acct.date_of_birth, None

    from apps.registry.models import PatientRelationship
    is_family = PatientRelationship.objects.using("default").filter(
        guardian_awpid=acct.awpid, dependent_awpid=target_awpid,
    ).exists()
    if not is_family:
        return None, None, error("That patient isn't linked to your account.", status=403)

    identity = PatientIdentity.objects.using("default").filter(awpid=target_awpid).first()
    return target_awpid, (identity.date_of_birth if identity else None), None
