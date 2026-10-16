"""Views for documents, the timeline, vaccination and growth, and the immunization and milestone schedules."""
import logging
import time
from apps.documents.models import DOMAIN_CHOICES, Schedule, ScheduleRule
from apps.documents.lib_documents import text, staff_name
from datetime import date
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from apps.patients.services import resolve_target_awpid_and_dob
from core.api.permissions import (
    IsDoctorOrNurse,
    IsPatient,
    IsHospitalAdmin,
    IsPlatformAdmin,
    IsHospitalStaff,
    IsDoctor,
    IsDoctorOrFrontDesk,
)
from core.api.response import error, not_found, success, created
from apps.documents.models import (
    BirthHistory, DocumentBatch, ImmunizationRecord, MilestoneRecord,
)
from apps.documents.serializers import SubmitSerializer, UploadSerializer
from apps.documents.lib_documents import BULK_QUEUE, INSTANT_QUEUE, awaiting_review_q, batch_summary, save_upload, start_processing, submit_decisions
from rest_framework.throttling import ScopedRateThrottle
from core.utils import qr_token as _qt
from core import storage as blob_storage
from apps.documents.lib_roadmap import milestone_rule_dict, schedule_dict, template_dict, vaccination_rule_dict
from django.utils import timezone
from core.utils.file_validation import validate_data_uri, FileValidationError
from core.utils.age import age_years_months
from apps.documents.lib_documents import PATIENT_NOT_FOUND, get_patient, parse_date, staff_name as _staff_name, text as _text
from apps.documents.lib_vitals import add_percentiles
from apps.documents.lib_roadmap import active_schedule, rules_for, schedule_usage
from apps.patients.models import Patient, PatientRelationship
from apps.documents.lib_vitals import growth_points
from core.utils.audit import log_action
from apps.opd.patient_serializers import BirthHistorySerializer
from apps.opd.patient_services import PatientService
from apps.patients.services import accounts
from apps.documents import lib_documents as classification
from apps.documents import lib_documents as records


logger = logging.getLogger(__name__)

class UploadView(APIView):
    """
    POST /api/v1/records/upload/   multipart: files=<file> (repeat for more), mode=instant|bulk, patient_awpid=<optional>

    mode "instant" takes exactly one file and is queued on its own fast lane; "bulk" takes up to 50 and is queued on
    the bulk lane, so a single file never waits behind someone's big upload. Left out, it is "instant" for one file
    and "bulk" for several. The mode is only used to pick the queue; it is not stored.

    Only the sizes are checked here (no empty file, none over 250 MB, 50 files and 250 MB at most). One DocumentBatch
    per upload; every file is stored in S3 under patients/<awpid>/… with a "queued" MedicalDocument, and every file
    is handed to Celery at once. Returns 202 with the batch id; follow it with GET /api/v1/records/batches/<id>/.
    Each document moves queued → extracting → classifying → completed | review_required | failed — the content
    check happens in the extraction job.
    """
    permission_classes = [IsPatient]
    parser_classes = [MultiPartParser]

    def post(self, request):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        serializer = UploadSerializer(data={"files": request.FILES.getlist("files")})
        if not serializer.is_valid():
            return error("Upload rejected — nothing was saved.", errors=serializer.errors)
        files = serializer.validated_data["files"]
        mode = (request.data.get("mode") or ("instant" if len(files) == 1 else "bulk")).strip().lower()
        if mode not in ("instant", "bulk"):
            return error("Upload rejected - mode must be instant or bulk.")
        if mode == "instant" and len(files) != 1:
            return error("Upload rejected - an instant upload takes exactly one file.")
        started = time.monotonic()
        try:
            batch, docs = save_upload(awpid, files)
            logger.info("records: batch %s — %d file(s) stored in %.1fs", batch.id, len(docs), time.monotonic() - started)
        except Exception:
            logger.exception("records: upload to S3 failed")
            return error("Upload to storage failed — nothing was saved. Please try again.", status=503)
        start_processing([d.id for d in docs], INSTANT_QUEUE if mode == "instant" else BULK_QUEUE)
        docs = list(batch.b_documents.order_by("id"))      # fresh: a file that couldn't be queued is already "failed"
        return success(data={
            "batch_id": batch.id, "mode": mode,
            "documents": [{"id": d.id, "file_name": records.display_name(d), "processing_status": d.status} for d in docs],
        }, status=202)


class BatchDetailView(APIView):
    """GET /api/v1/records/batches/<id>/ — the batch, its counts by status, then each of its documents.
    The patient (or the family member they act for) can only read their own batches."""
    permission_classes = [IsPatient]

    def get(self, request, batch_id):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        batch = DocumentBatch.objects.filter(pk=batch_id, patient__awpid=awpid).first()
        if not batch:
            return not_found("Batch not found.")
        return success(data=batch_summary(batch))


class TypesView(APIView):
    """GET /api/v1/records/types/ - the categories a document can be filed under (the one list every app reads).
    {"types": [{"code", "label"}]}"""
    permission_classes = [IsPatient]

    def get(self, request):
        return success(data={"types": classification.document_type_choices()})


