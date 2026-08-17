"""
apps/clinical/signals.py
--------------------------
Retired (HMS-07c-1) along with apps.clinical.models -- this used to write
Encounter/Vital/Diagnosis rows through to registry.SharedDiagnosis/
SharedVital on encounter close, but the live doctor-consultation flow
already does its own equivalent write-through off apps.opd.OPDEncounter
(see apps/opd/views.py's _sync_to_hie(), called from EncounterSignView) --
so this was firing on models nothing ever actually saved to in production,
not a live sync path.
"""
