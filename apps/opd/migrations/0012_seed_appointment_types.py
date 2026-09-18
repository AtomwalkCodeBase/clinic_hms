# Seeds billing.OptionList(list_type="appointment_type") with the three
# values Appointment.appointment_type used to enforce via a fixed choices=
# list, as is_system=True defaults — backend logic (see views.py's
# _resolve_doctor_consultation_fee) branches on "followup" specifically, so
# these three stay protected; a hospital can add its own (e.g.
# "teleconsult") alongside them. Same pattern as
# apps/ipd/migrations/0002_seed_admission_catalogs.py.

from django.db import migrations

APPOINTMENT_TYPES = [
    ("opd",       "OPD"),
    ("followup",  "Follow-up"),
    ("emergency", "Emergency"),
]


def seed_appointment_types(apps, schema_editor):
    OptionList = apps.get_model("billing", "OptionList")
    db = schema_editor.connection.alias
    for i, (value, label) in enumerate(APPOINTMENT_TYPES):
        OptionList.objects.using(db).get_or_create(
            list_type="appointment_type", value=value,
            defaults={"label": label, "is_active": True, "is_system": True, "sort_order": i},
        )


def unseed_appointment_types(apps, schema_editor):
    OptionList = apps.get_model("billing", "OptionList")
    db = schema_editor.connection.alias
    OptionList.objects.using(db).filter(list_type="appointment_type").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0011_alter_appointment_appointment_type"),
        ("billing", "0019_alter_optionlist_list_type"),
    ]

    operations = [
        migrations.RunPython(seed_appointment_types, unseed_appointment_types),
    ]
