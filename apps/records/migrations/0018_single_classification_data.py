import os
import re

from django.db import migrations
from django.utils import timezone

NUMBER = re.compile(r"\b([A-Z]{1,6}-\d{3,})\b")
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def forwards(apps, schema_editor):
    Doc = apps.get_model("records", "MedicalDocument")
    Result = apps.get_model("records", "DocumentResult")
    Type = apps.get_model("records", "DocumentClassification")
    Batch = apps.get_model("records", "DocumentBatch")
    Tenant = apps.get_model("tenants", "Tenant")

    # the master list: every type a document already carries has a row
    for t in Type.objects.filter(name=""):
        t.name = t.code.replace("_", " ").capitalize()
        t.save(update_fields=["name"])
    for code in set(Result.objects.exclude(classification_type=None).values_list("classification_type", flat=True)):
        Type.objects.get_or_create(code=code, defaults={"name": code.replace("_", " ").capitalize()})
    Type.objects.filter(code="consult_note").update(is_staff_only=True)
    by_code = {t.code: t for t in Type.objects.all()}
    tenant_names = dict(Tenant.objects.values_list("id", "name"))

    fields = ["status", "attempts", "claimed_at", "error", "classification", "classification_source", "score",
              "classification_details", "title", "hospital_label", "public_document_id", "document_date",
              "hidden_at", "deleted_at", "updated_at"]
    pending = []
    for res in Result.objects.select_related("document").iterator(chunk_size=500):
        d = res.document
        d.status, d.attempts, d.claimed_at, d.error = res.status, res.attempts, res.claimed_at, res.error
        d.classification = by_code.get(res.classification_type)
        d.classification_source, d.score = res.classified_by, res.score
        # one classification only: what the rules said before a person overwrote it is not kept
        d.classification_details = {k: v for k, v in (res.data or {}).items() if k != "system_verdict"}
        d.title = os.path.splitext(d.original_file_name or "")[0][:200]
        d.updated_at = res.updated_at
        if d.source_tenant_id:                       # a hospital-issued report: what we can read back from its name
            d.hospital_label = (tenant_names.get(d.source_tenant_id) or "")[:120]
            m = NUMBER.search(d.original_file_name or "")
            d.public_document_id = m.group(1) if m else ""
            m = DATE.search(d.original_file_name or "")
            d.document_date = timezone.datetime.strptime(m.group(1), "%Y-%m-%d").date() if m else None
            if d.deleted_at:                         # the patient removed it: hidden_at means that for these again
                d.hidden_at, d.deleted_at = d.deleted_at, None
        pending.append(d)
        if len(pending) >= 500:
            Doc.objects.bulk_update(pending, fields)
            pending = []
    if pending:
        Doc.objects.bulk_update(pending, fields)

    for batch in Batch.objects.all():
        docs = Doc.objects.filter(batch=batch)
        done = docs.filter(status__in=("completed", "rejected")).count()
        failed = docs.filter(status="failed").count()
        batch.processed_files, batch.failed_files = done, failed
        batch.status = ("processing" if done + failed < batch.total_files else
                        "completed_with_errors" if failed else "completed")
        batch.save(update_fields=["processed_files", "failed_files", "status"])


class Migration(migrations.Migration):
    """Step 2 of 3: copy each document's result back onto the document, and fill what can be read back."""

    dependencies = [
        ("records", "0017_single_classification_schema"),
        ("tenants", "0001_initial"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
