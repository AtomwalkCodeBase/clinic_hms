import django.db.models.deletion
from django.db import migrations, models


def tidy(apps, schema_editor):
    db = schema_editor.connection.alias
    LabRequest = apps.get_model("lab", "LabRequest")
    LabReport = apps.get_model("lab", "LabReport")
    Appointment = apps.get_model("opd", "Appointment")
    LabRequest.objects.using(db).exclude(appointment_id__in=Appointment.objects.using(db).values("id")).filter(
        appointment_id__isnull=False).update(appointment_id=None)
    for row in LabReport.objects.using(db).all().only("pk", "file_url"):
        if len(row.file_url or "") > 255:
            LabReport.objects.using(db).filter(pk=row.pk).update(file_url="")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("lab", "0002_initial"),
        ("opd", "0003_ids_as_foreign_keys"),
    ]

    operations = [
        migrations.RunPython(tidy, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="labrequest", name="lab_request_request_ccac3a_idx"),
        migrations.AlterField(model_name="labrequest", name="appointment_id", field=models.UUIDField(blank=True, null=True)),
        migrations.RenameField(model_name="labrequest", old_name="appointment_id", new_name="appointment"),
        migrations.AlterField(
            model_name="labrequest", name="appointment",
            field=models.ForeignKey(blank=True, db_column="appointment_id", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lab_requests", to="opd.appointment"),
        ),
        migrations.AlterField(model_name="labreport", name="file_url", field=models.CharField(blank=True, max_length=255)),
    ]
