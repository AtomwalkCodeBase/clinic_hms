# Generated for Option 1 + laptop binding on Share Records.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registry', '0029_recordssharerequest_code_attempts'),
    ]

    operations = [
        migrations.AddField(
            model_name='recordssharerequest',
            name='opened_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='recordssharerequest',
            name='device_hash',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='recordssharerequest',
            name='pairing',
            field=models.CharField(blank=True, max_length=12),
        ),
    ]
