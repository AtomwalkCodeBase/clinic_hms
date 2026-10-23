"""Phase 1 of 3: the doctor as a link to the staff table, and the place of the visit as a branch_department, beside the old columns."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0009_structure_remove"),
        ("opd", "0005_prefixed_related_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="doctor",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="u_appointments", to="hospital_setup.staffuser"),
        ),
        migrations.AddField(
            model_name="appointment",
            name="branch_department",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="bdp_appointments", to="hospital_setup.branchdepartment"),
        ),
        migrations.AddField(
            model_name="opdencounter",
            name="doctor",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="u_encounters", to="hospital_setup.staffuser"),
        ),
        migrations.AddField(
            model_name="prescription",
            name="doctor",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="u_prescriptions", to="hospital_setup.staffuser"),
        ),
        migrations.AddField(
            model_name="prescriptionfavourite",
            name="doctor",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="u_favourites", to="hospital_setup.staffuser"),
        ),
    ]
