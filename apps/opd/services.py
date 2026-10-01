"""
apps/opd/services.py
--------------------
OPD billing rules used when an encounter is signed. Moved out of opd/views.py, which the seed
commands had to import underscore-prefixed functions from.
"""

import logging

from apps.billing.services import recompute_invoice_totals, tenant_default_tax_rate

logger = logging.getLogger(__name__)


def resolve_doctor_consultation_fee(db, doctor_user_id, appointment_type=None):
    """
    encounter.doctor_user_id is a UUIDField, but the value actually stored
    in it is the StaffUser's plain integer pk — Django's UUIDField silently
    wraps a plain int via uuid.UUID(int=value) (see e.g. auth_app.views'
    "user_id": staff.id, saved straight into these UUID columns). Unwrap
    either form back to the integer pk so DoctorProfile can be looked up.

    For a "followup" visit, prefers DoctorProfile.followup_fee — but only
    if the doctor actually set one; otherwise falls back to their regular
    consultation_fee, so doctors who never configured a separate follow-up
    rate keep charging the same flat fee for every visit type (unchanged
    behaviour for them). Returns None if there's no doctor profile or no
    fee resolvable at all.
    """
    import uuid as _uuid
    from apps.org.models import StaffUser
    from apps.opd.models import Appointment

    raw = doctor_user_id.int if isinstance(doctor_user_id, _uuid.UUID) else doctor_user_id
    try:
        staff = StaffUser.objects.using(db).select_related("doctor_profile").get(pk=raw)
        profile = staff.doctor_profile
        if appointment_type == Appointment.TYPE_FOLLOWUP and profile.followup_fee is not None:
            return profile.followup_fee
        return profile.consultation_fee
    except Exception:
        return None


def auto_generate_invoice(encounter, db, user, patient=None, tenant_id=None):
    """
    Create a draft invoice after encounter sign-off. Never blocks sign-off.

    Uses the doctor's actual DoctorProfile fee (falls back to ₹0 — not a
    guessed flat amount — if the doctor never set one) and the tenant's
    configured default_tax_rate, instead of the old hardcoded ₹500.

    Picks consultation_fee vs followup_fee based on the appointment's
    appointment_type (see resolve_doctor_consultation_fee), and labels the
    invoice line accordingly — so a follow-up visit is no longer charged
    and described identically to a first consultation.
    """
    from decimal import Decimal
    from apps.billing.models import Invoice, InvoiceItem
    from apps.patients.models import Patient
    from apps.opd.models import Appointment
    from core.utils.nntm import get_next_number

    try:
        if patient is None:
            patient = Patient.objects.using(db).get(uuid=encounter.patient_id)

        appointment_type = getattr(encounter.appointment, "appointment_type", None)
        fee = resolve_doctor_consultation_fee(db, encounter.doctor_user_id, appointment_type)
        if fee is None:
            fee = Decimal("0")
        tax_rate = tenant_default_tax_rate(tenant_id)
        description = (
            "Follow-up Consultation" if appointment_type == Appointment.TYPE_FOLLOWUP
            else "OPD Consultation"
        )

        invoice_number, _ = get_next_number(branch_id=patient.branch_id or 1, entity="invoice", using=db)
        invoice = Invoice.objects.using(db).create(
            patient=patient,
            branch=patient.branch,
            invoice_number=invoice_number,
            status="draft",
            created_by_id=user.id,
            notes=f"Auto-generated for OPD encounter {encounter.id}",
        )
        InvoiceItem.objects.using(db).create(
            invoice=invoice,
            description=description,
            quantity=1,
            unit_price=fee,
            tax_rate=tax_rate,
            total=fee,
        )
        recompute_invoice_totals(invoice, db)
        logger.info("Auto-generated invoice %s for encounter %s (type=%s, fee=%s, tax_rate=%s%%)",
                    invoice.invoice_number, encounter.id, appointment_type, fee, tax_rate)
    except Exception as e:
        logger.warning("Could not auto-generate invoice: %s", e)
