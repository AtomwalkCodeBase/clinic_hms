"""
Management command: rebrand_investor_demo_doctors

One-off fix for a seed_investor_demo tenant that was seeded BEFORE this
project had --roster b, so its 15 doctors have identical names to another
seed_investor_demo hospital's doctors (both were seeded from the DOCTORS
roster — see that file's docstring). Cross-hospital patient search
(apps.patients.portal_views.PortalSearchView) shows every active
hospital's doctors together, so two hospitals with the same 15 doctor
names look like a duplicate-listing bug even though they're correctly two
different people at two different hospitals.

This renames each of that tenant's doctors to the corresponding DOCTORS_B
identity, matched by position — DOCTORS[i] and DOCTORS_B[i] share the same
specialty, schedule, and room by construction (see seed_investor_demo.py),
so this changes ONLY the person's name/mobile/registration number/email/
bio. Nothing else is touched: rooms, schedules, appointments, invoices,
prescriptions, and patients all stay exactly as they are, because every
one of those is foreign-keyed to StaffUser.id, never to the person's name.

Safe to run against a tenant with real demo activity already on it — this
never touches Tenant, Branch, Room, Appointment, or patient/billing data.

Usage:
  python manage.py rebrand_investor_demo_doctors --tenant aw_novacare_flagship --settings=atomwalk.settings.development
  python manage.py rebrand_investor_demo_doctors --tenant aw_novacare_flagship --dry-run --settings=atomwalk.settings.development

After running for real, anyone who logs in as one of the renamed doctors
needs their NEW mobile number / email (printed below) — the password is
unchanged (Demo@12345), but the old login identifiers stop working the
moment this runs, by design (StaffMobileIndex is the actual login lookup —
see apps.org.auth_views — so the old mobile can't be left pointing here
too without letting two different "identities" both log into one account).
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import StaffUser, DoctorProfile
from apps.registry.models import StaffMobileIndex

from apps.registry.management.commands.seed_investor_demo import DOCTORS, DOCTORS_B, BIO_TEMPLATES


class Command(BaseCommand):
    help = (
        "Rename an already-seeded seed_investor_demo tenant's doctors from roster A to "
        "roster B, so it no longer shares doctor names with another hospital seeded from "
        "the same script."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="db_name", required=True,
                             help="Tenant db_name to rebrand (e.g. aw_novacare_flagship).")
        parser.add_argument("--dry-run", action="store_true",
                             help="Print what would change without saving anything.")

    def handle(self, *args, **options):
        db = options["db_name"]
        dry_run = options["dry_run"]

        try:
            tenant = Tenant.objects.using("default").get(db_name=db)
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant found with db_name='{db}'.")

        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)

        # (first.lower(), last.lower()) -> index in DOCTORS, so we can find
        # each doctor's matching DOCTORS_B identity regardless of the order
        # StaffUser rows come back from the DB in.
        index_by_name = {(d["first"].lower(), d["last"].lower()): i for i, d in enumerate(DOCTORS)}
        subdomain = tenant.subdomain

        renamed, skipped = [], []

        with transaction.atomic(using=db):
            for staff in StaffUser.objects.using(db).filter(role="doctor"):
                key = (staff.first_name.lower(), staff.last_name.lower())
                if key not in index_by_name:
                    skipped.append(staff.get_full_name())
                    continue

                i = index_by_name[key]
                new = DOCTORS_B[i]
                old_mobile, old_email, old_name = staff.phone, staff.email, staff.get_full_name()
                new_email = f"{new['first'].lower()}.{new['last'].lower()}@{subdomain}.demo"
                bio = BIO_TEMPLATES[i % len(BIO_TEMPLATES)].format(
                    last=new["last"], qual=new["qual"], exp=new["exp"], spec=new["spec"],
                    known_for_lower=new["known_for"].lower(), hospital=tenant.name,
                )

                self.stdout.write(
                    f"  {old_name} -> Dr. {new['first']} {new['last']}  "
                    f"(mobile {old_mobile} -> {new['mobile']}, email {old_email} -> {new_email})"
                )

                if dry_run:
                    renamed.append(old_name)
                    continue

                staff.first_name = new["first"]
                staff.last_name = new["last"]
                staff.phone = new["mobile"]
                staff.email = new_email
                staff.save(using=db, update_fields=["first_name", "last_name", "phone", "email"])

                DoctorProfile.objects.using(db).filter(staff_id=staff.id).update(
                    registration_no=new["reg_no"], bio=bio,
                )

                # StaffMobileIndex lives in the shared "default" DB and is
                # the actual login lookup (mobile/email -> which tenant DB to
                # hit — see apps.org.auth_views), keyed on mobile. The old
                # row has to go, not just get a new one added alongside it,
                # or the old mobile number would still "work" and log into
                # this same account under the person's old identity.
                StaffMobileIndex.objects.using("default").filter(mobile=old_mobile).delete()
                StaffMobileIndex.objects.using("default").update_or_create(
                    mobile=new["mobile"],
                    defaults={"tenant_id": tenant.id, "db_name": db, "email": new_email},
                )

                renamed.append(old_name)

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\nDry run — {len(renamed)} doctor(s) would be renamed, nothing saved."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nDone — {len(renamed)} doctor(s) renamed."))
            self.stdout.write(self.style.WARNING(
                "\nHeads up: everyone renamed above now logs in with their NEW mobile number "
                "and email (password unchanged: Demo@12345) — their old credentials no longer work."
            ))
        if skipped:
            self.stdout.write(self.style.WARNING(
                "Skipped (not in the original DOCTORS roster — added by hand after seeding, "
                "no authored replacement identity to rename to):\n  " + "\n  ".join(skipped)
            ))
