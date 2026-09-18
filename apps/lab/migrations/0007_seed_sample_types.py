# Seeds billing.OptionList(list_type="sample_type") with the six values
# LabTest.sample_type used to enforce via a fixed choices= list, as
# is_system=True defaults — a hospital can deactivate one it never uses but
# not delete it, and can add its own (e.g. "tissue", "csf") alongside them.
# Same pattern as apps/ipd/migrations/0002_seed_admission_catalogs.py.

from django.db import migrations

SAMPLE_TYPES = [
    ("blood",  "Blood"),
    ("urine",  "Urine"),
    ("stool",  "Stool"),
    ("sputum", "Sputum"),
    ("swab",   "Swab"),
    ("other",  "Other"),
]


def seed_sample_types(apps, schema_editor):
    OptionList = apps.get_model("billing", "OptionList")
    db = schema_editor.connection.alias
    for i, (value, label) in enumerate(SAMPLE_TYPES):
        OptionList.objects.using(db).get_or_create(
            list_type="sample_type", value=value,
            defaults={"label": label, "is_active": True, "is_system": True, "sort_order": i},
        )


def unseed_sample_types(apps, schema_editor):
    OptionList = apps.get_model("billing", "OptionList")
    db = schema_editor.connection.alias
    OptionList.objects.using(db).filter(list_type="sample_type").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("lab", "0006_alter_labtest_sample_type"),
        ("billing", "0019_alter_optionlist_list_type"),
    ]

    operations = [
        migrations.RunPython(seed_sample_types, unseed_sample_types),
    ]
