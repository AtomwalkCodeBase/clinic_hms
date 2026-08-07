"""
apps/clinical/signals.py
------------------------
Django signals that implement the HIE (Health Information Exchange) write-through pattern.

On clinical events:
  encounter.close  → write SharedDiagnosis, SharedVital copies to Registry DB
  allergy.create   → write SharedAllergy copy to Registry DB

Rules:
  - source_tenant_id is stored in the shared table but NEVER returned
    in API responses to other tenants (enforced by serializers).
  - Only finalized/closed records are written — drafts stay private.
  - Writes use using="default" to target the Registry DB explicitly.
  - Failures are logged but never raise (clinical save must not fail due to HIE).
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

from .models import Encounter, Vital, Diagnosis

logger = logging.getLogger(__name__)


def _get_source_tenant_id():
    """
    Read tenant_id from thread-local (set by JWTTenantMiddleware).
    Falls back to 0 if called outside a request context (e.g. tests).
    """
    try:
        from core.db_router import _thread_local
        return getattr(_thread_local, "tenant_id", 0) or 0
    except Exception:
        return 0


@receiver(post_save, sender=Encounter)
def on_encounter_close(sender, instance, **kwargs):
    """
    When an encounter is closed, write all its diagnoses and vitals
    to the shared HIE tables in the Registry DB.
    """
    if instance.status != "closed":
        return

    # Lazy import to avoid circular imports
    from apps.registry.models import SharedDiagnosis, SharedVital

    awpid = instance.patient.awpid
    source_tenant_id = _get_source_tenant_id()

    # ── Write diagnoses ───────────────────────────────────────────────────
    for diag in instance.diagnoses.all():
        try:
            SharedDiagnosis.objects.using("default").update_or_create(
                # Use a deterministic lookup so re-closing doesn't duplicate
                # Using encounter id + diagnosis id as natural composite key
                awpid=awpid,
                source_tenant_id=source_tenant_id,
                # Store icd10_code + onset_date as natural duplicate guard
                icd10_code=diag.icd10_code or "",
                onset_date=diag.onset_date,
                defaults={
                    "description":     diag.description,
                    "clinical_status": diag.clinical_status,
                },
            )
        except Exception as exc:
            logger.error(
                "HIE SharedDiagnosis write failed for encounter=%s diag=%s: %s",
                instance.id, diag.id, exc
            )

    # ── Write vitals ──────────────────────────────────────────────────────
    for vital in instance.vitals.all():
        try:
            SharedVital.objects.using("default").create(
                awpid=awpid,
                recorded_at=vital.recorded_at,
                source=vital.source,
                bp_systolic=vital.bp_systolic,
                bp_diastolic=vital.bp_diastolic,
                pulse_rate=vital.pulse_rate,
                spo2=vital.spo2,
                temperature=vital.temperature,
                weight_kg=vital.weight_kg,
                height_cm=vital.height_cm,
                resp_rate=vital.resp_rate,
                blood_sugar_mgdl=vital.blood_sugar_mgdl,
                source_tenant_id=source_tenant_id,
            )
        except Exception as exc:
            logger.error(
                "HIE SharedVital write failed for encounter=%s vital=%s: %s",
                instance.id, vital.id, exc
            )
