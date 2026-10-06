import re

from django.db import migrations

TYPES = {
    "prescription", "lab_report", "imaging_report", "discharge_summary", "consultation_note",
    "medical_bill", "vaccination_record", "referral_letter", "medical_certificate", "other",
}
RENAMED = {"scan": "imaging_report"}
NOTE_REF = re.compile(r"^encounter:([0-9a-fA-F-]{36}):handwritten:note$")


def new_type(code):
    """An old type code as one of the fixed types: renamed, or "other" when it is not one of them."""
    code = RENAMED.get(code, code)
    return code if code in TYPES else "other"


def forwards(apps, schema_editor):
    """Moves every document onto the new tables:
      * the patient link: the AWPID text becomes the patient's id
      * the text read out of it  -> DocumentText
      * its type and how it was decided -> PatientDocumentClassification, and MedicalDocument.document_type
      * a document that was read but filed under no type -> "review_required" / "not_classified"
      * a report the patient had deleted, or a duplicate we had rejected -> removed (those flags are gone)
      * a file still in the pipeline -> failed ("try again"): its worker is gone with the old queue
      * the doctor-only consult notes -> out of the records, onto their consult session (ConsultSession.note_pdf)
    """
    Doc = apps.get_model("records", "MedicalDocument")
    Text = apps.get_model("records", "DocumentText")
    Cls = apps.get_model("records", "PatientDocumentClassification")
    Batch = apps.get_model("records", "DocumentBatch")
    Session = apps.get_model("registry", "ConsultSession")

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("UPDATE medical_document m SET patient_id = p.id FROM patient_identity p WHERE p.awpid = m.awpid")
        cursor.execute("UPDATE document_batch b SET patient_id = p.id FROM patient_identity p WHERE p.awpid = b.awpid")

    batches = set()
    for doc in Doc.objects.select_related("old_classification").order_by("id").iterator(chunk_size=500):
        old = doc.old_classification
        code = old.code if old else ""
        details = doc.classification_details or {}
        if doc.batch_id:
            batches.add(doc.batch_id)

        if code == "consult_note":
            match = NOTE_REF.match(doc.source_ref or "")
            session = Session.objects.filter(encounter_id=match.group(1)).first() if match else None
            if session and doc.file and not session.note_pdf:
                session.note_pdf = doc.file.name
                session.save(update_fields=["note_pdf"])
            doc.delete()
            continue
        if doc.deleted_at or doc.status == "rejected":
            doc.delete()
            continue

        doc.file_name = (doc.file_name or "")[:100]
        if doc.status in ("queued", "extracting", "classifying"):
            doc.status, doc.document_type = "failed", "not_classified"
            doc.error_message = "This file was interrupted by a system update. Please try it again."
            doc.save()
            continue
        if doc.status == "failed":
            doc.document_type = "not_classified"
            doc.save()
            continue

        text = details.get("extracted_text")
        if text:
            Text.objects.create(document=doc, extracted_text=text, engine="ocr")
        if old is None:                                    # read, but no type fit
            best = details.get("best_guess") or ""
            doc.status, doc.document_type = "review_required", "not_classified"
            Cls.objects.create(document=doc, ai_document_type=new_type(best) if best else "not_classified",
                               classifier="rule_engine", final_document_type="not_classified", status="review_required")
        else:
            doc_type = new_type(code)
            doc.document_type = doc_type
            if doc.classification_source == "human" and doc.source_tenant_id:        # issued by a hospital
                Cls.objects.create(document=doc, classifier="hospital", final_document_type=doc_type, status="issued")
            elif doc.classification_source == "human":                               # a person chose it
                Cls.objects.create(document=doc, human_document_type=doc_type, final_document_type=doc_type,
                                   status="human_classified")
            else:                                                                    # the rules did
                Cls.objects.create(document=doc, ai_document_type=doc_type, classifier="rule_engine",
                                   rule_score=doc.score, final_document_type=doc_type, status="rule_classified",
                                   rule_matches=[{"keyword": w} for w in details.get("matched", [])])
        doc.save()

    for batch in Batch.objects.filter(pk__in=batches):               # recount, as DocumentBatch.refresh() does
        docs = Doc.objects.filter(batch=batch)
        batch.total_files = docs.count()
        batch.processed_files = docs.filter(status__in=("completed", "review_required")).count()
        batch.failed_files = docs.filter(status="failed").count()
        done = batch.processed_files + batch.failed_files >= batch.total_files
        batch.status = "processing" if not done else ("completed_with_errors" if batch.failed_files else "completed")
        batch.save()


class Migration(migrations.Migration):
    """Step 2 of 3 of the pipeline rebuild: the data. One way: the old columns are dropped in 0022."""

    dependencies = [
        ("records", "0020_pipeline_rebuild_schema"),
        ("registry", "0047_consultsession_note_pdf"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
