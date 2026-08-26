"""
apps/registry/portal_sync.py
-----------------------------
Keeps the registry-DB PortalBooking ledger (what powers a patient's "My
Bookings"/Dashboard in the portal) in sync with Appointment rows created
OUTSIDE the patient portal itself — front desk, nurse, or any other staff
booking flow (apps.opd.views.AppointmentListCreateView.post).

Why this exists: PortalMyBookingsView reads exclusively from PortalBooking,
never from a live cross-tenant scan of every hospital's Appointment table
(that would mean querying every tenant DB on every dashboard load). Until
now, only the patient-initiated booking flow (PortalBookView.post) wrote a
PortalBooking row — a walk-in booked by front desk created a perfectly good
Appointment, but the patient logging into their portal afterward would never
see it, because nothing had ever written the registry-side row that lets the
portal find it. This is the fix: call sync_portal_booking() right after any
non-portal Appointment.create(), and it becomes visible the same way a
portal-made booking always was.
"""
import logging

logger = logging.getLogger(__name__)


def sync_portal_booking(appointment, db_name):
    """
    Best-effort — booking must never fail because this couldn't run. If
    neither the booked patient nor (for a dependent) their guardian has ever
    created a patient portal account, there's genuinely nothing to sync to;
    that's the normal case for most front-desk walk-ins, not an error.
    """
    try:
        from apps.registry.models import PatientAccount, PatientRelationship, PortalBooking
        from apps.tenants.models import Tenant
        from apps.patients.models import Patient

        patient_awpid = (appointment.patient_awpid or "").strip()
        if not patient_awpid:
            return

        # Already synced? (e.g. this Appointment was actually created via the
        # portal's own booking view, which writes its PortalBooking inline —
        # avoid a duplicate row if this ever gets called from both places.)
        if PortalBooking.objects.using("default").filter(appointment_id=appointment.id).exists():
            return

        acct = PatientAccount.objects.using("default").filter(awpid=patient_awpid).first()
        if not acct:
            # Not the account owner themself — maybe a dependent, in which
            # case the booking should show up on the GUARDIAN's dashboard
            # (same as when a patient books a family member through the
            # portal directly — see PortalBookView.post).
            rel = PatientRelationship.objects.using("default").filter(
                dependent_awpid=patient_awpid
            ).first()
            if rel:
                acct = PatientAccount.objects.using("default").filter(awpid=rel.guardian_awpid).first()

        if not acct:
            return  # no portal account anywhere in this chain — nothing to sync

        tenant = Tenant.objects.using("default").filter(db_name=db_name).first()
        if not tenant:
            return

        patient = Patient.objects.using(db_name).filter(awpid=patient_awpid).first()
        patient_name = patient.full_name if patient else ""

        PortalBooking.objects.using("default").create(
            account=acct,
            tenant_id=tenant.id,
            db_name=db_name,
            hospital_name=tenant.name,
            appointment_id=appointment.id,
            doctor_name=appointment.doctor_name or "",
            scheduled_date=appointment.scheduled_date,
            chief_complaint=appointment.chief_complaint or "",
            status=appointment.status,
            patient_awpid=patient_awpid,
            patient_name=patient_name,
        )
    except Exception:
        # Same graceful-degradation pattern as core.audit.log_action — a
        # booking that already succeeded in the tenant DB must not fail (or
        # roll back) just because this best-effort portal-visibility sync hit
        # an unexpected error.
        logger.warning("sync_portal_booking failed for appointment_id=%s db=%s", appointment.id, db_name, exc_info=True)
