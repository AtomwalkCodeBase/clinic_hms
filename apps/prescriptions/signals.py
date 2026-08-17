"""
apps/prescriptions/signals.py
------------------------------
Retired (HMS-07c-1) along with apps.prescriptions.Prescription/PrescriptionItem
-- this used to write-through a finalized Prescription to
registry.SharedPrescription/SharedPrescriptionItem, but the live
doctor-consultation flow already does its own equivalent write-through off
apps.opd.Prescription (see apps/opd/views.py's _sync_to_hie(), called from
EncounterSignView) -- so this was a signal handler on a model nothing ever
actually saved to in production, not a live sync path.
"""
