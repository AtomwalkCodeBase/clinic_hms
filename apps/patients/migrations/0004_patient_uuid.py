"""
Migration: 0004_patient_uuid
Add uuid field to Patient for cross-model referencing.
Used as patient_id in Appointment, OPDEncounter, Prescription, etc.
"""

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0003_patient_extended_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="patient",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
    ]
