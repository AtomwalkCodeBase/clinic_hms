import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Step 3 of 3: drop the columns step 2 copied out, set the final field options and indexes."""

    dependencies = [("records", "0006_three_tables_data")]

    operations = [
        migrations.RemoveField("MedicalDocument", "doc_type"),
        migrations.RemoveField("MedicalDocument", "extracted_text"),
        migrations.RemoveField("MedicalDocument", "method"),
        migrations.AlterField("MedicalDocument", "batch",
                              models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                                                related_name="documents", to="records.documentbatch")),
        migrations.AlterField("MedicalDocument", "status",
                              models.CharField(max_length=12, default="completed", db_index=True,
                                               choices=[("queued", "Queued"), ("extracting", "Extracting"),
                                                        ("classifying", "Classifying"), ("completed", "Completed"),
                                                        ("failed", "Failed")])),
        migrations.AlterField("MedicalDocument", "classification_source",
                              models.CharField(max_length=6, null=True, blank=True,
                                               choices=[("system", "System"), ("human", "Human")])),
        migrations.AlterField("DocumentBatch", "status",
                              models.CharField(max_length=24, default="processing",
                                               choices=[("processing", "Processing"), ("completed", "Completed"),
                                                        ("completed_with_errors", "Completed With Errors")])),
        migrations.AlterField("DocumentClassification", "name", models.CharField(max_length=60)),
        migrations.AlterField("MedicalDocument", "title", models.CharField(max_length=200, blank=True)),
        migrations.AddIndex("MedicalDocument", models.Index(fields=["status", "created_at"], name="meddoc_status_created_idx")),
        migrations.AddIndex("MedicalDocument", models.Index(fields=["awpid", "classification"], name="meddoc_awpid_class_idx")),
    ]
