"""
Management command: provision_pending_hospital_dbs

Finishes provisioning for hospitals that already have a Hospital + Subscription
row in the atomwalk DB (created by apps/hospitals/migrations/
0015_seed_east_bangalore_clinics.py, which deliberately only inserts
atomwalk rows — see that migration's docstring) but no real per-hospital
Postgres database yet, so they show up in "hospitals near me" with an
empty "View doctors" list.

For each target hospital this does exactly what provision_hospital does for a
brand-new hospital, minus the Hospital/Subscription creation (which already
exists here):
  1. Create the Postgres database
  2. Run all hospital-app migrations against it
  3. Point it at the default vaccination + milestone schedule templates
  4. Create a hospital_admin StaffUser + atomwalk StaffMobileIndex entry

Safe to re-run: skips any hospital whose database already exists (checked
via pg_database, not just db_name being set on the Hospital row) and skips
creating a second hospital_admin if one already exists in that hospital DB.

Usage:
  python manage.py provision_pending_hospital_dbs --settings=atomwalk.settings.development
  python manage.py provision_pending_hospital_dbs --subdomain care-cure-clinic --settings=atomwalk.settings.development
"""

import secrets
import string

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.atomwalk.hospital_master.models import Hospital
from apps.atomwalk.hospital_master.services import (
    create_hospital_database,
    run_hospital_migrations,
    drop_hospital_database,
    _make_db_config,
    ensure_hospital_db,
)

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
    help = "Create the missing Postgres database + run migrations + a hospital_admin login for hospitals that only have a atomwalk row so far."

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
            hospital = Hospital.objects.using("default").get(subdomain=subdomain)
        except Hospital.DoesNotExist:
            raise CommandError(f"No hospital with subdomain={subdomain!r}.")

        db = hospital.db_name
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{hospital.name} ({subdomain}, {db})"))

        if _database_exists(db):
            self.stdout.write(self.style.WARNING("  Database already exists — skipping create+migrate."))
        else:
            self.stdout.write(f"  Creating database '{db}'...")
            try:
                create_hospital_database(db)
            except Exception as exc:
                raise CommandError(f"Failed to create database for {subdomain}: {exc}")
            self.stdout.write("  Running hospital migrations...")
            try:
                run_hospital_migrations(db)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Migration failed: {exc} — dropping the half-migrated database."))
                drop_hospital_database(db)
                raise CommandError(f"Migration failed for {subdomain}, database rolled back: {exc}")
            self.stdout.write(self.style.SUCCESS("  Database created and migrated."))

        ensure_hospital_db(db)

        # Same default-template assignment provision_hospital does for a
        # brand-new hospital — these rows never got it since 0015 only wrote
        # the bare Hospital/Subscription fields.
        if hospital.active_vaccination_schedule_id is None:
            from apps.atomwalk.documents.models import Schedule
            default_schedule = (
                Schedule.objects.using("default")
                .filter(kind="vaccination", owner_hospital_id__isnull=True, is_template=True, active=True)
                .order_by("id").first()
            )
            if default_schedule:
                hospital.active_vaccination_schedule_id = default_schedule.id
                self.stdout.write(f"  Assigned default vaccination schedule (id={default_schedule.id}).")
        if hospital.active_milestone_schedule_id is None:
            default_milestones = (
                Schedule.objects.using("default")
                .filter(kind="milestone", owner_hospital_id__isnull=True, is_template=True, active=True)
                .order_by("id").first()
            )
            if default_milestones:
                hospital.active_milestone_schedule_id = default_milestones.id
                self.stdout.write(f"  Assigned default milestone schedule (id={default_milestones.id}).")
        hospital.save(using="default", update_fields=["active_vaccination_schedule_id", "active_milestone_schedule_id"])

        # ── Hospital admin login ────────────────────────────────────────
        from apps.hospital_master.staff.models import StaffUser
        from apps.hospital_master.staff.services import next_employee_id
        from apps.atomwalk.patients.models import StaffMobileIndex

        if StaffUser.objects.using(db).filter(role="hospital_admin").exists():
            self.stdout.write(self.style.WARNING("  hospital_admin already exists — skipping."))
            return

        mobile = self._next_admin_mobile()
        password = _gen_password()
        admin = StaffUser(
            phone=mobile,
            email="",
            employee_id=next_employee_id(db),
            first_name="Hospital",
            last_name="Admin",
            role="hospital_admin",
            must_change_password=True,
        )
        admin.set_password(password)
        admin.save(using=db)

        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=mobile,
            defaults={"hospital_id": hospital.id, "email": None},
        )
        self._credentials.append({"hospital": hospital.name, "mobile": mobile, "password": password})
        self.stdout.write(self.style.SUCCESS(f"  Created hospital_admin login: {mobile}"))

    def _next_admin_mobile(self):
        from apps.atomwalk.patients.models import StaffMobileIndex
        if not hasattr(self, "_mobile_counter"):
            self._mobile_counter = STARTING_ADMIN_MOBILE
        while True:
            candidate = str(self._mobile_counter)
            self._mobile_counter += 1
            if not StaffMobileIndex.objects.using("default").filter(mobile=candidate).exists():
                return candidate