class SubmitView(APIView):
    """
    POST /api/v1/records/submit/   {"decisions": [{"document_id": 1, "document_type": "lab_report"}]}   (1 to 100)

    The patient's final answer. Each file is checked on its own (yours, finished reading, not already confirmed, a
    valid type); the ones that pass get the person's type and are locked for good - nobody can change them again.
    Returns {"submitted": [ids], "rejected": [{"document_id", "reason"}], "counts": {"awaiting_review"}}. Sending the
    same list twice is safe: confirmed files are skipped.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        serializer = SubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Nothing was submitted - check the list and try again.", errors=serializer.errors)
        result = submit_decisions(awpid, serializer.validated_data["decisions"])
        from apps.documents.models import MedicalDocument
        result["counts"] = {"awaiting_review": MedicalDocument.objects.using("default")
                            .filter(awaiting_review_q(), patient__awpid=awpid,
                                    status__in=(MedicalDocument.Status.COMPLETED, MedicalDocument.Status.REVIEW_REQUIRED)).count()}
        return success(data=result)
# ------------------------------------------------------------------- view-report   
class DocumentViewView(APIView):
    """
    GET /api/v1/view-report/<token>/

    Verifies the signed token (bare, or the "/view-report/<token>" shape a
    generic scanner hands back unchanged), resolves the MedicalDocument it
    points to, and returns a signed file URL. Any invalid/malformed/unknown
    token returns a patient-safe 400/404 — this is reachable by anyone with a
    camera, never a stack trace.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "view_report"

    def get(self, request, token):
        v = _qt.verify(token)
        if not v.ok or not v.awpid or not v.public_document_id:
            return error(message="This code is invalid.", status=400)

        from apps.documents.models import MedicalDocument

        doc = (
            MedicalDocument.objects.using("default")
            .filter(
                patient__awpid=v.awpid,
                document_ref_name=v.public_document_id,
                doc_classification=v.doc_type,
            )
            .order_by("-created_at")
            .first()
        )
        if not doc:
            return error(message="This document could not be found.", status=404)

        try:
            file_url = blob_storage.signed_url(doc.file_name.name, download_name=records.display_name(doc) or None)
        except Exception:
            logger.exception("view-report: signed_url failed for MedicalDocument id=%s", doc.id)
            return error(message="This document could not be opened right now. Please try again.", status=500)

        return success(data={
            "doc_type": doc.doc_classification,
            "title": records.display_name(doc),
            "document_date": doc.document_date,
            "file_url": file_url,
        })


class _InvalidRule(ValueError):
    """A rule in the request has a number that can't be right; the message says which."""
_NUMBERS = ("min_age_days", "max_age_days", "dose_number", "sort_order")
def _whole_number(value, key):
    """The value as a whole number of 0 or more, or _InvalidRule."""
    try:
        number = int(value) if not isinstance(value, bool) and float(value) == int(float(value)) else None
    except (TypeError, ValueError):
        number = None
    if number is None or number < 0:
        raise _InvalidRule(f"{key.replace('_', ' ').capitalize()} must be a whole number of 0 or more.")
    return number
def _checked_numbers(rd, current=None):
    """The numeric fields given in `rd` as whole numbers, checked against each other (the maximum age may not be below the
    minimum). `current` is the existing rule when editing, so a change to one age is checked against the other."""
    numbers = {k: _whole_number(rd[k], k) for k in _NUMBERS if rd.get(k) not in (None, "")}
    low = numbers.get("min_age_days", getattr(current, "min_age_days", None))
    high = numbers["max_age_days"] if "max_age_days" in numbers else (None if "max_age_days" in rd else getattr(current, "max_age_days", None))
    if low is not None and high is not None and high < low:
        raise _InvalidRule("The maximum age cannot be below the minimum age.")
    return numbers
class _Kind:
    def __init__(self, noun, name_key, extra_key, extra_default, rule_dict, template_message):
        self.noun, self.name_key = noun, name_key
        self.extra_key, self.extra_default = extra_key, extra_default   # dose_number (defaults to 1) / domain (required)
        self.rule_dict, self.template_message = rule_dict, template_message
        self.editable = [name_key, extra_key, "scheduled_label", "min_age_days", "max_age_days", "mandatory", "sort_order"]

    def schedules(self):
        return Schedule.objects.using("default").filter(kind=self.noun)

    def rules(self):
        return ScheduleRule.objects.using("default").filter(schedule__kind=self.noun)

    def new_rule(self, rd, default_sort):
        """The field values for a new rule from a request dict, or None when it is missing something required."""
        if not rd.get(self.name_key) or not rd.get("scheduled_label") or rd.get("min_age_days") is None:
            return None
        if self.extra_default is None and rd.get(self.extra_key) not in dict(DOMAIN_CHOICES):
            return None
        numbers = _checked_numbers(rd)
        return {
            "item": rd[self.name_key], self.extra_key: numbers.get(self.extra_key, rd.get(self.extra_key, self.extra_default)),
            "scheduled_label": rd["scheduled_label"], "min_age_days": numbers["min_age_days"],
            "max_age_days": numbers.get("max_age_days"), "mandatory": rd.get("mandatory", True),
            "sort_order": numbers.get("sort_order", default_sort),
        }

    def rules_json(self, schedule):
        rules = schedule.s_rules.all().order_by("sort_order")
        return rules, [self.rule_dict(r) for r in rules]
