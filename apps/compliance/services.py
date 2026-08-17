"""
apps/compliance/services.py
-----------------------------
record_consent() — single entry point for writing a ConsentRecord row.

Mirrors core.audit.log_action()'s never-break-the-caller contract: consent
was already captured (the boolean flag on Patient is the source of truth
checked at request time), this is writing the durable proof of that event
after the fact, so a failure here must not turn a successful registration
or booking into a failed one. Logged at ERROR so a failure is still visible
to ops — unlike a routine access-log write, losing a consent-proof row is
something a compliance team would want to know about and backfill.

Current policy-text version — bump this (and keep a changelog somewhere,
e.g. this docstring) whenever the actual consent copy shown to
patients/front-desk changes:
  v1 — initial DPDP data-processing + HIE data-sharing consent language.
"""

import logging

logger = logging.getLogger(__name__)

CURRENT_POLICY_VERSION = "v1"


def record_consent(db, patient, consent_type, source, request=None,
                    recorded_by=None, granted=True, notes=""):
    """
    Write one ConsentRecord row to the given tenant db.

    Args:
        db:            tenant db alias (request.tenant_db).
        patient:       apps.patients.models.Patient instance (or patient_id int).
        consent_type:  ConsentRecord.CONSENT_DPDP_PROCESSING or CONSENT_HIE_SHARING.
        source:        ConsentRecord.SOURCE_FRONT_DESK or SOURCE_PORTAL.
        request:       optional — used to pull client IP/user agent when available.
        recorded_by:   optional StaffUser (or id) — set for front-desk-attested consent.
        granted:       True for a grant event (default) — kept as a parameter,
                       not hardcoded, so a future revocation flow can reuse
                       this same function with granted=False.
        notes:         optional free text (e.g. "verbal consent, patient could not sign").
    """
    try:
        from .models import ConsentRecord

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
