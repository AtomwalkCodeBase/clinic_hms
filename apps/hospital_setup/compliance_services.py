"""apps/hospital_setup/compliance_services.py"""

import logging

logger = logging.getLogger(__name__)

CURRENT_POLICY_VERSION = "v1"


def record_consent(db, patient, consent_type, source, request=None,
                    recorded_by=None, granted=True, notes=""):
    """Write one ConsentRecord row to the given hospital db."""
    try:
        from apps.hospital_setup.models import ConsentRecord

        ip_address = None
        user_agent = ""
        if request is not None:
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            ip_address = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
            user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]

        ConsentRecord.objects.using(db).create(
            patient=patient,
            consent_type=consent_type,
            granted=granted,
            source=source,
            recorded_by=recorded_by,
            ip_address=ip_address,
            user_agent=user_agent,
            policy_version=CURRENT_POLICY_VERSION,
            notes=notes,
        )
    except Exception as exc:
        logger.error(
            "Consent record write failed for patient=%s type=%s source=%s: %s",
            getattr(patient, "pk", patient), consent_type, source, exc,
        )
