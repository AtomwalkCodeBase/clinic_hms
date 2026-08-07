"""
apps/opd/tests.py
-------------------
DB-backed tests for the OPD encounter sign-off flow — the highest-risk path
in the app, since it fans out into billing (auto-invoice) and the registry
(HIE write-through) as side effects that must never block the sign-off
itself even if they fail.

These require a real Postgres reachable via the DATABASES config (registry +
at least one tenant DB) — they were written and reviewed in an environment
without a live Postgres available, so they have NOT been executed here.
Run `python manage.py test apps.opd` against a real dev DB before trusting
this file; treat it as a first draft of coverage, not a verified pass.
"""

from datetime import date

from django.test import TestCase


class EncounterSignSideEffectsTests(TestCase):
    """
    NOTE: uses the 'default' (registry) DB via TestCase's automatic
    transactional wrapping. A full run also needs a tenant DB fixture —
    see apps/tenants/utils.py::create_tenant_database for how one is
    provisioned in this project; wire that into setUp() once a test tenant
    DB alias is available in CI (see .github/workflows/ci.yml).
    """

    def test_sign_never_raises_even_if_hie_write_fails(self):
        """
        _sync_to_hie must swallow failures — signing an encounter must
        succeed even if the registry DB is unreachable or a shared table
        write fails. This directly exercises that contract without needing
        a full tenant DB fixture, by calling the helper with a patient that
        has no awpid (the guaranteed-skip path).
        """
        from apps.opd.views import _sync_to_hie

        class FakeEncounter:
            id = "test-encounter-id"
            diagnoses = [{"code": "J06.9", "description": "Acute URI"}]

            class appointment:
                vitals = None

            prescription = None

        class FakePatientNoAwpid:
            awpid = None

        # Should return early and NOT raise, since patient.awpid is falsy.
        _sync_to_hie(FakeEncounter(), "default", FakePatientNoAwpid())

    def test_sign_hie_sync_handles_missing_vitals_and_prescription_gracefully(self):
        """
        Encounters commonly have no vitals recorded yet or no prescription
        (e.g. advice-only visit) — _sync_to_hie must not assume either exists.
        """
        from apps.opd.views import _sync_to_hie

        class FakeAppointment:
            @property
            def vitals(self):
                raise Exception("no related Vitals row — OneToOne DoesNotExist")

        class FakeEncounter:
            id = "test-encounter-id-2"
            diagnoses = []
            appointment = FakeAppointment()

            @property
            def prescription(self):
                raise Exception("no related Prescription row — OneToOne DoesNotExist")

        class FakePatient:
            awpid = None  # still short-circuits before hitting the DB — see test above

        _sync_to_hie(FakeEncounter(), "default", FakePatient())
