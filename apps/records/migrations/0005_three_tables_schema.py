import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """Step 1 of 3: rename the three tables and add the new columns (the old ones stay until step 3)."""

    dependencies = [("records", "0004_rename_s3_key_file_path")]

    operations = [
        # ClassificationRule -> DocumentClassification (the master list of types)
        migrations.RenameModel("ClassificationRule", "DocumentClassification"),
        migrations.AlterModelTable("DocumentClassification", "document_classification"),
        migrations.RenameField("DocumentClassification", "doc_type", "code"),
        migrations.AlterModelOptions("DocumentClassification", options={"ordering": ["code"]}),
        migrations.AlterField("DocumentClassification", "code", models.SlugField(max_length=30, unique=True)),
        migrations.AlterField("DocumentClassification", "keywords", models.TextField(blank=True)),
        migrations.AddField("DocumentClassification", "name", models.CharField(max_length=60, default="")),
        migrations.AddField("DocumentClassification", "is_staff_only", models.BooleanField(default=False)),
        migrations.AddField("DocumentClassification", "created_at",
                            models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
                            preserve_default=False),

        # UploadBatch -> DocumentBatch
        migrations.RenameModel("UploadBatch", "DocumentBatch"),
        migrations.AlterModelTable("DocumentBatch", "document_batch"),
        migrations.AddField("DocumentBatch", "processed_files", models.PositiveIntegerField(default=0)),
        migrations.AddField("DocumentBatch", "failed_files", models.PositiveIntegerField(default=0)),
        migrations.AddField("DocumentBatch", "status", models.CharField(max_length=24, default="processing")),
        migrations.AddField("DocumentBatch", "updated_at",
                            models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
                            preserve_default=False),

        # SharedDocument -> MedicalDocument
        migrations.RemoveIndex("SharedDocument", "shared_doc_awpid_type_idx"),
        migrations.RenameModel("SharedDocument", "MedicalDocument"),
        migrations.AlterModelTable("MedicalDocument", "medical_document"),
        migrations.RenameField("MedicalDocument", "file_name", "original_file_name"),
        migrations.RenameField("MedicalDocument", "processing_status", "status"),
        migrations.AddField("MedicalDocument", "classification",
                            models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                              related_name="documents", to="records.documentclassification")),
        migrations.AddField("MedicalDocument", "classification_source",
                            models.CharField(max_length=6, null=True, blank=True)),
        migrations.AddField("MedicalDocument", "classification_details",
                            models.JSONField(default=dict, blank=True)),
        migrations.AddField("MedicalDocument", "attempts", models.PositiveSmallIntegerField(default=0)),
        migrations.AddField("MedicalDocument", "claimed_at", models.DateTimeField(null=True, blank=True)),
    ]
