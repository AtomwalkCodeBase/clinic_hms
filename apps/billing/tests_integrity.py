from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.billing.models import Invoice, Payment
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient


class MoneyRulesTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        branch, _place = make_branch(self.hospital_alias)
        patient = make_patient(self.hospital_alias, "AWP-B1", uhid="U-1", branch=branch, full_name="B")
        self.invoice = Invoice.objects.using(self.hospital_alias).create(
            patient=patient, branch=branch, invoice_number="INV-1", total_amount=Decimal("100"))

    def pay(self, amount, ref=""):
        with transaction.atomic(using=self.hospital_alias):
            return Payment.objects.using(self.hospital_alias).create(invoice=self.invoice, amount=amount, payment_mode="cash", transaction_ref=ref)

    def test_a_payment_must_be_more_than_zero(self):
        with self.assertRaises(IntegrityError):
            self.pay(Decimal("0"))

    def test_an_invoice_cannot_hold_a_negative_amount(self):
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            Invoice.objects.using(self.hospital_alias).filter(pk=self.invoice.pk).update(paid_amount=Decimal("-1"))

    def test_the_same_reference_cannot_be_used_twice_on_one_invoice(self):
        self.pay(Decimal("10"), ref="UPI-1")
        with self.assertRaises(IntegrityError):
            self.pay(Decimal("10"), ref="UPI-1")

    def test_payments_without_a_reference_can_repeat(self):
        self.pay(Decimal("10"))
        self.pay(Decimal("10"))
        self.assertEqual(Payment.objects.using(self.hospital_alias).count(), 2)
