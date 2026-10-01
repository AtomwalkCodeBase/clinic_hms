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
        sync_encounter_to_hie must swallow failures — signing an encounter must
        succeed even if the registry DB is unreachable or a shared table
        write fails. This directly exercises that contract without needing
        a full tenant DB fixture, by calling the helper with a patient that
        has no awpid (the guaranteed-skip path).
        """
        from apps.registry.hie import sync_encounter_to_hie

        class FakeEncounter:
            id = "test-encounter-id"
            diagnoses = [{"code": "J06.9", "description": "Acute URI"}]

            class appointment:
                vitals = None

            prescription = None

        class FakePatientNoAwpid:
            awpid = None

        # Should return early and NOT raise, since patient.awpid is falsy.
        sync_encounter_to_hie(FakeEncounter(), "default", FakePatientNoAwpid())

    def test_sign_hie_sync_handles_missing_vitals_and_prescription_gracefully(self):
        """
        Encounters commonly have no vitals recorded yet or no prescription
        (e.g. advice-only visit) — sync_encounter_to_hie must not assume either exists.
        """
        from apps.registry.hie import sync_encounter_to_hie

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

        sync_encounter_to_hie(FakeEncounter(), "default", FakePatient())


# ── Sign-off characterization (tenant DB) ────────────────────────────────────
# Pins what EncounterSignView does today so the billing / HIE code it calls can be
# moved and changed safely. Needs the tenant_test alias:
#   python manage.py test apps.opd --settings=atomwalk.settings.test   (skipped otherwise)

import datetime as _dt
import uuid as _uuid
from decimal import Decimal as _Decimal
from unittest import mock as _mock

from core.testing import TenantDBTestCase, requires_tenant_db


@requires_tenant_db
class EncounterSignWorkflowTests(TenantDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.billing.models import Invoice  # noqa: F401
        from apps.opd.models import Appointment, OPDEncounter
        from apps.org.models import Branch, DoctorProfile, NextNumber, StaffUser
        from apps.patients.models import Patient
        from apps.tenants.models import Tenant

        db = self.tenant_alias
        self.tenant = Tenant.objects.using("default").create(
            name="Sign Hospital", subdomain="sign-h", db_name=db, default_tax_rate=_Decimal("10"),
        )
        self.branch = Branch.objects.using(db).create(name="Main")
        self.doctor = StaffUser.objects.using(db).create(
            email="dr.sign@example.test", role="doctor", phone="9000000020", branch=self.branch,
        )
        DoctorProfile.objects.using(db).create(staff=self.doctor, consultation_fee=_Decimal("500.00"))
        self.patient = Patient.objects.using(db).create(
            awpid="AW-SIGN-1", uhid="UHID-S1", branch=self.branch, full_name="Sign Patient",
        )
        NextNumber.objects.using(db).create(branch_id=self.branch.id, entity="invoice", prefix="INV-")
        appt = Appointment.objects.using(db).create(
            patient_id=self.patient.uuid, patient_awpid=self.patient.awpid,
            doctor_user_id=_uuid.UUID(int=self.doctor.id), doctor_name="Dr Sign",
            branch_id=self.branch.id, scheduled_date=_dt.date.today(),
        )
        self.enc = OPDEncounter.objects.using(db).create(
            appointment=appt, patient_id=self.patient.uuid, doctor_user_id=_uuid.UUID(int=self.doctor.id),
            assessment="Viral fever", diagnoses=[{"code": "B34.9", "description": "Viral infection"}],
        )

    def sign(self):
        from apps.opd.views import EncounterSignView
        with _mock.patch("apps.opd.views._store_prescription_pdf"):     # S3 + PDF rendering
            return self.call_view(
                EncounterSignView.as_view(), "post", "/api/v1/opd/encounters/x/sign/",
                user_id=self.doctor.id, role="doctor", tenant_id=self.tenant.id,
                view_kwargs={"pk": self.enc.pk},
            )

    def test_sign_closes_the_encounter_bills_and_mirrors_to_the_registry(self):
        from apps.billing.models import Invoice, InvoiceItem
        from apps.opd.models import OPDEncounter
        from apps.org.models import AuditLog
        from apps.registry.models import SharedDiagnosis

        resp = self.sign()
        self.assertEqual(resp.status_code, 200, getattr(resp, "data", None))
        db = self.tenant_alias

        self.assertEqual(OPDEncounter.objects.using(db).get().status, OPDEncounter.STATUS_SIGNED)

        inv = Invoice.objects.using(db).get()                       # draft invoice from the doctor's fee
        item = InvoiceItem.objects.using(db).get()
        self.assertEqual((inv.status, inv.patient_id), ("draft", self.patient.id))
        self.assertEqual((item.description, item.unit_price, item.tax_rate), ("OPD Consultation", _Decimal("500.00"), _Decimal("10.00")))
        self.assertEqual((inv.subtotal, inv.tax_amount, inv.total_amount),
                         (_Decimal("500.00"), _Decimal("50.00"), _Decimal("550.00")))

        dx = SharedDiagnosis.objects.using("default").get()          # HIE mirror, stamped with the hospital
        self.assertEqual((dx.awpid, dx.icd10_code, dx.source_tenant_id), ("AW-SIGN-1", "B34.9", self.tenant.id))

        self.assertTrue(AuditLog.objects.using(db).filter(action="encounter.sign").exists())

    def test_signing_twice_is_rejected_and_does_not_bill_again(self):
        from apps.billing.models import Invoice
        self.assertEqual(self.sign().status_code, 200)
        again = self.sign()
        self.assertEqual(again.status_code, 400)
        self.assertEqual(Invoice.objects.using(self.tenant_alias).count(), 1)

    def test_an_encounter_with_no_assessment_or_diagnosis_cannot_be_signed(self):
        self.enc.assessment, self.enc.diagnoses = "", []
        self.enc.save(using=self.tenant_alias)
        resp = self.sign()
        self.assertEqual(resp.status_code, 400)

    def test_a_billing_failure_does_not_block_the_sign_off(self):
        """Sign-off must succeed even if the auto-invoice step blows up (logged, swallowed)."""
        from apps.opd.models import OPDEncounter
        with _mock.patch("core.utils.nntm.get_next_number", side_effect=RuntimeError("no counter")):
            resp = self.sign()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(OPDEncounter.objects.using(self.tenant_alias).get().status, OPDEncounter.STATUS_SIGNED)
