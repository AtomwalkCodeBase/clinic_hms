"""Management command: provision_pending_hospital_dbs"""

import secrets
import string

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.hospital_master.models import Hospital
from apps.hospital_master.services import parameters_of
from apps.hospital_master.services import (
    create_hospital_database,
    run_hospital_migrations,
    drop_hospital_database,
    _make_db_config,
    ensure_hospital_db,
)

DEFAULT_HOSPITAL_CODES = [
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
        parser.add_argument("--hospital-code", action="append", default=None,
                             help="Limit to this hospital_code (repeatable). Defaults to the 5 East-Bengaluru "
                                  "clinics that don't have a real database yet.")

    def handle(self, *args, **options):
        hospital_codes = options["hospital_code"] or DEFAULT_HOSPITAL_CODES
        self._credentials = []

        for hospital_code in hospital_codes:
            self._provision_one(hospital_code)

        if self._credentials:
            self.stdout.write(self.style.SUCCESS(f"\n{len(self._credentials)} hospital(s) provisioned.\n"))
            self.stdout.write(f"  {'Hospital':<38} {'Mobile':<12} {'Password'}")
            for row in self._credentials:
                self.stdout.write(f"  {row['hospital']:<38} {row['mobile']:<12} {row['password']}")
        self.stdout.write("")

    def _provision_one(self, hospital_code):
        try:
            hospital = Hospital.objects.using("default").get(hospital_code=hospital_code)
        except Hospital.DoesNotExist:
            raise CommandError(f"No hospital with hospital_code={hospital_code!r}.")

        db = hospital.db_name
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{hospital.name} ({hospital_code}, {db})"))

        if _database_exists(db):
            self.stdout.write(self.style.WARNING("  Database already exists — skipping create+migrate."))
        else:
            self.stdout.write(f"  Creating database '{db}'...")
            try:
                create_hospital_database(db)
            except Exception as exc:
                raise CommandError(f"Failed to create database for {hospital_code}: {exc}")
            self.stdout.write("  Running hospital migrations...")
            try:
                run_hospital_migrations(db)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Migration failed: {exc} — dropping the half-migrated database."))
                drop_hospital_database(db)
                raise CommandError(f"Migration failed for {hospital_code}, database rolled back: {exc}")
            self.stdout.write(self.style.SUCCESS("  Database created and migrated."))

        ensure_hospital_db(db)

        parameters_of(hospital)

        # ── Hospital admin login ────────────────────────────────────────
        from apps.hospital_setup.models import StaffUser
        from apps.hospital_setup.staff_services import next_employee_id
        from apps.hospital_setup.rbac import role_q, system_role
        from apps.patients.models import StaffMobileIndex

        if StaffUser.objects.using(db).filter(role_q("hospital_admin")).exists():
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
            group=system_role(db, "hospital_admin"),
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
        from apps.patients.models import StaffMobileIndex
        if not hasattr(self, "_mobile_counter"):
            self._mobile_counter = STARTING_ADMIN_MOBILE
        while True:
            candidate = str(self._mobile_counter)
            self._mobile_counter += 1
            if not StaffMobileIndex.objects.using("default").filter(mobile=candidate).exists():
                return candidate
