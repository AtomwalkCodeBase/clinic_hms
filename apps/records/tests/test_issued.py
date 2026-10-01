from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.records import services
from apps.records.models import DocumentBatch, DocumentClassification, MedicalDocument
from apps.records.tests.helpers import identity


class IssuedDocumentTests(TestCase):
    databases = {"default"}

    def test_a_hospital_issued_document_is_stored_classified_and_complete_with_what_is_printed_on_it(self):
        import datetime
        identity("AWP-T1")
        doc = services.create_issued_document(
            awpid="AWP-T1", file_path="patients/AWP-T1/prescriptions/x.pdf", name="Prescription RX-000123 — 2026-09-12.pdf",
            doc_type="prescription", source_tenant_id=3, source_ref="encounter:9", title="Prescription RX-000123 — 2026-09-12",
            public_document_id="RX-000123", hospital_label="Mahanandi Hospital", doctor_label="Dr. Rao",
            document_date=datetime.date(2026, 9, 12))
        self.assertEqual((doc.status, doc.doc_type, doc.classification_source, doc.uploaded_by), ("completed", "prescription", "human", "staff"))
        self.assertEqual((doc.public_document_id, doc.hospital_label, doc.doctor_label, doc.document_date),
                         ("RX-000123", "Mahanandi Hospital", "Dr. Rao", datetime.date(2026, 9, 12)))
        self.assertEqual(doc.title, "Prescription RX-000123 — 2026-09-12")

    def test_a_consult_note_is_staff_only_and_never_a_choice(self):
        identity("AWP-T1")
        doc = services.create_issued_document(awpid="AWP-T1", file_path="p", name="note.pdf", doc_type="consult_note",
                                              source_tenant_id=3, source_ref="encounter:9:handwritten:note")
        self.assertTrue(doc.is_staff_only)
        self.assertNotIn("consult_note", [c.code for c in DocumentClassification.configured()])

    def test_the_type_a_hospital_brings_does_not_become_something_the_patient_can_pick(self):
        identity("AWP-T1")
        services.create_issued_document(awpid="AWP-T1", file_path="p", name="x.pdf", doc_type="vaccination_card",
                                        source_tenant_id=3, source_ref="x")
        self.assertIn("vaccination_card", DocumentClassification.objects.values_list("code", flat=True))
        self.assertNotIn("vaccination_card", [c.code for c in DocumentClassification.configured()])      # no keywords


class AwpidForeignKeyTests(TestCase):
    databases = {"default"}

    def test_a_document_and_a_batch_need_a_real_patient(self):
        for create in (lambda: DocumentBatch.objects.create(awpid_id="NOBODY", total_files=1),
                       lambda: MedicalDocument.objects.create(awpid_id="NOBODY", file_path="x")):
            with self.assertRaises(IntegrityError), transaction.atomic():
                create()
                connection.check_constraints()

    def test_a_patient_with_documents_cannot_be_deleted(self):
        patient = identity("AWP-T1")
        MedicalDocument.objects.create(awpid_id="AWP-T1", file_path="x")
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            patient.delete()
