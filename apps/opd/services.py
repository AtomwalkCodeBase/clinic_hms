"""apps/opd/services.py"""

import logging

from apps.billing.services import line_from_request, recompute_invoice_totals, hospital_default_tax_rate

logger = logging.getLogger(__name__)


def resolve_doctor_consultation_fee(db, doctor_id, appointment_type=None):
    """The fee the doctor's profile sets for this kind of visit (a follow-up fee when there is one), or None when no fee is set."""
    from apps.hospital_setup.models import StaffUser
    from apps.opd.models import Appointment

    doctor = StaffUser.objects.using(db).filter(pk=doctor_id).first()
    if doctor is None:
        return None
    if appointment_type == Appointment.TYPE_FOLLOWUP and doctor.followup_fee is not None:
        return doctor.followup_fee
    return doctor.consultation_fee


def auto_generate_invoice(encounter, db, user, patient=None, hospital_id=None):
    """Create a draft invoice after encounter sign-off. Never blocks sign-off."""
    from decimal import Decimal
    from apps.billing.models import Invoice
    from apps.opd.models import Appointment
    from apps.hospital_setup.models import NextNumber

    try:
        appointment = encounter.appointment
        if patient is None:
            patient = appointment.patient
        branch = appointment.branch_department.branch

        appointment_type = appointment.appointment_type
        fee = resolve_doctor_consultation_fee(db, appointment.doctor_id, appointment_type)
        if fee is None:
            fee = Decimal("0")
        tax_rate = hospital_default_tax_rate(hospital_id)
        description = (
            "Follow-up Consultation" if appointment_type == Appointment.TYPE_FOLLOWUP
            else "OPD Consultation"
        )

        invoice_number, _ = NextNumber.next(branch.pk, "invoice", db)
        invoice = Invoice.objects.using(db).create(
            patient=patient,
            branch=branch,
            invoice_number=invoice_number,
            status="draft",
            created_by_id=user.pk,
            notes=f"Auto-generated for OPD encounter {encounter.pk}",
            lines=[line_from_request({"description": description, "quantity": 1, "unit_price": fee, "tax_rate": tax_rate})],
        )
        recompute_invoice_totals(invoice, db)
        logger.info("Auto-generated invoice %s for encounter %s (type=%s, fee=%s, tax_rate=%s%%)",
                    invoice.invoice_number, encounter.pk, appointment_type, fee, tax_rate)
    except Exception as e:
        logger.warning("Could not auto-generate invoice: %s", e)
