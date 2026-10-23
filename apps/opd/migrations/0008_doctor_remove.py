"""Phase 3 of 3: drop the UUID copies of the doctor, the doctor's name and the patient's awpid on the visit, and the visit's own branch."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0007_doctor_data"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="opdencounter", name="opd_encount_doctor__769594_idx"),
        migrations.RemoveIndex(model_name="appointment", name="appointment_schedul_446ce7_idx"),
        migrations.RemoveIndex(model_name="appointment", name="appointment_patient_d94625_idx"),
        migrations.RemoveConstraint(model_name="prescriptionfavourite", name="uniq_favourite_doctor_name"),
        migrations.RemoveField(model_name="appointment", name="patient_awpid"),
        migrations.RemoveField(model_name="appointment", name="doctor_user_id"),
        migrations.RemoveField(model_name="appointment", name="doctor_name"),
        migrations.RemoveField(model_name="appointment", name="branch"),
        migrations.RemoveField(model_name="opdencounter", name="doctor_user_id"),
        migrations.RemoveField(model_name="prescription", name="doctor_user_id"),
        migrations.RemoveField(model_name="prescriptionfavourite", name="doctor_user_id"),
        migrations.AlterField(
            model_name="appointment", name="doctor",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="u_appointments", to="hospital_setup.staffuser"),
        ),
        migrations.AlterField(
            model_name="appointment", name="branch_department",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bdp_appointments", to="hospital_setup.branchdepartment"),
        ),
        migrations.AlterField(
            model_name="opdencounter", name="doctor",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="u_encounters", to="hospital_setup.staffuser"),
        ),
        migrations.AlterField(
            model_name="prescription", name="doctor",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="u_prescriptions", to="hospital_setup.staffuser"),
        ),
        migrations.AlterField(
            model_name="prescriptionfavourite", name="doctor",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="u_favourites", to="hospital_setup.staffuser"),
        ),
        migrations.AddIndex(model_name="opdencounter", index=models.Index(fields=["doctor", "status"], name="opd_encount_doctor__e8f307_idx")),
        migrations.AddIndex(model_name="appointment", index=models.Index(fields=["scheduled_date", "doctor"], name="appointment_schedul_b70828_idx")),
        migrations.AddIndex(model_name="appointment", index=models.Index(fields=["patient", "scheduled_date"], name="appointment_patient_d94625_idx")),
        migrations.AddConstraint(
            model_name="prescriptionfavourite",
            constraint=models.UniqueConstraint(fields=("doctor", "name"), name="uniq_favourite_doctor_name"),
        ),
    ]
