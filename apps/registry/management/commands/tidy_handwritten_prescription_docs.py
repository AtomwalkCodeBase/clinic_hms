"""
tidy_handwritten_prescription_docs
----------------------------------
One-time cleanup for the "two prescription rows in My Reports" issue.

The consult pad archives the doctor's raw handwritten prescription as its own
SharedDocument (source_ref "encounter:<id>:handwritten:rx"). The portal now
folds that into the typeset prescription row as `handwritten_doc_id` (opened
from the detail sheet), so no separate My Reports entry — that part needs no
data change, PortalDocumentListCreateView.get() handles it live.

This command only fixes the ORPHAN case: a handwriting row whose encounter
never got a typeset prescription (the doctor wrote the script by hand and
added no structured items on sign). Left alone it still shows, but titled
"Handwritten Prescription …" with no doctor / hospital label. Here we:

  * rewrite source_ref  "encounter:<id>:handwritten:rx" -> "encounter:<id>"
    so it becomes the canonical prescription row for that visit;
  * fill hospital_label / doctor_label / public_document_id / document_date
    from the tenant record, best-effort;
  * mark it verified / filed / staff-classified like any hospital-issued Rx.

Idempotent — a row already rewritten (ref no longer ends ":handwritten:rx")
is skipped. Safe to run every deploy.

    python manage.py tidy_handwritten_prescription_docs --dry-run
    python manage.py tidy_handwritten_prescription_docs
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Promote orphan handwritten-prescription documents to the canonical Rx row."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")

    def handle(self, *args, **opts):
        from apps.registry.models import SharedDocument
        from apps.tenants.models import Tenant
        from apps.tenants.utils import _make_db_config

        dry = opts["dry_run"]
        n = {"promoted": 0, "linked": 0, "skipped": 0, "err": 0}

        tenants = {t.id: t for t in Tenant.objects.using("default").all()}
        for t in tenants.values():
            if t.db_name and t.db_name not in settings.DATABASES:
                settings.DATABASES[t.db_name] = _make_db_config(t.db_name)

        hw_docs = list(
            SharedDocument.objects.using("default")
            .filter(source_ref__endswith=":handwritten:rx")
        )
        for hw in hw_docs:
            base = hw.source_ref.rsplit(":handwritten:rx", 1)[0]  # "encounter:<id>"
            if SharedDocument.objects.using("default").filter(
                    awpid=hw.awpid, source_ref=base).exclude(pk=hw.pk).exists():
                n["linked"] += 1  # has a typeset sibling — portal links it live
                continue

            enc_id = base.split(":", 1)[1] if ":" in base else ""
            hospital_label, doctor_label, public_id, doc_date = "", "", "", None
            try:
                tenant = tenants.get(hw.source_tenant_id)
                if tenant:
                    hospital_label = tenant.name or ""
                    db = tenant.db_name
                    from apps.opd.models import Prescription, OPDEncounter, Appointment
                    from apps.org.models import StaffUser
                    rx = Prescription.objects.using(db).filter(encounter_id=enc_id).first()
                    if rx:
                        public_id = rx.rx_number or ""
                        try:
                            import uuid as _uuid
                            raw = rx.doctor_user_id.int if isinstance(rx.doctor_user_id, _uuid.UUID) else rx.doctor_user_id
                            nm = StaffUser.objects.using(db).get(pk=raw).get_full_name()
                            doctor_label = f"Dr. {nm}" if nm else ""
                        except Exception:
                            pass
                    enc = OPDEncounter.objects.using(db).filter(pk=enc_id).first()
                    appt = (Appointment.objects.using(db).filter(pk=enc.appointment_id).first()
                            if enc and enc.appointment_id else None)
                    doc_date = appt.scheduled_date if appt else (
                        hw.created_at.date() if hw.created_at else None)
            except Exception:
                logger.warning("tidy_handwritten: tenant lookup failed for %s", hw.source_ref, exc_info=True)

            if dry:
                self.stdout.write(f"  would promote {hw.source_ref} -> {base}  ({doctor_label or '—'} · {hospital_label or '—'})")
                n["promoted"] += 1
                continue

            hw.source_ref = base
            hw.doc_type = "prescription"
            if hospital_label and not hw.hospital_label:
                hw.hospital_label = hospital_label
            if doctor_label and not hw.doctor_label:
                hw.doctor_label = doctor_label
            if public_id and not hw.public_document_id:
                hw.public_document_id = public_id
            if doc_date and not hw.document_date:
                hw.document_date = doc_date
            if not hw.verification_status or hw.verification_status == "unverified":
                hw.verification_status = "verified"
            hw.review_state = "filed"
            if not hw.classification_method:
                hw.classification_method = "staff"
            try:
                hw.save(using="default")
                n["promoted"] += 1
                self.stdout.write(f"  promoted {base}")
            except Exception:
                logger.exception("tidy_handwritten: save failed for %s", hw.source_ref)
                n["err"] += 1

        prefix = "[dry-run] " if dry else ""
        self.stdout.write(
            f"{prefix}{n['promoted']} promoted, {n['linked']} already linked to a typeset Rx, "
            f"{n['skipped']} skipped, {n['err']} errors"
        )
