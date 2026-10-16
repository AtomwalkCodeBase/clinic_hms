"""Management command: provision_hospital"""

import secrets
import string
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from apps.hospital_master.models import Hospital, Subscription
from apps.hospital_master.services import parameters_of
from apps.hospital_master.services import create_hospital_database, run_hospital_migrations
# Re-exported for backwards compatibility — apps/atomwalk/management/commands/
from apps.hospital_master.services import TIER_FEATURE_DEFAULTS


def _gen_password(length=14):
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


class Command(BaseCommand):
    help = "Provision a new hospital hospital"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Hospital display name")
        parser.add_argument("--hospital-code", default=None,
                            help="Hospital code slug (auto-derived from name if omitted)")
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
        hospital_code = options["hospital_code"] or slugify(name)
        city = options["city"]
        state = options["state"]
        gstin = options["gstin"]
        admin_mobile = options["admin_mobile"]
        admin_email = options["admin_email"] or None
        tier = options["tier"]

        # Derive db_name from hospital_code
        db_name = hospital_code.replace("-", "_").replace(" ", "_").lower()
        db_name = f"aw_{db_name}"

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  Provisioning: {name}")
        self.stdout.write(f"  Hospital code:    {hospital_code}")
        self.stdout.write(f"  DB Name:      {db_name}")
        self.stdout.write(f"  Tier:         {tier}")
        self.stdout.write(f"{'='*60}\n")

        # ── 1. Validate uniqueness ────────────────────────────────────
        if Hospital.objects.filter(hospital_code=hospital_code).exists():
            raise CommandError(f"Hospital with hospital_code '{hospital_code}' already exists.")
        if Hospital.objects.filter(db_name=db_name).exists():
            raise CommandError(f"Hospital with db_name '{db_name}' already exists.")

        # ── 2. Create Hospital ─────────────────────────────────────────
        self.stdout.write("[ 1/5 ] Creating Hospital record...")
        hospital = Hospital.objects.create(
            name=name,
            hospital_code=hospital_code,
            db_name=db_name,
            city=city,
            state=state,
            gstin=gstin,
            is_active=True,
        )
        self.stdout.write(self.style.SUCCESS(f"    Hospital created (id={hospital.id})"))

        parameters_of(hospital)

        # ── 3. Create Subscription ───────────────────────────────────
        self.stdout.write("[ 2/5 ] Creating Subscription...")
        feats = TIER_FEATURE_DEFAULTS[tier]
        Subscription.objects.create(
            hospital=hospital,
            license_tier=tier,
            status="active",
            **feats,
        )
        self.stdout.write(self.style.SUCCESS(f"    Subscription created: {tier}"))

        # ── 4. Create PostgreSQL database ────────────────────────────
        self.stdout.write(f"[ 3/5 ] Creating database '{db_name}'...")
        try:
            create_hospital_database(db_name)
            self.stdout.write(self.style.SUCCESS("    Database created"))
        except Exception as e:
            hospital.delete()
            raise CommandError(f"Failed to create database: {e}")

        # ── 5. Run hospital migrations ─────────────────────────────────
        self.stdout.write("[ 4/5 ] Running hospital migrations...")
        try:
            run_hospital_migrations(db_name)
            self.stdout.write(self.style.SUCCESS("    Migrations complete"))
        except Exception as e:
            raise CommandError(f"Migration failed: {e}")

        # ── 6. Create hospital admin StaffUser ───────────────────────
        self.stdout.write("[ 5/5 ] Creating hospital admin user...")
        temp_password = _gen_password()
        try:
            from apps.hospital_setup.models import StaffUser
            from apps.hospital_setup.staff_services import next_employee_id
            admin = StaffUser(
                phone=admin_mobile,
                email=admin_email,
                employee_id=next_employee_id(db_name),
                first_name="Hospital",
                last_name="Admin",
                role="hospital_admin",
                must_change_password=True,
            )
            admin.set_password(temp_password)
            admin.save(using=db_name)

            # Write to atomwalk mobile index (enables login without hospital_code)
            from apps.patients.models import StaffMobileIndex
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=admin_mobile,
                defaults={
                    "hospital_id": hospital.id,
                    "email": admin_email or None,
                },
            )
            self.stdout.write(self.style.SUCCESS(f"    Admin user created: {admin_mobile}"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"    StaffUser creation failed: {e}"))
            self.stdout.write(self.style.WARNING("    You can create the admin via the API later."))

        # ── Done ─────────────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("  ✓ HOSPITAL PROVISIONED SUCCESSFULLY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Hospital:      {name}")
        self.stdout.write(f"  Hospital code:     {hospital_code}")
        self.stdout.write(f"  DB Name:       {db_name}")
        self.stdout.write(f"  Admin Mobile:  {admin_mobile}")
        self.stdout.write(f"  Temp Password: {temp_password}")
        self.stdout.write(f"  Tier:          {tier}")
        self.stdout.write("")
        self.stdout.write("  Login at the frontend with:")
        self.stdout.write(f"    Hospital code: {hospital_code}")
        self.stdout.write(f"    Mobile:    {admin_mobile}")
        self.stdout.write(f"    Password:  {temp_password}")
        self.stdout.write("=" * 60 + "\n")
