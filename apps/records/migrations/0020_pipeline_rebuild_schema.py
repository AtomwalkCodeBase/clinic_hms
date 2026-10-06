import django.db.models.deletion
from django.db import migrations, models

import apps.records.models

DOCUMENT_TYPES = [
    ("prescription", "Prescription"), ("lab_report", "Lab Report"), ("imaging_report", "Imaging Report"),
    ("discharge_summary", "Discharge Summary"), ("consultation_note", "Consultation Note"),
    ("medical_bill", "Medical Bill"), ("vaccination_record", "Vaccination Record"),
    ("referral_letter", "Referral Letter"), ("medical_certificate", "Medical Certificate"),
    ("other", "Other"), ("not_classified", "Not Classified"),
]
STATUSES = [
    ("queued", "Queued"), ("extracting", "Extracting"), ("classifying", "Classifying"), ("completed", "Completed"),
    ("review_required", "Review Required"), ("failed", "Failed"),
]


def patient_key(related_name):
    # null only until 0021 has filled it in; 0022 makes it required
    return models.ForeignKey("registry.patientidentity", null=True, on_delete=django.db.models.deletion.CASCADE,
                             related_name=related_name)


class Migration(migrations.Migration):
    """Step 1 of 3 of the pipeline rebuild: the new tables and columns, next to the old ones. The data is moved in
    0021 and the old columns and tables are dropped in 0022."""

    dependencies = [
        ("records", "0019_single_classification_cleanup"),
        ("registry", "0047_consultsession_note_pdf"),
    ]

    operations = [
        # the old per-document type link steps aside, so the new one-to-one can be called "classification"
        migrations.RenameField("MedicalDocument", "classification", "old_classification"),
        # the awpid indexes go (they name columns that are going); the patient link is a plain foreign key from now on
        migrations.RemoveIndex("MedicalDocument", "meddoc_awpid_created_idx"),
        migrations.RemoveIndex("MedicalDocument", "meddoc_awpid_hash_idx"),
        migrations.AddField("MedicalDocument", "patient", patient_key("p_documents")),
        migrations.AddField("DocumentBatch", "patient", patient_key("p_batches")),
        # file_path -> file (a Django FileField on the private S3 bucket; the stored value is the same S3 key)
        migrations.RenameField("MedicalDocument", "file_path", "file"),
        migrations.AlterField("MedicalDocument", "file", models.FileField(
            max_length=500, storage=apps.records.models.records_storage, upload_to=apps.records.models.get_file_path)),
        migrations.RenameField("MedicalDocument", "original_file_name", "file_name"),
        migrations.RenameField("MedicalDocument", "public_document_id", "document_ref"),
        migrations.AlterField("MedicalDocument", "document_ref", models.CharField(blank=True, max_length=40)),
        migrations.AlterField("MedicalDocument", "source_ref", models.CharField(blank=True, max_length=120)),
        migrations.RenameField("MedicalDocument", "error", "error_message"),
        migrations.AddField("MedicalDocument", "document_type", models.CharField(
            choices=DOCUMENT_TYPES, default="not_classified", max_length=30)),
        migrations.AlterField("MedicalDocument", "status", models.CharField(
            choices=STATUSES, db_index=True, default="queued", max_length=15)),
        migrations.AlterField("MedicalDocument", "source_tenant_id", models.CharField(blank=True, max_length=30, null=True)),
        migrations.CreateModel(
            name="DocumentText",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("extracted_text", models.TextField(blank=True)),
                ("engine", models.CharField(blank=True, max_length=30)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("document", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="text",
                                                  to="records.medicaldocument")),
            ],
            options={"db_table": "document_text"},
        ),
        migrations.CreateModel(
            name="PatientDocumentClassification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ai_document_type", models.CharField(blank=True, max_length=50, null=True)),
                ("classifier", models.CharField(default="rule_engine", max_length=30)),
                ("rule_score", models.FloatField(blank=True, null=True)),
                ("second_best_score", models.FloatField(blank=True, null=True)),
                ("score_margin", models.FloatField(blank=True, null=True)),
                ("rule_matches", models.JSONField(blank=True, null=True)),
                ("human_document_type", models.CharField(blank=True, max_length=50, null=True)),
                ("final_document_type", models.CharField(blank=True, max_length=50, null=True)),
                ("status", models.CharField(default="rule_classified", max_length=30)),
                ("document", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                                  related_name="classification", to="records.medicaldocument")),
            ],
            options={"db_table": "patient_document_classification"},
        ),
    ]
