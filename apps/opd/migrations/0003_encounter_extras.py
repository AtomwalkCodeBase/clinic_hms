"""
Migration: 0003_encounter_extras
Add structured clinical fields to OPDEncounter:
  - investigations   : free-text lab/radiology orders
  - advice_to_patient: discharge instructions / patient advice
  - follow_up_in_days: days until follow-up visit
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0002_vitals_extras"),
    ]

    operations = [
        migrations.AddField(
            model_name="opdencounter",
            name="investigations",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="opdencounter",
            name="advice_to_patient",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="opdencounter",
            name="follow_up_in_days",
            field=models.IntegerField(null=True, blank=True),
        ),
    ]
