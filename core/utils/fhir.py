"""
core/utils/fhir.py
------------------
FHIR R4 serialization helpers for Atomwalk HMS.

These functions convert internal Django model instances into FHIR R4
compliant resource dicts. They are used by:
  - API responses that expose patient records in FHIR format
  - The shared HIE write-through (signals write sanitized copies to Registry DB)
  - Future FHIR bundle export for external interoperability

FHIR resource types used:
  Encounter         → apps/clinical Encounter
  Observation       → apps/clinical Vital
  Condition         → apps/clinical Diagnosis
  MedicationRequest → apps/prescriptions Prescription item
  DiagnosticReport  → apps/lab LabReport
  AllergyIntolerance→ apps/clinical Allergy

Design rules:
  - NEVER include source_tenant_id, hospital name, doctor name, or billing
    in resources returned to other tenants.
  - All datetimes are ISO-8601 UTC strings.
  - Missing optional fields are omitted (not set to null) to keep bundles clean.
"""

from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(dt) -> str | None:
    """Convert a datetime/date to ISO-8601 string. Returns None if dt is falsy."""
    if not dt:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


# ─── Encounter ────────────────────────────────────────────────────────────────

def encounter_to_fhir(encounter, awpid: str) -> dict:
    """
    Convert an Encounter model instance to a FHIR R4 Encounter resource.

    Excluded (never shared cross-tenant):
      - branch, doctor identity, billing references
    """
    resource = {
        "resourceType": "Encounter",
        "id": str(encounter.id),
        "status": "finished" if encounter.status == "closed" else "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "Ambulatory",
        },
        "subject": {
            "identifier": {"system": "https://atomwalk.com/awpid", "value": awpid}
        },
    }
    if encounter.encounter_date:
        resource["period"] = {"start": _iso(encounter.encounter_date)}
    if encounter.chief_complaint:
        resource["reasonCode"] = [{"text": encounter.chief_complaint}]
    return resource


# ─── Vital (Observation) ──────────────────────────────────────────────────────

# LOINC codes for common vitals
_VITAL_LOINC = {
    "bp_systolic":    ("55284-4", "Blood pressure systolic",  "mm[Hg]"),
    "bp_diastolic":   ("8462-4",  "Blood pressure diastolic", "mm[Hg]"),
    "pulse_rate":     ("8867-4",  "Heart rate",               "/min"),
    "spo2":           ("59408-5", "Oxygen saturation",        "%"),
    "temperature":    ("8310-5",  "Body temperature",         "Cel"),
    "weight_kg":      ("29463-7", "Body weight",              "kg"),
    "height_cm":      ("8302-2",  "Body height",              "cm"),
    "resp_rate":      ("9279-1",  "Respiratory rate",         "/min"),
    "blood_sugar_mgdl":("2339-0", "Glucose",                  "mg/dL"),
}


def vital_to_fhir(vital, awpid: str) -> list[dict]:
    """
    Convert a Vital model instance to a list of FHIR R4 Observation resources.
    One resource per recorded metric (only non-null fields are included).
    """
    observations = []
    for field, (loinc_code, display, unit) in _VITAL_LOINC.items():
        value = getattr(vital, field, None)
        if value is None:
            continue
        obs = {
            "resourceType": "Observation",
            "id": f"{vital.id}-{field}",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "vital-signs",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": loinc_code,
                        "display": display,
                    }
                ]
            },
            "subject": {
                "identifier": {"system": "https://atomwalk.com/awpid", "value": awpid}
            },
            "valueQuantity": {
                "value": float(value),
                "unit": unit,
                "system": "http://unitsofmeasure.org",
                "code": unit,
            },
        }
        if vital.recorded_at:
            obs["effectiveDateTime"] = _iso(vital.recorded_at)
        observations.append(obs)
    return observations


# ─── Diagnosis (Condition) ────────────────────────────────────────────────────

def diagnosis_to_fhir(diagnosis, awpid: str) -> dict:
    """
    Convert a Diagnosis model instance to a FHIR R4 Condition resource.
    clinical_status is required by FHIR R4 (active/resolved/inactive).
    """
    resource = {
        "resourceType": "Condition",
        "id": str(diagnosis.id),
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": diagnosis.clinical_status or "active",
                }
            ]
        },
        "subject": {
            "identifier": {"system": "https://atomwalk.com/awpid", "value": awpid}
        },
    }
    if diagnosis.icd10_code:
        resource["code"] = {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10",
                    "code": diagnosis.icd10_code,
                    "display": diagnosis.description or "",
                }
            ],
            "text": diagnosis.description or diagnosis.icd10_code,
        }
    elif diagnosis.description:
        resource["code"] = {"text": diagnosis.description}

    if diagnosis.onset_date:
        resource["onsetDateTime"] = _iso(diagnosis.onset_date)
    return resource


# ─── Prescription item (MedicationRequest) ────────────────────────────────────

def prescription_item_to_fhir(item, awpid: str, prescription_id) -> dict:
    """
    Convert a PrescriptionItem model instance to a FHIR R4 MedicationRequest.
    """
    resource = {
        "resourceType": "MedicationRequest",
        "id": str(item.id),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "text": item.drug_name or getattr(item.drug, "name", "Unknown"),
        },
        "subject": {
            "identifier": {"system": "https://atomwalk.com/awpid", "value": awpid}
        },
        "basedOn": [{"reference": f"Prescription/{prescription_id}"}],
    }
    dosage = {}
    if item.dose:
        dosage["text"] = f"{item.dose} {item.unit or ''}".strip()
    if item.frequency:
        dosage["timing"] = {"code": {"text": item.frequency}}
    if item.route:
        dosage["route"] = {"text": item.route}
    if item.duration_days:
        dosage["extension"] = [
            {
                "url": "https://atomwalk.com/fhir/ext/duration-days",
                "valueInteger": item.duration_days,
            }
        ]
    if dosage:
        resource["dosageInstruction"] = [dosage]
    return resource


# ─── Lab Report (DiagnosticReport) ───────────────────────────────────────────

def lab_report_to_fhir(report, awpid: str) -> dict:
    """
    Convert a LabReport model instance to a FHIR R4 DiagnosticReport.
    """
    resource = {
        "resourceType": "DiagnosticReport",
        "id": str(report.id),
        "status": "final",
        "subject": {
            "identifier": {"system": "https://atomwalk.com/awpid", "value": awpid}
        },
    }
    if report.test_name:
        resource["code"] = {"text": report.test_name}
    if report.delivered_at:
        resource["effectiveDateTime"] = _iso(report.delivered_at)
    if report.result_summary:
        resource["conclusion"] = report.result_summary
    return resource


# ─── FHIR Bundle ─────────────────────────────────────────────────────────────

def build_patient_bundle(awpid: str, resources: list[dict]) -> dict:
    """
    Wrap a list of FHIR resources into a FHIR R4 Bundle of type 'collection'.
    Used for full patient history export or cross-tenant sharing.
    """
    return {
        "resourceType": "Bundle",
        "id": f"patient-bundle-{awpid}",
        "type": "collection",
        "timestamp": _utc_now_iso(),
        "total": len(resources),
        "entry": [
            {"fullUrl": f"{r['resourceType']}/{r['id']}", "resource": r}
            for r in resources
        ],
    }
