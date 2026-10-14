"""
apps/atomwalk/hie.py
--------------------
Write-through of a signed OPD encounter into the shared Atomwalk tables: its diagnoses become clinical events. (The
vitals are written to atomwalk when the nurse records them, and the prescription's drugs when its document is made, see
apps/opd/archive.py.) Moved out of opd/views.py, which the seed commands had to import an underscore-prefixed function from.
"""

import logging

logger = logging.getLogger(__name__)


def sync_encounter_to_hie(encounter, db, patient, hospital_id=None):
    """
    Copy this encounter's diagnoses to the shared clinical events so other hospitals can see this patient's
    cross-provider history. Never blocks sign-off: all failures are logged and swallowed.

    `hospital_id` is the atomwalk id of the hospital writing the rows (request.hospital_id);
    when omitted (seed commands) it is resolved from `db` — see resolve_source_hospital_id.
    """
    if patient is None or not getattr(patient, "awpid", None):
        logger.warning("HIE sync skipped for encounter %s: no patient/awpid.", encounter.id)
        return

    from apps.atomwalk.models import ClinicalEvent, Patient
    from apps.hospitals.utils import resolve_source_hospital_id

    shared = Patient.objects.using("default").filter(awpid=patient.awpid).first()
    if shared is None:
        logger.warning("HIE sync skipped for encounter %s: %s has no shared patient.", encounter.id, patient.awpid)
        return
    source_hospital_id = hospital_id or resolve_source_hospital_id(db)
    seen_on = getattr(encounter, "encounter_date", None)

    # OPDEncounter.diagnoses is a JSON list of {code, description}
    for diag in (encounter.diagnoses or []):
        try:
            ClinicalEvent.objects.using("default").update_or_create(
                patient=shared, source_hospital_id=source_hospital_id, event_type="DIAGNOSIS", icd10=diag.get("code", ""),
                defaults={"condition_text": diag.get("description", ""), "clinical_status": "active", "event_date": seen_on,
                          "source": "HOSPITAL"},
            )
        except Exception:
            logger.exception("HIE ClinicalEvent write failed for encounter=%s", encounter.id)
