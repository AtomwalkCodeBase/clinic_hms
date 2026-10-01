import django.db.models.deletion
from django.db import migrations, models

ADD_FK = (
    "ALTER TABLE {table} ADD CONSTRAINT {table}_awpid_fk "
    "FOREIGN KEY (awpid) REFERENCES patient_identity (awpid)"
)
DROP_FK = "ALTER TABLE {table} DROP CONSTRAINT {table}_awpid_fk"


class Migration(migrations.Migration):
    """Step 3 of 3: drop the columns step 2 copied out (and the ones no longer wanted), and make awpid a real
    foreign key to patient_identity. If this fails on the foreign key, some document's awpid has no
    patient_identity row — fix or remove those rows and run it again."""

    dependencies = [
        ("records", "0010_per_document_classification_data"),
        ("registry", "0046_drop_classifier_cache_tables"),
    ]

    operations = [
        migrations.RemoveIndex("MedicalDocument", "meddoc_status_created_idx"),
        migrations.RemoveIndex("MedicalDocument", "meddoc_awpid_class_idx"),
        *[migrations.RemoveField("MedicalDocument", f) for f in (
            "title", "public_document_id", "hospital_label", "doctor_label", "document_date",
            "classification", "classification_source", "score", "classification_details",
            "status", "attempts", "claimed_at", "error", "hidden_at", "updated_at")],
        migrations.AlterField("MedicalDocument", "awpid", models.CharField(max_length=30)),
        migrations.AddIndex("MedicalDocument", models.Index(fields=["awpid", "created_at"], name="meddoc_awpid_created_idx")),
        migrations.AddIndex("MedicalDocument", models.Index(fields=["awpid", "content_hash"], name="meddoc_awpid_hash_idx")),
        migrations.AlterField("MedicalDocument", "content_hash", models.CharField(max_length=64, blank=True)),

        migrations.AlterField("ClassificationRule", "keywords", models.TextField(
            blank=True, help_text="Pipe-separated, e.g. laboratory|hemoglobin|glucose|reference range")),
        *[migrations.RemoveField("ClassificationRule", f) for f in ("name", "is_staff_only", "created_at")],
        *[migrations.RemoveField("DocumentBatch", f) for f in ("processed_files", "failed_files", "status", "updated_at")],

        migrations.AlterField("DocumentClassification", "document",
                              models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                                   related_name="classification", to="records.medicaldocument")),

        migrations.RunSQL(ADD_FK.format(table="medical_document"), DROP_FK.format(table="medical_document")),
        migrations.RunSQL(ADD_FK.format(table="document_batch"), DROP_FK.format(table="document_batch")),
    ]
