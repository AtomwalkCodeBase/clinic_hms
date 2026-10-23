"""OPD API Views"""

import logging
from datetime import date, timedelta
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from core.api.permissions import IsHospitalStaff as IsHospitalStaff, IsDoctor, IsDoctorOrNurse, RequireFeature
from core.api.pagination import paginate_queryset
from core.api.response import error as api_error, not_found as api_not_found, forbidden as api_forbidden, success

from apps.billing.models import OptionList
from apps.billing.option_list_views import DropdownListCreateView, DropdownDetailView
from apps.documents.lib_vitals import sync_encounter_to_hie
from apps.opd.services import auto_generate_invoice

from apps.hospital_setup.rbac import acts_as_q
from apps.hospital_setup.models import StaffUser
from apps.opd.models import Appointment, HospitalPatient, OPDEncounter, Prescription, PrescriptionItem
from apps.opd.patient_services import PatientService
from apps.opd.vitals_service import record_vitals
from apps.documents.lib_vitals import attach_vitals, recorded
from apps.opd.serializers import (
    AppointmentSerializer,
    AppointmentCreateSerializer,
    AppointmentStatusUpdateSerializer,
    OPDEncounterSerializer,
    OPDEncounterCreateSerializer,
    PrescriptionSerializer,
    PrescriptionItemSerializer,
    PrescriptionFavouriteSerializer,
    VitalsSerializer,
    FollowUpActionSerializer,
    AppointmentTypeSerializer,
)

logger = logging.getLogger(__name__)


# ── Appointment Type catalog — "make it configurable" ───────────────────────
class AppointmentTypeListCreateView(DropdownListCreateView):
    list_type = OptionList.LIST_APPOINTMENT_TYPE
    serializer_class = AppointmentTypeSerializer
    identity_field = "name"
    model_field = "label"


class AppointmentTypeDetailView(DropdownDetailView):
    list_type = OptionList.LIST_APPOINTMENT_TYPE
    serializer_class = AppointmentTypeSerializer
    identity_field = "name"
    model_field = "label"
    system_can_deactivate = False


def _appointments(db):
    """Appointments with what the lists and screens read from each one, loaded together."""
    return Appointment.objects.using(db).select_related("patient", "doctor", "branch_department__branch", "branch_department__department")


def _search_appointments(qs, db, text):
    """Free-text search across the headers of the queue table: patient, doctor, complaint, room, token."""
    return qs.filter(
        Q(patient__awpid__in=PatientService.matching_awpids(db, text))
        | Q(doctor__first_name__icontains=text) | Q(doctor__last_name__icontains=text)
        | Q(chief_complaint__icontains=text)
        | Q(room__name__icontains=text)
        | Q(token_number__icontains=text)
    )


def _serialize_appointments(items, db):
    """Appointments as the API returns them: vitals and the patients' shared records attached in one go."""
    attach_vitals(items)
    patients = [a.patient for a in items]
    for p in patients[:1]:
        p.get_patient_details(batch=patients)             # the whole page at once
    return AppointmentSerializer(items, many=True, context={"db": db}).data


def _nurse_assigned_doctor_ids(request, db):
    """Doctor id(s) this nurse is rostered to (see apps.hospital_setup.NurseDoctorAssignment"""
    acts_as = getattr(request.user, "acts_as", [])
    if request.user.role != "nurse" and "nurse" not in acts_as:
        return None
    from apps.hospital_setup.nurse_doctor_utils import get_nurse_doctor_ids
    return get_nurse_doctor_ids(request.user.id, db)


# Appointments / Queue

class AppointmentListCreateView(APIView):
    """GET  — Today's OPD queue. Doctors see their own; admin sees all."""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        qs = _appointments(db)

        # Filter by date
        appt_date = request.query_params.get("date", str(date.today()))
        qs = qs.filter(scheduled_date=appt_date)

        # Doctor sees only their queue unless admin. Checks acts_as too, not
        acts_as = getattr(request.user, "acts_as", [])
        if request.user.role == "doctor" or "doctor" in acts_as:
            qs = qs.filter(doctor_id=request.user.id)

        # Nurse sees only the queue for doctor(s) the hospital admin has
        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_id__in=nurse_doctor_ids)

        # Branch scoping — explicit ?branch_id= wins; otherwise front-desk/nurse
        branch_param = request.query_params.get("branch_id")
        if branch_param and branch_param != "all":
            if request.user.role == "doctor" or "doctor" in acts_as:
                from apps.hospital_setup.branch_utils import is_staff_in_branch
                doctor = StaffUser.objects.using(db).filter(pk=request.user.id).first()
                if not doctor or not is_staff_in_branch(doctor, branch_param, db):
                    return api_forbidden("You are not assigned to that branch.")
            qs = qs.filter(branch_department__branch_id=branch_param)
        elif not branch_param and (
            request.user.role in ("front_desk", "nurse") or set(acts_as) & {"front_desk", "nurse"}
        ) and request.user.branch_id:
            qs = qs.filter(branch_department__branch_id=request.user.branch_id)

        # Status filter
        appt_status = request.query_params.get("status")
        if appt_status:
            qs = qs.filter(status=appt_status)

        # Doctor / room filters — same query param names as
        doctor_param = request.query_params.get("doctor_id")
        if doctor_param:
            qs = qs.filter(doctor_id=doctor_param)
        room_param = request.query_params.get("room_id")
        if room_param:
            qs = qs.filter(room_id=room_param)

        # Free-text search across every header the front-desk queue table
        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            qs = _search_appointments(qs, db, patient_q)

        # Status counts over the WHOLE day (pre-pagination) so dashboard stat
        status_counts = {
            "total":       qs.count(),
            "waiting":     qs.filter(status__in=["waiting", "scheduled"]).count(),
            "vitals_done": qs.filter(status="vitals_done").count(),
            "in_progress": qs.filter(status="in_progress").count(),
            "done":        qs.filter(status="done").count(),
        }

        # Active patients first (in consult > vitals ready > waiting > scheduled),
        from django.db.models import Case, When, IntegerField
        status_priority = Case(
            When(status="in_progress", then=0),
            When(status="vitals_done", then=1),
            When(status="waiting",     then=2),
            When(status="scheduled",   then=3),
            When(status="done",        then=4),
            default=5,
            output_field=IntegerField(),
        )
        qs = qs.annotate(
            _prio=status_priority
        ).order_by("_prio", "token_number")
        db = request.hospital_db
        page_items, meta = paginate_queryset(request, qs)
        return Response({
            "results": _serialize_appointments(page_items, db),
            "count": meta["total_count"],
            "pagination": meta,
            "status_counts": status_counts,
        })

    def post(self, request):
        db = request.hospital_db
        serializer = AppointmentCreateSerializer(data=request.data, context={"hospital_db": db})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        doctor = StaffUser.objects.using(db).filter(acts_as_q("doctor"), pk=data["doctor_id"], is_active=True).first()
        if doctor is None:
            return api_not_found("Doctor not found at this hospital.")

        scheduled_time = data.get("scheduled_time")
        if scheduled_time:
            taken = Appointment.objects.using(db).filter(
                scheduled_date=data.get("scheduled_date", date.today()),
                doctor_id=doctor.id,
                scheduled_time=scheduled_time,
            ).exclude(status="cancelled").exists()
            if taken:
                return api_error(message="That slot was just taken. Please pick another.", status=409)

        appt_date = data.get("scheduled_date", date.today())

        # An appointment belongs to the branch the request names (or the requester works at); the place is the department at that branch
        # where this doctor sits, else the doctor's primary place.
        from apps.hospital_setup.branch_utils import primary_place, staff_place_at
        patient = HospitalPatient.objects.using(db).filter(pk=data.pop("patient_id")).first()
        if patient is None:
            return api_not_found("Patient not found.")
        branch_id = request.query_params.get("branch_id") or getattr(request.user, "branch_id", None)
        place = (staff_place_at(doctor, branch_id, db) if branch_id else None) or primary_place(doctor, db)
        if place is None:
            return api_error("This doctor has no branch or department set up yet.")

        # The room the doctor sits in at that time, if the hospital has set one up
        room_fields = {}
        if scheduled_time:
            from apps.hospital_setup.room_utils import resolve_room_for_slot
            room = resolve_room_for_slot(db, doctor.id, appt_date.weekday(), scheduled_time)
            if room:
                room_fields = {"room_id": room.id}

        # Only a same-day booking means the patient is physically here now —
        initial_status = (
            Appointment.STATUS_WAITING if appt_date == date.today()
            else Appointment.STATUS_SCHEDULED
        )
        doctor_id = data.pop("doctor_id")
        with transaction.atomic(using=db):
            appointment = Appointment.objects.using(db).create(
                **data,
                patient=patient,
                doctor_id=doctor_id,
                token_number=Appointment.next_token(place.id, appt_date, db),
                status=initial_status,
                branch_department=place,
                **room_fields,
            )

        # Make this visible in the patient's own portal login, if they (or
        from apps.patients.services import sync_patient_booking
        sync_patient_booking(appointment, db)

        appointment = _appointments(db).get(pk=appointment.pk)
        return Response(_serialize_appointments([appointment], db)[0], status=status.HTTP_201_CREATED)


