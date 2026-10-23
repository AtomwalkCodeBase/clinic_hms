"""The audit log's patient column holds a UHID (the opd migrations have replaced the old uuids), so it shrinks to the UHID's length."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0012_places_profiles_remove"),
        ("opd", "0016_visit_data"),
    ]

    operations = [
        migrations.AlterField(model_name="auditlog", name="patient_id", field=models.CharField(blank=True, max_length=20, null=True)),
    ]
