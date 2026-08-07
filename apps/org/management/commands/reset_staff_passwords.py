"""
Management command: reset_staff_passwords

Resets StaffUser passwords across one or more tenant databases. Built to
replace the old repo-root reset_all_credentials.py script, which was
removed for hardcoding a password directly in source (see
Atomwalk_HMS_Production_Readiness_Audit.md). This command takes the new
password as a runtime argument or environment variable instead — it is
never written into the codebase.

Usage:
  # Password via flag (still not committed anywhere — this is just your
  # shell history, same as any other CLI secret):
  python manage.py reset_staff_passwords --password 'hms@1234' --tenant aw_greenleaf_clinic

  # Or via env var, so it never even appears in shell history:
  ATOMWALK_RESET_PASSWORD='hms@1234' python manage.py reset_staff_passwords --tenant aw_greenleaf_clinic

  # All active tenants:
  python manage.py reset_staff_passwords --password 'hms@1234' --all-tenants

  # Restrict to one role or one email:
  python manage.py reset_staff_passwords --password 'hms@1234' --tenant aw_greenleaf_clinic --role doctor
  python manage.py reset_staff_passwords --password 'hms@1234' --tenant aw_greenleaf_clinic --email doctorglc01@gmail.com

Every affected account is also flagged must_change_password=True, so this
is meant as a one-time unblock, not a way to leave shared passwords in
place — each person should set their own password on next login.
"""

import os

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import StaffUser


class Command(BaseCommand):
    help = "Reset StaffUser passwords for a tenant (or all tenants) — password given at runtime, never hardcoded."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=None,
                             help="New password. If omitted, reads ATOMWALK_RESET_PASSWORD from the environment.")
        parser.add_argument("--tenant", dest="db_name", default=None,
                             help="Tenant db_name to target (e.g. aw_greenleaf_clinic).")
        parser.add_argument("--all-tenants", action="store_true",
                             help="Target every active tenant instead of one.")
        parser.add_argument("--role", default=None,
                             help="Only reset staff with this role (e.g. doctor, nurse).")
        parser.add_argument("--email", default=None,
                             help="Only reset this one staff member's password.")

    def handle(self, *args, **options):
        password = options.get("password") or os.environ.get("ATOMWALK_RESET_PASSWORD")
        if not password:
            raise CommandError(
                "No password given. Pass --password '<new password>' or set ATOMWALK_RESET_PASSWORD."
            )
        if len(password) < 6:
            raise CommandError("Password must be at least 6 characters.")

        db_name = options.get("db_name")
        all_tenants = options.get("all_tenants")
        role = options.get("role")
        email = options.get("email")

        if not db_name and not all_tenants:
            raise CommandError("Specify --tenant <db_name> or --all-tenants.")

        tenants = Tenant.objects.filter(db_name=db_name) if db_name else Tenant.objects.filter(is_active=True)
        if db_name and not tenants.exists():
            raise CommandError(f"No tenant found with db_name='{db_name}'")

        total = 0
        for tenant in tenants:
            if tenant.db_name not in settings.DATABASES:
                settings.DATABASES[tenant.db_name] = _make_db_config(tenant.db_name)

            qs = StaffUser.objects.using(tenant.db_name).filter(is_active=True)
            if role:
                qs = qs.filter(role=role)
            if email:
                qs = qs.filter(email=email)

            count = 0
            for staff in qs:
                staff.set_password(password)
                staff.must_change_password = True
                staff.save(using=tenant.db_name, update_fields=["password", "must_change_password"])
                count += 1

            self.stdout.write(self.style.SUCCESS(
                f"  {tenant.name} ({tenant.db_name}): reset {count} account(s)"
            ))
            total += count

        self.stdout.write(f"\nDone — {total} account(s) reset. "
                           "Each will be prompted to set their own password on next login.")
