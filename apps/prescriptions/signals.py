"""
apps/prescriptions/signals.py
------------------------------
Write-through: when a Prescription is finalized, mirror it to registry.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Prescription

logger = logging.getLogger(__name__)


def _get_source_tenant_id():
    try:
        from core.db_router import _thread_local
        return getattr(_thread_local, "tenant_id", 0) or 0
    except Exception:
        return 0


@receiver(post_save, sender=Prescription)
def on_prescription_finalized(sender, instance, **kwargs):
    if instance.status != "finalized":
        return

    from apps.registry.models import SharedPrescription, SharedPrescriptionItem
    try:
        shared_rx, _ = SharedPrescription.objects.using("default").update_or_create(
            awpid=instance.patient.awpid,
            source_tenant_id=_get_source_tenant_id(),
            prescribed_on=instance.finalized_at.date() if instance.finalized_at else None,
        )
        # Sync items
        SharedPrescriptionItem.objects.using("default").filter(
            prescription=shared_rx
        ).delete()
        for item in instance.items.all():
            SharedPrescriptionItem.objects.using("default").create(
                prescription=shared_rx,
                drug_name=item.drug_name,
                dose=item.dose,
                unit=item.unit,
                frequency=item.frequency,
                route=item.route,
                duration_days=item.duration_days,
            )
    except Exception as exc:
        logger.error(
            "HIE SharedPrescription write failed for prescription=%s: %s", instance.id, exc
        )
