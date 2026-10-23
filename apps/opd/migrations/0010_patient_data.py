"""Phase 2 of 3: move what only this hospital knows into the new tables, and make sure the shared patient record holds who the patient is.

The shared record (atomwalk) is the one place for name, birth date, gender, blood group, email, mobile, language, emergency contact and guardian.
Where it lacks a value the hospital row has, the value is copied there first (never overwriting one it already has); a hospital patient with
no shared record at all gets one, so no identity is lost when the hospital's copy is dropped in phase 3.
"""
import re

from django.db import migrations

CONTACT_FIELDS = ["emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation"]


def _digits(raw):
    """The mobile number as the shared record keeps it: the last 10 digits."""
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else ""


def forward(apps, schema_editor):
    db = schema_editor.connection.alias
    HospitalPatient = apps.get_model("opd", "HospitalPatient")
    PatientPayer = apps.get_model("opd", "PatientPayer")
    PatientDetail = apps.get_model("opd", "PatientDetail")
    PatientEmergencyIntake = apps.get_model("opd", "PatientEmergencyIntake")
    Patient = apps.get_model("patients", "Patient")

    rows = list(HospitalPatient.objects.using(db).all())
    if not rows:
        return
    shared = {p.awpid: p for p in Patient.objects.using("default").filter(awpid__in=[r.awpid for r in rows])}

    for row in rows:
        # what only this hospital knows
        if row.payer_type != "self" or row.insurance_provider or row.policy_number or row.tpa_name:
            PatientPayer.objects.using(db).create(
                patient_id=row.pk, payer_type=row.payer_type, insurance_provider=row.insurance_provider,
                policy_number=row.policy_number, tpa_name=row.tpa_name)
        if (row.alternate_mobile or row.address_line1 or row.city or row.state or row.pincode or row.marital_status
                or row.occupation or row.nationality not in ("", "Indian")):
            PatientDetail.objects.using(db).create(
                patient_id=row.pk, alternate_mobile=row.alternate_mobile, address_line1=row.address_line1, city=row.city,
                state=row.state, pincode=row.pincode, marital_status=row.marital_status, nationality=row.nationality,
                occupation=row.occupation)
        if row.identity_status != "confirmed" or row.is_mlc or row.arrival_channel or row.placeholder_label or row.consent_deferred_reason:
            noted_here_only = not (shared.get(row.awpid) and shared[row.awpid].mobile)
            PatientEmergencyIntake.objects.using(db).create(
                patient_id=row.pk, identity_status=row.identity_status, is_mlc=row.is_mlc, arrival_channel=row.arrival_channel,
                placeholder_label=row.placeholder_label, consent_deferred_reason=row.consent_deferred_reason,
                mobile=row.mobile if noted_here_only else "", guardian_name=row.guardian_name, guardian_mobile=row.guardian_mobile)

        # who the patient is: into the shared record where it lacks it
        person = shared.get(row.awpid)
        if person is None:
            person = Patient.objects.using("default").create(
                awpid=row.awpid, full_name=row.full_name or row.placeholder_label or "Unknown patient", date_of_birth=row.date_of_birth,
                gender=row.gender, mobile=_digits(row.mobile) or None, guardian_mobile=_digits(row.guardian_mobile) or None,
                is_dependent=row.is_dependent, email=row.email, blood_group=row.blood_group,
                preferred_language=row.preferred_language, created_by="hospital",
                emergency_contact_name=row.emergency_contact_name, emergency_contact_phone=row.emergency_contact_phone,
                emergency_contact_relation=row.emergency_contact_relation)
            shared[row.awpid] = person
            continue
        changed = []
        for field in ("full_name", "date_of_birth", "gender", "blood_group", "email", "preferred_language"):
            if not getattr(person, field) and getattr(row, field):
                setattr(person, field, getattr(row, field))
                changed.append(field)
        for field in CONTACT_FIELDS:
            if not getattr(person, field) and getattr(row, field):
                setattr(person, field, getattr(row, field))
                changed.append(field)
        if not person.mobile and _digits(row.mobile) and not Patient.objects.using("default").filter(mobile=_digits(row.mobile)).exists():
            person.mobile = _digits(row.mobile)
            changed.append("mobile")
        if not person.guardian_mobile and _digits(row.guardian_mobile):
            person.guardian_mobile = _digits(row.guardian_mobile)
            changed.append("guardian_mobile")
        if row.is_dependent and not person.is_dependent:
            person.is_dependent = True
            changed.append("is_dependent")
        if changed:
            person.save(using="default", update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0009_patient_add"),
        ("patients", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
