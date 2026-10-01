import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

STATUSES = [("queued", "Queued"), ("extracting", "Extracting"), ("classifying", "Classifying"),
            ("completed", "Completed"), ("failed", "Failed"), ("rejected", "Rejected")]


class Migration(migrations.Migration):
    """Step 1 of 3: back to one table per concern, with a document's classification stored on the document.
    The per-document results table steps aside (document_result_old) and the rules table becomes the master
    list `document_classification`; the document and batch get their columns back (empty until step 2)."""

    dependencies = [("records", "0016_scoring_settings")]

    operations = [
        # 1. the per-document table steps aside, freeing the name "document_classification" and the field "classification"
        migrations.AlterField("DocumentClassification", "document",
                              models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                                   related_name="old_result", to="records.medicaldocument")),
        migrations.RenameModel("DocumentClassification", "DocumentResult"),
        migrations.AlterModelTable("DocumentResult", "document_result_old"),

        # 2. the rules table becomes the master list of types
        migrations.RenameModel("ClassificationRule", "DocumentClassification"),
        migrations.AlterModelTable("DocumentClassification", "document_classification"),
        migrations.RenameField("DocumentClassification", "doc_type", "code"),
        migrations.AlterField("DocumentClassification", "code", models.SlugField(max_length=30, unique=True)),
        migrations.AlterModelOptions("DocumentClassification", options={"ordering": ["code"]}),
        migrations.AddField("DocumentClassification", "name", models.CharField(max_length=60, default="")),
        migrations.AddField("DocumentClassification", "is_staff_only", models.BooleanField(default=False)),
        migrations.AddField("DocumentClassification", "created_at",
                            models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now), preserve_default=False),
        migrations.AlterField("DocumentClassification", "keywords", models.TextField(blank=True)),

        # 3. the batch gets its counters and status back
        migrations.AddField("DocumentBatch", "processed_files", models.PositiveIntegerField(default=0)),
        migrations.AddField("DocumentBatch", "failed_files", models.PositiveIntegerField(default=0)),
        migrations.AddField("DocumentBatch", "status", models.CharField(
            max_length=24, default="processing",
            choices=[("processing", "Processing"), ("completed", "Completed"), ("completed_with_errors", "Completed With Errors")])),
        migrations.AddField("DocumentBatch", "updated_at",
                            models.DateTimeField(auto_now=True, default=django.utils.timezone.now), preserve_default=False),

        # 4. the document gets its columns back
        migrations.AddField("MedicalDocument", "title", models.CharField(max_length=200, blank=True)),
        migrations.AddField("MedicalDocument", "public_document_id", models.CharField(max_length=40, blank=True, db_index=True)),
        migrations.AddField("MedicalDocument", "hospital_label", models.CharField(max_length=120, blank=True)),
        migrations.AddField("MedicalDocument", "doctor_label", models.CharField(max_length=120, blank=True)),
        migrations.AddField("MedicalDocument", "document_date", models.DateField(null=True, blank=True)),
        migrations.AddField("MedicalDocument", "status", models.CharField(max_length=12, choices=STATUSES, default="completed", db_index=True)),
        migrations.AddField("MedicalDocument", "attempts", models.PositiveSmallIntegerField(default=0)),
        migrations.AddField("MedicalDocument", "claimed_at", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("MedicalDocument", "error", models.TextField(blank=True)),
        migrations.AddField("MedicalDocument", "classification",
                            models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                              related_name="documents", to="records.documentclassification")),
        migrations.AddField("MedicalDocument", "classification_source",
                            models.CharField(max_length=6, null=True, blank=True, choices=[("system", "System"), ("human", "Human")])),
        migrations.AddField("MedicalDocument", "score", models.FloatField(null=True, blank=True)),
        migrations.AddField("MedicalDocument", "classification_details", models.JSONField(default=dict, blank=True)),
        migrations.AddField("MedicalDocument", "hidden_at", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("MedicalDocument", "updated_at",
                            models.DateTimeField(auto_now=True, default=django.utils.timezone.now), preserve_default=False),
    ]
