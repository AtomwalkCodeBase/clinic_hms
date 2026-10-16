"""apps/opd/services.py"""

import logging

from apps.billing.services import recompute_invoice_totals, hospital_default_tax_rate

logger = logging.getLogger(__name__)


def resolve_doctor_consultation_fee(db, doctor_user_id, appointment_type=None):
    """encounter.doctor_user_id is a UUIDField, but the value actually stored"""
    import uuid as _uuid
    from apps.hospital_setup.models import StaffUser
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


def auto_generate_invoice(encounter, db, user, patient=None, hospital_id=None):
    """Create a draft invoice after encounter sign-off. Never blocks sign-off."""
    from decimal import Decimal
    from apps.billing.models import Invoice, InvoiceItem
    from apps.opd.models import HospitalPatient
    from apps.opd.models import Appointment
    from core.utils.nntm import get_next_number

    try:
        if patient is None:
            patient = HospitalPatient.objects.using(db).get(uuid=encounter.patient_id)

        appointment_type = getattr(encounter.appointment, "appointment_type", None)
        fee = resolve_doctor_consultation_fee(db, encounter.doctor_user_id, appointment_type)
        if fee is None:
            fee = Decimal("0")
        tax_rate = hospital_default_tax_rate(hospital_id)
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
