from django.db import migrations

FIELDS = ["alternate_mobile", "address_line1", "city", "state", "pincode", "marital_status", "nationality", "occupation"]


def forward(apps, schema_editor):
    db = schema_editor.connection.alias
    PatientDetail = apps.get_model("opd", "PatientDetail")
    HospitalPatient = apps.get_model("opd", "HospitalPatient")
    Patient = apps.get_model("patients", "Patient")
    rows = list(PatientDetail.objects.using(db).all())
    if not rows:
        return
    awpid_of = dict(HospitalPatient.objects.using(db).filter(pk__in=[r.patient_id for r in rows]).values_list("pk", "awpid"))
    for row in rows:
        person = Patient.objects.using("default").filter(awpid=awpid_of.get(row.patient_id)).first()
        if person is None:
            continue
        changed = []
        for field in FIELDS:
            kept, here = getattr(person, field), getattr(row, field)
            if here and (not kept or (field == "nationality" and kept == "Indian" and here != "Indian")):
                setattr(person, field, here)
                changed.append(field)
        if changed:
            person.save(using="default", update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0011_patient_remove"),
        ("patients", "0002_patient_personal_details"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
