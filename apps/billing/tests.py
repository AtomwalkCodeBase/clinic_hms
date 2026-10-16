"""
apps/billing/tests.py
---------------------
Hospital-DB tests for payment posting. Needs the "hospital_test" alias:
  python manage.py test apps.billing --settings=atomwalk.settings.test   (skipped otherwise)
"""

import threading
from decimal import Decimal

from django.db import connections

from core.db_router import set_hospital_db
from core.testing import HospitalDBTestCase, HospitalDBTransactionTestCase, requires_hospital_db

from apps.billing.models import Invoice, Payment
from apps.billing.views import PaymentCreateView
from apps.hospital_setup.models import Branch
from apps.hospital_setup.models import StaffUser
from apps.opd.models import HospitalPatient


@requires_hospital_db
class PaymentCreateTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        db = self.hospital_alias
        self.branch = Branch.objects.using(db).create(name="Main")
        self.staff = StaffUser.objects.using(db).create(
            email="fd@example.test", role="front_desk", phone="9000000002", branch=self.branch,
        )
        self.patient = HospitalPatient.objects.using(db).create(
            awpid="AW-TEST-2", uhid="UHID-2", branch=self.branch, full_name="Test Patient",
        )
        self.invoice = Invoice.objects.using(db).create(
            patient=self.patient, branch=self.branch, invoice_number="INV-1",
            status="issued", subtotal=Decimal("100"), total_amount=Decimal("100"),
        )

    def pay(self, amount):
        return self.call_view(
            PaymentCreateView.as_view(), "post", "/api/v1/billing/payments/",
            user_id=self.staff.id, role="front_desk",
            data={"invoice": self.invoice.id, "amount": str(amount), "payment_mode": "cash"},
        )

    def test_payment_records_the_staff_member_and_updates_the_invoice(self):
        """Regression: recorded_by was assigned the MockUser (request.user), which Django rejects."""
        resp = self.pay("40.00")
        self.assertEqual(resp.status_code, 201, resp.data)
        payment = Payment.objects.using(self.hospital_alias).get()
        self.assertEqual(payment.recorded_by_id, self.staff.id)
        self.invoice.refresh_from_db(using=self.hospital_alias)
        self.assertEqual(self.invoice.paid_amount, Decimal("40.00"))
        self.assertEqual(self.invoice.status, "partially_paid")

    def test_full_payment_marks_the_invoice_paid(self):
        self.assertEqual(self.pay("100.00").status_code, 201)
        self.invoice.refresh_from_db(using=self.hospital_alias)
        self.assertEqual(self.invoice.status, "paid")


@requires_hospital_db
class ConcurrentPaymentTests(HospitalDBTransactionTestCase):
    def test_simultaneous_payments_are_all_counted(self):
        """paid_amount was read, incremented in Python and saved, so racing payments lost updates."""
        db = self.hospital_alias
        branch = Branch.objects.using(db).create(name="Main")
        staff = StaffUser.objects.using(db).create(email="fd2@example.test", role="front_desk", phone="9000000003", branch=branch)
        patient = HospitalPatient.objects.using(db).create(awpid="AW-TEST-3", uhid="UHID-3", branch=branch, full_name="P")
        invoice = Invoice.objects.using(db).create(
            patient=patient, branch=branch, invoice_number="INV-2", status="issued",
            subtotal=Decimal("100"), total_amount=Decimal("100"),
        )
        barrier = threading.Barrier(4)
        codes = []

        def worker():
            set_hospital_db(db)
            try:
                barrier.wait(timeout=10)
                resp = self.call_view(
                    PaymentCreateView.as_view(), "post", "/api/v1/billing/payments/",
                    user_id=staff.id, role="front_desk",
                    data={"invoice": invoice.id, "amount": "10.00", "payment_mode": "cash"},
                )
                codes.append(resp.status_code)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in threads]
        [t.join(timeout=30) for t in threads]

        self.assertEqual(codes, [201] * 4)
        invoice.refresh_from_db(using=db)
        self.assertEqual(invoice.paid_amount, Decimal("40.00"))
        self.assertEqual(Payment.objects.using(db).count(), 4)


@requires_hospital_db
class RecomputeInvoiceTotalsTests(HospitalDBTestCase):
    """Golden numbers for the shared totals helper (used by billing, opd, ipd, lab, pharmacy, patients)."""

    def make_invoice(self, discount="0"):
        from apps.billing.models import InvoiceItem  # noqa: F401  (imported for the helper below)
        db = self.hospital_alias
        branch = Branch.objects.using(db).create(name="Main")
        patient = HospitalPatient.objects.using(db).create(awpid="AW-T-4", uhid="UHID-4", branch=branch, full_name="P")
        return Invoice.objects.using(db).create(
            patient=patient, branch=branch, invoice_number="INV-9", discount_amount=Decimal(discount),
        )

    def add_item(self, invoice, unit_price, quantity, tax_rate):
        from apps.billing.models import InvoiceItem
        return InvoiceItem.objects.using(self.hospital_alias).create(
            invoice=invoice, description="x", quantity=quantity, unit_price=Decimal(unit_price),
            tax_rate=Decimal(tax_rate), total=Decimal(unit_price) * quantity,
        )

    def test_subtotal_tax_and_total_are_derived_from_the_lines(self):
        from apps.billing.services import recompute_invoice_totals
        inv = self.make_invoice()
        self.add_item(inv, "100.00", 2, "18")   # 200 + 36
        self.add_item(inv, "50.00", 1, "0")     # 50
        recompute_invoice_totals(inv, self.hospital_alias)
        inv.refresh_from_db(using=self.hospital_alias)
        self.assertEqual((inv.subtotal, inv.tax_amount, inv.total_amount),
                         (Decimal("250.00"), Decimal("36.00"), Decimal("286.00")))

    def test_discount_is_subtracted_after_tax(self):
        from apps.billing.services import recompute_invoice_totals
        inv = self.make_invoice(discount="26.00")
        self.add_item(inv, "100.00", 2, "18")
        recompute_invoice_totals(inv, self.hospital_alias)
        inv.refresh_from_db(using=self.hospital_alias)
        self.assertEqual(inv.total_amount, Decimal("210.00"))   # 200 + 36 - 26

    def test_an_invoice_with_no_lines_totals_zero(self):
        from apps.billing.services import recompute_invoice_totals
        inv = self.make_invoice()
        recompute_invoice_totals(inv, self.hospital_alias)
        inv.refresh_from_db(using=self.hospital_alias)
        self.assertEqual((inv.subtotal, inv.tax_amount, inv.total_amount), (Decimal("0"),) * 3)


@requires_hospital_db
class HospitalDefaultTaxRateTests(HospitalDBTestCase):
    def test_reads_the_hospitals_configured_rate(self):
        from apps.billing.services import hospital_default_tax_rate
        from apps.hospital_master.models import Hospital, HospitalParameters
        t = Hospital.objects.using("default").create(name="H", hospital_code="h-tax", db_name="h_tax")
        HospitalParameters.objects.using("default").create(hospital=t, default_tax_rate=Decimal("5.00"))
        self.assertEqual(hospital_default_tax_rate(t.id), Decimal("5.00"))

    def test_unknown_or_missing_hospital_is_zero(self):
        from apps.billing.services import hospital_default_tax_rate
        self.assertEqual(hospital_default_tax_rate(None), Decimal("0"))
        self.assertEqual(hospital_default_tax_rate(999999), Decimal("0"))