class AppointmentHistoryView(APIView):
    """GET /api/v1/opd/history/?patient=&date_from=&date_to=&status=&page=&page_size="""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        qs = _appointments(db)

        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            qs = qs.filter(doctor_id=request.user.id)

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_id__in=nurse_doctor_ids)

        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            qs = qs.filter(patient__awpid__in=PatientService.matching_awpids(db, patient_q))

        date_from = request.query_params.get("date_from")
        date_to   = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(scheduled_date__gte=date_from)
        if date_to:
            qs = qs.filter(scheduled_date__lte=date_to)

        appt_status = request.query_params.get("status")
        if appt_status:
            qs = qs.filter(status=appt_status)

        qs = qs.order_by("-scheduled_date", "-token_number")
        page_items, meta = paginate_queryset(request, qs)
        data = _serialize_appointments(page_items, db)

        # Per-visit indicators for the History module: does this visit have a
        enc_ids = [row["encounter"]["id"] for row in data if row.get("encounter")]
        if enc_ids:
            from apps.documents.models import MedicalDocument
            encs = {
                str(e.id): e for e in OPDEncounter.objects.using(db)
                .filter(id__in=enc_ids)
                .only("id", "subjective", "objective", "assessment", "plan", "diagnoses")
            }
            rx_enc_ids = {
                str(x) for x in Prescription.objects.using(db)
                .filter(encounter_id__in=enc_ids, rx_items__isnull=False)
                .values_list("encounter_id", flat=True).distinct()
            }
            # Two archived PDFs can hang off one encounter (see
            from apps.patients.models import ConsultSession
            typeset_rx_docs, hw_rx_docs = {}, {}
            Source = MedicalDocument.Source
            for d in (MedicalDocument.objects.using("default")
                      .filter(source_type__in=(Source.ENCOUNTER, Source.ENCOUNTER_HANDWRITTEN_RX),
                              source_id__in=[str(i) for i in enc_ids])
                      .values("id", "source_type", "source_id", "doc_classification")):
                eid = str(d["source_id"])
                if d["source_type"] == Source.ENCOUNTER_HANDWRITTEN_RX:
                    hw_rx_docs[eid] = d["id"]
                elif d["doc_classification"] == "prescription":
                    typeset_rx_docs[eid] = d["id"]
            noted = {str(e) for e in ConsultSession.objects.using("default")
                     .filter(encounter_id__in=enc_ids, hospital_id=request.hospital_id)
                     .exclude(note_pdf="").values_list("encounter_id", flat=True)}
            for row in data:
                eid = row["encounter"]["id"] if row.get("encounter") else None
                e = encs.get(eid) if eid else None
                row["prescription_doc_id"] = typeset_rx_docs.get(eid)
                row["handwritten_prescription_doc_id"] = hw_rx_docs.get(eid)
                row["internal_note_available"] = eid in noted
                row["has_internal_note"] = row["internal_note_available"] or bool(e and (
                    (e.subjective or e.objective or e.assessment or e.plan or "").strip() or e.diagnoses
                ))
                row["has_prescription"] = bool(
                    row["prescription_doc_id"] or row["handwritten_prescription_doc_id"]
                    or (eid in rx_enc_ids)
                )
        else:
            for row in data:
                row["has_internal_note"] = False
                row["has_prescription"] = False
                row["prescription_doc_id"] = None
                row["handwritten_prescription_doc_id"] = None
                row["internal_note_available"] = False

        return Response({"results": data, "pagination": meta})


