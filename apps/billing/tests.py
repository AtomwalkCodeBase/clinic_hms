"""apps/billing/tests.py"""

import threading
from decimal import Decimal

from django.db import connections

from core.db_router import set_hospital_db
from core.tests.testing import HospitalDBTestCase, HospitalDBTransactionTestCase, make_branch, make_patient, make_staff, requires_hospital_db

from apps.billing.models import Invoice
from apps.billing.views import PaymentCreateView


@requires_hospital_db
class PaymentCreateTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        db = self.hospital_alias
        self.branch, place = make_branch(db)
        self.staff = make_staff(db, "front_desk", email="fd@example.test", phone="9000000002", place=place)
        self.patient = make_patient(db, "AW-TEST-2", uhid="UHID-2", branch=self.branch)
        self.invoice = Invoice.objects.using(db).create(
            patient=self.patient, branch=self.branch, invoice_number="INV-1",
            status="issued", subtotal=Decimal("100"), total_amount=Decimal("100"),
        )

    def pay(self, amount):
        return self.call_view(
            PaymentCreateView.as_view(), "post", "/api/v1/billing/payments/",
            user_id=self.staff.pk, role="front_desk",
            data={"invoice": self.invoice.pk, "amount": str(amount), "payment_mode": "cash"},
        )

    def test_a_zero_or_negative_payment_is_refused_not_a_crash(self):
        for amount in ("0", "-5"):
            self.assertEqual(self.pay(amount).status_code, 400)

    def test_paying_more_than_is_owed_is_refused(self):
        self.assertEqual(self.pay("101").status_code, 400)
        self.assertEqual(self.pay("100").status_code, 201)

    def test_payment_records_the_staff_member_and_updates_the_invoice(self):
        """Regression: recorded_by was assigned the MockUser (request.user), which Django rejects."""
        resp = self.pay("40.00")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.invoice.refresh_from_db(using=self.hospital_alias)
        (payment,) = self.invoice.payments
        self.assertEqual((payment["recorded_by_id"], payment["payment_id"], payment["amount"]), (self.staff.pk, 1, "40.00"))
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
        branch, place = make_branch(db)
        staff = make_staff(db, "front_desk", email="fd2@example.test", phone="9000000003", place=place)
        patient = make_patient(db, "AW-TEST-3", uhid="UHID-3", branch=branch, full_name="P")
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
                    user_id=staff.pk, role="front_desk",
                    data={"invoice": invoice.pk, "amount": "10.00", "payment_mode": "cash"},
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
        self.assertEqual(sorted(p["payment_id"] for p in invoice.payments), [1, 2, 3, 4])


@requires_hospital_db
class RecomputeInvoiceTotalsTests(HospitalDBTestCase):
    """Golden numbers for the shared totals helper (used by billing, opd, patients)."""

    def make_invoice(self, discount="0"):
        db = self.hospital_alias
        branch, _place = make_branch(db)
        patient = make_patient(db, "AW-T-4", uhid="UHID-4", branch=branch, full_name="P")
        return Invoice.objects.using(db).create(
            patient=patient, branch=branch, invoice_number="INV-9", discount_amount=Decimal(discount),
        )

    def add_item(self, invoice, unit_price, quantity, tax_rate):
        from apps.billing.services import line_from_request
        invoice.lines = [*invoice.lines, line_from_request({"description": "x", "quantity": quantity, "unit_price": unit_price, "tax_rate": tax_rate})]

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
        self.assertEqual(hospital_default_tax_rate(t.pk), Decimal("5.00"))

    def test_unknown_or_missing_hospital_is_zero(self):
        from apps.billing.services import hospital_default_tax_rate
        self.assertEqual(hospital_default_tax_rate(None), Decimal("0"))
        self.assertEqual(hospital_default_tax_rate(999999), Decimal("0"))


