# Metadata-only migration — choices= on OptionList.list_type is part of
# Django's migration state even though it isn't a DB-level CHECK
# constraint (see OptionList docstring: "validated at the view layer, so a
# hospital can extend it"). No schema change; keeps makemigrations quiet
# after apps/ipd added the two new LIST_ADMISSION_* constants.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0009_remove_old_option_tables"),
    ]

    operations = [
        migrations.AlterField(
            model_name="optionlist",
            name="list_type",
            field=models.CharField(
                choices=[
                    ("service_category", "Service Category"),
                    ("payment_mode", "Payment Mode"),
                    ("invoice_status", "Invoice Status"),
                    ("drug_form", "Drug Form"),
                    ("admission_type", "Admission Type"),
                    ("admission_source", "Admission Source"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
