import datetime

from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from apps.records import services
from apps.records.models import DocumentBatch, MedicalDocument, PatientDocumentClassification
from apps.records.tests.helpers import identity, make_doc


class IssuedDocumentTests(TestCase):
    databases = {"default"}

    def test_a_hospital_issued_document_is_stored_typed_and_complete_with_what_is_printed_on_it(self):
        identity("AWP-T1")
        doc = services.create_issued_document(
            awpid="AWP-T1", file_path="patients/AWP-T1/prescriptions/x.pdf", name="Prescription RX-000123 — 2026-09-12.pdf",
            doc_type="prescription", source_tenant_id=3, source_ref="encounter:9", public_document_id="RX-000123",
            document_date=datetime.date(2026, 9, 12))
        self.assertEqual((doc.status, doc.document_type, doc.uploaded_by), ("completed", "prescription", "staff"))
        self.assertEqual((doc.document_ref, doc.document_date, doc.source_tenant_id, doc.source_ref),
                         ("RX-000123", datetime.date(2026, 9, 12), "3", "encounter:9"))
        self.assertEqual((doc.patient.awpid, doc.file_name), ("AWP-T1", "Prescription RX-000123 — 2026-09-12.pdf"))

    def test_the_file_is_the_one_already_in_the_bucket(self):
        identity("AWP-T1")
        doc = services.create_issued_document(awpid="AWP-T1", file_path="patients/AWP-T1/lab-reports/r.pdf", name="r.pdf",
                                              doc_type="lab_report", source_tenant_id=3, source_ref="labreport:1")
        self.assertEqual((doc.file.name, doc.file_name), ("patients/AWP-T1/lab-reports/r.pdf", "r.pdf"))

    def test_a_long_name_is_cut_to_fit(self):
        identity("AWP-T1")
        doc = services.create_issued_document(awpid="AWP-T1", file_path="p", name="x" * 150 + ".pdf", doc_type="other",
                                              source_tenant_id=3, source_ref="x")
        self.assertEqual(len(doc.file_name), 100)

    def test_it_skips_the_rules_and_records_that_the_hospital_chose_the_type(self):
        identity("AWP-T1")
        doc = services.create_issued_document(awpid="AWP-T1", file_path="p", name="x.pdf", doc_type="lab_report",
                                              source_tenant_id=3, source_ref="labreport:1")
        c = PatientDocumentClassification.objects.get(document=doc)
        self.assertEqual((c.classifier, c.status, c.final_document_type, c.rule_score), ("hospital", "issued", "lab_report", None))

    def test_a_type_that_is_not_one_of_the_fixed_types_becomes_other(self):
        identity("AWP-T1")
        doc = services.create_issued_document(awpid="AWP-T1", file_path="p", name="x.pdf", doc_type="vaccination_card",
                                              source_tenant_id=3, source_ref="x")
        self.assertEqual(doc.document_type, "other")


class PatientLinkTests(TestCase):
    databases = {"default"}

    def test_a_document_and_a_batch_need_a_real_patient(self):
        for create in (lambda: DocumentBatch.objects.create(patient_id=999999, total_files=1),
                       lambda: MedicalDocument.objects.create(patient_id=999999, file="x")):
            with self.assertRaises(IntegrityError), transaction.atomic():
                create()
                connection.check_constraints()

    def test_a_document_and_its_text_and_classification_go_with_the_patient(self):
        """The patient link is a cascade: remove the patient and everything filed under them goes too."""
        patient = identity("AWP-T1")
        make_doc(text="some text", by="rules")
        patient.delete()
        self.assertEqual(MedicalDocument.objects.count(), 0)
        self.assertEqual(PatientDocumentClassification.objects.count(), 0)

    def test_a_documents_patient_is_reached_through_the_link(self):
        doc = make_doc("AWP-T1")
        self.assertEqual(MedicalDocument.objects.filter(patient__awpid="AWP-T1").get().id, doc.id)
        self.assertEqual(MedicalDocument.objects.filter(patient__awpid="NOBODY").count(), 0)
