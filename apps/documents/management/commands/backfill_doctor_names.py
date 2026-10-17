"""Management command: backfill_doctor_names

Fills `doctor_name` on documents that were processed before the field existed, by reading the doctor's name from the
text already stored for each document (nothing is re-read from storage). Only a patient's own uploads whose name is
still empty are touched: a hospital-issued file, or a name someone already typed, is left alone.

    python manage.py backfill_doctor_names --dry-run     # shows what would change, writes nothing
    python manage.py backfill_doctor_names               # does it
"""
from django.core.management.base import BaseCommand

from apps.documents.doctor_names import find_doctor_name
from apps.documents.models import DocumentExtraction, MedicalDocument


class Command(BaseCommand):
    help = "Read the doctor's name from the stored text of existing patient uploads that have none."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count and show the names found, but save nothing.")
        parser.add_argument("--limit", type=int, default=0, help="Stop after this many documents (0 = all).")

    def handle(self, *args, dry_run=False, limit=0, **options):
        rows = (DocumentExtraction.objects.using("default")
                .filter(document__doctor_name="", document__created_by_type="P", document__source_hospital__isnull=True)
                .exclude(extracted_text="")
                .values_list("document_id", "extracted_text"))
        if limit:
            rows = rows[:limit]
        looked, found = 0, 0
        for document_id, text in rows.iterator(chunk_size=500):
            looked += 1
            name = find_doctor_name(text)
            if not name:
                continue
            found += 1
            if dry_run:
                self.stdout.write(f"  document {document_id}: Dr. {name}")
            else:
                MedicalDocument.objects.using("default").filter(pk=document_id, doctor_name="").update(doctor_name=name)
        verb = "would be filled" if dry_run else "filled"
        self.stdout.write(self.style.SUCCESS(f"Looked at {looked} document(s); a doctor's name {verb} on {found}."))
