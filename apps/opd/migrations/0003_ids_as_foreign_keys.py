import django.db.models.deletion
from django.db import migrations, models


def check_and_tidy(apps, schema_editor):
    db = schema_editor.connection.alias
    Appointment = apps.get_model("opd", "Appointment")
    Allergy = apps.get_model("opd", "Allergy")
    HospitalPatient = apps.get_model("opd", "HospitalPatient")
    OPDEncounter = apps.get_model("opd", "OPDEncounter")
    Prescription = apps.get_model("opd", "Prescription")
    Branch = apps.get_model("hospital_setup", "Branch")
    Room = apps.get_model("hospital_setup", "Room")
    StaffUser = apps.get_model("hospital_setup", "StaffUser")

    Appointment.objects.using(db).exclude(branch_id__in=Branch.objects.using(db).values("id")).filter(branch_id__isnull=False).update(branch_id=None)
    Appointment.objects.using(db).exclude(room_id__in=Room.objects.using(db).values("id")).filter(room_id__isnull=False).update(room_id=None)
    Allergy.objects.using(db).exclude(recorded_by__in=StaffUser.objects.using(db).values("id")).filter(recorded_by__isnull=False).update(recorded_by=None)

    known = set(HospitalPatient.objects.using(db).values_list("uuid", flat=True))
    lost = [str(pk) for model in (OPDEncounter, Prescription)
            for pk in model.objects.using(db).values_list("patient_id", flat=True) if pk not in known]
    if lost:
        raise RuntimeError(f"{len(lost)} encounter or prescription rows point at a patient that does not exist in {db}; fix or remove them first.")
    seen, twice = set(), set()
    for awpid in HospitalPatient.objects.using(db).values_list("awpid", flat=True):
        (twice if awpid in seen else seen).add(awpid)
    if twice:
        raise RuntimeError(f"These awpids are registered twice in {db}: {sorted(twice)[:5]}. Merge the duplicate patients first.")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("opd", "0002_initial"),
        ("hospital_setup", "0004_hygiene_and_integrity"),
    ]

    operations = [
        migrations.RunPython(check_and_tidy, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="opdencounter", name="opd_encount_patient_fa14c2_idx"),
        migrations.RemoveIndex(model_name="prescription", name="opd_prescri_patient_7eb5c3_idx"),
        migrations.RemoveIndex(model_name="prescription", name="opd_prescri_rx_numb_474241_idx"),

        migrations.AlterField(model_name="appointment", name="branch_id", field=models.IntegerField(blank=True, null=True)),
        migrations.RenameField(model_name="appointment", old_name="branch_id", new_name="branch"),
        migrations.AlterField(
            model_name="appointment", name="branch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="appointments", to="hospital_setup.branch"),
        ),
        migrations.AlterField(model_name="appointment", name="room_id", field=models.IntegerField(blank=True, null=True)),
        migrations.RenameField(model_name="appointment", old_name="room_id", new_name="room"),
        migrations.AlterField(
            model_name="appointment", name="room",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="appointments", to="hospital_setup.room"),
        ),
        migrations.RemoveField(model_name="appointment", name="booked_by_user_id"),

        migrations.AlterField(model_name="opdencounter", name="patient_id", field=models.UUIDField()),
        migrations.RenameField(model_name="opdencounter", old_name="patient_id", new_name="patient"),
        migrations.AlterField(
            model_name="opdencounter", name="patient",
            field=models.ForeignKey(db_column="patient_id", on_delete=django.db.models.deletion.PROTECT, related_name="encounters", to="opd.hospitalpatient", to_field="uuid"),
        ),
        migrations.RemoveField(model_name="opdencounter", name="ai_transcript_job_id"),
        migrations.RemoveField(model_name="opdencounter", name="ai_transcript_text"),

        migrations.AlterField(model_name="prescription", name="patient_id", field=models.UUIDField()),
        migrations.RenameField(model_name="prescription", old_name="patient_id", new_name="patient"),
        migrations.AlterField(
            model_name="prescription", name="patient",
            field=models.ForeignKey(db_column="patient_id", on_delete=django.db.models.deletion.PROTECT, related_name="prescriptions", to="opd.hospitalpatient", to_field="uuid"),
        ),
        migrations.RemoveField(model_name="prescriptionitem", name="is_controlled"),

        migrations.AlterField(model_name="hospitalpatient", name="awpid", field=models.CharField(max_length=30, unique=True)),
        migrations.AlterField(
            model_name="allergy", name="recorded_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="allergies_recorded", to="hospital_setup.staffuser"),
        ),
    ]
