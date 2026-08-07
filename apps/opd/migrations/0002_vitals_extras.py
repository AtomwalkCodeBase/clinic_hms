"""
Migration: 0002_vitals_extras
Add blood_sugar_rbs (random blood sugar) and nurse_notes to Vitals.
Also aligns Appointment.status max_length to accommodate "vitals_done".
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="vitals",
            name="blood_sugar_rbs",
            field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="vitals",
            name="nurse_notes",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