VACCINATION = _Kind("vaccination", "vaccine_name", "dose_number", 1,
                    vaccination_rule_dict, "Vaccination schedule template created.")
MILESTONE = _Kind("milestone", "milestone", "domain", None,
                  milestone_rule_dict, "Milestone schedule template created.")
def _edit(kind, schedule, d):
    """Apply a PATCH body to a schedule and its rules. Returns how many rule changes were made. Raises _InvalidRule, before
    anything is saved, when a rule's numbers are wrong."""
    rules_in = [rd for rd in (d["rules"] if isinstance(d.get("rules"), list) else []) if isinstance(rd, dict)]
    existing = {str(r.id): r for r in schedule.s_rules.all()}
    checked = {}
    for rd in rules_in:
        if rd.get("_delete"):
            continue
        current = existing.get(str(rd.get("id"))) if rd.get("id") else None
        if "min_age_days" in rd and rd["min_age_days"] in (None, ""):
            raise _InvalidRule("Minimum age is required.")
        checked[id(rd)] = _checked_numbers(rd, current) if (current or rd.get("min_age_days") is not None) else {}
        if not rd.get("id"):
            kind.new_rule(rd, 0)                                    # also checks the rest of a new rule

    changed = []
    if "name" in d and (d["name"] or "").strip():
        schedule.name = d["name"].strip()
        changed.append("name")
    if "description" in d:
        schedule.description = d["description"] or ""
        changed.append("description")
    if "active" in d:
        schedule.active = bool(d["active"])
        changed.append("active")
    if changed:
        schedule.save(using="default", update_fields=changed)

    touched = 0
    for rd in rules_in:
        rid = rd.get("id")
        if rid and rd.get("_delete"):
            ScheduleRule.objects.using("default").filter(pk=rid, schedule=schedule).delete()
            touched += 1
        elif rid:
            rule = ScheduleRule.objects.using("default").filter(pk=rid, schedule=schedule).first()
            fields = [f for f in kind.editable if f in rd] if rule else []
            for f in fields:
                setattr(rule, "item" if f == kind.name_key else f,
                        checked[id(rd)].get(f, None if rd[f] in (None, "") else rd[f]) if f in _NUMBERS else rd[f])
            if fields:
                rule.save(using="default", update_fields=["item" if f == kind.name_key else f for f in fields])
                touched += 1
        else:
            values = kind.new_rule(rd, 0)
            if values:
                ScheduleRule.objects.using("default").create(schedule=schedule, **values)
                touched += 1
    return touched
def _clone_template(request, kind, template, name):
    """The hospital's own copy of a template, switched on (the hospital's other schedules of this kind are switched off)."""
    clone = Schedule.objects.using("default").create(kind=kind.noun,
        name=name, description=template.description, owner_hospital_id=request.hospital_id, is_template=False, active=True)
    rules = list(kind.rules().filter(schedule=template).order_by("sort_order"))
    ScheduleRule.objects.using("default").bulk_create([
        ScheduleRule(schedule=clone, item=r.item, dose_number=r.dose_number, domain=r.domain,
                  scheduled_label=r.scheduled_label, min_age_days=r.min_age_days, max_age_days=r.max_age_days,
                  mandatory=r.mandatory, sort_order=r.sort_order)
        for r in rules])
    _set_active(request, kind, clone)
    return clone, rules
def _set_active(request, kind, schedule):
    from apps.hospital_master.models import Hospital
    hospital = Hospital.objects.using("default").filter(pk=request.hospital_id).first()
    if hospital:
        kind.schedules().filter(owner_hospital_id=hospital.id).exclude(pk=schedule.pk).update(active=False)
    return hospital
