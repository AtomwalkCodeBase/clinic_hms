import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Step 1 of 3: the type list goes back to being the keyword rules table (classification_rule), and a
    new per-document table (document_classification) is created next to medical_document."""

    dependencies = [("records", "0008_medicaldocument_size")]

    operations = [
        migrations.RenameModel("DocumentClassification", "ClassificationRule"),
        migrations.AlterModelTable("ClassificationRule", "classification_rule"),
        migrations.RenameField("ClassificationRule", "code", "doc_type"),
        migrations.AlterField("ClassificationRule", "doc_type", models.CharField(max_length=30, unique=True)),
        migrations.AlterModelOptions("ClassificationRule", options={"ordering": ["doc_type"]}),

        migrations.AddField("MedicalDocument", "content_hash", models.CharField(max_length=64, blank=True, default="")),
        migrations.CreateModel(
            name="DocumentClassification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("classification_type", models.CharField(max_length=30, null=True, blank=True)),
                ("classified_by", models.CharField(max_length=6, null=True, blank=True,
                                                   choices=[("system", "System"), ("human", "Human")])),
                ("score", models.FloatField(null=True, blank=True)),
                ("status", models.CharField(max_length=12, default="queued",
                                            choices=[("queued", "Queued"), ("extracting", "Extracting"),
                                                     ("classifying", "Classifying"), ("completed", "Completed"),
                                                     ("failed", "Failed"), ("rejected", "Rejected")])),
                ("data", models.JSONField(default=dict, blank=True)),
                ("error", models.TextField(blank=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("claimed_at", models.DateTimeField(null=True, blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                # related_name becomes "classification" in step 3, once the old field of that name is gone
                ("document", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                                  related_name="new_classification", to="records.medicaldocument")),
            ],
            options={"db_table": "document_classification"},
        ),
        migrations.AddIndex("DocumentClassification",
                            models.Index(fields=["status", "claimed_at"], name="docclass_status_claimed_idx")),
    ]
