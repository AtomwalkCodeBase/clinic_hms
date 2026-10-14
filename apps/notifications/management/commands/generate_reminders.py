"""
Management command: generate_reminders

Generates in-app reminder notifications (appointment + follow-up — see
apps/notifications/services.py) across every active hospital. There is no
Celery/cron runner built into this stack, so this has to be invoked on a
schedule by something outside Django:

  Linux/cron (once a day, e.g. 7am):
    0 7 * * * cd /path/to/repo && python manage.py generate_reminders --settings=atomwalk.settings.production

  Windows Task Scheduler: create a daily basic task that runs
    python manage.py generate_reminders --settings=atomwalk.settings.production
  from the repo directory.

Safe to run more than once a day — every reminder is keyed by a stable
reference (appointment id / encounter id) and only ever created once (see
_log_in_app in services.py), so re-runs just find nothing new to do.

Usage:
  python manage.py generate_reminders --settings=atomwalk.settings.development
  python manage.py generate_reminders --db aw_sunrise_clinic --settings=atomwalk.settings.development
"""

from django.core.management.base import BaseCommand

from apps.hospitals.models import Hospital
from apps.hospitals.utils import ensure_hospital_db
from apps.notifications.services import run_for_hospital


class Command(BaseCommand):
    help = "Generate in-app appointment/follow-up reminders for all active hospitals"

    def add_arguments(self, parser):
        parser.add_argument(
            "--db",
            dest="db_name",
            default=None,
            help="Specific hospital db_name to run (default: all active hospitals)",
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

        self.stdout.write(f"Generating reminders for {hospitals.count()} hospital(s)...\n")

        total_appt, total_followup = 0, 0
        for hospital in hospitals:
            ensure_hospital_db(hospital.db_name)
            try:
                counts = run_for_hospital(hospital.db_name)
                total_appt += counts["appointment_reminders"]
                total_followup += counts["followup_reminders"]
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ {hospital.name} ({hospital.db_name}) — "
                    f"{counts['appointment_reminders']} appointment, {counts['followup_reminders']} follow-up"
                ))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  ✗ {hospital.name} ({hospital.db_name}) — {exc}"))

        self.stdout.write(
            f"\nDone — {total_appt} appointment reminder(s), {total_followup} follow-up reminder(s) created."
        )
