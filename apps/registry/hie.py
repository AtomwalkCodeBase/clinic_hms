"""
apps/registry/hie.py
--------------------
Write-through of a signed OPD encounter into the registry's shared HIE tables
(SharedDiagnosis / SharedVital / SharedPrescription). Moved out of opd/views.py, which
the seed commands had to import an underscore-prefixed function from.
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def sync_encounter_to_hie(encounter, db, patient, tenant_id=None):
    """
    Push a sanitized copy of this encounter's diagnoses, vitals, and
    prescription to the registry's shared HIE tables so other hospitals can
    see this patient's cross-provider history. Never blocks sign-off —
    all failures are logged and swallowed.

    `tenant_id` is the registry id of the hospital writing the rows (request.tenant_id);
    when omitted (seed commands) it is resolved from `db` — see resolve_source_tenant_id.
    """
    if patient is None or not getattr(patient, "awpid", None):
        logger.warning("HIE sync skipped for encounter %s: no patient/awpid.", encounter.id)
        return

    from apps.registry.models import SharedDiagnosis, SharedVital, SharedPrescription, SharedPrescriptionItem
    from apps.tenants.utils import resolve_source_tenant_id

    source_tenant_id = tenant_id or resolve_source_tenant_id(db)
    awpid = patient.awpid

    # ── Diagnoses (OPDEncounter.diagnoses is a JSON list of {code, description}) ──
    for diag in (encounter.diagnoses or []):
        try:
            SharedDiagnosis.objects.using("default").update_or_create(
                awpid=awpid,
                source_tenant_id=source_tenant_id,
                icd10_code=diag.get("code", ""),
                defaults={
                    "description":     diag.get("description", ""),
                    "clinical_status": "active",
                    "onset_date":      encounter.encounter_date if hasattr(encounter, "encounter_date") else None,
                },
            )
        except Exception:
            logger.exception("HIE SharedDiagnosis write failed for encounter=%s", encounter.id)

    # ── Vitals (one row per appointment, via OneToOne) ─────────────────────
    try:
        vitals = encounter.appointment.vitals
    except Exception:
        vitals = None
    if vitals is not None:
        try:
            SharedVital.objects.using("default").update_or_create(
                awpid=awpid,
                recorded_at=vitals.recorded_at,
                defaults={
                    "source":            "clinic",
                    "bp_systolic":       vitals.systolic_bp,
                    "bp_diastolic":      vitals.diastolic_bp,
                    "pulse_rate":        vitals.pulse_rate,
                    "spo2":              vitals.spo2,
                    "temperature":       vitals.temperature,
                    "weight_kg":         vitals.weight_kg,
                    "height_cm":         vitals.height_cm,
                    "head_circumference_cm": vitals.head_circumference_cm,
                    "resp_rate":         vitals.respiratory_rate,
                    "blood_sugar_mgdl":  vitals.blood_sugar_rbs,
                    "source_tenant_id":  source_tenant_id,
                },
            )
        except Exception:
            logger.exception("HIE SharedVital write failed for encounter=%s", encounter.id)

    # ── Prescription (opd.Prescription is OneToOne on the encounter) ───────
    try:
        rx = encounter.prescription
    except Exception:
        rx = None
    if rx is not None:
        try:
            shared_rx, _ = SharedPrescription.objects.using("default").update_or_create(
                awpid=awpid,
                source_tenant_id=source_tenant_id,
                prescribed_on=(rx.created_at.date() if rx.created_at else timezone.now().date()),
            )
            SharedPrescriptionItem.objects.using("default").filter(prescription=shared_rx).delete()
            for item in rx.items.all():
                SharedPrescriptionItem.objects.using("default").create(
                    prescription=shared_rx,
                    drug_name=item.drug_name,
                    dose=item.dosage,
                    unit="",
                    frequency=item.frequency,
                    route=item.route,
                    duration_days=item.duration_days,
                )
        except Exception:
            logger.exception("HIE SharedPrescription write failed for encounter=%s", encounter.id)
