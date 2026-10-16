"""core/utils/audit.py"""

import logging

logger = logging.getLogger(__name__)


def log_action(request, db, action, resource_type="", resource_id="", patient_id=None, metadata=None):
    """Write one AuditLog row to the given hospital db. `request` is used to pull"""
    try:
        from apps.hospital_setup.models import AuditLog

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
