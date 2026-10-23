"""Phase 1 of 3: an appointment gets its patient by the patient's own id (the uuid column it used is going away)."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0014_protect_history_and_item_checks"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="patient_new",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="opd.hospitalpatient"),
        ),
    ]
