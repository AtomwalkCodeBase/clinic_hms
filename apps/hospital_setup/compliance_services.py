"""apps/hospital_setup/compliance_services.py"""

import logging

logger = logging.getLogger(__name__)

CURRENT_POLICY_VERSION = "v1"




def log_action(request, db, action, resource_type="", resource_id="", patient_id=None, metadata=None):
    """Write one AuditLog row to the given hospital db. `request` is used to pull the actor and address; `patient_id` is the HospitalPatient, its id or its uhid."""
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

        patient_pk = getattr(patient_id, "pk", patient_id)            # a HospitalPatient, its id, or its uhid
        if isinstance(patient_pk, str):
            from apps.hospital_patients.models import HospitalPatient
            patient_pk = HospitalPatient.objects.using(db).filter(uhid=patient_pk).values_list("pk", flat=True).first()

        AuditLog.objects.using(db).create(
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            actor_role=actor_role,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else "",
            patient_id=patient_pk,
            ip_address=ip_address,
            metadata=metadata or {},
        )
    except Exception as exc:
        logger.error("Audit log write failed for action=%s: %s", action, exc)
