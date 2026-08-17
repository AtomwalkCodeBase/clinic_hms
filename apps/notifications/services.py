"""
apps/notifications/services.py
--------------------------------
Reminder generation — appointment reminders and follow-up-visit reminders
(HMS-10g-1/2). Deliberately scoped to in-app only: this writes
NotificationLog rows with channel="in_app" so they show up in the patient
portal's notification list (see apps.patients.portal_views.PortalNotificationsView).
Nothing here sends a real SMS/email/push — that needs a provider account
(Twilio/SendGrid/FCM-style) the hospital would have to supply; wiring one in
is a follow-up once credentials exist, not something to fake here.

Meant to be run by apps/notifications/management/commands/generate_reminders.py
on a schedule (there's no Celery/cron runner in this stack yet — see that
command's docstring for how to actually schedule it).

Vaccination-due reminders are NOT generated here. They're computed live, per
request, in PortalNotificationsView via apps.registry.vaccine_schedule.build_roadmap()
— vaccination due-ness is inherently always-current (it's just today's date
vs. the patient's age), so persisting a stale "reminder" row for it would be
wrong the moment the underlying roadmap changes (e.g. a dose gets logged).
Also SharedVaccination is a registry (cross-hospital) model, not tenant-owned,
so there's no single tenant DB to log it against.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def _log_in_app(db, patient, reference, body):
    """
    Idempotent — a reference that's already logged is skipped, so re-running
    the generator daily doesn't spam the same appointment/follow-up over and
    over. Returns True if a new row was created.
    """
    from .models import NotificationLog

    if NotificationLog.objects.using(db).filter(reference=reference).exists():
        return False
    NotificationLog.objects.using(db).create(
        patient=patient,
        recipient=patient.mobile or patient.uhid,
        channel="in_app",
        body=body,
        status="sent",          # in-app items need no delivery step — appearing in the list IS delivery
        sent_at=timezone.now(),
        reference=reference,
    )
    return True


def generate_appointment_reminders(db, lookahead_days=1):
    """
    One reminder per appointment still SCHEDULED/WAITING for lookahead_days
    from now (default: tomorrow). Cancelled/done/no_show appointments and
    ones already reminded (see _log_in_app's reference check) are skipped.
    Returns the count of new reminders created.
    """
    from apps.opd.models import Appointment
    from apps.patients.models import Patient

    target_date = timezone.localdate() + timedelta(days=lookahead_days)
    appts = (
        Appointment.objects.using(db)
        .filter(scheduled_date=target_date, status__in=[Appointment.STATUS_SCHEDULED, Appointment.STATUS_WAITING])
    )
    patient_uuids = {a.patient_id for a in appts}
    patients = {p.uuid: p for p in Patient.objects.using(db).filter(uuid__in=patient_uuids)}

    created = 0
    for appt in appts:
        patient = patients.get(appt.patient_id)
        if not patient:
            continue
        when = appt.scheduled_time.strftime("%I:%M %p").lstrip("0") if appt.scheduled_time else "your scheduled slot"
        doctor = f" with {appt.doctor_name}" if appt.doctor_name else ""
        body = f"Reminder: you have an appointment{doctor} on {target_date.strftime('%d %b %Y')} at {when}."
        if _log_in_app(db, patient, f"appt_reminder:{appt.id}", body):
            created += 1
    return created


def generate_followup_reminders(db):
    """
    A signed OPDEncounter with follow_up_in_days set is due today when
    signed_at.date() + follow_up_in_days == today. One reminder per
    encounter, same idempotency guard as appointment reminders.
    """
    from apps.opd.models import OPDEncounter
    from apps.patients.models import Patient

    today = timezone.localdate()
    encounters = (
        OPDEncounter.objects.using(db)
        .filter(status=OPDEncounter.STATUS_SIGNED, follow_up_in_days__isnull=False, signed_at__isnull=False)
    )
    patient_uuids = {e.patient_id for e in encounters}
    patients = {p.uuid: p for p in Patient.objects.using(db).filter(uuid__in=patient_uuids)}

    created = 0
    for enc in encounters:
        due_date = enc.signed_at.date() + timedelta(days=enc.follow_up_in_days)
        if due_date != today:
            continue
        patient = patients.get(enc.patient_id)
        if not patient:
            continue
        body = "Reminder: your doctor recommended a follow-up visit around now. Please book an appointment when convenient."
        if _log_in_app(db, patient, f"followup:{enc.id}", body):
            created += 1
    return created


def run_for_tenant(db):
    """Runs every generator for one tenant DB, returns a {name: count} summary."""
    return {
        "appointment_reminders": generate_appointment_reminders(db),
        "followup_reminders": generate_followup_reminders(db),
    }
