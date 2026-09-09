"""
apps/lab/signals.py
--------------------
Write-through: when a LabReport is delivered, mirror it to registry.SharedLabResult.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import LabReport

logger = logging.getLogger(__name__)


def _get_source_tenant_id():
    try:
        from core.db_router import _thread_local
        return getattr(_thread_local, "tenant_id", 0) or 0
    except Exception:
        return 0


@receiver(post_save, sender=LabReport)
def on_report_delivered(sender, instance, **kwargs):
    if instance.status != "delivered" or not instance.delivered_at:
        return

    from apps.registry.models import SharedLabResult
    try:
        SharedLabResult.objects.using("default").update_or_create(
            awpid=instance.patient.awpid,
            source_tenant_id=_get_source_tenant_id(),
            delivered_at=instance.delivered_at,
            defaults={
                "test_name":      instance.request.test.name,
                "result_summary": instance.result_summary,
                # file_url stays untouched (URLField, can't hold a base64 data
                # URI) — the actual result file goes in file_data instead.
                "file_data":      instance.file_url,
                "mime_type":      instance.mime_type,
            },
        )
    except Exception as exc:
        logger.error("HIE SharedLabResult write failed for report=%s: %s", instance.id, exc)

    # Mirror into the My Reports document vault (SharedDocument) — same as
    # prescriptions get on sign, so a delivered lab report shows in the
    # patient's My Reports alongside them. Best-effort; a failure here must
    # not roll back the deliver.
    try:
        from apps.lab.archive import store_lab_report_document
        store_lab_report_document(instance, instance._state.db, _get_source_tenant_id())
    except Exception as exc:
        logger.error("My Reports vault mirror failed for report=%s: %s", instance.id, exc)
