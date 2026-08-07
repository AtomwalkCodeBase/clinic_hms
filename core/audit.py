"""
core/audit.py
--------------
Single entry point for writing audit log entries. Never raises — an audit
write failure must not break the request it's auditing.

Usage:
    from core.audit import log_action
    log_action(request, db, action="encounter.sign",
               resource_type="OPDEncounter", resource_id=str(enc.id),
               patient_id=enc.patient_id)
"""

import logging

logger = logging.getLogger(__name__)


def log_action(request, db, action, resource_type="", resource_id="", patient_id=None, metadata=None):
    """
    Write one AuditLog row to the given tenant db. `request` is used to pull
    the actor identity (request.user, set by JWTTenantAuthentication) and
    client IP — both optional, so this degrades gracefully outside a request
    (e.g. management commands can pass request=None).
    """
    try:
        from apps.org.models import AuditLog

        actor_user_id = None
        actor_email = ""
        actor_role = ""
        ip_address = None

        if request is not None:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                actor_user_id = getattr(user, "id", None)
                actor_email = getattr(user, "email", "") or ""
                actor_role = getattr(user, "role", "") or ""
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            ip_address = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")

        AuditLog.objects.using(db).create(
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else "",
            patient_id=patient_id,
            ip_address=ip_address,
            metadata=metadata or {},
        )
    except Exception as exc:
        logger.error("Audit log write failed for action=%s: %s", action, exc)
