from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0012_patient_detail_to_shared"),
    ]

    operations = [
        migrations.DeleteModel(name="PatientDetail"),
    ]
