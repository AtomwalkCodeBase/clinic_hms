from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0007_tenant_active_vaccination_schedule_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="fee_ownership",
            field=models.CharField(
                choices=[
                    ("doctor",   "Doctor self-configures"),
                    ("hospital", "Hospital controls"),
                ],
                default="doctor",
                max_length=10,
            ),
        ),
    ]
