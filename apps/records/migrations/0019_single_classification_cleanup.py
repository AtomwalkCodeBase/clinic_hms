import django.db.models.deletion
from django.db import migrations, models

DROP_FK = "ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_awpid_fk"
ADD_FK = ("ALTER TABLE {table} ADD CONSTRAINT {table}_awpid_fk FOREIGN KEY (awpid) "
          "REFERENCES patient_identity (awpid)")


def patient_key():
    return models.ForeignKey("registry.patientidentity", to_field="awpid", db_column="awpid",
                             on_delete=django.db.models.deletion.PROTECT, related_name="+")


class Migration(migrations.Migration):
    """Step 3 of 3: the per-document results table goes, and awpid becomes a real foreign key in the models
    (the database-level constraint added in 0011 is replaced by Django's own)."""

    dependencies = [
        ("records", "0018_single_classification_data"),
        ("registry", "0046_drop_classifier_cache_tables"),
    ]

    operations = [
        migrations.DeleteModel("DocumentResult"),
        migrations.RunSQL(DROP_FK.format(table="medical_document"), ADD_FK.format(table="medical_document")),
        migrations.RunSQL(DROP_FK.format(table="document_batch"), ADD_FK.format(table="document_batch")),
        migrations.AlterField("MedicalDocument", "awpid", patient_key()),
        migrations.AlterField("DocumentBatch", "awpid", patient_key()),
        migrations.AlterField("DocumentClassification", "name", models.CharField(max_length=60)),
        migrations.AddIndex("MedicalDocument", models.Index(fields=["status", "created_at"], name="meddoc_status_created_idx")),
    ]
