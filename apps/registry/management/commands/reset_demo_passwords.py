"""
Management command: reset_demo_passwords

Resets every login created by seed_full_demo — every staff account across
the 4 demo hospitals (Lakeview, Horizon Care, Cedar Health, Metro Wellness)
plus the flagship patient portal account (Meera Krishnan) — to one password
of your choosing.

Unlike reset_staff_passwords (apps/org), this does NOT set
must_change_password=True, so logins go straight to the dashboard instead
of being redirected to a change-password screen — meant for live-demo
convenience, not production account handoff. It also only ever touches the
4 seed_full_demo tenants by subdomain, so it can never reset passwords on
your real/other hospitals by accident.

Usage:
  python manage.py reset_demo_passwords --password 'hms@1234'

  # Or via env var, so it never appears in shell history:
  ATOMWALK_RESET_PASSWORD='hms@1234' python manage.py reset_demo_passwords
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.org.models import StaffUser
from apps.registry.models import PatientAccount
from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config

DEMO_SUBDOMAINS = ["lakeview-demo", "horizon-care-demo", "cedar-health-demo", "metro-wellness-demo"]
FLAGSHIP_PATIENT_EMAIL = "meera.krishnan@patientdemo.com"


class Command(BaseCommand):
    help = "Reset all seed_full_demo staff + the flagship patient portal login to one password (demo convenience — no forced password-change screen)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=None, help="New password. If omitted, reads ATOMWALK_RESET_PASSWORD from the environment.")

    def handle(self, *args, **options):
        password = options.get("password") or os.environ.get("ATOMWALK_RESET_PASSWORD")
        if not password:
            raise CommandError("No password given. Pass --password '<new password>' or set ATOMWALK_RESET_PASSWORD.")
        if len(password) < 6:
            raise CommandError("Password must be at least 6 characters.")

        tenants = list(Tenant.objects.filter(subdomain__in=DEMO_SUBDOMAINS))
        if not tenants:
            raise CommandError("No seed_full_demo hospitals found — run 'python manage.py seed_full_demo' first.")

        total = 0
        for tenant in tenants:
            if tenant.db_name not in settings.DATABASES:
                settings.DATABASES[tenant.db_name] = _make_db_config(tenant.db_name)
            count = 0
            for staff in StaffUser.objects.using(tenant.db_name).all():
                staff.set_password(password)
                staff.save(using=tenant.db_name, update_fields=["password"])
                count += 1
            self.stdout.write(self.style.SUCCESS(f"  {tenant.name} ({tenant.db_name}): reset {count} staff account(s)"))
            total += count

        patient_count = 0
        for acct in PatientAccount.objects.using("default").filter(email=FLAGSHIP_PATIENT_EMAIL):
            acct.set_password(password)
            acct.save(using="default", update_fields=["password"])
            patient_count += 1
        if patient_count:
            self.stdout.write(self.style.SUCCESS(f"  Patient portal ({FLAGSHIP_PATIENT_EMAIL}): reset"))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone — {total} staff account(s) + {patient_count} patient account(s) now use the password you gave. "
            "Emails are unchanged — see DEMO_CREDENTIALS.md for the full list."
        ))
