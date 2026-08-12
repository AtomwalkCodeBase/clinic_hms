"""
Management command: provision_tenant

Creates a new hospital tenant end-to-end:
  1. Creates Tenant + Subscription rows in Registry DB
  2. Creates a PostgreSQL database for the tenant
  3. Runs all tenant-app migrations against that DB
  4. Creates a hospital_admin StaffUser in the tenant DB

Usage:
  python manage.py provision_tenant \\
    --name "Apollo Delhi" \\
    --subdomain apollo-delhi \\
    --city Delhi \\
    --state Delhi \\
    --gstin 07AABCU9603R1ZX \\
    --admin-email admin@apollodelhi.in \\
    --tier starter \\
    --settings=atomwalk.settings.development
"""

import secrets
import string
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from apps.tenants.models import Tenant, Subscription
from apps.tenants.utils import create_tenant_database, run_tenant_migrations
# Re-exported for backwards compatibility — apps/registry/management/commands/
# seed_full_demo.py imports TIER_FEATURE_DEFAULTS from this module. The real
# definition now lives in apps/tenants/constants.py (single source of truth,
# also used by apps/platform_admin/views.py) so the two copies can't drift.
from apps.tenants.constants import TIER_FEATURE_DEFAULTS  # noqa: F401


def _gen_password(length=14):
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


class Command(BaseCommand):
    help = "Provision a new hospital tenant"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Hospital display name")
        parser.add_argument("--subdomain", default=None,
                            help="Subdomain slug (auto-derived from name if omitted)")
        parser.add_argument("--city", default="")
        parser.add_argument("--state", default="")
        parser.add_argument("--gstin", default="")
        parser.add_argument("--admin-mobile", required=True, dest="admin_mobile")
        parser.add_argument("--admin-email", required=False, default="", dest="admin_email")
        parser.add_argument(
            "--tier",
            choices=["starter", "growth", "pro", "enterprise"],
            default="starter",
        )

    def handle(self, *args, **options):
        name = options["name"]
        subdomain = options["subdomain"] or slugify(name)
        city = options["city"]
        state = options["state"]
        gstin = options["gstin"]
        admin_mobile = options["admin_mobile"]
        admin_email = options["admin_email"] or None
        tier = options["tier"]

        # Derive db_name from subdomain
        db_name = subdomain.replace("-", "_").replace(" ", "_").lower()
        db_name = f"aw_{db_name}"

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  Provisioning: {name}")
        self.stdout.write(f"  Subdomain:    {subdomain}")
        self.stdout.write(f"  DB Name:      {db_name}")
        self.stdout.write(f"  Tier:         {tier}")
        self.stdout.write(f"{'='*60}\n")

        # ── 1. Validate uniqueness ────────────────────────────────────
        if Tenant.objects.filter(subdomain=subdomain).exists():
            raise CommandError(f"Tenant with subdomain '{subdomain}' already exists.")
        if Tenant.objects.filter(db_name=db_name).exists():
            raise CommandError(f"Tenant with db_name '{db_name}' already exists.")

        # ── 2. Create Tenant ─────────────────────────────────────────
        self.stdout.write("[ 1/5 ] Creating Tenant record...")
        tenant = Tenant.objects.create(
            name=name,
            subdomain=subdomain,
            db_name=db_name,
            city=city,
            state=state,
            gstin=gstin,
            is_active=True,
        )
        self.stdout.write(self.style.SUCCESS(f"    Tenant created (id={tenant.id})"))

        # Point the new tenant at the shared system "Default Schedule"
        # vaccination-schedule template so it doesn't lose vaccination
        # roadmap functionality on day one. This is v1's simplest-correct
        # behavior: point directly at the shared template's id — NOT a
        # clone-on-provision. The hospital can later clone it into its own
        # editable copy via the admin UI (a separate task) if it wants to
        # customize; until then it's reading (not owning) the template.
        from apps.registry.models import VaccinationSchedule
        default_schedule = (
            VaccinationSchedule.objects.using("default")
            .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
            .order_by("id")
            .first()
        )
        if default_schedule:
            tenant.active_vaccination_schedule_id = default_schedule.id
            tenant.save(update_fields=["active_vaccination_schedule_id"])
            self.stdout.write(self.style.SUCCESS(
                f"    Assigned default vaccination schedule (id={default_schedule.id})"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "    No system 'Default Schedule' found — tenant provisioned without a vaccination schedule."
            ))

        # ── 3. Create Subscription ───────────────────────────────────
        self.stdout.write("[ 2/5 ] Creating Subscription...")
        feats = TIER_FEATURE_DEFAULTS[tier]
        Subscription.objects.create(
            tenant=tenant,
            license_tier=tier,
            status="active",
            **feats,
        )
        self.stdout.write(self.style.SUCCESS(f"    Subscription created: {tier}"))

        # ── 4. Create PostgreSQL database ────────────────────────────
        self.stdout.write(f"[ 3/5 ] Creating database '{db_name}'...")
        try:
            create_tenant_database(db_name)
            self.stdout.write(self.style.SUCCESS(f"    Database created"))
        except Exception as e:
            tenant.delete()
            raise CommandError(f"Failed to create database: {e}")

        # ── 5. Run tenant migrations ─────────────────────────────────
        self.stdout.write("[ 4/5 ] Running tenant migrations...")
        try:
            run_tenant_migrations(db_name)
            self.stdout.write(self.style.SUCCESS("    Migrations complete"))
        except Exception as e:
            raise CommandError(f"Migration failed: {e}")

        # ── 6. Create hospital admin StaffUser ───────────────────────
        self.stdout.write("[ 5/5 ] Creating hospital admin user...")
        temp_password = _gen_password()
        try:
            from apps.org.models import StaffUser
            from apps.org.views import _next_employee_id
            admin = StaffUser(
                phone=admin_mobile,
                email=admin_email,
                employee_id=_next_employee_id(db_name),
                first_name="Hospital",
                last_name="Admin",
                role="hospital_admin",
                must_change_password=True,
            )
            admin.set_password(temp_password)
            admin.save(using=db_name)

            # Write to registry mobile index (enables login without subdomain)
            from apps.registry.models import StaffMobileIndex
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=admin_mobile,
                defaults={
                    "tenant_id": tenant.id,
                    "db_name": db_name,
                    "email": admin_email or None,
                },
            )
            self.stdout.write(self.style.SUCCESS(f"    Admin user created: {admin_mobile}"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"    StaffUser creation failed: {e}"))
            self.stdout.write(self.style.WARNING("    You can create the admin via the API later."))

        # ── Done ─────────────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("  ✓ TENANT PROVISIONED SUCCESSFULLY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Hospital:      {name}")
        self.stdout.write(f"  Subdomain:     {subdomain}")
        self.stdout.write(f"  DB Name:       {db_name}")
        self.stdout.write(f"  Admin Mobile:  {admin_mobile}")
        self.stdout.write(f"  Temp Password: {temp_password}")
        self.stdout.write(f"  Tier:          {tier}")
        self.stdout.write("")
        self.stdout.write("  Login at the frontend with:")
        self.stdout.write(f"    Subdomain: {subdomain}")
        self.stdout.write(f"    Mobile:    {admin_mobile}")
        self.stdout.write(f"    Password:  {temp_password}")
        self.stdout.write("=" * 60 + "\n")
