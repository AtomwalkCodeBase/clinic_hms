"""
Management command: migrate_hospitals

Runs Django migrations against all active hospital DBs (or a specific one).

Usage:
  # Migrate all active hospitals:
  python manage.py migrate_hospitals --settings=atomwalk.settings.development

  # Migrate a specific hospital by db_name:
  python manage.py migrate_hospitals --db aw_sunrise_clinic --settings=atomwalk.settings.development
"""

from django.core.management.base import BaseCommand

from apps.atomwalk.hospital_master.models import Hospital
from apps.atomwalk.hospital_master.services import ensure_hospital_db, run_hospital_migrations


class Command(BaseCommand):
    help = "Run migrations on all active hospital databases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--db",
            dest="db_name",
            default=None,
            help="Specific hospital db_name to migrate (default: all active hospitals)",
        )

    def handle(self, *args, **options):
        db_name = options.get("db_name")

        if db_name:
            hospitals = Hospital.objects.filter(db_name=db_name)
            if not hospitals.exists():
                self.stderr.write(self.style.ERROR(f"No hospital found with db_name='{db_name}'"))
                return
        else:
            hospitals = Hospital.objects.filter(is_active=True)

        self.stdout.write(f"Found {hospitals.count()} hospital(s) to migrate.\n")

        for hospital in hospitals:
            self.stdout.write(f"  Migrating: {hospital.name} ({hospital.db_name})")
            # Register in settings.DATABASES if not already there
            ensure_hospital_db(hospital.db_name)
            try:
                run_hospital_migrations(hospital.db_name)
                self.stdout.write(self.style.SUCCESS(f"    ✓ {hospital.db_name} — done"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"    ✗ {hospital.db_name} — {exc}"))

        self.stdout.write("\nAll done.")
