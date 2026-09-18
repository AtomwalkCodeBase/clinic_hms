"""
Management command: provision_pending_hospital_dbs

Finishes provisioning for tenants that already have a Tenant + Subscription
row in the registry DB (created by apps/tenants/migrations/
0015_seed_east_bangalore_clinics.py, which deliberately only inserts
registry rows — see that migration's docstring) but no real per-tenant
Postgres database yet, so they show up in "hospitals near me" with an
empty "View doctors" list.

For each target tenant this does exactly what provision_tenant does for a
brand-new hospital, minus the Tenant/Subscription creation (which already
exists here):
  1. Create the Postgres database
  2. Run all tenant-app migrations against it
  3. Point it at the default vaccination + milestone schedule templates
  4. Create a hospital_admin StaffUser + registry StaffMobileIndex entry

Safe to re-run: skips any tenant whose database already exists (checked
via pg_database, not just db_name being set on the Tenant row) and skips
creating a second hospital_admin if one already exists in that tenant DB.

Usage:
  python manage.py provision_pending_hospital_dbs --settings=atomwalk.settings.development
  python manage.py provision_pending_hospital_dbs --subdomain care-cure-clinic --settings=atomwalk.settings.development
"""

import secrets
import string

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.tenants.models import Tenant
from apps.tenants.utils import create_tenant_database, run_tenant_migrations, drop_tenant_database, _make_db_config

DEFAULT_SUBDOMAINS = [
    "care-cure-clinic",
    "krishna-healthcare",
    "nationwide-family-doctors",
    "sri-lakshmi-family-dental-clinic",
    "pushpa-nursing-home",
]

STARTING_ADMIN_MOBILE = 9820000001


def _gen_password(length=14):
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


def _database_exists(db_name):
    sys_db_config = _make_db_config("postgres")
    conn_alias = f"_sys_check_{db_name}"
    settings.DATABASES[conn_alias] = sys_db_config
    try:
        conn = connections[conn_alias]
        conn.ensure_connection()
        with conn.connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [db_name])
            return cursor.fetchone() is not None
    finally:
        connections[conn_alias].close()
        del settings.DATABASES[conn_alias]


class Command(BaseCommand):
    help = "Create the missing Postgres database + run migrations + a hospital_admin login for tenants that only have a registry row so far."

    def add_arguments(self, parser):
        parser.add_argument("--subdomain", action="append", default=None,
                             help="Limit to this subdomain (repeatable). Defaults to the 5 East-Bengaluru "
                                  "clinics that don't have a real database yet.")

    def handle(self, *args, **options):
        subdomains = options["subdomain"] or DEFAULT_SUBDOMAINS
        self._credentials = []

        for subdomain in subdomains:
            self._provision_one(subdomain)

        if self._credentials:
            self.stdout.write(self.style.SUCCESS(f"\n{len(self._credentials)} hospital(s) provisioned.\n"))
            self.stdout.write(f"  {'Hospital':<38} {'Mobile':<12} {'Password'}")
            for row in self._credentials:
                self.stdout.write(f"  {row['hospital']:<38} {row['mobile']:<12} {row['password']}")
        self.stdout.write("")

    def _provision_one(self, subdomain):
        try:
            tenant = Tenant.objects.using("default").get(subdomain=subdomain)
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant with subdomain={subdomain!r}.")

        db = tenant.db_name
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{tenant.name} ({subdomain}, {db})"))

        if _database_exists(db):
            self.stdout.write(self.style.WARNING(f"  Database already exists — skipping create+migrate."))
        else:
            self.stdout.write(f"  Creating database '{db}'...")
            try:
                create_tenant_database(db)
            except Exception as exc:
                raise CommandError(f"Failed to create database for {subdomain}: {exc}")
            self.stdout.write("  Running tenant migrations...")
            try:
                run_tenant_migrations(db)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Migration failed: {exc} — dropping the half-migrated database."))
                drop_tenant_database(db)
                raise CommandError(f"Migration failed for {subdomain}, database rolled back: {exc}")
            self.stdout.write(self.style.SUCCESS("  Database created and migrated."))

        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)

        # Same default-template assignment provision_tenant does for a
        # brand-new tenant — these rows never got it since 0015 only wrote
        # the bare Tenant/Subscription fields.
        if tenant.active_vaccination_schedule_id is None:
            from apps.registry.models import VaccinationSchedule
            default_schedule = (
                VaccinationSchedule.objects.using("default")
                .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
                .order_by("id").first()
            )
            if default_schedule:
                tenant.active_vaccination_schedule_id = default_schedule.id
                self.stdout.write(f"  Assigned default vaccination schedule (id={default_schedule.id}).")
        if tenant.active_milestone_schedule_id is None:
            from apps.registry.models import MilestoneSchedule
            default_milestones = (
                MilestoneSchedule.objects.using("default")
                .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
                .order_by("id").first()
            )
            if default_milestones:
                tenant.active_milestone_schedule_id = default_milestones.id
                self.stdout.write(f"  Assigned default milestone schedule (id={default_milestones.id}).")
        tenant.save(using="default", update_fields=["active_vaccination_schedule_id", "active_milestone_schedule_id"])

        # ── Hospital admin login ────────────────────────────────────────
        from apps.org.models import StaffUser
        from apps.org.views import _next_employee_id
        from apps.registry.models import StaffMobileIndex

        if StaffUser.objects.using(db).filter(role="hospital_admin").exists():
            self.stdout.write(self.style.WARNING("  hospital_admin already exists — skipping."))
            return

        mobile = self._next_admin_mobile()
        password = _gen_password()
        admin = StaffUser(
            phone=mobile,
            email="",
            employee_id=_next_employee_id(db),
            first_name="Hospital",
            last_name="Admin",
            role="hospital_admin",
            must_change_password=True,
        )
        admin.set_password(password)
        admin.save(using=db)

        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=mobile,
            defaults={"tenant_id": tenant.id, "db_name": db, "email": None},
        )
        self._credentials.append({"hospital": tenant.name, "mobile": mobile, "password": password})
        self.stdout.write(self.style.SUCCESS(f"  Created hospital_admin login: {mobile}"))

    def _next_admin_mobile(self):
        from apps.registry.models import StaffMobileIndex
        if not hasattr(self, "_mobile_counter"):
            self._mobile_counter = STARTING_ADMIN_MOBILE
        while True:
            candidate = str(self._mobile_counter)
            self._mobile_counter += 1
            if not StaffMobileIndex.objects.using("default").filter(mobile=candidate).exists():
                return candidate
