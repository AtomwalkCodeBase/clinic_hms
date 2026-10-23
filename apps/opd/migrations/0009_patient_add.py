"""Phase 1 of 3: the tables for what only this hospital knows about a patient (payer, registration details, emergency intake)."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0008_doctor_remove"),
    ]

    operations = [
        migrations.CreateModel(
            name="PatientPayer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payer_type", models.CharField(choices=[("self", "Self Pay"), ("insurance", "Insurance"), ("corporate", "Corporate")], default="self", max_length=20)),
                ("insurance_provider", models.CharField(blank=True, max_length=200)),
                ("policy_number", models.CharField(blank=True, max_length=100)),
                ("tpa_name", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("patient", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="p_payer", to="opd.hospitalpatient")),
            ],
            options={"db_table": "patient_payer"},
        ),
        migrations.CreateModel(
            name="PatientDetail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alternate_mobile", models.CharField(blank=True, max_length=15)),
                ("address_line1", models.CharField(blank=True, max_length=255)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=100)),
                ("pincode", models.CharField(blank=True, max_length=10)),
                ("marital_status", models.CharField(blank=True, max_length=20)),
                ("nationality", models.CharField(blank=True, default="Indian", max_length=50)),
                ("occupation", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("patient", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="p_detail", to="opd.hospitalpatient")),
            ],
            options={"db_table": "patient_detail"},
        ),
        migrations.CreateModel(
            name="PatientEmergencyIntake",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("identity_status", models.CharField(choices=[("confirmed", "Confirmed"), ("provisional", "Provisional")], default="provisional", max_length=12)),
                ("is_mlc", models.BooleanField(default=False)),
                ("arrival_channel", models.CharField(blank=True, choices=[("ambulance", "Ambulance"), ("brought_in", "Brought in"), ("police_case", "Police case"), ("walk_in_unresponsive", "Walk-in, unresponsive"), ("other", "Other")], max_length=25)),
                ("placeholder_label", models.CharField(blank=True, max_length=200)),
                ("consent_deferred_reason", models.CharField(blank=True, max_length=255)),
                ("mobile", models.CharField(blank=True, max_length=15)),
                ("guardian_name", models.CharField(blank=True, max_length=200)),
                ("guardian_mobile", models.CharField(blank=True, max_length=15)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("patient", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="p_emergency_intake", to="opd.hospitalpatient")),
            ],
            options={"db_table": "patient_emergency_intake"},
        ),
    ]
