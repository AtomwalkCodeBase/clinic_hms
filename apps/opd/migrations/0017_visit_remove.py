"""Phase 3 of 3: drop what the new design no longer keeps, and tighten what it requires.

- the patient is known by his id only (no uuid, no branch); an appointment, not its encounter or prescription, says who and which doctor
- a room's name and floor are read from the room; the check-in time and the prescription's dispensed time are gone
- the emergency record keeps only the registration facts (contact numbers belong to the shared patient record)
- the saved prescription templates live on the doctor's staff row
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0016_visit_data"),
        ("hospital_setup", "0012_places_profiles_remove"),
    ]

    operations = [
        # the appointment's patient column now holds the id
        migrations.RemoveIndex(model_name="appointment", name="appointment_patient_d94625_idx"),
        migrations.RemoveField(model_name="appointment", name="patient"),
        migrations.RenameField(model_name="appointment", old_name="patient_new", new_name="patient"),
        migrations.AlterField(
            model_name="appointment", name="patient",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="p_appointments", to="opd.hospitalpatient")),
        migrations.AddIndex(model_name="appointment", index=models.Index(fields=["patient", "scheduled_date"], name="appointment_patient_d94625_idx")),
        migrations.RemoveField(model_name="appointment", name="room_name"),
        migrations.RemoveField(model_name="appointment", name="floor"),
        migrations.RemoveField(model_name="appointment", name="checked_in_at"),
        # an encounter and a prescription belong to a visit, which knows the patient and the doctor
        migrations.RemoveIndex(model_name="opdencounter", name="opd_encount_doctor__e8f307_idx"),
        migrations.RemoveField(model_name="opdencounter", name="patient"),
        migrations.RemoveField(model_name="opdencounter", name="doctor"),
        migrations.RemoveField(model_name="prescription", name="patient"),
        migrations.RemoveField(model_name="prescription", name="doctor"),
        migrations.RemoveField(model_name="prescription", name="dispensed_at"),
        # the patient is known by id only
        migrations.RemoveField(model_name="hospitalpatient", name="uuid"),
        migrations.RemoveField(model_name="hospitalpatient", name="branch"),
        migrations.RemoveField(model_name="patientemergencyintake", name="mobile"),
        migrations.RemoveField(model_name="patientemergencyintake", name="guardian_name"),
        migrations.RemoveField(model_name="patientemergencyintake", name="guardian_mobile"),
        migrations.DeleteModel(name="PrescriptionFavourite"),
    ]
