"""
Management command: backfill_drug_prices

One-time backfill for Drug.default_mrp (added in prescriptions/0005) on
existing tenants. Run this AFTER migrate_tenants has applied that migration.

For every drug that doesn't have a default_mrp yet, looks at that drug's
most recent stock batch and copies its price across (MRP preferred, unit
cost as a fallback) — so the catalog-level reference price used for
billing isn't starting from a blank slate for hospitals that already have
stock history. Drugs with no stock ever received are left unset and
listed at the end, since there's genuinely no price on file to pull from.

Usage:
  python manage.py backfill_drug_prices
  python manage.py backfill_drug_prices --db aw_sunrise_clinic
"""

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.prescriptions.models import Drug
from apps.pharmacy.models import Stock


class Command(BaseCommand):
    help = "Backfill Drug.default_mrp from existing stock batch prices, per tenant"

    def add_arguments(self, parser):
        parser.add_argument(
            "--db",
            dest="db_name",
            default=None,
            help="Specific tenant db_name to backfill (default: all active tenants)",
        )

    def handle(self, *args, **options):
        db_name = options.get("db_name")

        if db_name:
            tenants = Tenant.objects.filter(db_name=db_name)
            if not tenants.exists():
                self.stderr.write(self.style.ERROR(f"No tenant found with db_name='{db_name}'"))
                return
        else:
            tenants = Tenant.objects.filter(is_active=True)

        self.stdout.write(f"Found {tenants.count()} tenant(s) to check.\n")

        for tenant in tenants:
            db = tenant.db_name
            self.stdout.write(f"\n=== {tenant.name} ({db}) ===")
            if db not in settings.DATABASES:
                settings.DATABASES[db] = _make_db_config(db)

            try:
                filled, unresolved = 0, []
                for d in Drug.objects.using(db).filter(default_mrp__isnull=True):
                    stock = Stock.objects.using(db).filter(drug=d, mrp__isnull=False).order_by("-created_at").first()
                    price = stock.mrp if stock else None
                    if price is None:
                        stock = Stock.objects.using(db).filter(drug=d, unit_cost__isnull=False).order_by("-created_at").first()
                        price = stock.unit_cost if stock else None
                    if price is not None:
                        d.default_mrp = price
                        d.save(using=db, update_fields=["default_mrp"])
                        filled += 1
                    else:
                        unresolved.append(d.name)

                self.stdout.write(self.style.SUCCESS(f"  Filled {filled} drug price(s) from existing stock batches."))
                if unresolved:
                    self.stdout.write(self.style.WARNING(
                        f"  {len(unresolved)} drug(s) have no stock/price history — set these manually on Drug Catalog Setup:"
                    ))
                    for name in unresolved:
                        self.stdout.write(f"    - {name}")
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Failed: {exc}"))

        self.stdout.write("\nAll done.")
