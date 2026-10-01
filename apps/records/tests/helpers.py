from apps.records.models import DocumentClassification, MedicalDocument
from apps.registry.models import PatientIdentity

PDF = b"%PDF-1.4\n" + b"x" * 100


def identity(awpid="AWP-T1"):
    """documents.awpid is a real foreign key to patient_identity."""
    return PatientIdentity.objects.get_or_create(awpid=awpid, defaults={"full_name": "Test Patient"})[0]


def make_doc(awpid="AWP-T1", *, status="queued", doc_type=None, by=None, data=None, batch=None, name="doc.pdf",
             content_hash="", **fields):
    """A MedicalDocument in `status`, classified as `doc_type` by `by` ("system" / "human") if given."""
    identity(awpid)
    doc = MedicalDocument.objects.create(
        awpid_id=awpid, batch=batch, title=MedicalDocument.title_from(name), original_file_name=name,
        file_path="patients/AWP-T1/documents/1/1.pdf", content_hash=content_hash, status=status,
        classification=DocumentClassification.for_code(doc_type) if doc_type else None,
        classification_source=by, classification_details=data or {}, **fields)
    return MedicalDocument.objects.get(pk=doc.pk)


def reload(doc):
    return MedicalDocument.objects.get(pk=doc.pk)
