"""
Management command: seed_pharmacy_stock

Makes the pharmacist module demo-ready end to end: seed_drug_catalog gives
every tenant a starter Drug catalog with realistic prices, but a catalog
entry alone has nothing to actually dispense against — Stock (a real
batch on hand) is a separate table, and the Stock page/dispense flow have
nothing to show until at least one batch exists per drug. This command
receives one starter batch per active drug per branch, at a quantity sized
to the drug's form (tablets counted individually, syrups in ml, etc.),
priced from the drug's own default_mrp so dispense billing is consistent
with the catalog price shown on Drug Catalog Setup.

Safe to re-run — skips (drug, branch) pairs that already have any Stock
row, so it never creates duplicate batches or touches stock a pharmacist
has since adjusted by hand.

Usage:
  python manage.py seed_pharmacy_stock --tenant aw_greenleaf_clinic
  python manage.py seed_pharmacy_stock --all-tenants
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import Branch
from apps.prescriptions.models import Drug
from apps.pharmacy.models import Stock, StockTransaction

# Starting quantity + reorder level per drug form — tablets/capsules counted
# individually, syrups/liquids in ml, everything else (drops, creams,
# inhalers, patches, vials) as whole packs/units, matching how
# seed_drug_catalog priced each form's default_mrp per dispensing unit.
FORM_STOCK_LEVELS = {
    "Tablet":            (300, 50),
    "Capsule":           (300, 50),
    "Syrup":             (1500, 250),
    "Injection":         (100, 20),
    "Drops":             (40, 10),
    "Cream / Ointment":  (40, 10),
    "Inhaler":           (25, 8),
    "Patch":             (30, 8),
    "Other":             (100, 20),
}
DEFAULT_STOCK_LEVEL = (100, 20)


class Command(BaseCommand):
    help = ("Receive a starter stock batch for every drug in the catalog that doesn't "
            "already have one, for a tenant (or all tenants) — makes Stock/dispense "
            "demo-ready. Safe to re-run — skips drugs that already have stock.")

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="db_name", default=None,
                             help="Tenant db_name to target (e.g. aw_greenleaf_clinic).")
        parser.add_argument("--all-tenants", action="store_true",
                             help="Target every active tenant instead of one.")

    def handle(self, *args, **options):
        db_name = options.get("db_name")
        all_tenants = options.get("all_tenants")

        if not db_name and not all_tenants:
            raise CommandError("Specify --tenant <db_name> or --all-tenants.")

        tenants = Tenant.objects.filter(db_name=db_name) if db_name else Tenant.objects.filter(is_active=True)
        if db_name and not tenants.exists():
            raise CommandError(f"No tenant found with db_name='{db_name}'")

        expiry = date.today() + timedelta(days=730)
        total_batches = 0

        for tenant in tenants:
            if tenant.db_name not in settings.DATABASES:
                settings.DATABASES[tenant.db_name] = _make_db_config(tenant.db_name)
            db = tenant.db_name

            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            if not branch:
                self.stdout.write(self.style.WARNING(f"  {tenant.name} ({db}): no branch found — skipped."))
                continue

            drugs = list(Drug.objects.using(db).filter(is_active=True))
            stocked_drug_ids = set(
                Stock.objects.using(db).filter(branch=branch, drug_id__in=[d.id for d in drugs])
                .values_list("drug_id", flat=True)
            )

            batch_count = 0
            for drug in drugs:
                if drug.id in stocked_drug_ids:
                    continue
                quantity, reorder_level = FORM_STOCK_LEVELS.get(drug.form, DEFAULT_STOCK_LEVEL)
                mrp = drug.default_mrp
                unit_cost = (mrp * Decimal("0.7")).quantize(Decimal("0.01")) if mrp is not None else None

                stock = Stock.objects.using(db).create(
                    drug=drug, branch=branch,
                    batch_number=f"DEMO-{drug.drug_code or drug.id}",
                    expiry_date=expiry,
                    quantity=quantity, reorder_level=reorder_level,
                    unit_cost=unit_cost, mrp=mrp,
                )
                StockTransaction.objects.using(db).create(
                    stock=stock, txn_type="purchase",
                    quantity_change=quantity, quantity_before=0, quantity_after=quantity,
                    reference_type="Demo seed", notes="Starter batch — seed_pharmacy_stock",
                )
                batch_count += 1

            self.stdout.write(self.style.SUCCESS(
                f"  {tenant.name} ({db}): +{batch_count} batch(es) received "
                f"({len(drugs) - batch_count} drug(s) already had stock)."
            ))
            total_batches += batch_count

        self.stdout.write(f"\nDone — {total_batches} batch(es) received across {tenants.count()} tenant(s).")
