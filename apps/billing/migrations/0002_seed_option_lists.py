"""Every hospital database starts with the system option lists: service categories, payment modes, invoice statuses,
room types, admission types and sources, appointment types and lab sample types."""
from decimal import Decimal

from django.db import migrations

OPTIONS = [   # list_type, value, label, sort_order, category, is_bed_based, daily_rate
    ('service_category', 'Consultation', 'Consultation', 0, '', False, None),
    ('service_category', 'Procedure', 'Procedure', 1, '', False, None),
    ('service_category', 'Lab', 'Lab', 2, '', False, None),
    ('service_category', 'Pharmacy', 'Pharmacy', 3, '', False, None),
    ('service_category', 'Room / Bed', 'Room / Bed', 4, '', False, None),
    ('service_category', 'Other', 'Other', 5, '', False, None),
    ('payment_mode', 'Cash', 'Cash', 0, '', False, None),
    ('payment_mode', 'Card', 'Card', 1, '', False, None),
    ('payment_mode', 'UPI', 'UPI', 2, '', False, None),
    ('payment_mode', 'Online', 'Online', 3, '', False, None),
    ('payment_mode', 'Credit', 'Credit', 4, '', False, None),
    ('invoice_status', 'draft', 'Draft', 0, '', False, None),
    ('invoice_status', 'issued', 'Issued', 1, '', False, None),
    ('invoice_status', 'paid', 'Paid', 2, '', False, None),
    ('invoice_status', 'partially_paid', 'Partially Paid', 3, '', False, None),
    ('invoice_status', 'cancelled', 'Cancelled', 4, '', False, None),
    ('admission_type', 'emergency', 'Emergency', 0, '', False, None),
    ('admission_type', 'urgent', 'Urgent', 1, '', False, None),
    ('admission_type', 'elective', 'Elective', 2, '', False, None),
    ('admission_type', 'day_care', 'Day Care', 3, '', False, None),
    ('admission_type', 'newborn', 'Newborn', 4, '', False, None),
    ('admission_source', 'opd_consultation', 'OPD Consultation', 0, '', False, None),
    ('admission_source', 'external_referral', 'External Referral', 1, '', False, None),
    ('admission_source', 'walk_in', 'Walk-in', 2, '', False, None),
    ('admission_source', 'direct_order', 'Direct / Physician Order', 3, '', False, None),
    ('admission_source', 'transfer_in', 'Transfer-in', 4, '', False, None),
    ('admission_source', 'ambulance_ems', 'Ambulance / EMS', 5, '', False, None),
    ('admission_source', 'tpa_cashless', 'Insurance / TPA-coordinated', 6, '', False, None),
    ('admission_source', 'medical_tourism', 'Medical Tourism', 7, '', False, None),
    ('admission_source', 'telemedicine', 'Telemedicine', 8, '', False, None),
    ('admission_source', 'involuntary_mlc', 'Involuntary / MLC', 9, '', False, None),
    ('room_type', 'consultation', 'Consultation', 0, 'opd', False, None),
    ('room_type', 'procedure', 'Procedure', 1, 'opd', False, None),
    ('room_type', 'other', 'Other', 2, 'other', False, None),
    ('room_type', 'general', 'General', 100, 'ipd', True, None),
    ('room_type', 'private', 'Private', 101, 'ipd', True, None),
    ('room_type', 'semi_private', 'Semi-Private', 102, 'ipd', True, None),
    ('room_type', 'icu', 'ICU', 103, 'ipd', True, None),
    ('room_type', 'hdu', 'HDU', 104, 'ipd', True, None),
    ('room_type', 'isolation', 'Isolation', 105, 'ipd', True, None),
    ('room_type', 'ward_other', 'Other (Ward)', 106, 'ipd', True, None),
    ('sample_type', 'blood', 'Blood', 0, '', False, None),
    ('sample_type', 'urine', 'Urine', 1, '', False, None),
    ('sample_type', 'stool', 'Stool', 2, '', False, None),
    ('sample_type', 'sputum', 'Sputum', 3, '', False, None),
    ('sample_type', 'swab', 'Swab', 4, '', False, None),
    ('sample_type', 'other', 'Other', 5, '', False, None),
    ('appointment_type', 'opd', 'OPD', 0, '', False, None),
    ('appointment_type', 'followup', 'Follow-up', 1, '', False, None),
    ('appointment_type', 'emergency', 'Emergency', 2, '', False, None),
]


def seed(apps, schema_editor):
    OptionList = apps.get_model("billing", "OptionList")
    for list_type, value, label, order, category, bed_based, rate in OPTIONS:
        OptionList.objects.using(schema_editor.connection.alias).get_or_create(
            list_type=list_type, value=value,
            defaults={"label": label, "is_system": True, "is_active": True, "sort_order": order, "category": category,
                      "is_bed_based": bed_based, "daily_rate": Decimal(rate) if rate is not None else None})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
