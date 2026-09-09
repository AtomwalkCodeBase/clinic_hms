"""
HMS-DOC — My Reports document pipeline.

Adds the classification / verification / dedup / soft-delete columns to
shared_document, plus the two bulk-upload tracking tables
(document_upload_batch, document_upload_item). Schema-only: every new
column is nullable or has a default, so this applies without a data
migration.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0026_consultsession_delete_consultpadsubmission_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentUploadBatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("awpid", models.CharField(db_index=True, max_length=30)),
                ("initiated_by", models.CharField(default="patient", max_length=10)),
                ("method", models.CharField(
                    choices=[("folder", "Folder"), ("files", "Files"), ("photo", "Photo"), ("qr", "QR")],
                    default="files", max_length=12)),
                ("total_files", models.IntegerField(default=0)),
                ("accepted", models.IntegerField(default=0)),
                ("unsorted", models.IntegerField(default=0)),
                ("ignored", models.IntegerField(default=0)),
                ("failed", models.IntegerField(default=0)),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("processing", "Processing"),
                             ("done", "Done"), ("partial", "Partial")],
                    db_index=True, default="pending", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "document_upload_batch"},
        ),
        migrations.AddIndex(
            model_name="documentuploadbatch",
            index=models.Index(fields=["awpid", "status"], name="doc_batch_awpid_status_idx"),
        ),

        migrations.AddField(
            model_name="shareddocument",
            name="public_document_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=40),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="document_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="content_hash",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="classification_method",
            field=models.CharField(blank=True, default="", max_length=20),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="classification_confidence",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="verification_status",
            field=models.CharField(default="unverified", max_length=16),
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="review_state",
            field=models.CharField(db_index=True, default="filed", max_length=12),
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="batch",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="documents", to="registry.documentuploadbatch"),
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="is_duplicate_of",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="registry.shareddocument"),
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="hospital_label",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="doctor_label",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="prescription_ref",
            field=models.CharField(blank=True, default="", max_length=60),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="lab_report_ref",
            field=models.CharField(blank=True, default="", max_length=60),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="hidden_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shareddocument",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="shareddocument",
            index=models.Index(fields=["awpid", "review_state"], name="shared_doc_awpid_review_idx"),
        ),
        migrations.AddIndex(
            model_name="shareddocument",
            index=models.Index(fields=["awpid", "doc_type", "document_date"], name="shared_doc_awpid_type_date_idx"),
        ),
        migrations.AddIndex(
            model_name="shareddocument",
            index=models.Index(fields=["awpid", "content_hash"], name="shared_doc_awpid_hash_idx"),
        ),

        migrations.CreateModel(
            name="DocumentUploadItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("declared_size", models.IntegerField(default=0)),
                ("content_hash", models.CharField(blank=True, max_length=64)),
                ("staging_key", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(
                    choices=[("uploading", "Uploading"), ("scanning", "Scanning"),
                             ("classified", "Classified"), ("filed", "Filed"), ("unsorted", "Unsorted"),
                             ("ignored", "Ignored"), ("failed", "Failed"), ("duplicate", "Duplicate")],
                    db_index=True, default="uploading", max_length=14)),
                ("reason", models.CharField(blank=True, max_length=160)),
                ("classified_as", models.CharField(blank=True, max_length=20)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("batch", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="items",
                    to="registry.documentuploadbatch")),
                ("result_document", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="registry.shareddocument")),
            ],
            options={"db_table": "document_upload_item"},
        ),
        migrations.AddIndex(
            model_name="documentuploaditem",
            index=models.Index(fields=["batch", "status"], name="doc_item_batch_status_idx"),
        ),
    ]
