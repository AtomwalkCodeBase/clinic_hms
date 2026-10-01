from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    Document = apps.get_model("records", "MedicalDocument")
    Result = apps.get_model("records", "DocumentClassification")

    batch = []
    for doc in Document.objects.select_related("classification").iterator(chunk_size=500):
        batch.append(Result(
            document_id=doc.id,
            classification_type=doc.classification.doc_type if doc.classification_id else None,
            classified_by=doc.classification_source,
            score=doc.score,
            status=doc.status,
            data=doc.classification_details or {},
            error=doc.error,
            attempts=doc.attempts,
            claimed_at=doc.claimed_at,
        ))
        if len(batch) >= 500:
            Result.objects.bulk_create(batch)
            batch = []
    if batch:
        Result.objects.bulk_create(batch)

    # hidden_at (a hospital-issued report the patient removed from their view) is dropped in step 3: carry it over
    # to deleted_at, which now means "removed from the patient's view" for every report, so nothing reappears.
    Document.objects.filter(hidden_at__isnull=False, deleted_at__isnull=True).update(deleted_at=F("hidden_at"))


class Migration(migrations.Migration):
    """Step 2 of 3: one document_classification row per existing document, copied from medical_document; a hidden report becomes a removed one."""

    dependencies = [("records", "0009_per_document_classification")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