class AppointmentUpcomingView(APIView):
    """GET /api/v1/opd/appointments/upcoming/?date_from=&date_to=&status=&room_id=&branch_id=&patient="""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        qs = _appointments(db)

        acts_as = getattr(request.user, "acts_as", [])
        if request.user.role == "doctor" or "doctor" in acts_as:
            qs = qs.filter(doctor_id=request.user.id)

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_id__in=nurse_doctor_ids)

        date_from = request.query_params.get("date_from") or str(date.today())
        qs = qs.filter(scheduled_date__gte=date_from)
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(scheduled_date__lte=date_to)

        appt_status = request.query_params.get("status")
        if appt_status:
            qs = qs.filter(status=appt_status)
        else:
            # Default view excludes cancelled/no-show clutter from "what's
            qs = qs.exclude(status__in=[Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW])

        room_id = request.query_params.get("room_id")
        if room_id:
            qs = qs.filter(room_id=room_id)

        doctor_param = request.query_params.get("doctor_id")
        if doctor_param:
            qs = qs.filter(doctor_id=doctor_param)

        branch_param = request.query_params.get("branch_id")
        if branch_param and branch_param != "all":
            qs = qs.filter(branch_department__branch_id=branch_param)
        elif not branch_param and (
            request.user.role in ("front_desk", "nurse") or set(acts_as) & {"front_desk", "nurse"}
        ) and request.user.branch_id:
            qs = qs.filter(branch_department__branch_id=request.user.branch_id)

        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            qs = _search_appointments(qs, db, patient_q)

        # Ascending — "what's next" reads top-to-bottom chronologically,
        from django.db.models import F
        qs = qs.order_by("scheduled_date", F("scheduled_time").asc(nulls_last=True), "token_number")

        page_items, meta = paginate_queryset(request, qs)
        return Response({"results": _serialize_appointments(page_items, db), "pagination": meta})


_whisper_model = None


