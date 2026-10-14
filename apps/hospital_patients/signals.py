"""
apps/hospital_patients/signals.py
-------------------------
Write-through: when an Allergy is saved, mirror it to atomwalk.SharedAllergy.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Allergy

logger = logging.getLogger(__name__)


def _get_source_hospital_id(instance):
    """Atomwalk id of the hospital this Allergy belongs to (0 if it can't be resolved)."""
    try:
        from apps.hospitals.utils import resolve_source_hospital_id
        return resolve_source_hospital_id(instance._state.db)
    except Exception:
        return 0


@receiver(post_save, sender=Allergy)
def on_allergy_save(sender, instance, **kwargs):
    from apps.atomwalk.models import SharedAllergy
    try:
        SharedAllergy.objects.using("default").update_or_create(
            awpid=instance.patient.awpid,
            substance=instance.substance,
            source_hospital_id=_get_source_hospital_id(instance),
            defaults={
                "reaction":    instance.reaction,
                "severity":    instance.severity,
                "is_active":   instance.is_active,
                "recorded_at": instance.recorded_at,
            },
        )
    except Exception:
        logger.exception("HIE SharedAllergy write failed for allergy=%s", instance.id)
