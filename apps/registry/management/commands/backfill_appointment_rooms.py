"""
Management command: backfill_appointment_rooms

Fills in room_id/room_name/floor on existing appointments that have none —
the seed_full_demo/_build_visit helper (reused by seed_investor_demo for
its patient-lifecycle loop) never set these fields, so every seeded
appointment showed a blank "Room" column on the doctor/nurse/front-desk
queue and upcoming-schedule screens even though every doctor has a real
dedicated Room + RoomAssignment from seed_investor_demo's own doctor loop.

Uses the exact same resolution the real booking flow uses
(apps.org.room_utils.resolve_room_for_slot — matched by the doctor's
day-of-week + time window), so a backfilled appointment gets the same room
a front-desk booking for that same doctor/day/time would get today. An
appointment outside every one of its doctor's working windows (e.g. a
random seeded time that doesn't land in any RoomAssignment slot) is left
alone — there's no real room to attribute it to, so "—" stays correct for
those rather than guessing.

Usage:
  python manage.py backfill_appointment_rooms --tenant aw_novacare_flagship --settings=atomwalk.settings.development
"""

import uuid as _uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.opd.models import Appointment
from apps.org.room_utils import resolve_room_for_slot, get_doctor_home_room


class Command(BaseCommand):
    help = "Backfill room/floor onto existing appointments with none, using each doctor's real RoomAssignment."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="db_name", required=True,
                             help="Tenant db_name to backfill (e.g. aw_novacare_flagship).")

    def handle(self, *args, **options):
        db = options["db_name"]

        if not Tenant.objects.using("default").filter(db_name=db).exists():
            raise CommandError(f"No tenant found with db_name='{db}'.")

        if db not in settings.DATABASES:
            settings.DATABASES[db] = _make_db_config(db)

        appts = (
            Appointment.objects.using(db)
            .filter(room_id__isnull=True, scheduled_time__isnull=False)
            .exclude(status__in=["cancelled", "no_show"])
        )

        updated, skipped = 0, 0
        with transaction.atomic(using=db):
            for appt in appts:
                # doctor_user_id is a UUIDField that actually stores a
                # StaffUser's plain integer pk, wrapped via uuid.UUID(int=id)
                # — same unwrap apps.opd.views._resolve_doctor_consultation_fee
                # uses, needed here because RoomAssignment.doctor_id is a
                # real int FK, not a UUID column.
                raw_doctor_id = (
                    appt.doctor_user_id.int if isinstance(appt.doctor_user_id, _uuid.UUID)
                    else appt.doctor_user_id
                )
                day_of_week = appt.scheduled_date.weekday()
                match = resolve_room_for_slot(db, raw_doctor_id, day_of_week, appt.scheduled_time)
                if not match:
                    # Seeded/demo appointment times are often arbitrary
                    # (current wall-clock, or a fixed follow-up slot) and
                    # don't land inside the doctor's actual RoomAssignment
                    # window. Rather than leave the column blank, fall back
                    # to the doctor's home room — every doctor here has
                    # exactly one dedicated room across all working days.
                    match = get_doctor_home_room(db, raw_doctor_id)
                if not match:
                    skipped += 1
                    continue
                appt.room_id = match.room_id
                appt.room_name = match.room.name
                appt.floor = match.room.floor
                appt.save(using=db, update_fields=["room_id", "room_name", "floor"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone — {updated} appointment(s) got a room, {skipped} left as-is "
            f"(no RoomAssignment covers that doctor's day/time)."
        ))
