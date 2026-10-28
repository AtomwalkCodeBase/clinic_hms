"""Every hospital database starts with the system dropdown lists: service categories, payment modes, invoice statuses, room types and appointment types."""
from django.db import migrations

OPTIONS = [   # list_type, value, label
    ("service_category", "Consultation", "Consultation"),
    ("service_category", "Procedure", "Procedure"),
    ("service_category", "Other", "Other"),
    ("payment_mode", "Cash", "Cash"),
    ("payment_mode", "Card", "Card"),
    ("payment_mode", "UPI", "UPI"),
    ("payment_mode", "Online", "Online"),
    ("payment_mode", "Credit", "Credit"),
    ("invoice_status", "draft", "Draft"),
    ("invoice_status", "issued", "Issued"),
    ("invoice_status", "paid", "Paid"),
    ("invoice_status", "partially_paid", "Partially Paid"),
    ("invoice_status", "cancelled", "Cancelled"),
    ("room_type", "consultation", "Consultation"),
    ("room_type", "procedure", "Procedure"),
    ("room_type", "other", "Other"),
    ("appointment_type", "opd", "OPD"),
    ("appointment_type", "followup", "Follow-up"),
    ("appointment_type", "emergency", "Emergency"),
]


def seed(apps, schema_editor):
    OptionList = apps.get_model("hospital_setup", "OptionList")
    db = schema_editor.connection.alias
    for order, (list_type, value, label) in enumerate(OPTIONS):
        OptionList.objects.using(db).get_or_create(
            list_type=list_type, value=value, defaults={"label": label, "is_system": True, "is_active": True, "sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("hospital_setup", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
