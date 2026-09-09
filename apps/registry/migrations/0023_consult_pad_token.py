from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registry', '0022_emergencyaccesslog_consent_confirmed'),
    ]

    operations = [
        migrations.AddField(
            model_name='patientidentity',
            name='consult_pad_token',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='patientidentity',
            name='consult_pad_owner_tenant_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='shareddocument',
            name='doc_type',
            field=models.CharField(
                choices=[
                    ('lab_report', 'Lab Report'),
                    ('prescription', 'Prescription'),
                    ('scan', 'Scan / Imaging'),
                    ('discharge_summary', 'Discharge Summary'),
                    ('consult_note', 'Consultation Note'),
                    ('other', 'Other'),
                ],
                default='other',
                max_length=20,
            ),
        ),
    ]
