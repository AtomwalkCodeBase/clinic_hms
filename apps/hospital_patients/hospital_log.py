"""The hospital's own log of what happened to a patient (HospitalEvent) and the documents it issued about it (HospitalDocument).

Events are written by signals, so every place that creates a visit, a bill or a result is covered; documents are written where the file is stored.
An event does not name the row it came from. A document finds its event by the patient, the kind of event and the time: the event is written
the moment the row is saved, so the event closest in time to the row is its own."""
import logging

from django.db.models.signals import post_save, pre_save
from django.utils import timezone

from apps.hospital_patients.models import HospitalDocument, HospitalEvent

logger = logging.getLogger(__name__)


def record_event(db, patient_id, event_type, *, branch_department_id=None, created_by_id=None):
    return HospitalEvent.objects.using(db).create(
        patient_id=patient_id, event_type=event_type, branch_department_id=branch_department_id, created_by_id=created_by_id)


def event_for(db, patient_id, event_type, at):
    """The event of this patient and kind that was written closest to `at` (when the row it came from was saved); one is written if there is none."""
    at = at or timezone.now()
    events = list(HospitalEvent.objects.using(db).filter(patient_id=patient_id, event_type=event_type))
    if not events:
        return record_event(db, patient_id, event_type)
    return min(events, key=lambda event: abs((event.created_at - at).total_seconds()))


def record_document(db, event, file_key):
    """Keep `file_key` (a path in the bucket) as the document of an event. An event has one document of this kind, so recording again replaces its
    file. Returns the previous file's path when it was replaced by a different one, else None."""
    document = HospitalDocument.objects.using(db).filter(event=event).first()
    if document is None:
        HospitalDocument.objects.using(db).create(event=event, file=file_key)
        return None
    old = document.file.name
    document.file = file_key
    document.save(using=db, update_fields=["file"])
    return old if old and old != file_key else None


def _log(event_type, *, patient, branch_department=None, created_by=None, only_if=None, once=None):
    """A post_save receiver that records an event for the saved row. Each argument names how to read it off the row. `once` names a flag set by
    the pre_save receiver when the row already qualified before this save, so a row is logged the first time it qualifies and not again."""
    def receiver(sender, instance, created, using, raw=False, **kwargs):
        if raw or using == "default" or (once is None and not created) or (only_if and not only_if(instance)) or (once and getattr(instance, once, False)):
            return
        try:
            record_event(using, patient(instance), event_type,
                         branch_department_id=branch_department(instance) if branch_department else None,
                         created_by_id=created_by(instance) if created_by else None)
        except Exception:
            logger.exception("hospital event %s not recorded for %s", event_type, instance.pk)
    return receiver


def _remember_signed(sender, instance, using, raw=False, **kwargs):
    """Before a save: note whether the encounter was already signed, so the consultation event is written once."""
    instance._was_signed = bool(not raw and instance.pk and sender.objects.using(using).filter(pk=instance.pk, signed_at__isnull=False).exists())


def connect(apps):
    Appointment, OPDEncounter, Prescription = (apps.get_model("opd", n) for n in ("Appointment", "OPDEncounter", "Prescription"))
    Vitals = apps.get_model("hospital_patients", "Vitals")
    Invoice = apps.get_model("billing", "Invoice")
    HospitalPatient = apps.get_model("hospital_patients", "HospitalPatient")

    for sender, receiver in [
        (HospitalPatient, _log(HospitalEvent.TYPE_REGISTRATION, patient=lambda r: r.pk, created_by=lambda r: r.created_by_id)),
        (Appointment, _log(HospitalEvent.TYPE_APPOINTMENT, patient=lambda r: r.patient_id, branch_department=lambda r: r.branch_department_id)),
        (Vitals, _log(HospitalEvent.TYPE_VITALS, patient=lambda r: r.appointment.patient_id, branch_department=lambda r: r.appointment.branch_department_id,
                      created_by=lambda r: r.recorded_by_id)),
        (OPDEncounter, _log(HospitalEvent.TYPE_CONSULTATION, patient=lambda r: r.appointment.patient_id, once="_was_signed",
                            branch_department=lambda r: r.appointment.branch_department_id, created_by=lambda r: r.appointment.doctor_id,
                            only_if=lambda r: r.signed_at is not None)),
        (Prescription, _log(HospitalEvent.TYPE_PRESCRIPTION, patient=lambda r: r.encounter.appointment.patient_id,
                            branch_department=lambda r: r.encounter.appointment.branch_department_id, created_by=lambda r: r.encounter.appointment.doctor_id)),
        (Invoice, _log(HospitalEvent.TYPE_BILLING, patient=lambda r: r.patient_id, created_by=lambda r: r.created_by_id)),
    ]:
        post_save.connect(receiver, sender=sender, weak=False, dispatch_uid=f"hospital_event_{sender.__name__}")
    pre_save.connect(_remember_signed, sender=OPDEncounter, weak=False, dispatch_uid="hospital_event_encounter_signed")
