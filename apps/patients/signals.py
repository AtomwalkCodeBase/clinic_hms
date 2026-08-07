"""
apps/patients/signals.py
-------------------------
Write-through: when an Allergy is saved, mirror it to registry.SharedAllergy.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Allergy

logger = logging.getLogger(__name__)


def _get_source_tenant_id():
    try:
        from core.db_router import _thread_local
        return getattr(_thread_local, "tenant_id", 0) or 0
    except Exception:
        return 0


@receiver(post_save, sender=Allergy)
def on_allergy_save(sender, instance, **kwargs):
    from apps.registry.models import SharedAllergy
    try:
        SharedAllergy.objects.using("default").update_or_create(
            awpid=instance.patient.awpid,
            substance=instance.substance,
            source_tenant_id=_get_source_tenant_id(),
            defaults={
                "reaction":    instance.reaction,
                "severity":    instance.severity,
                "is_active":   instance.is_active,
                "recorded_at": instance.recorded_at,
            },
        )
    except Exception as exc:
        logger.error("HIE SharedAllergy write failed for allergy=%s: %s", instance.id, exc)