# ── hospital admin ────────────────────────────────────────────────────────────────────────────────────────────────
def hospital_views(kind):
    class ListCreate(APIView):
        permission_classes = [IsAuthenticated, IsHospitalAdmin]

        def get(self, request):
            active = active_schedule(kind.noun, request.hospital_id)
            active_id = active.id if active else None
            own = kind.schedules().filter(owner_hospital_id=request.hospital_id).order_by("-created_at")
            templates = (kind.schedules()
                         .filter(owner_hospital_id__isnull=True, is_template=True, active=True).order_by("name"))
            return success(data={
                "own_schedules": [schedule_dict(s, active_id) for s in own],
                "templates": [schedule_dict(s, active_id) for s in templates],
                "active_schedule_id": active_id,
            })

        def post(self, request):
            template_id = request.data.get("template_id")
            if not template_id:
                return error("template_id is required.", errors={"template_id": "Required."})
            template = kind.schedules().filter(
                pk=template_id, owner_hospital_id__isnull=True, is_template=True).first()
            if not template:
                return not_found("Template schedule not found.")

            name = (request.data.get("name") or "").strip() or f"{template.name} (customized)"
            clone, rules = _clone_template(request, kind, template, name)
            label = "" if kind is VACCINATION else f"{kind.noun} "
            return created(data=schedule_dict(clone, clone.id, len(rules)),
                           message=f"Cloned '{template.name}' and set as this hospital's active {label}schedule.")

    class Detail(APIView):
        permission_classes = [IsAuthenticated, IsHospitalAdmin]

        def get(self, request, pk):
            schedule = kind.schedules().filter(pk=pk).first()
            if not schedule or schedule.owner_hospital_id not in (None, request.hospital_id):
                return not_found("Schedule not found.")
            rules, rules_json = kind.rules_json(schedule)
            return success(data={**schedule_dict(schedule, rule_count=len(rules)), "rules": rules_json})

        def patch(self, request, pk):
            schedule = kind.schedules().filter(pk=pk, owner_hospital_id=request.hospital_id).first()
            if not schedule:
                return not_found("Schedule not found, or not owned by this hospital — clone a template first.")
            try:
                touched = _edit(kind, schedule, request.data)
            except _InvalidRule as exc:
                return error(str(exc))
            rules, rules_json = kind.rules_json(schedule)
            return success(data={**schedule_dict(schedule, rule_count=len(rules)), "rules": rules_json},
                           message=f"Schedule updated ({touched} rule change(s)).")

    class Activate(APIView):
        """Make an own schedule this hospital's active one. A system template is copied first, since a hospital runs on its own copy."""
        permission_classes = [IsAuthenticated, IsHospitalAdmin]

        def post(self, request, pk):
            schedule = kind.schedules().filter(pk=pk, active=True).first()
            if not schedule:
                return not_found("Schedule not found.")
            if schedule.owner_hospital_id not in (None, request.hospital_id):
                return error("You can only activate your own schedules or a system template.")
            if schedule.owner_hospital_id is None:
                schedule, _ = _clone_template(request, kind, schedule, schedule.name)
            elif not _set_active(request, kind, schedule):
                return not_found("Hospital not found.")
            else:
                kind.schedules().filter(pk=schedule.pk).update(active=True)
            return success(data={"active_schedule_id": schedule.id},
                           message=f"'{schedule.name}' is now this hospital's active {kind.noun} schedule.")

    return ListCreate, Detail, Activate
# ── platform admin ────────────────────────────────────────────────────────────────────────────────────────────────
def template_views(kind):
    def get_template(pk):
        return kind.schedules().filter(pk=pk, owner_hospital_id__isnull=True, is_template=True).first()

    class ListCreate(APIView):
        permission_classes = [IsAuthenticated, IsPlatformAdmin]

        def get(self, request):
            templates = (kind.schedules()
                         .filter(owner_hospital_id__isnull=True, is_template=True).order_by("name"))
            using = schedule_usage(kind.noun)
            return success(data=[template_dict(t, hospitals_using=using.get(t.id, 0)) for t in templates])

        def post(self, request):
            d = request.data
            name = (d.get("name") or "").strip()
            if not name:
                return error("Name is required.", errors={"name": "Required."})
            rules_in = d.get("rules") if isinstance(d.get("rules"), list) else []
            try:
                checked = [kind.new_rule(rd, i) if isinstance(rd, dict) else None for i, rd in enumerate(rules_in)]
            except _InvalidRule as exc:
                return error(str(exc))
            template = Schedule.objects.using("default").create(kind=kind.noun, 
                name=name, description=(d.get("description") or "").strip(), owner_hospital_id=None,
                is_template=True, active=bool(d.get("active", True)))
            rules = [ScheduleRule(schedule=template, **values) for values in checked if values]
            if rules:
                ScheduleRule.objects.using("default").bulk_create(rules)
            return created(data=template_dict(template, rule_count=len(rules), hospitals_using=0),
                           message=kind.template_message)

    class Detail(APIView):
        permission_classes = [IsAuthenticated, IsPlatformAdmin]

        def get(self, request, pk):
            template = get_template(pk)
            if not template:
                return not_found("Template not found.")
            rules, rules_json = kind.rules_json(template)
            return success(data={**template_dict(template, rule_count=len(rules)), "rules": rules_json})

        def patch(self, request, pk):
            template = get_template(pk)
            if not template:
                return not_found("Template not found.")
            try:
                touched = _edit(kind, template, request.data)
            except _InvalidRule as exc:
                return error(str(exc))
            rules, rules_json = kind.rules_json(template)
            return success(data={**template_dict(template, rule_count=len(rules)), "rules": rules_json},
                           message=f"Template updated ({touched} rule change(s)).")

        def delete(self, request, pk):
            template = get_template(pk)
            if not template:
                return not_found("Template not found.")
            in_use = schedule_usage(kind.noun).get(template.id, 0)
            if in_use:
                return error(
                    f"{in_use} hospital(s) currently have this template set as their active {kind.noun} schedule — "
                    "it can't be deleted while in use. Deactivate it instead, or have those hospitals "
                    "switch schedules first.", status=400)
            template.delete(using="default")
            return success(message="Template deleted.")

    return ListCreate, Detail
VaccinationScheduleListCreateView, VaccinationScheduleDetailView, VaccinationScheduleActivateView = hospital_views(VACCINATION)
MilestoneScheduleListCreateView, MilestoneScheduleDetailView, MilestoneScheduleActivateView = hospital_views(MILESTONE)
VaccinationTemplateListCreateView, VaccinationTemplateDetailView = template_views(VACCINATION)
MilestoneTemplateListCreateView, MilestoneTemplateDetailView = template_views(MILESTONE)


