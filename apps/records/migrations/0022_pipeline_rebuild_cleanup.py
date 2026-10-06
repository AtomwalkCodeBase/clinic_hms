import django.db.models.deletion
from django.db import migrations, models

BEAT_TASK = "records: recover_stuck_documents"


def drop_sweep_schedule(apps, schema_editor):
    """The periodic sweep is gone with its settings table: remove the Celery Beat row that kept calling it, so Beat
    doesn't send a task no worker knows."""
    connection = schema_editor.connection
    if "django_celery_beat_periodictask" in connection.introspection.table_names():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM django_celery_beat_periodictask WHERE name = %s", [BEAT_TASK])


def patient_key(related_name):
    return models.ForeignKey("registry.patientidentity", on_delete=django.db.models.deletion.CASCADE,
                             related_name=related_name)


class Migration(migrations.Migration):
    """Step 3 of 3 of the pipeline rebuild: what the new tables replace is dropped — the document-types table (the types
    and keywords are in code now), the AWPID links (replaced by the patient link), the duplicate / claim / classification
    columns, the title and hospital / doctor labels, the patient-delete flags, and the sweep settings."""

    dependencies = [("records", "0021_pipeline_rebuild_data")]

    operations = [
        migrations.RunPython(drop_sweep_schedule, migrations.RunPython.noop),
        migrations.RemoveIndex("MedicalDocument", "meddoc_status_created_idx"),
        # the patient link is filled in now: it becomes required, and the old AWPID link goes
        migrations.AlterField("MedicalDocument", "patient", patient_key("p_documents")),
        migrations.AlterField("DocumentBatch", "patient", patient_key("p_batches")),
        migrations.RemoveField("MedicalDocument", "awpid"),
        migrations.RemoveField("DocumentBatch", "awpid"),
        migrations.RemoveField("MedicalDocument", "old_classification"),
        migrations.RemoveField("MedicalDocument", "content_hash"),
        migrations.RemoveField("MedicalDocument", "attempts"),
        migrations.RemoveField("MedicalDocument", "claimed_at"),
        migrations.RemoveField("MedicalDocument", "classification_source"),
        migrations.RemoveField("MedicalDocument", "score"),
        migrations.RemoveField("MedicalDocument", "classification_details"),
        migrations.RemoveField("MedicalDocument", "title"),
        migrations.RemoveField("MedicalDocument", "hospital_label"),
        migrations.RemoveField("MedicalDocument", "doctor_label"),
        migrations.RemoveField("MedicalDocument", "hidden_at"),
        migrations.RemoveField("MedicalDocument", "deleted_at"),
        migrations.AlterField("MedicalDocument", "file_name", models.CharField(blank=True, max_length=100)),
        migrations.DeleteModel("DocumentClassification"),
        migrations.DeleteModel("SweepConfig"),
    ]
