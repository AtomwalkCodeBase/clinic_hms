"""
apps/pharmacy/tests.py
----------------------
Tenant-DB tests for stock receipt and dispensing. They need the extra "tenant_test"
database alias:  python manage.py test apps.pharmacy --settings=atomwalk.settings.test
(skipped under the normal settings).
"""

from decimal import Decimal

import threading
from unittest import mock

from django.db import connections
from django.test.utils import CaptureQueriesContext

from core.testing import TenantDBTestCase, TenantDBTransactionTestCase, requires_tenant_db

from apps.billing.models import Invoice
from apps.opd.models import Appointment, OPDEncounter, Prescription, PrescriptionItem
from apps.org.models import Branch, NextNumber, StaffUser
from apps.patients.models import Patient
from apps.pharmacy.models import Dispense, Stock, StockTransaction
from apps.pharmacy.views import DispenseView, StockListView
from apps.prescriptions.models import Drug

import datetime
import uuid

from core.db_router import set_tenant_db


class PharmacyFixtureMixin:
    """Minimal rows needed to dispense one prescription item."""

    def make_fixture(self, stock_qty=10):
        db = self.tenant_alias
        self.branch = Branch.objects.using(db).create(name="Main")
        self.pharmacist = StaffUser.objects.using(db).create(
            email="ph@example.test", role="pharmacist", phone="9000000001", branch=self.branch,
        )
        self.patient = Patient.objects.using(db).create(
            awpid="AW-TEST-1", uhid="UHID-1", branch=self.branch, full_name="Test Patient",
        )
        self.drug = Drug.objects.using(db).create(name="Paracetamol", default_mrp=Decimal("2.00"))
        self.stock = Stock.objects.using(db).create(
            drug=self.drug, branch=self.branch, batch_number="B1",
            quantity=stock_qty, mrp=Decimal("2.00"),
        )
        doctor_id = uuid.uuid4()
        appt = Appointment.objects.using(db).create(
            patient_id=self.patient.uuid, patient_awpid=self.patient.awpid,
            doctor_user_id=doctor_id, doctor_name="Dr Test",
            scheduled_date=datetime.date.today(),
        )
        enc = OPDEncounter.objects.using(db).create(
            appointment=appt, patient_id=self.patient.uuid, doctor_user_id=doctor_id,
        )
        self.rx = Prescription.objects.using(db).create(
            encounter=enc, patient_id=self.patient.uuid, doctor_user_id=doctor_id,
            rx_number="RX-1",
        )
        self.item = PrescriptionItem.objects.using(db).create(
            prescription=self.rx, drug=self.drug, drug_name="Paracetamol",
            dosage="500mg", frequency="od",
        )
        NextNumber.objects.using(db).create(branch_id=self.branch.id, entity="invoice", prefix="INV-")

    def dispense(self, qty):
        return self.call_view(
            DispenseView.as_view(), "post", "/api/v1/pharmacy/dispense/",
            user_id=self.pharmacist.id, role="pharmacist",
            data={"prescription_item": str(self.item.id), "stock": self.stock.id, "quantity": qty},
        )


