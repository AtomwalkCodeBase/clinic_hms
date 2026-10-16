"""apps/hospital_patients/signals.py"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.opd.models import Allergy

logger = logging.getLogger(__name__)


def _get_source_hospital_id(instance):
    """Atomwalk id of the hospital this Allergy belongs to (0 if it can't be resolved)."""
    try:
        from apps.hospital_master.services import resolve_source_hospital_id
        return resolve_source_hospital_id(instance._state.db)
    except Exception:
        return 0


@receiver(post_save, sender=Allergy)
def on_allergy_save(sender, instance, **kwargs):
    from apps.patients.models import Patient
    from apps.documents.models import SharedAllergy
    try:
        shared = Patient.objects.using("default").filter(awpid=instance.patient.awpid).first()
        if shared is None:
            raise LookupError(f"{instance.patient.awpid} has no shared patient")
        SharedAllergy.objects.using("default").update_or_create(
            patient=shared,
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
