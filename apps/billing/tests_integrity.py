from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.billing.models import Invoice
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient


class MoneyRulesTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        branch, _place = make_branch(self.hospital_alias)
        patient = make_patient(self.hospital_alias, "AWP-B1", uhid="U-1", branch=branch, full_name="B")
        self.invoice = Invoice.objects.using(self.hospital_alias).create(
            patient=patient, branch=branch, invoice_number="INV-1", total_amount=Decimal("100"))

    def test_an_invoice_cannot_hold_a_negative_amount(self):
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            Invoice.objects.using(self.hospital_alias).filter(pk=self.invoice.pk).update(paid_amount=Decimal("-1"))

    def test_lines_and_payments_start_empty_and_are_kept_as_given(self):
        self.assertEqual((self.invoice.lines, self.invoice.payments), ([], []))
        Invoice.objects.using(self.hospital_alias).filter(pk=self.invoice.pk).update(payments=[{"id": 1, "amount": "10.00"}])
        self.invoice.refresh_from_db(using=self.hospital_alias)
        self.assertEqual(self.invoice.payments, [{"id": 1, "amount": "10.00"}])

    def test_the_same_reference_cannot_be_used_twice_on_one_invoice(self):
        from apps.billing.views import PaymentCreateView
        paid = []
        for _ in range(2):
            resp = self.call_view(PaymentCreateView.as_view(), "post", "/x/", user_id=1, role="front_desk",
                                  data={"invoice": self.invoice.pk, "amount": "10", "payment_mode": "upi", "transaction_ref": "UPI-1"})
            paid.append(resp.status_code)
        self.assertEqual(paid, [201, 400])