@requires_hospital_db
class TaxModeTests(HospitalDBTestCase):
    """A price either gets its tax added on top (500 at 18% is 590) or already contains it (stays 500)."""

    def setUp(self):
        super().setUp()
        db = self.hospital_alias
        self.branch, self.place = make_branch(db)
        self.patient = make_patient(db, "AW-TAX-1", uhid="UHID-TAX1", branch=self.branch)
        self.staff = make_staff(db, "hospital_admin", phone="9000000081", first_name="Ad", last_name="Min")
        self.invoice = Invoice.objects.using(db).create(patient=self.patient, branch=self.branch, invoice_number="INV-TAX")

    def service(self, **fields):
        from apps.billing.models import BillingItem
        return BillingItem.objects.using(self.hospital_alias).create(**{"name": "Consultation", "code": "C001", "unit_price": Decimal("500"),
                                                                          "tax_rate": Decimal("18"), **fields})

    def totals(self, service, **line):
        from apps.billing.services import line_from_item, recompute_invoice_totals
        self.invoice.lines = [*self.invoice.lines, line_from_item(service, **line)]
        recompute_invoice_totals(self.invoice, self.hospital_alias)
        self.invoice.refresh_from_db(using=self.hospital_alias)
        return self.invoice.subtotal, self.invoice.tax_amount, self.invoice.total_amount

    def test_tax_added_on_top(self):
        self.assertEqual(self.totals(self.service()), (Decimal("500.00"), Decimal("90.00"), Decimal("590.00")))

    def test_tax_already_in_the_price(self):
        self.assertEqual(self.totals(self.service(tax_inclusive=True)), (Decimal("423.73"), Decimal("76.27"), Decimal("500.00")))

    def test_a_price_that_cannot_be_edited_is_the_listed_one(self):
        fixed, open_ = self.service(is_price_editable=False), self.service(code="C002", name="Other")
        self.assertEqual(self.totals(fixed, unit_price=Decimal("1")), (Decimal("500.00"), Decimal("90.00"), Decimal("590.00")))
        self.invoice.lines = []
        self.assertEqual(self.totals(open_, unit_price=Decimal("100")), (Decimal("100.00"), Decimal("18.00"), Decimal("118.00")))

    def test_codes_are_unique_but_blank_codes_may_repeat(self):
        from django.db import IntegrityError, transaction
        self.service()
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            self.service(name="Duplicate")
        self.service(code="", name="No code 1")
        self.service(code="", name="No code 2")

    def upload(self, **data):
        from apps.billing.views import BillingServiceUploadView
        return self.call_view(BillingServiceUploadView.as_view(), "post", "/api/v1/billing/services/upload/", user_id=self.staff.pk, role="hospital_admin", data=data)

    def test_an_uploaded_price_list_adds_new_codes_and_updates_known_ones(self):
        from apps.billing.models import BillingItem
        self.service()
        resp = self.upload(services=[
            {"code": "C001", "name": "Consultation", "unit_price": "600", "tax_rate": "18", "is_price_editable": False},
            {"code": "R001", "name": "Registration", "unit_price": "300", "tax_rate": "0", "tax_inclusive": True},
        ])
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["data"], {"added": 1, "updated": 1})
        rows = {s.code: s for s in BillingItem.objects.using(self.hospital_alias).all()}
        self.assertEqual((rows["C001"].unit_price, rows["C001"].is_price_editable, rows["R001"].tax_inclusive), (Decimal("600.00"), False, True))

    def test_one_wrong_row_saves_nothing(self):
        from apps.billing.models import BillingItem
        resp = self.upload(services=[{"code": "A1", "name": "Fine", "unit_price": "10"}, {"code": "A2", "name": "No price"}])
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(BillingItem.objects.using(self.hospital_alias).exists())
        self.assertEqual(self.upload(services=[{"code": "A1", "name": "x", "unit_price": "1"}, {"code": "A1", "name": "y", "unit_price": "2"}]).status_code, 400)
        self.assertEqual(self.upload(services=[{"name": "No code", "unit_price": "1"}]).status_code, 400)

    def test_a_csv_file_is_read_the_same_way(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.billing.models import BillingItem
        from apps.billing.views import BillingServiceUploadView
        from core.api.authentication import MockUser
        csv_text = "code,name,category,unit_price,tax_rate,tax_inclusive,is_price_editable\nC001,Consultation,OPD,500,18,no,no\nR001,Registration,OPD,300,0,yes,yes\n"
        request = APIRequestFactory().post("/x/", {"file": SimpleUploadedFile("prices.csv", csv_text.encode())}, format="multipart")
        force_authenticate(request, user=MockUser({"user_id": self.staff.pk, "role": "hospital_admin", "hospital_id": 1}))
        request.hospital_db, request.hospital_id = self.hospital_alias, 1
        resp = BillingServiceUploadView.as_view()(request)
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = {s.code: s for s in BillingItem.objects.using(self.hospital_alias).all()}
        self.assertEqual((rows["C001"].tax_inclusive, rows["C001"].is_price_editable, rows["R001"].tax_inclusive), (False, False, True))

    def test_printing_an_invoice_keeps_its_pdf_as_a_hospital_document_and_a_reprint_replaces_it(self):
        from unittest import mock
        from apps.billing.views import InvoicePDFView
        from apps.hospital_patients.models import HospitalDocument, HospitalEvent
        keys = iter(["inv/one.pdf", "inv/two.pdf"])
        with mock.patch("core.storage.upload_data_uri", side_effect=lambda *a, **k: next(keys)), mock.patch("core.storage.delete") as delete:
            for _ in range(2):
                resp = self.call_view(InvoicePDFView.as_view(), "get", "/x/", user_id=self.staff.pk, role="hospital_admin", view_kwargs={"pk": self.invoice.pk})
                self.assertEqual(resp.status_code, 200)
        (doc,) = HospitalDocument.objects.using(self.hospital_alias).all()
        self.assertEqual(doc.file.name, "inv/two.pdf")
        self.assertEqual(doc.event, HospitalEvent.objects.using(self.hospital_alias).get(event_type="billing"))
        self.assertEqual(doc.event.patient_id, self.patient.pk)
        delete.assert_called_once_with("inv/one.pdf")
