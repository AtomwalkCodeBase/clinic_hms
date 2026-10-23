"""apps/hospital_setup/notification_services.py"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def _log_in_app(db, patient, reference, body):
    """Idempotent — a reference that's already logged is skipped, so re-running"""
    from apps.hospital_setup.models import NotificationLog

    if NotificationLog.objects.using(db).filter(reference=reference).exists():
        return False
    NotificationLog.objects.using(db).create(
        patient=patient,
        recipient=patient.get_patient_details()["mobile"] or patient.uhid,
        channel="in_app",
        body=body,
        status="sent",
        sent_at=timezone.now(),
        reference=reference,
    )
    return True


def generate_appointment_reminders(db, lookahead_days=1):
    """One reminder per appointment still SCHEDULED/WAITING for lookahead_days"""
    from apps.opd.models import Appointment

    target_date = timezone.localdate() + timedelta(days=lookahead_days)
    appts = (
        Appointment.objects.using(db)
        .filter(scheduled_date=target_date, status__in=[Appointment.STATUS_SCHEDULED, Appointment.STATUS_WAITING])
    )
    appts = appts.select_related("patient", "doctor")

    created = 0
    for appt in appts:
        patient = appt.patient
        when = appt.scheduled_time.strftime("%I:%M %p").lstrip("0") if appt.scheduled_time else "your scheduled slot"
        doctor = f" with {appt.doctor.get_full_name()}" if appt.doctor.get_full_name() else ""
        body = f"Reminder: you have an appointment{doctor} on {target_date.strftime('%d %b %Y')} at {when}."
        if _log_in_app(db, patient, f"appt_reminder:{appt.id}", body):
            created += 1
    return created


def generate_followup_reminders(db):
    """A signed OPDEncounter with follow_up_in_days set is due today when"""
    from apps.opd.models import OPDEncounter

    today = timezone.localdate()
    encounters = (
        OPDEncounter.objects.using(db)
        .filter(status=OPDEncounter.STATUS_SIGNED, follow_up_in_days__isnull=False, signed_at__isnull=False)
        .select_related("appointment__patient")
    )

    created = 0
    for enc in encounters:
        due_date = enc.signed_at.date() + timedelta(days=enc.follow_up_in_days)
        if due_date != today:
            continue
        patient = enc.appointment.patient
        body = "Reminder: your doctor recommended a follow-up visit around now. Please book an appointment when convenient."
        if _log_in_app(db, patient, f"followup:{enc.id}", body):
            created += 1
    return created


def run_for_hospital(db):
    """Runs every generator for one hospital DB, returns a {name: count} summary."""
    return {
        "appointment_reminders": generate_appointment_reminders(db),
        "followup_reminders": generate_followup_reminders(db),
    }
