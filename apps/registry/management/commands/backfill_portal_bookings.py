"""
Management command: backfill_portal_bookings

One-time repair for appointments booked BEFORE apps.registry.portal_sync
existed. sync_portal_booking() is now called automatically every time
front-desk/nurse staff create an Appointment (apps.opd.views.
AppointmentListCreateView.post), so any appointment booked going forward
writes its PortalBooking row and shows up in the patient's portal
automatically. But that call was only added going forward — appointments
that were already sitting in a tenant DB before the fix shipped have no
PortalBooking row and never will, unless something walks back over them
once.

This walks every active tenant's Appointment table and, for every row that
has a patient_awpid but no matching PortalBooking yet, calls the same
sync_portal_booking() the live booking flow uses — so a patient (or their
guardian) who already has a portal account will see their pre-existing
front-desk bookings appear without needing to be rebooked.

Genuinely explained by sync_portal_booking()'s own no-op paths, NOT bugs
(these are the majority of walk-ins in most demo/early data — nothing to
fix, nothing missing):
  - the appointment's patient has no portal account at all, and isn't a
    dependent of anyone who does
  - the appointment's patient_awpid is blank (very old data, pre-AWPID)

Usage:
  python manage.py backfill_portal_bookings              # apply, all tenants
  python manage.py backfill_portal_bookings --dry-run     # report only
  python manage.py backfill_portal_bookings --db aw_sunrise_clinic
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.registry.models import PortalBooking
from apps.registry.portal_sync import sync_portal_booking


class Command(BaseCommand):
    help = "Backfill PortalBooking rows for pre-existing front-desk/nurse appointments so they appear in the patient portal."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would sync without writing anything.")
        parser.add_argument("--db", dest="db_name", default=None, help="Specific tenant db_name to backfill (default: all active tenants)")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        db_name = options.get("db_name")

        from apps.opd.models import Appointment

        if db_name:
            tenants = Tenant.objects.filter(db_name=db_name)
            if not tenants.exists():
                self.stderr.write(self.style.ERROR(f"No tenant found with db_name='{db_name}'"))
                return
        else:
            tenants = Tenant.objects.filter(is_active=True)

        self.stdout.write(f"Found {tenants.count()} tenant(s) to check.\n")

        total_synced = 0
        total_checked = 0

        for tenant in tenants:
            db = tenant.db_name
            if db not in settings.DATABASES:
                settings.DATABASES[db] = _make_db_config(db)

            candidates = Appointment.objects.using(db).exclude(patient_awpid="").exclude(patient_awpid__isnull=True)
            already_synced_ids = set(
                PortalBooking.objects.using("default").filter(db_name=db).values_list("appointment_id", flat=True)
            )
            to_sync = [a for a in candidates if a.id not in already_synced_ids]

            self.stdout.write(f"\n=== {tenant.name} ({db}) — {len(to_sync)} appointment(s) not yet in PortalBooking ===")
            total_checked += len(to_sync)

            synced_here = 0
            for appt in to_sync:
                before = PortalBooking.objects.using("default").filter(appointment_id=appt.id).exists()
                if before:
                    continue
                if not dry_run:
                    sync_portal_booking(appt, db)
                after = dry_run or PortalBooking.objects.using("default").filter(appointment_id=appt.id).exists()
                if not dry_run and after:
                    synced_here += 1
                    self.stdout.write(f"  synced appointment {appt.id} (patient_awpid={appt.patient_awpid})")

            if dry_run:
                self.stdout.write(f"  [dry-run] would attempt {len(to_sync)} — actual sync count depends on portal-account matches (not evaluated in dry-run).")
            else:
                self.stdout.write(self.style.SUCCESS(f"  Synced {synced_here} of {len(to_sync)} (rest have no portal account on file — nothing to sync to)."))
            total_synced += synced_here

        self.stdout.write(self.style.SUCCESS(
            f"\n{'Would check' if dry_run else 'Checked'} {total_checked} appointment(s) across {tenants.count()} tenant(s)"
            + ("" if dry_run else f" — synced {total_synced} new PortalBooking row(s).")
        ))
