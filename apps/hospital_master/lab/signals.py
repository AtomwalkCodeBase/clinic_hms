"""
apps/lab/signals.py
--------------------
Write-through: when a LabReport is delivered, mirror it to atomwalk.LabResult.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.hospital_master.lab.models import LabReport

logger = logging.getLogger(__name__)


def _get_source_hospital_id(instance):
    """Atomwalk id of the hospital this LabReport belongs to (0 if it can't be resolved)."""
    try:
        from apps.atomwalk.hospital_master.services import resolve_source_hospital_id
        return resolve_source_hospital_id(instance._state.db)
    except Exception:
        return 0


@receiver(post_save, sender=LabReport)
def on_report_delivered(sender, instance, **kwargs):
    if instance.status != "delivered" or not instance.delivered_at:
        return

    from apps.atomwalk.documents.models import LabResult
    from apps.atomwalk.documents.models import MedicalDocument
    from apps.atomwalk.patients.models import Patient

    # Mirror into the My Reports document vault (MedicalDocument) so a delivered lab report shows in the patient's
    # My Reports. The result below links to it; it is also the report's file. Best-effort: a failure here must not
    # roll back the deliver.
    document = None
    try:
        from apps.hospital_master.lab.archive import store_lab_report_document
        document = store_lab_report_document(instance, instance._state.db, _get_source_hospital_id(instance))
    except Exception:
        logger.exception("My Reports vault mirror failed for report=%s", instance.id)

    try:
        shared = Patient.objects.using("default").filter(awpid=instance.patient.awpid).first()
        if shared is None:
            raise LookupError(f"{instance.patient.awpid} has no shared patient")
        LabResult.objects.using("default").update_or_create(
            patient=shared,
            source_hospital_id=_get_source_hospital_id(instance),
            delivered_at=instance.delivered_at,
            defaults={
                "test_name":      instance.request.test.name,
                "result_summary": instance.result_summary,
                "document":       document if isinstance(document, MedicalDocument) else None,
            },
        )
    except Exception:
        logger.exception("HIE LabResult write failed for report=%s", instance.id)