@requires_tenant_db
class StockReceiptTests(PharmacyFixtureMixin, TenantDBTestCase):
    def test_receiving_stock_records_the_staff_member(self):
        """Regression: recorded_by was assigned the MockUser (request.user), which Django rejects."""
        self.make_fixture(stock_qty=0)
        resp = self.call_view(
            StockListView.as_view(), "post", "/api/v1/pharmacy/stock/",
            user_id=self.pharmacist.id, role="pharmacist",
            data={"drug": self.drug.id, "branch": self.branch.id, "batch_number": "B2", "quantity": 5},
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        txn = StockTransaction.objects.using(self.tenant_alias).get()
        self.assertEqual(txn.recorded_by_id, self.pharmacist.id)
        self.assertEqual(txn.txn_type, "purchase")
        self.assertEqual(Stock.objects.using(self.tenant_alias).get(batch_number="B2").quantity, 5)


    def test_receiving_an_existing_batch_tops_it_up(self):
        """The view supports top-ups, but the serializer's unique_together check used to reject them."""
        self.make_fixture(stock_qty=10)
        resp = self.call_view(
            StockListView.as_view(), "post", "/api/v1/pharmacy/stock/",
            user_id=self.pharmacist.id, role="pharmacist",
            data={"drug": self.drug.id, "branch": self.branch.id, "batch_number": "B1", "quantity": 5},
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Stock.objects.using(self.tenant_alias).get().quantity, 15)
        txn = StockTransaction.objects.using(self.tenant_alias).get()
        self.assertEqual((txn.quantity_before, txn.quantity_after), (10, 15))


@requires_tenant_db
class DispenseTests(PharmacyFixtureMixin, TenantDBTestCase):
    def test_dispense_deducts_stock_and_records_the_staff_member(self):
        """Regression: Dispense.dispensed_by / StockTransaction.recorded_by got the MockUser."""
        self.make_fixture(stock_qty=10)
        resp = self.dispense(3)
        self.assertEqual(resp.status_code, 201, resp.data)
        db = self.tenant_alias
        self.assertEqual(Stock.objects.using(db).get().quantity, 7)
        txn = StockTransaction.objects.using(db).get()
        self.assertEqual((txn.txn_type, txn.quantity_change, txn.quantity_before, txn.quantity_after),
                         ("dispense", -3, 10, 7))
        self.assertEqual(txn.recorded_by_id, self.pharmacist.id)
        self.assertEqual(Dispense.objects.using(db).get().dispensed_by_id, self.pharmacist.id)

    def test_dispense_more_than_available_changes_nothing(self):
        self.make_fixture(stock_qty=2)
        resp = self.dispense(3)
        self.assertEqual(resp.status_code, 400)
        db = self.tenant_alias
        self.assertEqual(Stock.objects.using(db).get().quantity, 2)
        self.assertFalse(StockTransaction.objects.using(db).exists())
        self.assertFalse(Dispense.objects.using(db).exists())

    def test_dispense_bills_the_prescription(self):
        self.make_fixture(stock_qty=10)
        self.assertEqual(self.dispense(2).status_code, 201)
        inv = Invoice.objects.using(self.tenant_alias).get()
        self.assertEqual(inv.subtotal, Decimal("4.00"))
        self.rx.refresh_from_db(using=self.tenant_alias)
        self.assertEqual(self.rx.invoice_id, inv.id)

    def test_a_failure_part_way_rolls_the_stock_deduction_back(self):
        """Stock used to be saved before the ledger row, so a failure left it reduced with no record."""
        self.make_fixture(stock_qty=10)
        boom = mock.MagicMock()
        boom.objects.using.return_value.create.side_effect = RuntimeError("ledger write failed")
        with mock.patch("apps.pharmacy.views.StockTransaction", boom):
            with self.assertRaises(RuntimeError):
                self.dispense(3)
        db = self.tenant_alias
        self.assertEqual(Stock.objects.using(db).get().quantity, 10)
        self.assertFalse(Dispense.objects.using(db).exists())

    def test_the_batch_row_is_locked_while_dispensing(self):
        self.make_fixture(stock_qty=10)
        with CaptureQueriesContext(connections[self.tenant_alias]) as ctx:
            self.assertEqual(self.dispense(1).status_code, 201)
        locking = [q["sql"] for q in ctx.captured_queries if 'FROM "stock"' in q["sql"] and "FOR UPDATE" in q["sql"]]
        self.assertTrue(locking, "expected a SELECT ... FOR UPDATE on the stock row")

    def test_receiving_stock_also_locks_the_batch_row(self):
        self.make_fixture(stock_qty=0)
        with CaptureQueriesContext(connections[self.tenant_alias]) as ctx:
            resp = self.call_view(
                StockListView.as_view(), "post", "/api/v1/pharmacy/stock/",
                user_id=self.pharmacist.id, role="pharmacist",
                data={"drug": self.drug.id, "branch": self.branch.id, "batch_number": "B9", "quantity": 4},
            )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue([q for q in ctx.captured_queries if 'FROM "stock"' in q["sql"] and "FOR UPDATE" in q["sql"]])


@requires_tenant_db
class ConcurrentDispenseTests(PharmacyFixtureMixin, TenantDBTransactionTestCase):
    def test_two_simultaneous_dispenses_cannot_oversell_a_batch(self):
        """10 in stock, two pharmacists each dispense 6 at the same moment: exactly one may succeed."""
        self.make_fixture(stock_qty=10)
        barrier = threading.Barrier(2)
        statuses = []

        def worker():
            set_tenant_db(self.tenant_alias)
            try:
                barrier.wait(timeout=10)
                statuses.append(self.dispense(6).status_code)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        db = self.tenant_alias
        self.assertEqual(sorted(statuses), [201, 400])
        self.assertEqual(Stock.objects.using(db).get().quantity, 4)
        self.assertEqual(Dispense.objects.using(db).count(), 1)
        self.assertEqual(StockTransaction.objects.using(db).count(), 1)