V = ImmunizationRecord
def _given(request):
    """The fields that make a record a verified dose given at this clinic."""
    return {"source": V.SOURCE_CLINIC, "verification_status": V.STATUS_VERIFIED,
            "verified_by_name": _staff_name(request), "verified_at": timezone.now()}
def _new_record(request, patient, **fields):
    return V.objects.using("default").create(
        patient=Patient.objects.using("default").filter(awpid=patient.awpid).first(),
        source_hospital_id=request.hospital_id, **fields)
def _already_recorded(patient, name, given_on, dose_number):
    """The same dose (vaccine, date and dose number) is already on this child's record."""
    return V.objects.using("default").filter(
        patient__awpid=patient.awpid, vaccine_name__iexact=name, administered_date=given_on, dose_number=dose_number).exists()
_DUPLICATE = "This dose is already recorded for this patient."
def _given_json(record):
    return {"id": record.id, "vaccine_name": record.vaccine_name, "administered_date": str(record.administered_date),
            "verification_status": record.verification_status, "has_certificate": bool(record.file_data)}
def _certificate(patient, data, vaccine_name):
    """
    The optional scanned certificate sent with a dose: (file_name, mime_type, stored_key, error_response).
    No file sent -> three empty strings. A bad file -> error_response is ready to return.
    """
    file_data = data.get("file_data") or ""
    if not file_data:
        return "", "", "", None
    try:
        mime_type = validate_data_uri(file_data)
        key = blob_storage.upload_data_uri(
            file_data, prefix="vaccination-certs", mime_type=mime_type, category="vaccination-certificate",
            identity=blob_storage.identity_slug(name=patient.full_name, identifier=patient.awpid))
    except (FileValidationError, blob_storage.StorageError) as exc:
        return None, None, None, error(str(exc), errors={"file_data": str(exc)})
    name = blob_storage.display_file_name("vaccination-certificate", mime_type, detail=vaccine_name,
                                          name=patient.full_name, identifier=patient.awpid)
    return name, mime_type, key, None
# ── vaccinations ──────────────────────────────────────────────────────────────────────────────────────────────────
class PatientVaccinationListCreateView(APIView):
    def get_permissions(self):
        return [IsHospitalStaff() if self.request.method == "GET" else IsDoctorOrNurse()]

    def get(self, request, pk):
        from apps.documents.lib_roadmap import build_roadmap

        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        roadmap = build_roadmap(patient.awpid, patient.date_of_birth, rules_for("vaccination", request.hospital_id),
                                viewer_hospital_id=request.hospital_id, hie_consent=patient.hie_consent_given)
        return success(data={"patient_name": patient.full_name, "date_of_birth": patient.date_of_birth,
                             "consent_given": patient.hie_consent_given, "roadmap": roadmap})

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        name = _text(d, "vaccine_name")
        if not name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not d.get("administered_date"):
            return error("Administered date is required.", errors={"administered_date": "Required."})
        given_on, err = parse_date(d["administered_date"], "administered_date", "Administered date")
        if err:
            return err
        if _already_recorded(patient, name, given_on, d.get("dose_number") or None):
            return error(_DUPLICATE, status=409)
        file_name, mime_type, key, err = _certificate(patient, d, name)
        if err:
            return err
        record = _new_record(request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"),
                             administered_date=given_on, dose_number=d.get("dose_number") or None, file_name=file_name, mime_type=mime_type,
                             file_data=key, **_given(request))
        return created(data=_given_json(record), message="Vaccination logged.")
class PatientVaccinationVerifyView(APIView):
    """Body: {action: "verify" | "reject", review_notes?}. Any hospital's doctor or nurse can review a parent's upload."""
    permission_classes = [IsDoctorOrNurse]

    def patch(self, request, pk):
        record = V.objects.using("default").filter(pk=pk).first()
        if not record:
            return not_found("Vaccination record not found.")
        action = _text(request.data, "action")
        if action not in ("verify", "reject"):
            return error("action must be 'verify' or 'reject'.", errors={"action": "Invalid."})
        record.verification_status = V.STATUS_VERIFIED if action == "verify" else V.STATUS_REJECTED
        record.verified_by_name = _staff_name(request)
        record.verified_at = timezone.now()
        record.review_notes = _text(request.data, "review_notes")
        record.source_hospital_id = record.source_hospital_id or request.hospital_id      # first hospital to review claims it
        record.save(using="default", update_fields=[
            "verification_status", "verified_by_name", "verified_at", "review_notes", "source_hospital_id"])
        return success(data={"id": record.id, "verification_status": record.verification_status},
                       message=f"Vaccination record {action}d.")
