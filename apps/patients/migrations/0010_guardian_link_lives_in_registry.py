"""
Patient.guardian_awpid / guardian_relation are dropped: the link to the guardian lives only in
registry.PatientRelationship. Any dependent that has no relationship row yet gets one first, so nothing is lost.
"""
from django.db import migrations


def keep_links(apps, schema_editor):
    if schema_editor.connection.alias == "default":
        return
    from apps.registry.models import PatientIdentity, PatientRelationship
    Patient = apps.get_model("patients", "Patient")
    for p in Patient.objects.using(schema_editor.connection.alias).exclude(guardian_awpid=""):
        if PatientRelationship.objects.using("default").filter(dependent_awpid=p.awpid, guardian_awpid=p.guardian_awpid).exists():
            continue
        if PatientIdentity.objects.using("default").filter(awpid=p.guardian_awpid).exists():
            PatientRelationship.objects.using("default").create(
                dependent_awpid=p.awpid, guardian_awpid=p.guardian_awpid, relationship=p.guardian_relation or "other")


def restore_columns(apps, schema_editor):
    if schema_editor.connection.alias == "default":
        return
    from apps.registry.models import PatientRelationship
    Patient = apps.get_model("patients", "Patient")
    for p in Patient.objects.using(schema_editor.connection.alias).filter(is_dependent=True):
        link = PatientRelationship.objects.using("default").filter(dependent_awpid=p.awpid).order_by("-is_primary", "id").first()
        if link:
            Patient.objects.using(schema_editor.connection.alias).filter(pk=p.pk).update(
                guardian_awpid=link.guardian_awpid, guardian_relation=link.relationship)


class Migration(migrations.Migration):

    dependencies = [("patients", "0009_birthhistory")]

    operations = [
        migrations.RunPython(keep_links, migrations.RunPython.noop),
        migrations.RemoveField("Patient", "guardian_awpid"),
        migrations.RemoveField("Patient", "guardian_relation"),
        # reverse of the two RemoveFields re-adds the columns; fill them from the registry afterwards
        migrations.RunPython(migrations.RunPython.noop, restore_columns),
    ]
