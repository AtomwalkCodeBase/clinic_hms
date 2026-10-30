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


class InvoiceLinesAreRowsTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        from apps.billing.models import BillingItem
        self.branch, _place = make_branch(self.hospital_alias)
        self.patient = make_patient(self.hospital_alias, "AWP-L1", uhid="U-L1", branch=self.branch, full_name="L")
        self.item = BillingItem.objects.using(self.hospital_alias).create(name="Consultation", code="CON", unit_price=Decimal("500"))

    def invoice(self, lines):
        return Invoice.objects.using(self.hospital_alias).create(patient=self.patient, branch=self.branch, invoice_number="INV-L", lines=lines)

    def test_lines_are_saved_as_billing_item_rows_and_read_back_as_the_same_dicts(self):
        from apps.billing.models import BillingItem
        line = {"item_id": self.item.pk, "description": "Consultation", "quantity": 2, "unit_price": "500.00", "tax_rate": "5.00", "tax_inclusive": False, "total": "1000.00"}
        inv = self.invoice([line])
        self.assertEqual(BillingItem.objects.using(self.hospital_alias).filter(bill=inv).count(), 1)
        fresh = Invoice.objects.using(self.hospital_alias).get(pk=inv.pk)
        self.assertEqual(fresh.lines, [line])

    def test_setting_lines_again_replaces_the_rows(self):
        from apps.billing.models import BillingItem
        from apps.billing.services import recompute_invoice_totals
        inv = self.invoice([{"description": "A", "quantity": 1, "unit_price": "10.00"}])
        inv.lines = [*inv.lines, {"description": "B", "quantity": 3, "unit_price": "20.00"}]
        recompute_invoice_totals(inv, self.hospital_alias)
        self.assertEqual([r.name for r in BillingItem.objects.using(self.hospital_alias).filter(bill=inv).order_by("pk")], ["A", "B"])
        self.assertEqual(Invoice.objects.using(self.hospital_alias).get(pk=inv.pk).total_amount, Decimal("70.00"))

    def test_invoice_lines_are_not_part_of_the_price_list(self):
        from apps.billing.models import BillingItem
        self.invoice([{"description": "A", "quantity": 1, "unit_price": "10.00"}])
        self.assertEqual(list(BillingItem.objects.using(self.hospital_alias).filter(bill__isnull=True)), [self.item])


class InvoicePdfTests(HospitalDBTestCase):
    def test_the_invoice_pdf_renders_lines_given_as_dicts(self):
        from apps.billing.pdf import generate_invoice_pdf
        branch, _place = make_branch(self.hospital_alias)
        patient = make_patient(self.hospital_alias, "AWP-PDF", uhid="U-PDF", branch=branch, full_name="Pdf Patient")
        inv = Invoice.objects.using(self.hospital_alias).create(
            patient=patient, branch=branch, invoice_number="INV-PDF", lines=[{"description": "Consultation", "quantity": 2, "unit_price": "500.00", "tax_rate": "5.00", "tax_inclusive": False}])
        pdf = generate_invoice_pdf(invoice=inv, items=inv.lines, payments=[], patient=patient, branch=branch, hospital_name="H")
        self.assertTrue(bytes(pdf).startswith(b"%PDF"))
