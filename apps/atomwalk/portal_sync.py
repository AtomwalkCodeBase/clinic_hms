"""
apps/atomwalk/portal_sync.py
-----------------------------
Keeps the atomwalk-DB PatientBooking ledger (what powers a patient's "My
Bookings"/Dashboard in the portal) in sync with Appointment rows created
OUTSIDE the patient portal itself — front desk, nurse, or any other staff
booking flow (apps.opd.views.AppointmentListCreateView.post).

Why this exists: PortalMyBookingsView reads exclusively from PatientBooking,
never from a live cross-hospital scan of every hospital's Appointment table
(that would mean querying every hospital DB on every dashboard load). Until
now, only the patient-initiated booking flow (PortalBookView.post) wrote a
PatientBooking row — a walk-in booked by front desk created a perfectly good
Appointment, but the patient logging into their portal afterward would never
see it, because nothing had ever written the atomwalk-side row that lets the
portal find it. This is the fix: call sync_patient_booking() right after any
non-portal Appointment.create(), and it becomes visible the same way a
portal-made booking always was.
"""
import logging

logger = logging.getLogger(__name__)


def sync_patient_booking(appointment, db_name):
    """
    Best-effort — booking must never fail because this couldn't run. If
    neither the booked patient nor (for a dependent) their guardian has ever
    created a patient portal account, there's genuinely nothing to sync to;
    that's the normal case for most front-desk walk-ins, not an error.
    """
    try:
        from apps.atomwalk.models import Patient, PatientAccount, PatientRelationship, PatientBooking
        from apps.hospitals.models import Hospital

        patient_awpid = (appointment.patient_awpid or "").strip()
        if not patient_awpid:
            return

        # Already synced? (e.g. this Appointment was actually created via the
        # portal's own booking view, which writes its PatientBooking inline —
        # avoid a duplicate row if this ever gets called from both places.)
        if PatientBooking.objects.using("default").filter(appointment_id=appointment.id).exists():
            return

        acct = PatientAccount.objects.using("default").filter(awpid=patient_awpid).first()
        if not acct:
            # Not the account owner themself — maybe a dependent, in which
            # case the booking should show up on the GUARDIAN's dashboard
            # (same as when a patient books a family member through the
            # portal directly — see PortalBookView.post).
            rel = PatientRelationship.objects.using("default").filter(
                dependent__awpid=patient_awpid
            ).first()
            if rel:
                acct = PatientAccount.objects.using("default").filter(awpid=rel.guardian_awpid).first()

        if not acct:
            return  # no portal account anywhere in this chain — nothing to sync

        hospital = Hospital.objects.using("default").filter(db_name=db_name).first()
        if not hospital:
            return

        PatientBooking.objects.using("default").create(
            booked_by=acct,
            hospital=hospital,
            appointment_id=appointment.id,
            doctor_name=appointment.doctor_name or "",
            scheduled_date=appointment.scheduled_date,
            chief_complaint=appointment.chief_complaint or "",
            status=appointment.status,
            patient=Patient.objects.using("default").filter(awpid=patient_awpid).first(),
        )
    except Exception:
        # Same graceful-degradation pattern as core.audit.log_action — a
        # booking that already succeeded in the hospital DB must not fail (or
        # roll back) just because this best-effort portal-visibility sync hit
        # an unexpected error.
        logger.warning("sync_patient_booking failed for appointment_id=%s db=%s", appointment.id, db_name, exc_info=True)