class PatientVaccinationOrderView(APIView):
    """Doctor recommends a vaccine that isn't given yet. Body: {vaccine_name, reason, due_date?, scheduled_label?, dose_number?}"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        name, reason = _text(d, "vaccine_name"), _text(d, "reason")
        if not name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not reason:
            return error("A clinical reason is required for an ad-hoc order.", errors={"reason": "Required."})
        due_on, err = parse_date(d.get("due_date"), "due_date", "Due date", allow_future=True)
        if err:
            return err
        record = _new_record(
            request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"), reason=reason,
            due_date=due_on, dose_number=d.get("dose_number") or None, administered_date=None,
            source=V.SOURCE_DOCTOR_ORDERED, verification_status=V.STATUS_ORDERED,
            verified_by_name=_staff_name(request, "Doctor"))
        return created(data={"id": record.id, "vaccine_name": record.vaccine_name, "reason": record.reason,
                             "due_date": str(record.due_date) if record.due_date else None,
                             "verification_status": record.verification_status}, message="Vaccine order recorded.")
class PatientVaccinationDeclineView(APIView):
    """Doctor marks a slot not required. Body: {record_id?} for an existing record, else {vaccine_name, scheduled_label?}; reason?"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        if d.get("record_id"):
            record = V.objects.using("default").filter(pk=d["record_id"], patient__awpid=patient.awpid).first()
            if not record:
                return not_found("Vaccination record not found for this patient.")
        else:
            name = _text(d, "vaccine_name")
            if not name:
                return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
            record = _new_record(request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"),
                                 administered_date=None, source=V.SOURCE_DOCTOR_ORDERED,
                                 verification_status=V.STATUS_DECLINED)
        reason = _text(d, "reason")
        record.verification_status = V.STATUS_DECLINED
        record.reason = reason or record.reason
        record.review_notes = reason or record.review_notes
        record.verified_by_name = _staff_name(request, "Doctor")
        record.verified_at = timezone.now()
        record.source_hospital_id = record.source_hospital_id or request.hospital_id
        record.save(using="default", update_fields=[
            "verification_status", "reason", "review_notes", "verified_by_name", "verified_at", "source_hospital_id"])
        return success(data={"id": record.id, "vaccine_name": record.vaccine_name,
                             "verification_status": record.verification_status}, message="Vaccine marked as not required.")
class PatientVaccinationAdministerView(APIView):
    """
    Nurse or doctor marks a dose given today (or on administered_date).
    Body: {record_id?} to close an existing record (typically a doctor's order) in place, else {vaccine_name,
    scheduled_label?} to log a new one; administered_date?, dose_number?, file_data?.
    """
    permission_classes = [IsDoctorOrNurse]

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        record = None
        if d.get("record_id"):
            record = V.objects.using("default").filter(pk=d["record_id"], patient__awpid=patient.awpid).first()
            if not record:
                return not_found("Vaccination record not found for this patient.")
        name = record.vaccine_name if record else _text(d, "vaccine_name")
        if not name:
            return error("vaccine_name or record_id is required.", errors={"vaccine_name": "Required."})

        given_on, err = parse_date(d.get("administered_date"), "administered_date", "Administered date")
        if err:
            return err
        given_on = given_on or date.today()
        if record is None and _already_recorded(patient, name, given_on, d.get("dose_number") or None):
            return error(_DUPLICATE, status=409)
        file_name, mime_type, key, err = _certificate(patient, d, name)
        if err:
            return err
        fields = {"administered_date": given_on, "dose_number": d.get("dose_number") or None, **_given(request)}
        if key:
            fields.update(file_name=file_name, mime_type=mime_type, file_data=key)

        if record is None:
            record = _new_record(request, patient, vaccine_name=name, scheduled_label=_text(d, "scheduled_label"), **fields)
        else:
            old_key = record.file_data
            if not fields["dose_number"]:
                del fields["dose_number"]                                   # keep the dose the order already had
            fields.update(source_hospital_id=record.source_hospital_id or request.hospital_id)
            for field, value in fields.items():
                setattr(record, field, value)
            record.save(using="default", update_fields=list(fields))
            if key and old_key:
                blob_storage.delete(old_key)                                # the new certificate replaces the old file
        return success(data=_given_json(record), message="Vaccination recorded as administered.")


def _shared_patient(patient):
    """The patient's row in Atomwalk, where the birth history is kept for every hospital."""
    return Patient.objects.using("default").filter(awpid=patient.awpid).first()