def _get_whisper():
    """Lazy-load faster-whisper once per process (base model, CPU int8)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


class TranscribeView(APIView):
    """POST /api/v1/opd/transcribe/  (multipart, field: audio)"""
    permission_classes = [IsDoctor, RequireFeature("feat_ai_voice")]

    def post(self, request):
        audio = request.FILES.get("audio")
        if not audio:
            return api_error("No audio file received.")

        import os
        import tempfile
        suffix = os.path.splitext(audio.name)[1] or ".webm"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                for chunk in audio.chunks():
                    f.write(chunk)
                tmp_path = f.name

            try:
                model = _get_whisper()
            except ImportError:
                return api_error(
                    "Whisper not installed on server. Run: pip install faster-whisper",
                    status=503,
                )

            segments, _info = model.transcribe(tmp_path, language="en", beam_size=1)
            text = " ".join(s.text.strip() for s in segments).strip()
            return Response({"text": text})
        except Exception:
            # Log the real exception server-side only — the raw message
            logger.exception("Transcription failed")
            return api_error("Transcription failed. Please try again or type the note manually.", status=500)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


class OPDStatsView(APIView):
    """GET /api/v1/opd/stats/?days=7"""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        try:
            days = min(max(int(request.query_params.get("days", 7)), 1), 30)
        except ValueError:
            days = 7
        today = date.today()
        start = today - timedelta(days=days - 1)

        qs = Appointment.objects.using(db).filter(
            scheduled_date__gte=start, scheduled_date__lte=today,
        )
        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            qs = qs.filter(doctor_id=request.user.id)

        rows = qs.values("scheduled_date").annotate(
            total=Count("id"),
            done=Count("id", filter=Q(status="done")),
        )
        by_date = {r["scheduled_date"]: r for r in rows}

        results = []
        for i in range(days):
            d = start + timedelta(days=i)
            r = by_date.get(d, {})
            results.append({
                "date":  str(d),
                "day":   d.strftime("%a"),
                "total": r.get("total", 0),
                "done":  r.get("done", 0),
            })
        return Response({"results": results})


class MonitoringListView(APIView):
    """GET /api/v1/opd/monitoring/?date=YYYY-MM-DD  (default today)"""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        mon_date = request.query_params.get("date", str(date.today()))

        encounters = (OPDEncounter.objects.using(db)
                      .select_related("appointment__patient")
                      .filter(appointment__scheduled_date=mon_date)
                      .order_by("appointment__token_number"))

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            encounters = encounters.filter(appointment__doctor_id__in=nurse_doctor_ids)

        branch_param = request.query_params.get("branch_id")
        if branch_param and branch_param != "all":
            encounters = encounters.filter(appointment__branch_department__branch_id=branch_param)
        elif not branch_param and request.user.role in ("front_desk", "nurse") and request.user.branch_id:
            encounters = encounters.filter(appointment__branch_department__branch_id=request.user.branch_id)

        # Summary counts over the WHOLE day (pre-pagination) so the nurse's
        summary = {
            "total":            encounters.count(),
            "with_tests":       encounters.exclude(investigations="").exclude(investigations__isnull=True).count(),
            "with_followup":    encounters.exclude(follow_up_in_days__isnull=True).count(),
        }

        page_items, meta = paginate_queryset(request, encounters)

        # Batched lookups for the whole page instead of 3-4 separate queries
        enc_ids = [enc.id for enc in page_items]
        appt_ids = [enc.appointment_id for enc in page_items]
        patients = [enc.appointment.patient for enc in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)
        rx_by_encounter = {
            rx.encounter_id: rx
            for rx in Prescription.objects.using(db).filter(encounter_id__in=enc_ids)
        }
        items_by_rx = {}
        for item in PrescriptionItem.objects.using(db).filter(prescription_id__in=[rx.id for rx in rx_by_encounter.values()]):
            items_by_rx.setdefault(item.prescription_id, []).append(item)
        vitals_appt_ids = recorded(appt_ids)

        results = []
        for enc in page_items:
            appt = enc.appointment
            patient = appt.patient
            rx = rx_by_encounter.get(enc.id)
            drugs = []
            if rx:
                drugs = [
                    f"{i.drug_name} {i.dosage} {i.frequency.upper()}"
                    + (f" × {i.duration_days}d" if i.duration_days else "")
                    for i in items_by_rx.get(rx.id, [])
                ]
            has_vitals = appt.id in vitals_appt_ids
            results.append({
                "encounter_id":    str(enc.id),
                "token_number":    appt.token_number,
                # Patient's real numeric id (enc.patient_id is Patient.uuid,
                "patient_pk":      patient.id,
                "patient_name":    patient.get_patient_details()["full_name"] or patient.awpid,
                "patient_uhid":    patient.uhid,
                "is_dependent":    patient.get_patient_details()["is_dependent"],
                "guardian_name":   patient.get_patient_details()["guardian_name"],
                "guardian_relation": patient.get_patient_details()["guardian_relation"],
                "appointment_status": appt.status,
                "encounter_status":   enc.status,
                "chief_complaint": appt.chief_complaint,
                "has_vitals":      has_vitals,
                "diagnoses":       enc.diagnoses or [],
                "investigations":  enc.investigations or "",
                "prescription":    drugs,
                "advice":          enc.advice_to_patient or "",
                "follow_up_in_days": enc.follow_up_in_days,
                "referred_to":     enc.referred_to or "",
            })
        return Response({
            "results": results,
            "count": meta["total_count"],
            "pagination": meta,
            "summary": summary,
        })


class AppointmentDetailView(APIView):
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        db = request.hospital_db
        try:
            appt = _appointments(db).get(pk=pk)
        except Appointment.DoesNotExist:
            return api_not_found("Appointment not found.")
        return Response(_serialize_appointments([appt], db)[0])


class AppointmentStatusView(APIView):
    """POST /api/v1/opd/appointments/<id>/status/"""
    permission_classes = [IsHospitalStaff]

    VALID_TRANSITIONS = {
        Appointment.STATUS_SCHEDULED:   [Appointment.STATUS_WAITING, Appointment.STATUS_CANCELLED],
        Appointment.STATUS_WAITING:     [Appointment.STATUS_VITALS_DONE, Appointment.STATUS_IN_PROGRESS, Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW],
        Appointment.STATUS_VITALS_DONE: [Appointment.STATUS_IN_PROGRESS, Appointment.STATUS_WAITING],
        Appointment.STATUS_IN_PROGRESS: [Appointment.STATUS_DONE, Appointment.STATUS_WAITING],
    }

    def post(self, request, pk):
        db = request.hospital_db
        try:
            appt = _appointments(db).get(pk=pk)
        except Appointment.DoesNotExist:
            return api_not_found("Not found.")

        serializer = AppointmentStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]

        # Validate transition
        allowed = self.VALID_TRANSITIONS.get(appt.status, [])
        if new_status not in allowed:
            return api_error(f"Cannot transition from '{appt.status}' to '{new_status}'.")

        appt.status = new_status
        if new_status == Appointment.STATUS_IN_PROGRESS:
            appt.started_at = timezone.now()
        elif new_status == Appointment.STATUS_DONE:
            appt.completed_at = timezone.now()
        if serializer.validated_data.get("notes"):
            appt.notes = serializer.validated_data["notes"]
        appt.save(using=db)
        return Response(_serialize_appointments([appt], db)[0])


class AppointmentRescheduleView(APIView):
    """POST /api/v1/opd/appointments/<id>/reschedule/  {scheduled_date, scheduled_time?}"""
    permission_classes = [IsHospitalStaff]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            appt = _appointments(db).get(pk=pk)
        except Appointment.DoesNotExist:
            return api_not_found("Not found.")

        if appt.status not in (Appointment.STATUS_SCHEDULED, Appointment.STATUS_WAITING):
            return api_error(f"Cannot reschedule an appointment that's already '{appt.status}'.")

        new_date_raw = request.data.get("scheduled_date")
        new_time = (request.data.get("scheduled_time") or "").strip() or None
        if not new_date_raw:
            return api_error("scheduled_date is required.")
        try:
            new_date = date.fromisoformat(str(new_date_raw))
        except ValueError:
            return api_error("Invalid date.")

        if new_time:
            taken = Appointment.objects.using(db).filter(
                scheduled_date=new_date,
                doctor_id=appt.doctor_id,
                scheduled_time=new_time,
            ).exclude(status="cancelled").exclude(pk=appt.pk).exists()
            if taken:
                return api_error("That slot was just taken. Please pick another.", status=409)

        room_id = None
        if new_time:
            from apps.hospital_setup.room_utils import resolve_room_for_slot
            room = resolve_room_for_slot(db, appt.doctor_id, new_date.weekday(), new_time)
            if room:
                room_id = room.id

        with transaction.atomic(using=db):
            appt.scheduled_date = new_date
            appt.scheduled_time = new_time
            appt.token_number = Appointment.next_token(appt.branch_department_id, new_date, db)
            appt.status = Appointment.STATUS_SCHEDULED
            appt.room_id = room_id
            appt.save(using=db)
        return Response(_serialize_appointments([appt], db)[0])


class VitalsView(APIView):
    """POST /api/v1/opd/appointments/<id>/vitals/ (nurse or doctor)"""
    permission_classes = [IsDoctorOrNurse]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            appt = Appointment.objects.using(db).get(pk=pk)
        except Appointment.DoesNotExist:
            return api_not_found("Appointment not found.")

        # Extract appointment-level fields before passing to Vitals serializer
        chief_complaint = request.data.get("chief_complaint", "").strip()

        # Build vitals-only data (exclude non-Vitals fields)
        APPT_FIELDS = {"chief_complaint", "notes"}
        vitals_data = {k: v for k, v in request.data.items() if k not in APPT_FIELDS}

        serializer = VitalsSerializer(data=vitals_data)
        serializer.is_valid(raise_exception=True)

        vitals, created = record_vitals(appt, db, request.hospital_id, request.user.id, serializer.validated_data)

        # Update chief complaint on appointment if provided
        appt_update_fields = ["status"]
        if chief_complaint:
            appt.chief_complaint = chief_complaint
            appt_update_fields.append("chief_complaint")

        # Advance appointment status: waiting/scheduled → vitals_done
        if appt.status in ("waiting", "scheduled"):
            appt.status = "vitals_done"

        appt.save(using=db, update_fields=appt_update_fields)

        return Response(VitalsSerializer(vitals).data, status=status.HTTP_201_CREATED if created else 200)


# OPD Encounters

class EncounterCreateView(APIView):
    """GET/POST /api/v1/opd/encounters/"""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        qs = _encounter(db)
        appointment_id = request.query_params.get("appointment")
        if appointment_id:
            qs = qs.filter(appointment_id=appointment_id)
        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            qs = qs.filter(appointment__doctor_id=request.user.id)
        qs = qs.order_by("-created_at")
        page_items, meta = paginate_queryset(request, qs)
        patients = [e.appointment.patient for e in page_items]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)
        return Response({
            "results": OPDEncounterSerializer(page_items, many=True, context={"db": db}).data,
            "pagination": meta,
        })

    def post(self, request):
        # Checks acts_as too — a custom role bundling "doctor" (e.g. a
        if request.user.role != "doctor" and "doctor" not in getattr(request.user, "acts_as", []):
            return api_forbidden("Only doctors can create encounters.")
        db = request.hospital_db
        # The encounter is always the logged-in doctor's own
        serializer = OPDEncounterCreateSerializer(data=request.data, context={"db": db})
        serializer.is_valid(raise_exception=True)
        appointment = Appointment.objects.using(db).filter(pk=serializer.validated_data["appointment_id"]).first()
        if appointment is None:
            return api_not_found("Appointment not found.")
        if appointment.doctor_id != request.user.id:
            return api_forbidden("This appointment is with another doctor.")
        encounter = serializer.save()
        # Move appointment to IN_PROGRESS
        try:
            appt = Appointment.objects.using(db).get(pk=encounter.appointment_id)
            if appt.status in (Appointment.STATUS_WAITING, Appointment.STATUS_VITALS_DONE):
                appt.status = Appointment.STATUS_IN_PROGRESS
                appt.started_at = timezone.now()
                appt.save(using=db, update_fields=["status", "started_at"])
        except Appointment.DoesNotExist:
            pass
        enc = _encounter(db).get(pk=encounter.pk)
        return Response(_serialize_encounter(enc, db), status=status.HTTP_201_CREATED)


def _encounter(db):
    """Encounters with the appointment, patient and doctor each one is shown with."""
    return OPDEncounter.objects.using(db).select_related("appointment__patient", "appointment__doctor")


def _serialize_encounter(enc, db):
    return OPDEncounterSerializer(enc, context={"db": db}).data


class EncounterDetailView(APIView):
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        db = request.hospital_db
        try:
            enc = _encounter(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")
        return Response(_serialize_encounter(enc, db))

    def patch(self, request, pk):
        db = request.hospital_db
        try:
            enc = _encounter(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Not found.")

        if enc.status == OPDEncounter.STATUS_SIGNED:
            return api_error("Cannot edit a signed encounter.")

        # A follow-up "in 0 days" isn't a real follow-up (it's just today,
        if "follow_up_in_days" in request.data:
            raw = request.data["follow_up_in_days"]
            if raw not in (None, "", "null"):
                try:
                    raw = int(raw)
                except (TypeError, ValueError):
                    return api_error("follow_up_in_days must be a whole number of days.")
                if raw < 1:
                    return api_error("Follow-up must be at least 1 day out — use 0 or leave it blank if there's no follow-up needed.")

        allowed_fields = ["subjective", "objective", "assessment", "plan",
                          "investigations", "advice_to_patient", "follow_up_in_days",
                          "diagnoses", "referred_to", "referral_notes"]
        for field in allowed_fields:
            if field in request.data:
                setattr(enc, field, request.data[field])
        enc.save(using=db)
        return Response(_serialize_encounter(enc, db))


def _open_consult_session(encounter_id, hospital_id):
    from apps.patients.models import ConsultSession
    return (ConsultSession.objects.using("default")
            .filter(encounter_id=encounter_id, hospital_id=hospital_id, status=ConsultSession.STATUS_OPEN)
            .order_by("-created_at").first())


def _fold_session_into_encounter(sess, enc, db):
    """Belt-and-suspenders: if the doctor signs without pressing "Load"""
    changed = False
    note = (sess.note_recognised or {}) if sess else {}
    if note.get("status") == "done":
        m = {"subjective": "subjective", "objective": "objective",
             "assessment": "assessment", "plan": "plan",
             "investigations": "investigations", "advice": "advice_to_patient"}
        soap_filled = False
        for src, field in m.items():
            val = (note.get(src) or "").strip()
            if val and not (getattr(enc, field) or "").strip():
                setattr(enc, field, val)
                changed = True
            if val:
                soap_filled = True
        # Model transcribed the note but didn't split it into SOAP sections —
        if not soap_filled:
            raw = (note.get("raw_text") or "").strip()
            if raw and not (enc.subjective or "").strip():
                enc.subjective = raw
                changed = True
        fu = note.get("follow_up_days")
        if fu and enc.follow_up_in_days is None:
            enc.follow_up_in_days = int(fu)
            changed = True
        for d in (note.get("diagnoses") or []):
            desc = (d.get("description") or "").strip()
            if desc and not any((x.get("description") or "").lower() == desc.lower() for x in (enc.diagnoses or [])):
                enc.diagnoses = (enc.diagnoses or []) + [{
                    "code": (d.get("code") or "").strip(), "description": desc,
                    "clinical_status": "active", "is_primary": not (enc.diagnoses or []),
                }]
                changed = True
    if changed:
        enc.save(using=db)

    rx = (sess.rx_recognised or {}) if sess else {}
    items = rx.get("items") or rx.get("prescription") or []
    if rx.get("status") == "done" and items:
        prescription = Prescription.objects.using(db).filter(encounter_id=enc.id).first()
        if prescription is None:
            prescription = _create_prescription_for(enc, db)
        # De-dupe by drug name alone — folding on sign runs on top of whatever
        def _norm_drug(s):
            return " ".join((s or "").strip().lower().split())
        existing = {_norm_drug(i.drug_name)
                    for i in PrescriptionItem.objects.using(db).filter(prescription=prescription)}
        for it in items:
            name = (it.get("drug_name") or "").strip()
            if not name or _norm_drug(name) in existing:
                continue
            existing.add(_norm_drug(name))
            freq = (it.get("frequency") or "od").strip().lower()
            route = (it.get("route") or "oral").strip().lower()
            dur = it.get("duration_days")
            PrescriptionItem.objects.using(db).create(
                prescription=prescription, drug_name=name,
                dosage=(it.get("dosage") or "").strip() or "as directed",
                frequency=freq if freq in dict(PrescriptionItem.FREQUENCY_CHOICES) else "od",
                route=route if route in dict(PrescriptionItem.ROUTE_CHOICES) else "oral",
                duration_days=int(dur) if isinstance(dur, int) and dur > 0 else None,
                instructions=(it.get("instructions") or "").strip(),
            )
            changed = True
    return changed


