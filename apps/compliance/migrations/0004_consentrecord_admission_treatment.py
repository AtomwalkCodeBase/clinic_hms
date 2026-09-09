# Metadata-only migration — adds the admission_treatment choice used by
# apps.ipd.views.CompleteAdmissionView. No schema change.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compliance", "0003_consentrecord_delete_accesslog"),
    ]

    operations = [
        migrations.AlterField(
            model_name="consentrecord",
            name="consent_type",
            field=models.CharField(
                choices=[
                    ("dpdp_data_processing", "DPDP — Personal Data Processing"),
                    ("hie_data_sharing", "HIE — Cross-Hospital Data Sharing"),
                    ("admission_treatment", "Admission — Consent to Inpatient Treatment"),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
    ]
