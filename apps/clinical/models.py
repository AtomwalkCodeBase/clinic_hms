"""
apps/clinical/models.py
-----------------------
Retired (HMS-07c-1). This app used to hold FHIR-aligned clinical models
(Encounter, Vital, Diagnosis, FollowUp, ClinicalDocument) that predated the
current live OPD consultation flow. Confirmed dead-to-live-traffic before
removal: apps/clinical/urls.py routed a full CRUD API for these, but
nothing in frontend/src ever called API_ENDPOINTS.CLINICAL.* (grepped,
zero hits), and ClinicalDocument had no view/route at all. The live flow
has always used apps.opd.OPDEncounter (encounters), apps.opd.Vitals
(vitals), OPDEncounter.diagnoses (a JSON field, not a Diagnosis table),
and never had a working follow-up-date or document-upload feature backed
by this app either.

The app stays registered in INSTALLED_APPS (empty of models is valid) so
its migration history remains resolvable — see
apps/clinical/migrations/000X_delete_*.py for the table drops.
"""