def _next_rx_number(appointment, db):
    """The next prescription number, counted per branch of the visit (None if the counter cannot be read)."""
    from core.utils.nntm import get_next_number
    try:
        return get_next_number(branch_id=appointment.branch_department.branch_id, entity="prescription", using=db)[0]
    except Exception as e:
        logger.warning("Could not generate rx_number for appointment %s: %s", appointment.id, e)
        return None


def _create_prescription_for(enc, db):
    return Prescription.objects.using(db).create(encounter=enc, rx_number=_next_rx_number(enc.appointment, db))


def _store_prescription_pdf(enc, db, hospital_id):
    """After sign: mirror the prescription to a atomwalk"""
    rx = Prescription.objects.using(db).filter(encounter_id=enc.id).first()
    if rx is None:
        return
    try:
        from apps.opd.archive import store_prescription_document
        store_prescription_document(rx, db, hospital_id)
    except Exception:
        logger.exception("prescription PDF store failed for encounter=%s", enc.id)


def _store_consultation_note(enc, db, hospital_id):
    """After sign: the typed consultation note joins the patient's documents."""
    try:
        from apps.opd.archive import store_consultation_note_document
        store_consultation_note_document(enc, db, hospital_id)
    except Exception:
        logger.exception("consultation note store failed for encounter=%s", enc.id)