class BirthHistoryView(APIView):
    def get_permissions(self):
        return [IsHospitalStaff() if self.request.method == "GET" else IsDoctorOrFrontDesk()]

    def get(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        bh = BirthHistory.objects.using("default").filter(patient__awpid=patient.awpid).first()
        if not bh:
            return success(data=None, message="No birth history recorded yet.")
        return success(data=BirthHistorySerializer(bh).data)

    def post(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        shared = _shared_patient(patient)
        if not shared:
            return error("This patient has no shared identity yet, so a birth history can't be kept for them.", status=400)
        if BirthHistory.objects.using("default").filter(patient=shared).exists():
            return error("Birth history already exists for this patient — use PATCH to edit it.", status=400)
        serializer = BirthHistorySerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        bh = BirthHistory.objects.using("default").create(
            patient=shared, source_hospital_id=request.hospital_id, **serializer.validated_data)
        log_action(request, request.hospital_db, "birth_history.create", resource_type="BirthHistory",
                   resource_id=bh.id, patient_id=patient.uuid, metadata={"replaced_other_hospitals_copy": None})
        return created(data=BirthHistorySerializer(bh).data, message="Birth history recorded.")

    def patch(self, request, pk):
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        bh = BirthHistory.objects.using("default").filter(patient__awpid=patient.awpid).first()
        if not bh:
            return not_found("No birth history recorded yet for this patient — use POST to create it.")
        serializer = BirthHistorySerializer(bh, data=request.data, partial=True)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        before = {f: getattr(bh, f) for f in serializer.validated_data}
        previous_hospital = bh.source_hospital_id
        serializer.save(source_hospital_id=request.hospital_id)
        changed = {f: [str(old), str(getattr(bh, f))] for f, old in before.items() if getattr(bh, f) != old}
        replaced = previous_hospital if previous_hospital not in (None, request.hospital_id) else None
        log_action(request, request.hospital_db, "birth_history.update", resource_type="BirthHistory",
                   resource_id=bh.id, patient_id=patient.uuid,
                   metadata={"changed": changed, "replaced_other_hospitals_copy": replaced})
        return success(data=BirthHistorySerializer(bh).data, message="Birth history updated.")
class PatientMilestoneListCreateView(APIView):
    """POST body: {domain, milestone, status ("achieved" | "not_yet" | "concern"), scheduled_label?, achieved_date?, assessed_date?, notes?}"""
    permission_classes = [IsDoctorOrNurse]

    def get(self, request, pk):
        from apps.documents.lib_roadmap import milestone_roadmap_build_roadmap as build_roadmap

        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        roadmap = build_roadmap(patient.awpid, patient.date_of_birth, rules_for("milestone", request.hospital_id),
                                viewer_hospital_id=request.hospital_id, hie_consent=patient.hie_consent_given)
        return success(data={"patient_name": patient.full_name, "date_of_birth": patient.date_of_birth,
                             "consent_given": patient.hie_consent_given, "roadmap": roadmap})

    def post(self, request, pk):
        M = MilestoneRecord
        patient = get_patient(request, pk)
        if not patient:
            return not_found(PATIENT_NOT_FOUND)
        d = request.data
        domain, milestone = text(d, "domain"), text(d, "milestone")
        status = text(d, "status") or M.STATUS_ACHIEVED
        if domain not in dict(M._meta.get_field("domain").choices):
            return error("A valid domain is required.", errors={"domain": "Required/invalid."})
        if not milestone:
            return error("Milestone is required.", errors={"milestone": "Required."})
        if status not in dict(M.STATUS_CHOICES):
            return error("Invalid status.", errors={"status": "Invalid."})

        achieved_on, err = parse_date(d.get("achieved_date"), "achieved_date", "Achieved date")
        if err:
            return err
        assessed_on, err = parse_date(d.get("assessed_date"), "assessed_date", "Assessed date")
        if err:
            return err
        # only an achieved milestone has an achieved date (today unless one is given)
        achieved = (achieved_on or date.today()) if status == M.STATUS_ACHIEVED else None
        record = M.objects.using("default").create(
            patient=_shared_patient(patient), domain=domain, milestone=milestone, scheduled_label=text(d, "scheduled_label"),
            status=status, achieved_date=achieved, assessed_date=assessed_on or date.today(),
            notes=text(d, "notes"), recorded_by_name=staff_name(request), source_hospital_id=request.hospital_id)
        return created(data={
            "id": record.id, "domain": record.domain, "milestone": record.milestone, "status": record.status,
            "achieved_date": str(record.achieved_date) if record.achieved_date else None,
            "assessed_date": str(record.assessed_date) if record.assessed_date else None,
        }, message="Milestone assessment recorded.")


_MAX_CERTIFICATE_CHARS = 15_500_000      # about 11 MB of base64, the same cap as document uploads
def _account(request):
    return accounts().get(pk=request.user.id)
# ── growth ────────────────────────────────────────────────────────────────────────────────────────────────────────
class PortalGrowthView(APIView):
    """Readings come from growth_measurement and vitals (every hospital's visits), with source "clinic" or "home"."""
    permission_classes = [IsPatient]

    def get(self, request):
        awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        series = growth_points(awpid)
        age = age_years_months(dob)
        is_minor = age is not None and age[0] < 18
        gender = getattr(Patient.objects.using("default").filter(awpid=awpid).first(), "gender", None)
        return success(data={
            "date_of_birth": dob,
            "age_years": age[0] if age else None,
            "age_months": age[1] if age else None,
            "is_minor": is_minor,
            "series": series,
            "latest": series[-1] if series else None,
            "percentile_available": is_minor and add_percentiles(series, gender, dob),
        })
# ── roadmaps ──────────────────────────────────────────────────────────────────────────────────────────────────────
class PortalVaccinationListView(APIView):
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.documents.lib_roadmap import build_roadmap, summarize_roadmap

        awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        roadmap = build_roadmap(awpid, dob, rules_for("vaccination"))
        summary = summarize_roadmap(roadmap)
        return success(data={"date_of_birth": dob, "roadmap": roadmap, "completed_count": summary["completed_count"],
                             "total_count": summary["total_count"], "next_recommended": summary["next_recommended"],
                             "stats": summary["stats"]})
class PortalMilestoneListView(APIView):
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.documents.lib_roadmap import milestone_roadmap_build_roadmap as build_roadmap, milestone_roadmap_summarize_roadmap as summarize_roadmap

        awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        roadmap = build_roadmap(awpid, dob, rules_for("milestone"))
        summary = summarize_roadmap(roadmap)
        return success(data={"date_of_birth": dob, "roadmap": roadmap, "achieved_count": summary["achieved_count"],
                             "total_count": summary["total_count"], "next_recommended": summary["next_recommended"],
                             "stats": summary["stats"]})
# ── vaccination uploads ───────────────────────────────────────────────────────────────────────────────────────────
class PortalVaccinationUploadView(APIView):
    """
    Body: {vaccine_name, administered_date, scheduled_label?, patient_awpid?, file_data?}.
    A parent reports a dose given outside the network, optionally with a certificate photo. It always lands as
    "pending_review": only a doctor or nurse verifying it (PatientVaccinationVerifyView) makes it count as verified.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        d = request.data
        name = text(d, "vaccine_name")
        if not name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not d.get("administered_date"):
            return error("Administered date is required.", errors={"administered_date": "Required."})
        given_on, err = parse_date(d["administered_date"], "administered_date", "Administered date")
        if err:
            return err

        file_name, mime_type, file_key = text(d, "file_name"), text(d, "mime_type"), d.get("file_data") or ""
        if file_key:
            if len(file_key) > _MAX_CERTIFICATE_CHARS:
                return error("File is too large. Please upload a smaller file (under ~11MB).")
            owner = Patient.objects.using("default").filter(awpid=awpid).first()
            owner_name = owner.full_name if owner else ""
            try:
                mime_type = validate_data_uri(file_key)
                file_key = blob_storage.upload_data_uri(
                    file_key, prefix="vaccination-certs", mime_type=mime_type, category="vaccination-certificate",
                    identity=blob_storage.identity_slug(name=owner_name, identifier=awpid))
            except (FileValidationError, blob_storage.StorageError) as exc:
                return error(str(exc), errors={"file_data": str(exc)})
            file_name = blob_storage.display_file_name("vaccination-certificate", mime_type, detail=name,
                                                       name=owner_name, identifier=awpid)

        record = ImmunizationRecord.objects.using("default").create(
            patient=Patient.objects.using("default").filter(awpid=awpid).first(), vaccine_name=name, scheduled_label=text(d, "scheduled_label"), administered_date=given_on,
            source=ImmunizationRecord.SOURCE_SELF_REPORTED, verification_status=ImmunizationRecord.STATUS_PENDING,
            file_name=file_name, mime_type=mime_type, file_data=file_key)
        return success(data={"id": record.id, "vaccine_name": record.vaccine_name,
                             "administered_date": str(record.administered_date),
                             "verification_status": record.verification_status},
                       message="Submitted. This will show as pending review until a doctor confirms it.")
class PortalVaccinationFileView(APIView):
    """One certificate. The roadmap only says has_certificate; the file is fetched here, for the account or its family."""
    permission_classes = [IsPatient]

    def get(self, request, record_id):
        record = ImmunizationRecord.objects.using("default").filter(pk=record_id).first()
        if not record:
            return not_found("Vaccination record not found.")
        account = _account(request)
        owner_awpid = record.patient.awpid if record.patient_id else ""
        if owner_awpid != account.awpid and not PatientRelationship.objects.using("default").filter(
                guardian__awpid=account.awpid, dependent__awpid=owner_awpid).exists():
            return error("This record does not belong to you.", status=403)
        if not record.file_data:
            return not_found("No certificate has been uploaded for this record.")
        return success(data={"file_data": blob_storage.signed_url(record.file_data),
                             "file_name": record.file_name, "mime_type": record.mime_type})
# ── family ────────────────────────────────────────────────────────────────────────────────────────────────────────
class PortalFamilyListCreateView(APIView):
    """
    POST body: {full_name, date_of_birth, gender?, relationship?}. A member added here and one added by a hospital's
    front desk under the same guardian resolve to the same AWPID (matched on name and date of birth).
    """
    permission_classes = [IsPatient]

    def get(self, request):
        return success(data={"results": PatientService.list_family_members(_account(request).awpid)})

    def post(self, request):
        account, d = _account(request), request.data
        try:
            member = PatientService.add_family_member(
                guardian_awpid=account.awpid, guardian_mobile=account.mobile,
                data={"full_name": text(d, "full_name"), "date_of_birth": d.get("date_of_birth"),
                      "gender": d.get("gender", ""), "relationship": d.get("relationship", "other")})
        except ValueError as exc:
            return error(str(exc))
        return success(data=member, message="Family member added." if member.get("created")
                       else "Reconnected — their existing records are linked again.")
class PortalFamilyDetailView(APIView):
    """Edit a family member, or unlink them from this account (their records stay). Only for members linked to the account."""
    permission_classes = [IsPatient]

    def patch(self, request, awpid):
        changes = {k: request.data.get(k) for k in ("full_name", "date_of_birth", "gender", "relationship") if k in request.data}
        try:
            member = PatientService.update_family_member(
                guardian_awpid=_account(request).awpid, dependent_awpid=awpid, data=changes)
        except ValueError as exc:
            return error(str(exc))
        return success(data=member, message="Family member updated.")

    def delete(self, request, awpid):
        try:
            PatientService.remove_family_member(guardian_awpid=_account(request).awpid, dependent_awpid=awpid)
        except ValueError as exc:
            return error(str(exc))
        return success(message="Family member removed.")
