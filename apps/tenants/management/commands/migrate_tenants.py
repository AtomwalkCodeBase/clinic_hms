"""
Management command: migrate_tenants

Runs Django migrations against all active tenant DBs (or a specific one).

Usage:
  # Migrate all active tenants:
  python manage.py migrate_tenants --settings=atomwalk.settings.development

  # Migrate a specific tenant by db_name:
  python manage.py migrate_tenants --db aw_sunrise_clinic --settings=atomwalk.settings.development
"""

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config, run_tenant_migrations


class Command(BaseCommand):
    help = "Run migrations on all active tenant databases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--db",
            dest="db_name",
            default=None,
            help="Specific tenant db_name to migrate (default: all active tenants)",
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

        self.stdout.write(f"Found {tenants.count()} tenant(s) to migrate.\n")

        for tenant in tenants:
            self.stdout.write(f"  Migrating: {tenant.name} ({tenant.db_name})")
            # Register in settings.DATABASES if not already there
            if tenant.db_name not in settings.DATABASES:
                settings.DATABASES[tenant.db_name] = _make_db_config(tenant.db_name)
            try:
                run_tenant_migrations(tenant.db_name)
                self.stdout.write(self.style.SUCCESS(f"    ✓ {tenant.db_name} — done"))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"    ✗ {tenant.db_name} — {exc}"))

        self.stdout.write("\nAll done.")
