from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0002_seed_default_schedules"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicaldocument",
            name="doctor_name",
            field=models.CharField(blank=True, default="", max_length=60),
        ),
    ]