def _store_handwriting_pdfs(enc, db, hospital_id, session_id):
    """After sign: archive the consult pad's RAW HANDWRITING as permanent PDFs"""
    if not session_id:
        return
    try:
        import base64
        from apps.opd.pdf import images_to_pdf
        from apps.hospital_master.models import Hospital
        from apps.patients.models import ConsultSession
        from apps.documents.models import MedicalDocument
        from apps.documents.lib_documents import create_issued_document
        from core import storage as blob_storage

        sess = ConsultSession.objects.using("default").filter(id=session_id).first()
        if not sess:
            return
        patient = enc.appointment.patient
        owner = Hospital.objects.using("default").filter(pk=hospital_id).first()
        hospital_name = owner.name if owner else "Hospital"
        appt = enc.appointment if enc.appointment_id else None
        visit_date = appt.scheduled_date if appt else timezone.now().date()
        rx = Prescription.objects.using(db).filter(encounter_id=enc.id).first()
        rx_label = (rx.rx_number if rx and rx.rx_number else "")

        # (tab, pages, doc_type, folder, s3_category, title)
        specs = [
            ("rx", sess.rx_pages, "prescription", "prescriptions", "prescription",
             f"Handwritten Prescription{(' ' + rx_label) if rx_label else ''} — {visit_date}"),
            ("note", sess.note_pages, "consultation_note", "consult-notes", "consult-note",
             f"Handwritten Consultation Note — {visit_date}"),
        ]
        cleared = {}
        for tab, pages, doc_type, prefix, category, title in specs:
            if not pages:
                continue
            ref = {"source_type": MedicalDocument.Source.ENCOUNTER_HANDWRITTEN_RX, "source_id": str(enc.id)}
            already = (bool(sess.note_pdf) if tab == "note"
                       else MedicalDocument.objects.using("default").filter(**ref).exists())
            if already:
                cleared[tab] = True  # already archived on a prior attempt
                continue
            pdf_bytes = images_to_pdf(pages, header=f"{title}  ·  {hospital_name}")
            if not pdf_bytes:
                continue
            pdf_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
            awpid = getattr(patient, "awpid", "")
            file_path = blob_storage.upload_data_uri(
                pdf_uri, prefix=f"patients/{awpid}/{prefix}", mime_type="application/pdf", category=category,
            )
            if tab == "note":
                # the doctor's own record: it stays on the consult session, not in the patient's documents
                ConsultSession.objects.using("default").filter(id=sess.id).update(note_pdf=file_path)
            else:
                create_issued_document(
                    awpid=awpid, file_path=file_path, name=f"{title}.pdf", doc_type=doc_type,
                    source_hospital_id=hospital_id, **ref, document_date=visit_date,
                )
            cleared[tab] = True

        upd = {}
        if cleared.get("rx"):
            upd["rx_pages"] = []
        if cleared.get("note"):
            upd["note_pages"] = []
        if upd:
            ConsultSession.objects.using("default").filter(id=sess.id).update(**upd)
    except Exception:
        logger.exception("consult-pad handwriting archive failed for encounter=%s", enc.id)


class EncounterInternalNoteView(APIView):
    """GET /api/v1/opd/encounters/<id>/internal-note/[?download=1]"""
    permission_classes = [IsDoctor]

    def get(self, request, pk):
        from apps.patients.models import ConsultSession
        from core import storage as blob_storage

        sess = (ConsultSession.objects.using("default")
                .filter(encounter_id=pk, hospital_id=request.hospital_id).exclude(note_pdf="").first())
        if not sess:
            return api_not_found("No internal note was archived for this visit.")
        want_download = (request.query_params.get("download") or "").lower() in ("1", "true", "yes")
        name = "Handwritten Consultation Note.pdf"
        return success(data={
            "id": str(sess.encounter_id), "title": "Handwritten Consultation Note", "doc_type": "consultation_note",
            "file_name": name, "mime_type": "application/pdf", "created_at": sess.signed_at or sess.updated_at,
            "file_data": blob_storage.signed_url(sess.note_pdf, download_name=name if want_download else None),
            "download": want_download,
        })


