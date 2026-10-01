from django.db import migrations

BUILT_IN = {
    "lab_report": "Lab Report", "prescription": "Prescription", "scan": "Scan / Imaging",
    "discharge_summary": "Discharge Summary", "consult_note": "Consultation Note", "other": "Unknown / Other",
}


def forwards(apps, schema_editor):
    Classification = apps.get_model("records", "DocumentClassification")
    Document = apps.get_model("records", "MedicalDocument")
    Batch = apps.get_model("records", "DocumentBatch")

    # every type a document already uses gets a master row (built-ins first)
    used = set(Document.objects.values_list("doc_type", flat=True).distinct())
    for code in [*BUILT_IN, *sorted(used - set(BUILT_IN))]:
        row, _ = Classification.objects.get_or_create(code=code)
        row.name = BUILT_IN.get(code) or code.replace("_", " ").title()
        row.is_staff_only = code == "consult_note"
        row.save()
    for row in Classification.objects.filter(name=""):
        row.name = row.code.replace("_", " ").title()
        row.save(update_fields=["name"])

    by_code = {c.code: c for c in Classification.objects.all()}
    for doc in Document.objects.iterator(chunk_size=500):
        # documents still in the pipeline have no verdict yet; every other row keeps its type
        in_pipeline = doc.status in ("queued", "ocr", "classifying")
        failed_unclassified = doc.status == "failed" and not doc.method
        doc.classification = None if (in_pipeline or failed_unclassified) else by_code[doc.doc_type]
        if doc.classification is None:
            doc.classification_source = None
        else:
            doc.classification_source = "system" if doc.method in ("rule", "llm") else "human"
        doc.classification_details = {"extracted_text": doc.extracted_text,
                                      **({"method": doc.method} if doc.method else {})}
        if doc.status == "ocr":
            doc.status = "extracting"
        doc.save()

    for batch in Batch.objects.all():
        done_n = Document.objects.filter(batch=batch, status="completed").count()
        failed_n = Document.objects.filter(batch=batch, status="failed").count()
        batch.processed_files, batch.failed_files = done_n, failed_n
        finished = done_n + failed_n >= batch.total_files
        batch.status = ("processing" if not finished else
                        "completed_with_errors" if failed_n else "completed")
        batch.save()


class Migration(migrations.Migration):
    """Step 2 of 3: copy doc_type / method / extracted_text / ocr status into the new columns."""

    dependencies = [("records", "0005_three_tables_schema")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
