"""apps/hospital_setup/compliance_services.py"""

import logging

logger = logging.getLogger(__name__)

CURRENT_POLICY_VERSION = "v1"


_CONSENT_FLAGS = {
    "hie_data_sharing": ("hie_consent_given", "hie_consent_at"),
    "dpdp_data_processing": ("dpdp_consent_captured", "dpdp_consent_at"),
}


def record_consent(db, patient, consent_type, source, request=None,
                    recorded_by=None, granted=True, notes=""):
    """Write one ConsentRecord row and set the matching flag on the patient in the same transaction."""
    try:
        from apps.hospital_setup.models import ConsentRecord

        ip_address = None
        user_agent = ""
        if request is not None:
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            ip_address = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
            user_agent = request.META.get("HTTP_USER_AGENT", "")[:1000]

        from django.db import transaction
        from django.utils import timezone

        with transaction.atomic(using=db):
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
            flags = _CONSENT_FLAGS.get(consent_type)
            if flags:
                now = timezone.now()
                values = {flags[0]: granted, flags[1]: now}
                type(patient).objects.using(db).filter(pk=patient.pk).update(**values)
                for name, value in values.items():
                    setattr(patient, name, value)
    except Exception as exc:
        logger.error(
            "Consent record write failed for patient=%s type=%s source=%s: %s",
            getattr(patient, "pk", patient), consent_type, source, exc,
        )
