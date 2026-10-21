from django.db import IntegrityError, transaction

from apps.hospital_setup.models import Branch
from apps.pharmacy.models import Drug, Stock, StockTransaction
from core.tests.testing import HospitalDBTestCase


class StockRulesTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.using(self.hospital_alias).create(name="Main")
        self.drug = Drug.objects.using(self.hospital_alias).create(name="Paracetamol", drug_code="D-1")

    def test_stock_cannot_go_below_zero(self):
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            Stock.objects.using(self.hospital_alias).create(drug=self.drug, branch=self.branch, quantity=-1)

    def test_a_ledger_row_must_add_up(self):
        stock = Stock.objects.using(self.hospital_alias).create(drug=self.drug, branch=self.branch, quantity=5)
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            StockTransaction.objects.using(self.hospital_alias).create(
                stock=stock, txn_type="purchase", quantity_change=3, quantity_before=5, quantity_after=9)

    def test_two_drugs_cannot_share_a_code_but_blank_codes_can(self):
        with self.assertRaises(IntegrityError), transaction.atomic(using=self.hospital_alias):
            Drug.objects.using(self.hospital_alias).create(name="Other", drug_code="D-1")
        Drug.objects.using(self.hospital_alias).create(name="A")
        Drug.objects.using(self.hospital_alias).create(name="B")