class EncounterConsultSessionView(APIView):
    """POST /api/v1/opd/encounters/<id>/consult-session/                 — start /"""
    permission_classes = [IsDoctor]

    def _enc(self, request, pk):
        return _encounter(request.hospital_db).get(pk=pk)

    def post(self, request, pk):
        if (request.data or {}).get("action") == "recognise":
            return self._recognise(request, pk)
        from django.conf import settings
        from apps.patients.models import Patient
        from apps.patients.models import ConsultSession
        from apps.opd.qr import render_qr_data_uri

        try:
            enc = self._enc(request, pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        patient = enc.appointment.patient
        identity = Patient.objects.using("default").filter(awpid=patient.awpid).first()
        if not identity:
            return api_not_found("This patient has no atomwalk identity yet.")

        sess = _open_consult_session(enc.id, request.hospital_id)
        if not sess:
            sess = ConsultSession.objects.using("default").create(
                patient=identity, hospital_id=request.hospital_id, encounter_id=enc.id,
                doctor_user_id=request.user.id,
                expires_at=timezone.now() + timedelta(hours=settings.CONSULT_PAD_EXPIRY_HOURS),
            )

        pad_url = f"{settings.FRONTEND_URL.rstrip('/')}/consult-pad/{sess.token}"
        return success(data={
            "session_id": sess.id, "status": sess.status,
            "pad_url": pad_url, "qr_image": render_qr_data_uri(pad_url),
        })

    def _recognise(self, request, pk):
        """Kick off transcription on demand. Only tabs with un-transcribed"""
        import threading
        from apps.patients.models import ConsultSession
        from apps.patients.views import _run_tab_recognition, _decode_pages
        from apps.patients.services import _page_key

        try:
            enc = self._enc(request, pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")
        sess = _open_consult_session(enc.id, request.hospital_id)
        if not sess:
            return success(data={"active": False})

        started, already = [], []
        for tab, pages_attr, recog_attr in (
            ("rx", "rx_pages", "rx_recognised"),
            ("note", "note_pages", "note_recognised"),
        ):
            raw_pages = getattr(sess, pages_attr) or []
            if not raw_pages:
                continue
            blob = getattr(sess, recog_attr) or {}
            if blob.get("status") == "pending":
                started.append(tab)          # a compile is already running
                continue
            covered = set((blob.get("_page_texts") or {}).keys())
            page_hashes = [_page_key(p) for p in _decode_pages(raw_pages)]
            needs_run = (
                blob.get("status") in (None, "", "idle", "dirty", "failed")
                or any(h not in covered for h in page_hashes)
            )
            if not needs_run:
                already.append(tab)
                continue
            token = timezone.now().isoformat()
            ConsultSession.objects.using("default").filter(id=sess.id).update(
                **{recog_attr: {**blob, "status": "pending", "at": token}})
            threading.Thread(
                target=_run_tab_recognition, args=(sess.id, tab, token), daemon=True,
            ).start()
            started.append(tab)

        return success(data={"active": True, "recognising": started, "already_done": already})

    def get(self, request, pk):
        try:
            enc = self._enc(request, pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")
        sess = _open_consult_session(enc.id, request.hospital_id)
        if not sess:
            return success(data={"active": False})

        def _public(blob):
            # Drop the internal page-text cache before it goes to the client.
            if not blob:
                return None
            return {k: v for k, v in blob.items() if k != "_page_texts"}

        return success(data={
            "active": True,
            "updated_at": sess.updated_at,
            "rx": _public(sess.rx_recognised),
            "note": _public(sess.note_recognised),
            # Page images so the encounter screen can show the doctor the
            "rx_pages": sess.rx_pages or [],
            "note_pages": sess.note_pages or [],
        })


class EncounterSignView(APIView):
    """POST /api/v1/opd/encounters/<id>/sign/"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            enc = _encounter(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Not found.")

        if enc.status == OPDEncounter.STATUS_SIGNED:
            return api_error("Already signed.")

        # Fold in any handwriting-session content the doctor didn't explicitly
        sess = _open_consult_session(enc.id, request.hospital_id)
        if sess:
            try:
                _fold_session_into_encounter(sess, enc, db)
                enc.refresh_from_db(using=db)
            except Exception:
                logger.exception("consult-session fold failed for encounter=%s", enc.id)

        if not enc.assessment and not enc.diagnoses:
            return api_error("Add an assessment or at least one ICD-10 diagnosis before signing.")

        enc.sign(using=db)

        # Share the patient across the post-sign side effects below.
        patient = enc.appointment.patient

        # Auto-generate invoice for this encounter
        auto_generate_invoice(enc, db, request.user, patient, hospital_id=request.hospital_id)

        # Write-through to the cross-hospital HIE shared tables (atomwalk DB).
        sync_encounter_to_hie(enc, db, patient, hospital_id=request.hospital_id)

        # Store the prescription as a PDF (doctor history + patient portal),
        _store_prescription_pdf(enc, db, request.hospital_id)
        _store_consultation_note(enc, db, request.hospital_id)
        if sess:
            _store_handwriting_pdfs(enc, db, request.hospital_id, sess.id)
            from apps.patients.models import ConsultSession
            ConsultSession.objects.using("default").filter(id=sess.id).update(
                status=ConsultSession.STATUS_SIGNED, signed_at=timezone.now(),
            )

        from core.utils.audit import log_action
        log_action(request, db, action="encounter.sign", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.appointment.patient)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


class FollowUpActionView(APIView):
    """POST /api/v1/opd/encounters/<id>/follow-up/"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            enc = _encounter(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        s = FollowUpActionSerializer(data=request.data)
        if not s.is_valid():
            return api_error("Validation error.", errors=s.errors)
        v = s.validated_data

        if v["mode"] == "nurse":
            enc.followup_ask_nurse = True
            enc.followup_nurse_note = v.get("note", "")
            enc.followup_nurse_requested_at = timezone.now()
            enc.followup_nurse_booked = False
            enc.followup_nurse_booked_at = None
        else:  # "reminder"
            enc.follow_up_in_days = v["follow_up_in_days"]
            enc.followup_ask_nurse = False
            enc.followup_nurse_note = ""
            enc.followup_nurse_requested_at = None
            enc.followup_nurse_booked = False
            enc.followup_nurse_booked_at = None

        enc.save(using=db)

        from core.utils.audit import log_action
        log_action(request, db, action=f"encounter.followup.{v['mode']}", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.appointment.patient)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


def _reconstruct_shared_reference(enc, db):
    """Best-effort "most recent documented visit" summary built from the"""
    from apps.opd.patient_services import PatientService

    patient = enc.appointment.patient
    if not patient.hie_consent_given:
        return None

    history = PatientService.get_shared_history(awpid=patient.awpid)

    # Don't reference this same visit's own not-yet-signed data — only
    cutoff = enc.appointment.scheduled_date if getattr(enc, "appointment", None) else date.today()

    def before_cutoff(items, date_field):
        out = []
        for item in items:
            d = item.get(date_field)
            if d is None:
                continue
            d = d.date() if hasattr(d, "date") else d
            if d < cutoff:
                out.append(item)
        return out

    diagnoses    = before_cutoff(history.get("diagnoses", []), "created_at")
    lab_results  = before_cutoff(history.get("lab_results", []), "delivered_at")
    prescriptions = before_cutoff(history.get("prescriptions", []), "prescribed_on")

    # Find the single most recent date among what's left, then keep only
    candidate_dates = []
    for item in diagnoses:
        d = item["created_at"]
        candidate_dates.append(d.date() if hasattr(d, "date") else d)
    for item in lab_results:
        d = item["delivered_at"]
        candidate_dates.append(d.date() if hasattr(d, "date") else d)
    for item in prescriptions:
        candidate_dates.append(item["prescribed_on"])

    if not candidate_dates:
        return None
    last_date = max(candidate_dates)

    def on_date(items, date_field):
        result = []
        for item in items:
            d = item[date_field]
            d = d.date() if hasattr(d, "date") else d
            if d == last_date:
                result.append(item)
        return result

    return {
        "visit_date": last_date.isoformat(),
        "diagnoses": [
            {"icd10_code": d["icd10_code"], "description": d["description"]}
            for d in on_date(diagnoses, "created_at")
        ],
        "lab_results": [
            {"test_name": l["test_name"], "result_summary": l["result_summary"]}
            for l in on_date(lab_results, "delivered_at")
        ],
        "prescriptions": on_date(prescriptions, "prescribed_on"),
    }


class PreviousEncounterView(APIView):
    """GET /api/v1/opd/encounters/<id>/previous/"""
    permission_classes = [IsDoctorOrNurse]

    def get(self, request, pk):
        db = request.hospital_db
        try:
            enc = _encounter(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        earlier = (OPDEncounter.objects.using(db)
                   .filter(appointment__patient_id=enc.appointment.patient_id)
                   .exclude(pk=enc.pk))

        previous = (earlier.filter(status=OPDEncounter.STATUS_SIGNED)
                    .select_related("appointment__patient", "appointment__doctor")
                    .order_by("-signed_at")
                    .first())

        if previous:
            return Response({
                "data": _serialize_encounter(previous, db),
                "unsigned_pending": False,
                "shared_reference": None,
            })

        unsigned_pending = earlier.exclude(status=OPDEncounter.STATUS_SIGNED).exists()
        shared_reference = None if unsigned_pending else _reconstruct_shared_reference(enc, db)

        return Response({
            "data": None, "unsigned_pending": unsigned_pending,
            "shared_reference": shared_reference,
        })


class FollowupNurseWorklistView(APIView):
    """GET /api/v1/opd/followups/nurse-worklist/"""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        db = request.hospital_db
        encounters = (_encounter(db)
                      .filter(followup_ask_nurse=True, followup_nurse_booked=False)
                      .order_by("-followup_nurse_requested_at"))

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            encounters = encounters.filter(appointment__doctor_id__in=nurse_doctor_ids)

        encounters = list(encounters)
        patients = [e.appointment.patient for e in encounters]
        for p in patients[:1]:
            p.get_patient_details(batch=patients)
        results = []
        for enc in encounters:
            results.append({
                "encounter_id": str(enc.id),
                "patient_name": enc.appointment.patient.get_patient_details()["full_name"],
                "patient_uhid": enc.appointment.patient.uhid,
                "doctor_name": enc.appointment.doctor.get_full_name(),
                "note": enc.followup_nurse_note or "",
                "requested_at": enc.followup_nurse_requested_at,
            })
        return Response({"results": results})


class FollowupMarkBookedView(APIView):
    """POST /api/v1/opd/followups/<id>/mark-booked/ — nurse confirms they've"""
    permission_classes = [IsHospitalStaff]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            enc = _encounter(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        enc.followup_nurse_booked = True
        enc.followup_nurse_booked_at = timezone.now()
        enc.save(using=db)

        from core.utils.audit import log_action
        log_action(request, db, action="encounter.followup.marked_booked", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.appointment.patient)

        return Response(_serialize_encounter(_encounter(db).get(pk=enc.pk), db))


class EncounterSummaryPDFView(APIView):
    """GET /api/v1/opd/encounters/<id>/pdf/"""
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        import base64
        from apps.opd.archive import build_consultation_summary

        db = request.hospital_db
        try:
            enc = _encounter(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Not found.")

        pdf_bytes, patient, _visit_date = build_consultation_summary(enc, db, request.hospital_id)
        data_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
        uhid = patient.uhid if patient else str(enc.id)[:8]
        return success(data={
            "file_data": data_uri,
            "file_name": f"{uhid}_consultation_summary.pdf",
            "mime_type": "application/pdf",
        })


# Prescriptions

class PrescriptionCreateView(APIView):
    """POST /api/v1/opd/prescriptions/"""
    permission_classes = [IsDoctor]

    def post(self, request):
        db = request.hospital_db
        encounter_id = request.data.get("encounter_id")
        if not encounter_id:
            return api_error("encounter_id required.")

        try:
            enc = _encounter(db).get(pk=encounter_id)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        if hasattr(enc, "e_prescription"):
            # Carries an extra `prescription_id` field alongside the standard
            return Response({
                "success": False,
                "message": "Prescription already exists for this encounter.",
                "errors": {},
                "prescription_id": str(enc.e_prescription.id),
            }, status=409)

        # rx_number: a real, sequential, quotable-at-the-counter token —
        rx = Prescription.objects.using(db).create(
            encounter=enc,
            notes=request.data.get("notes", ""),
            rx_number=_next_rx_number(enc.appointment, db),
        )
        return Response(PrescriptionSerializer(rx).data, status=201)


class PrescriptionDetailView(APIView):
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        db = request.hospital_db
        try:
            rx = Prescription.objects.using(db).prefetch_related("rx_items").get(pk=pk)
        except Prescription.DoesNotExist:
            return api_not_found("Not found.")
        return Response(PrescriptionSerializer(rx).data)


class PrescriptionItemView(APIView):
    """POST   /api/v1/opd/prescriptions/<pk>/items/           — add drug item"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            rx = Prescription.objects.using(db).get(pk=pk)
        except Prescription.DoesNotExist:
            return api_not_found("Prescription not found.")

        # `drug` is looked up manually against the hospital DB rather than left
        payload = dict(request.data)
        drug_id = payload.pop("drug", None)
        drug_obj = None
        if drug_id:
            from apps.pharmacy.models import Drug
            drug_obj = Drug.objects.using(db).filter(pk=drug_id, is_active=True).first()

        serializer = PrescriptionItemSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        item = PrescriptionItem.objects.using(db).create(
            prescription=rx, drug=drug_obj, **serializer.validated_data
        )
        return Response(PrescriptionItemSerializer(item).data, status=201)

    def delete(self, request, pk, item_id):
        db = request.hospital_db
        try:
            item = PrescriptionItem.objects.using(db).get(pk=item_id, prescription_id=pk)
        except PrescriptionItem.DoesNotExist:
            return api_not_found("Item not found.")
        item.delete(using=db)
        return Response(status=204)


def _favourites_of(db, doctor_id):
    """The doctor's staff row and their saved prescription templates ({id: {name, items, created_at}})."""
    doctor = StaffUser.objects.using(db).get(pk=doctor_id)
    return doctor, doctor.prescription_favourites


def _favourite_json(fav_id, fav, doctor_id):
    return {"id": fav_id, "doctor_id": doctor_id, "name": fav["name"], "items": fav["items"], "created_at": fav["created_at"]}


class FavouriteListCreateView(APIView):
    permission_classes = [IsDoctor]

    def get(self, request):
        doctor, favs = _favourites_of(request.hospital_db, request.user.id)
        rows = sorted(favs.items(), key=lambda kv: kv[1]["name"])
        return Response([_favourite_json(fav_id, fav, doctor.id) for fav_id, fav in rows])

    def post(self, request):
        import uuid as _uuid
        serializer = PrescriptionFavouriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doctor, favs = _favourites_of(request.hospital_db, request.user.id)
        name = serializer.validated_data["name"]
        if any(f["name"] == name for f in favs.values()):
            return api_error("You already have a favourite with this name.", errors={"name": "Already in use."})
        fav_id = str(_uuid.uuid4())
        favs[fav_id] = {"name": name, "items": serializer.validated_data["items"], "created_at": timezone.now().isoformat()}
        doctor.save(using=request.hospital_db, update_fields=["prescription_favourites", "updated_at"])
        return Response(_favourite_json(fav_id, favs[fav_id], doctor.id), status=201)


class FavouriteDeleteView(APIView):
    permission_classes = [IsDoctor]

    def delete(self, request, pk):
        doctor, favs = _favourites_of(request.hospital_db, request.user.id)
        if str(pk) not in favs:
            return api_not_found("Not found.")
        del favs[str(pk)]
        doctor.save(using=request.hospital_db, update_fields=["prescription_favourites", "updated_at"])
        return Response(status=204)
