"""Phase 2 of 3: carry the data across.

- every appointment points at its patient by id
- a doctor's saved prescription templates move onto the doctor's staff row
- the audit log keeps the patient's UHID instead of the old uuid (an id that matches no patient becomes empty)
"""
from django.db import migrations


def forward(apps, schema_editor):
    db = schema_editor.connection.alias
    HospitalPatient = apps.get_model("opd", "HospitalPatient")
    Appointment = apps.get_model("opd", "Appointment")
    PrescriptionFavourite = apps.get_model("opd", "PrescriptionFavourite")
    StaffUser = apps.get_model("hospital_setup", "StaffUser")
    AuditLog = apps.get_model("hospital_setup", "AuditLog")

    uhid_of_uuid = {}
    for patient in HospitalPatient.objects.using(db).all():
        Appointment.objects.using(db).filter(patient_id=patient.uuid).update(patient_new_id=patient.id)
        uhid_of_uuid[str(patient.uuid)] = patient.uhid

    for fav in PrescriptionFavourite.objects.using(db).order_by("created_at"):
        doctor = StaffUser.objects.using(db).get(pk=fav.doctor_id)
        doctor.prescription_favourites[str(fav.id)] = {"name": fav.name, "items": fav.items, "created_at": fav.created_at.isoformat()}
        doctor.save(using=db, update_fields=["prescription_favourites"])

    for log in AuditLog.objects.using(db).exclude(patient_id__isnull=True).exclude(patient_id=""):
        log.patient_id = uhid_of_uuid.get(log.patient_id)
        log.save(using=db, update_fields=["patient_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0015_visit_add"),
        ("hospital_setup", "0010_places_profiles_add"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
