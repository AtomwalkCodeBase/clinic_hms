"""
Management command: seed_lab_catalog

Populates a tenant's lab test catalog with a starter set of common tests
(CBC, LFT, KFT, lipid profile, blood sugar, thyroid, urine R/E, etc.) so
the doctor's ordering dropdown, the patient portal, and the nurse's
in-house/outside picker all have real data to work with instead of an
empty catalog.

Codes are assigned through NNTM (entity="lab_test", prefix "LT-"), the
same mechanism the Test Catalog page's "Add Test" form uses — never typed
by hand. Existing tests (matched by name, case-insensitive) are skipped,
so this is safe to re-run.

Usage:
  python manage.py seed_lab_catalog --tenant aw_greenleaf_clinic
  python manage.py seed_lab_catalog --all-tenants
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import Branch, NextNumber
from apps.lab.models import LabTest
from core.utils.nntm import get_next_number

# (name, sample_type, price, turnaround_hours, description)
STARTER_TESTS = [
    ("Complete Blood Count (CBC)",        "blood", 350.00,  6,  "FBC with differential"),
    ("Blood Sugar — Fasting",             "blood", 120.00,  4,  "Fasting plasma glucose"),
    ("Blood Sugar — Post Prandial (PP)",  "blood", 120.00,  4,  "2-hour post-meal glucose"),
    ("HbA1c",                             "blood", 550.00,  24, "3-month average blood glucose"),
    ("Liver Function Test (LFT)",         "blood", 650.00,  12, "SGOT, SGPT, bilirubin, ALP, proteins"),
    ("Kidney Function Test (KFT)",        "blood", 600.00,  12, "Urea, creatinine, electrolytes"),
    ("Lipid Profile",                     "blood", 500.00,  12, "Cholesterol, HDL, LDL, triglycerides"),
    ("Thyroid Profile (T3, T4, TSH)",     "blood", 700.00,  24, "Thyroid panel"),
    ("Urine Routine & Microscopy (R/E)",  "urine", 200.00,  6,  "Routine urinalysis"),
    ("Dengue NS1 Antigen",                "blood", 900.00,  8,  "Dengue early detection"),
    ("Widal Test",                        "blood", 300.00,  8,  "Typhoid screening"),
    ("Malaria Parasite (MP) Smear",       "blood", 250.00,  4,  "Peripheral smear for malaria"),
]


class Command(BaseCommand):
    help = "Seed a starter lab test catalog for a tenant (or all tenants). Safe to re-run — skips existing names."

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

        total = 0
        for tenant in tenants:
            if tenant.db_name not in settings.DATABASES:
                settings.DATABASES[tenant.db_name] = _make_db_config(tenant.db_name)
            db = tenant.db_name

            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            if not branch:
                self.stdout.write(self.style.WARNING(f"  {tenant.name} ({db}): no branch found — skipped."))
                continue

            NextNumber.objects.using(db).get_or_create(
                branch_id=branch.id, entity="lab_test",
                defaults={"prefix": "LT-", "pad_length": 4, "last_number": 0},
            )

            existing_names = set(
                LabTest.objects.using(db).values_list("name", flat=True)
            )
            existing_lower = {n.lower() for n in existing_names}

            count = 0
            for name, sample_type, price, turnaround, desc in STARTER_TESTS:
                if name.lower() in existing_lower:
                    continue
                code, _ = get_next_number(branch_id=branch.id, entity="lab_test", using=db)
                LabTest.objects.using(db).create(
                    name=name, code=code, sample_type=sample_type,
                    turnaround_hours=turnaround, price=price, description=desc,
                    is_active=True,
                )
                count += 1

            self.stdout.write(self.style.SUCCESS(
                f"  {tenant.name} ({db}): added {count} test(s), {len(STARTER_TESTS) - count} already present."
            ))
            total += count

        self.stdout.write(f"\nDone — {total} test(s) added across {tenants.count()} tenant(s).")
