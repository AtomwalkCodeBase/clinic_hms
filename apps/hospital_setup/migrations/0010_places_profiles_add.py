"""Phase 1 of 3: add what the new design needs, next to what it replaces.

- a primary flag on a staff member's places of work, and a schedule that belongs to such a place
- the profile columns on the staff row, the extra roles as a plain many-to-many, the doctor's saved prescription templates
- audit-log patient ids as text, wide enough to hold the old UUIDs until the opd migrations turn them into UHIDs
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0009_structure_remove"),
    ]

    operations = [
        migrations.AddField(model_name="staffbranchdepartment", name="is_primary", field=models.BooleanField(default=False)),
        migrations.AddField(
            model_name="doctorschedule",
            name="staff_branch_department",
            field=models.OneToOneField(
                null=True, limit_choices_to={"staff__group__system_role_key": "doctor"}, on_delete=django.db.models.deletion.CASCADE,
                related_name="sbd_schedule", to="hospital_setup.staffbranchdepartment"),
        ),
        migrations.AddField(model_name="doctorschedule", name="weekly_hours", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="staffuser", name="registration_no", field=models.CharField(blank=True, max_length=50)),
        migrations.AddField(model_name="staffuser", name="council_name", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="staffuser", name="registration_expiry", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="staffuser", name="qualification", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="staffuser", name="experience_years", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="staffuser", name="specialisation", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(
            model_name="staffuser", name="consultation_fee", field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
        migrations.AddField(
            model_name="staffuser", name="followup_fee", field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
        migrations.AddField(model_name="staffuser", name="digital_signature", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="staffuser", name="known_for", field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(
            model_name="staffuser", name="gender",
            field=models.CharField(blank=True, choices=[("M", "Male"), ("F", "Female"), ("O", "Other")], max_length=1)),
        migrations.AddField(model_name="staffuser", name="bio", field=models.TextField(blank=True)),
        migrations.AddField(model_name="staffuser", name="languages", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="staffuser", name="extra", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="staffuser", name="prescription_favourites", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(
            model_name="staffuser", name="extra_roles",
            field=models.ManyToManyField(blank=True, related_name="ro_extra_staff", to="hospital_setup.role")),
        migrations.AlterField(model_name="auditlog", name="patient_id", field=models.CharField(blank=True, max_length=40, null=True)),
    ]
