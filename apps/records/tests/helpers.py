from apps.records import classification as rules
from apps.records.models import DocumentText, MedicalDocument, PatientDocumentClassification
from apps.registry.models import PatientIdentity

PDF = b"%PDF-1.4\n" + b"x" * 100


def identity(awpid="AWP-T1"):
    """documents.patient is a real foreign key to patient_identity (by AWPID)."""
    return PatientIdentity.objects.get_or_create(awpid=awpid, defaults={"full_name": "Test Patient"})[0]


def make_doc(awpid="AWP-T1", *, status="queued", document_type=rules.NOT_CLASSIFIED, by=None, text=None, batch=None,
             name="doc.pdf", **fields):
    """A MedicalDocument in `status` and of `document_type`. `by` records how the type was decided
    ("rules", "human" or "issued"); `text` stores the extracted text."""
    doc = MedicalDocument(patient=identity(awpid), batch=batch, file_name=name, status=status,
                          document_type=document_type, **fields)
    doc.file = "documents/AWP-T1/1/1.pdf"
    doc.save()
    if text is not None:
        DocumentText.objects.create(document=doc, extracted_text=text, engine="ocr")
    if by == "rules":
        PatientDocumentClassification.objects.create(
            document=doc, ai_document_type=document_type, rule_score=20, final_document_type=document_type,
            status=rules.RULE_CLASSIFIED if document_type != rules.NOT_CLASSIFIED else rules.REVIEW_REQUIRED)
    elif by == "human":
        PatientDocumentClassification.objects.create(
            document=doc, human_document_type=document_type, final_document_type=document_type,
            status=rules.HUMAN_CLASSIFIED)
    elif by == "issued":
        PatientDocumentClassification.objects.create(
            document=doc, classifier=rules.CLASSIFIER_HOSPITAL, final_document_type=document_type, status=rules.ISSUED)
    return reload(doc)


def reload(doc):
    return MedicalDocument.objects.get(pk=doc.pk)
