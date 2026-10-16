"""OPD API Views"""

import logging
from datetime import date, timedelta
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

from apps.opd.models import Appointment, OPDEncounter, Prescription, PrescriptionItem, PrescriptionFavourite
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
        qs = Appointment.objects.using(db)

        # Filter by date
        appt_date = request.query_params.get("date", str(date.today()))
        qs = qs.filter(scheduled_date=appt_date)

        # Doctor sees only their queue unless admin. Checks acts_as too, not
        acts_as = getattr(request.user, "acts_as", [])
        if request.user.role == "doctor" or "doctor" in acts_as:
            qs = qs.filter(doctor_user_id=request.user.id)

        # Nurse sees only the queue for doctor(s) the hospital admin has
        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_user_id__in=nurse_doctor_ids)

        # Branch scoping — explicit ?branch_id= wins; otherwise front-desk/nurse
        branch_param = request.query_params.get("branch_id")
        if branch_param and branch_param != "all":
            if request.user.role == "doctor" or "doctor" in acts_as:
                from apps.hospital_setup.models import StaffUser
                from apps.hospital_setup.branch_utils import is_staff_in_branch
                doctor = StaffUser.objects.using(db).filter(pk=request.user.id).first()
                if not doctor or not is_staff_in_branch(doctor, branch_param, db):
                    return api_forbidden("You are not assigned to that branch.")
            qs = qs.filter(branch_id=branch_param)
        elif not branch_param and (
            request.user.role in ("front_desk", "nurse") or set(acts_as) & {"front_desk", "nurse"}
        ) and request.user.branch_id:
            qs = qs.filter(branch_id=request.user.branch_id)

        # Status filter
        appt_status = request.query_params.get("status")
        if appt_status:
            qs = qs.filter(status=appt_status)

        # Doctor / room filters — same query param names as
        doctor_param = request.query_params.get("doctor_user_id")
        if doctor_param:
            qs = qs.filter(doctor_user_id=doctor_param)
        room_param = request.query_params.get("room_id")
        if room_param:
            qs = qs.filter(room_id=room_param)

        # Free-text search across every header the front-desk queue table
        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            from apps.opd.models import HospitalPatient
            matching_awpids = list(
                HospitalPatient.objects.using(db).filter(
                    Q(full_name__icontains=patient_q) |
                    Q(uhid__icontains=patient_q) |
                    Q(awpid__icontains=patient_q) |
                    Q(mobile__icontains=patient_q)
                ).values_list("awpid", flat=True)
            )
            qs = qs.filter(
                Q(patient_awpid__in=matching_awpids)
                | Q(doctor_name__icontains=patient_q)
                | Q(chief_complaint__icontains=patient_q)
                | Q(room_name__icontains=patient_q)
                | Q(token_number__icontains=patient_q)
            )

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
        attach_vitals(page_items)
        serializer = AppointmentSerializer(page_items, many=True, context={"db": db})
        return Response({
            "results": serializer.data,
            "count": meta["total_count"],
            "pagination": meta,
            "status_counts": status_counts,
        })

    def post(self, request):
        db = request.hospital_db
        serializer = AppointmentCreateSerializer(data=request.data, context={"hospital_db": db})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        scheduled_time = data.get("scheduled_time")
        if scheduled_time:
            taken = Appointment.objects.using(db).filter(
                scheduled_date=data.get("scheduled_date", date.today()),
                doctor_user_id=data["doctor_user_id"],
                scheduled_time=scheduled_time,
            ).exclude(status="cancelled").exists()
            if taken:
                return api_error(message="That slot was just taken. Please pick another.", status=409)

        # Auto-assign token number for the day
        appt_date = data.get("scheduled_date", date.today())
        last_token = Appointment.objects.using(db).filter(
            scheduled_date=appt_date,
            doctor_user_id=data["doctor_user_id"],
        ).values_list("token_number", flat=True)
        next_token = (max(last_token) + 1) if last_token else 1

        # Branch scoping — an appointment belongs to the branch the PATIENT
        from apps.opd.models import HospitalPatient
        patient = HospitalPatient.objects.using(db).filter(uuid=data["patient_id"]).first()
        branch_id = (
            (patient.branch_id if patient else None)
            or request.query_params.get("branch_id")
            or getattr(request.user, "branch_id", None)
        )

        # Resolve room/floor from org.RoomAssignment, if the hospital has set
        room_fields = {}
        if scheduled_time:
            from apps.hospital_setup.room_utils import resolve_room_for_slot
            day_of_week = appt_date.weekday()
            match = resolve_room_for_slot(db, data["doctor_user_id"], day_of_week, scheduled_time)
            if match:
                room_fields = {
                    "room_id": match.room_id,
                    "room_name": match.room.name,
                    "floor": match.room.floor,
                }

        # Only a same-day booking means the patient is physically here now —
        initial_status = (
            Appointment.STATUS_WAITING if appt_date == date.today()
            else Appointment.STATUS_SCHEDULED
        )
        appointment = Appointment.objects.using(db).create(
            **data,
            token_number=next_token,
            status=initial_status,
            booked_by_user_id=request.user.id,
            branch_id=branch_id,
            **room_fields,
        )

        # Make this visible in the patient's own portal login, if they (or
        from apps.patients.services import sync_patient_booking
        sync_patient_booking(appointment, db)

        return Response(AppointmentSerializer(appointment, context={"db": db}).data, status=status.HTTP_201_CREATED)


class AppointmentHistoryView(APIView):
    """GET /api/v1/opd/history/?patient=&date_from=&date_to=&status=&page=&page_size="""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        from apps.opd.models import HospitalPatient

        db = request.hospital_db
        qs = Appointment.objects.using(db)

        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            qs = qs.filter(doctor_user_id=request.user.id)

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_user_id__in=nurse_doctor_ids)

        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            matching_awpids = list(
                HospitalPatient.objects.using(db).filter(
                    Q(full_name__icontains=patient_q) |
                    Q(uhid__icontains=patient_q) |
                    Q(awpid__icontains=patient_q) |
                    Q(mobile__icontains=patient_q)
                ).values_list("awpid", flat=True)
            )
            qs = qs.filter(patient_awpid__in=matching_awpids)

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
        attach_vitals(page_items)
        serializer = AppointmentSerializer(page_items, many=True, context={"db": db})
        data = serializer.data

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
                .filter(encounter_id__in=enc_ids, items__isnull=False)
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
        from apps.opd.models import HospitalPatient

        db = request.hospital_db
        qs = Appointment.objects.using(db)

        acts_as = getattr(request.user, "acts_as", [])
        if request.user.role == "doctor" or "doctor" in acts_as:
            qs = qs.filter(doctor_user_id=request.user.id)

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_user_id__in=nurse_doctor_ids)

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

        doctor_param = request.query_params.get("doctor_user_id")
        if doctor_param:
            qs = qs.filter(doctor_user_id=doctor_param)

        branch_param = request.query_params.get("branch_id")
        if branch_param and branch_param != "all":
            qs = qs.filter(branch_id=branch_param)
        elif not branch_param and (
            request.user.role in ("front_desk", "nurse") or set(acts_as) & {"front_desk", "nurse"}
        ) and request.user.branch_id:
            qs = qs.filter(branch_id=request.user.branch_id)

        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            matching_awpids = list(
                HospitalPatient.objects.using(db).filter(
                    Q(full_name__icontains=patient_q) |
                    Q(uhid__icontains=patient_q) |
                    Q(awpid__icontains=patient_q) |
                    Q(mobile__icontains=patient_q)
                ).values_list("awpid", flat=True)
            )
            qs = qs.filter(
                Q(patient_awpid__in=matching_awpids)
                | Q(doctor_name__icontains=patient_q)
                | Q(chief_complaint__icontains=patient_q)
                | Q(room_name__icontains=patient_q)
                | Q(token_number__icontains=patient_q)
            )

        # Ascending — "what's next" reads top-to-bottom chronologically,
        from django.db.models import F
        qs = qs.order_by("scheduled_date", F("scheduled_time").asc(nulls_last=True), "token_number")

        page_items, meta = paginate_queryset(request, qs)
        attach_vitals(page_items)
        serializer = AppointmentSerializer(page_items, many=True, context={"db": db})
        return Response({"results": serializer.data, "pagination": meta})


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
            qs = qs.filter(doctor_user_id=request.user.id)

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
        from apps.opd.models import HospitalPatient

        db = request.hospital_db
        mon_date = request.query_params.get("date", str(date.today()))

        encounters = (OPDEncounter.objects.using(db)
                      .select_related("appointment")
                      .filter(appointment__scheduled_date=mon_date)
                      .order_by("appointment__token_number"))

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            encounters = encounters.filter(doctor_user_id__in=nurse_doctor_ids)

        branch_param = request.query_params.get("branch_id")
        if branch_param and branch_param != "all":
            encounters = encounters.filter(appointment__branch_id=branch_param)
        elif not branch_param and request.user.role in ("front_desk", "nurse") and request.user.branch_id:
            encounters = encounters.filter(appointment__branch_id=request.user.branch_id)

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
        patient_uuids = [enc.patient_id for enc in page_items if enc.patient_id]

        patients_by_uuid = {
            p.uuid: p for p in HospitalPatient.objects.using(db).filter(uuid__in=patient_uuids)
        }
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
            patient = patients_by_uuid.get(enc.patient_id)
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
                "patient_pk":      patient.id if patient else None,
                "patient_name":    patient.full_name if patient else appt.patient_awpid,
                "patient_uhid":    patient.uhid if patient else "",
                "is_dependent":    bool(patient and patient.is_dependent),
                "guardian_name":   patient.guardian_name if patient else "",
                "guardian_relation": patient.guardian_relation if patient else "",
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
            appt = Appointment.objects.using(db).get(pk=pk)
        except Appointment.DoesNotExist:
            return api_not_found("Appointment not found.")
        return Response(AppointmentSerializer(appt, context={"db": db}).data)


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
            appt = Appointment.objects.using(db).get(pk=pk)
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
        return Response(AppointmentSerializer(appt, context={"db": db}).data)


class AppointmentRescheduleView(APIView):
    """POST /api/v1/opd/appointments/<id>/reschedule/  {scheduled_date, scheduled_time?}"""
    permission_classes = [IsHospitalStaff]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            appt = Appointment.objects.using(db).get(pk=pk)
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
                doctor_user_id=appt.doctor_user_id,
                scheduled_time=new_time,
            ).exclude(status="cancelled").exclude(pk=appt.pk).exists()
            if taken:
                return api_error("That slot was just taken. Please pick another.", status=409)

        last_token = Appointment.objects.using(db).filter(
            scheduled_date=new_date,
            doctor_user_id=appt.doctor_user_id,
        ).exclude(pk=appt.pk).values_list("token_number", flat=True)
        next_token = (max(last_token) + 1) if last_token else 1

        room_fields = {"room_id": None, "room_name": "", "floor": ""}
        if new_time:
            from apps.hospital_setup.room_utils import resolve_room_for_slot
            match = resolve_room_for_slot(db, appt.doctor_user_id, new_date.weekday(), new_time)
            if match:
                room_fields = {
                    "room_id": match.room_id,
                    "room_name": match.room.name,
                    "floor": match.room.floor,
                }

        appt.scheduled_date = new_date
        appt.scheduled_time = new_time
        appt.token_number = next_token
        appt.status = Appointment.STATUS_SCHEDULED
        for k, v in room_fields.items():
            setattr(appt, k, v)
        appt.save(using=db)
        return Response(AppointmentSerializer(appt, context={"db": db}).data)


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
        qs = OPDEncounter.objects.using(db).select_related("appointment")
        appointment_id = request.query_params.get("appointment")
        if appointment_id:
            qs = qs.filter(appointment_id=appointment_id)
        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            qs = qs.filter(doctor_user_id=request.user.id)
        qs = qs.order_by("-created_at")
        page_items, meta = paginate_queryset(request, qs)
        return Response({
            "results": OPDEncounterSerializer(page_items, many=True, context={"db": db}).data,
            "pagination": meta,
        })

    def post(self, request):
        # Checks acts_as too — a custom role bundling "doctor" (e.g. a
        if request.user.role != "doctor" and "doctor" not in getattr(request.user, "acts_as", []):
            return api_forbidden("Only doctors can create encounters.")
        db = request.hospital_db
        serializer = OPDEncounterCreateSerializer(data=request.data, context={"db": db})
        serializer.is_valid(raise_exception=True)
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
        enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=encounter.pk)
        return Response(OPDEncounterSerializer(enc, context={"db": db}).data, status=status.HTTP_201_CREATED)


class EncounterDetailView(APIView):
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        db = request.hospital_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")
        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)

    def patch(self, request, pk):
        db = request.hospital_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
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
        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


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


def _create_prescription_for(enc, db):
    from core.utils.nntm import get_next_number
    from apps.opd.models import HospitalPatient
    rx_number = None
    try:
        patient = HospitalPatient.objects.using(db).get(uuid=enc.patient_id)
        rx_number, _ = get_next_number(branch_id=patient.branch_id or 1, entity="prescription", using=db)
    except Exception:
        pass
    return Prescription.objects.using(db).create(
        encounter=enc, patient_id=enc.patient_id, doctor_user_id=enc.doctor_user_id, rx_number=rx_number,
    )


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


def _store_handwriting_pdfs(enc, db, hospital_id, session_id):
    """After sign: archive the consult pad's RAW HANDWRITING as permanent PDFs"""
    if not session_id:
        return
    try:
        import base64
        from apps.opd.pdf import images_to_pdf
        from apps.opd.models import HospitalPatient
        from apps.hospital_master.models import Hospital
        from apps.patients.models import ConsultSession
        from apps.documents.models import MedicalDocument
        from apps.documents.lib_documents import create_issued_document
        from core import storage as blob_storage

        sess = ConsultSession.objects.using("default").filter(id=session_id).first()
        if not sess:
            return
        patient = HospitalPatient.objects.using(db).filter(uuid=enc.patient_id).first()
        if not patient:
            return
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
        return OPDEncounter.objects.using(request.hospital_db).get(pk=pk)

    def post(self, request, pk):
        if (request.data or {}).get("action") == "recognise":
            return self._recognise(request, pk)
        from django.conf import settings
        from apps.patients.models import Patient
        from apps.patients.models import ConsultSession
        from apps.opd.models import HospitalPatient
        from apps.opd.qr import render_qr_data_uri

        try:
            enc = self._enc(request, pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        patient = HospitalPatient.objects.using(request.hospital_db).filter(uuid=enc.patient_id).first()
        if not patient:
            return api_not_found("Patient not found.")
        identity = Patient.objects.using("default").filter(awpid=patient.awpid).first()
        if not identity:
            return api_not_found("This patient has no atomwalk identity yet.")

        sess = _open_consult_session(enc.id, request.hospital_id)
        if not sess:
            sess = ConsultSession.objects.using("default").create(
                patient=identity, hospital_id=request.hospital_id, encounter_id=enc.id,
                doctor_user_id=request.user.id,
                expires_at=timezone.now() + timedelta(hours=12),
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
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
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

        # Fetch patient once, share across the two post-sign side effects below.
        from apps.opd.models import HospitalPatient
        try:
            patient = HospitalPatient.objects.using(db).get(uuid=enc.patient_id)
        except HospitalPatient.DoesNotExist:
            patient = None

        # Auto-generate invoice for this encounter
        auto_generate_invoice(enc, db, request.user, patient, hospital_id=request.hospital_id)

        # Write-through to the cross-hospital HIE shared tables (atomwalk DB).
        sync_encounter_to_hie(enc, db, patient, hospital_id=request.hospital_id)

        # Store the prescription as a PDF (doctor history + patient portal),
        _store_prescription_pdf(enc, db, request.hospital_id)
        if sess:
            _store_handwriting_pdfs(enc, db, request.hospital_id, sess.id)
            from apps.patients.models import ConsultSession
            ConsultSession.objects.using("default").filter(id=sess.id).update(
                status=ConsultSession.STATUS_SIGNED, signed_at=timezone.now(),
            )

        from core.utils.audit import log_action
        log_action(request, db, action="encounter.sign", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.patient_id)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


class FollowUpActionView(APIView):
    """POST /api/v1/opd/encounters/<id>/follow-up/"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        db = request.hospital_db
        try:
            enc = OPDEncounter.objects.using(db).get(pk=pk)
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
                    resource_id=enc.id, patient_id=enc.patient_id)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


def _reconstruct_shared_reference(enc, db):
    """Best-effort "most recent documented visit" summary built from the"""
    from apps.opd.models import HospitalPatient
    from apps.opd.patient_services import PatientService

    try:
        patient = HospitalPatient.objects.using(db).get(uuid=enc.patient_id)
    except HospitalPatient.DoesNotExist:
        return None
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
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        # Match on patient_id OR the appointment's own patient_awpid.
        awpid = getattr(enc.appointment, "patient_awpid", "") if getattr(enc, "appointment", None) else ""
        match = Q(patient_id=enc.patient_id)
        if awpid:
            match |= Q(appointment__patient_awpid=awpid)

        earlier = (OPDEncounter.objects.using(db)
                   .filter(match)
                   .exclude(pk=enc.pk))

        previous = (earlier.filter(status=OPDEncounter.STATUS_SIGNED)
                    .order_by("-signed_at")
                    .first())

        if previous:
            return Response({
                "data": OPDEncounterSerializer(previous, context={"db": db}).data,
                "unsigned_pending": False,
                "shared_reference": None,
            })

        unsigned_pending = earlier.exclude(status=OPDEncounter.STATUS_SIGNED).exists()
        shared_reference = None if unsigned_pending else _reconstruct_shared_reference(enc, db)

        # TEMPORARY diagnostic — this "not found" result has been wrong
        from apps.opd.models import HospitalPatient as _DebugPatient

        recent = list(
            OPDEncounter.objects.using(db)
            .exclude(pk=enc.pk)
            .select_related("appointment")
            .order_by("-created_at")[:15]
            .values(
                "id", "status", "signed_at", "created_at", "patient_id", "subjective",
                "appointment__patient_awpid", "appointment__scheduled_date", "appointment__patient_id",
            )
        )
        for row in recent:
            row["id"] = str(row["id"])
            row["patient_id"] = str(row["patient_id"])
            row["appointment__patient_id"] = str(row["appointment__patient_id"])
            row["subjective"] = (row["subjective"] or "")[:60]
            row["signed_at"] = row["signed_at"].isoformat() if row["signed_at"] else None
            row["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
            row["appointment__scheduled_date"] = (
                row["appointment__scheduled_date"].isoformat() if row["appointment__scheduled_date"] else None
            )

        # Pull in the real Patient identity (uhid/full_name) behind both
        id_pool = {enc.patient_id}
        for row in recent:
            id_pool.add(row["patient_id"])
            id_pool.add(row["appointment__patient_id"])
        id_pool.discard(None)
        patients_by_id = {
            str(p.uuid): {"uhid": p.uhid, "name": p.full_name, "awpid": p.awpid}
            for p in _DebugPatient.objects.using(db).filter(uuid__in=id_pool)
        }
        for row in recent:
            row["patient"] = patients_by_id.get(row["patient_id"])
            row["appointment_patient"] = patients_by_id.get(row["appointment__patient_id"])

        debug = {
            "this_encounter_id": str(enc.pk),
            "this_patient_id": str(enc.patient_id),
            "this_patient": patients_by_id.get(str(enc.patient_id)),
            "this_appointment_patient_id": str(getattr(enc.appointment, "patient_id", "")),
            "this_appointment_awpid": awpid,
            "recent_encounters_this_hospital": recent,
        }

        return Response({
            "data": None, "unsigned_pending": unsigned_pending,
            "shared_reference": shared_reference, "debug": debug,
        })


class FollowupNurseWorklistView(APIView):
    """GET /api/v1/opd/followups/nurse-worklist/"""
    permission_classes = [IsHospitalStaff]

    def get(self, request):
        from apps.opd.models import HospitalPatient
        from apps.hospital_setup.models import StaffUser

        db = request.hospital_db
        encounters = (OPDEncounter.objects.using(db)
                      .filter(followup_ask_nurse=True, followup_nurse_booked=False)
                      .order_by("-followup_nurse_requested_at"))

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            encounters = encounters.filter(doctor_user_id__in=nurse_doctor_ids)

        patients_by_uuid = {
            p.uuid: p for p in HospitalPatient.objects.using(db).filter(
                uuid__in=[e.patient_id for e in encounters]
            )
        }
        doctors_by_id = {
            d.id: d for d in StaffUser.objects.using(db).filter(
                pk__in=[e.doctor_user_id for e in encounters]
            )
        }

        results = []
        for enc in encounters:
            patient = patients_by_uuid.get(enc.patient_id)
            doctor = doctors_by_id.get(enc.doctor_user_id)
            results.append({
                "encounter_id": str(enc.id),
                "patient_name": patient.full_name if patient else "",
                "patient_uhid": patient.uhid if patient else "",
                "doctor_name": doctor.get_full_name() if doctor else "",
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
            enc = OPDEncounter.objects.using(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        enc.followup_nurse_booked = True
        enc.followup_nurse_booked_at = timezone.now()
        enc.save(using=db)

        from core.utils.audit import log_action
        log_action(request, db, action="encounter.followup.marked_booked", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.patient_id)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


class EncounterSummaryPDFView(APIView):
    """GET /api/v1/opd/encounters/<id>/pdf/"""
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        import base64
        import uuid as _uuid
        from apps.opd.pdf import generate_encounter_summary_pdf
        from apps.opd.models import HospitalPatient
        from apps.hospital_setup.models import StaffUser
        from apps.hospital_setup.models import Branch

        db = request.hospital_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Not found.")

        appointment = enc.appointment
        try:
            patient = HospitalPatient.objects.using(db).get(uuid=enc.patient_id)
        except HospitalPatient.DoesNotExist:
            patient = None

        doctor_name = None
        try:
            raw = enc.doctor_user_id.int if isinstance(enc.doctor_user_id, _uuid.UUID) else enc.doctor_user_id
            doctor_name = StaffUser.objects.using(db).get(pk=raw).get_full_name()
        except Exception:
            logger.debug("EncounterSummaryPDFView: doctor lookup failed for encounter=%s", enc.id, exc_info=True)

        rx_items = []
        try:
            rx = Prescription.objects.using(db).get(encounter_id=enc.id)
            rx_items = list(rx.items.using(db).all())
        except Prescription.DoesNotExist:
            pass

        branch = Branch.objects.using(db).filter(pk=appointment.branch_id).first() if appointment and appointment.branch_id else None
        from apps.hospital_master.models import Hospital
        hospital = Hospital.objects.using("default").filter(pk=request.hospital_id).first()
        hospital_name = hospital.name if hospital else "Hospital"

        pdf_bytes = generate_encounter_summary_pdf(
            encounter=enc, appointment=appointment, diagnoses=enc.diagnoses or [],
            rx_items=rx_items, doctor_name=doctor_name, patient=patient,
            branch=branch, hospital_name=hospital_name,
        )
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
            enc = OPDEncounter.objects.using(db).get(pk=encounter_id)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        if hasattr(enc, "prescription"):
            # Carries an extra `prescription_id` field alongside the standard
            return Response({
                "success": False,
                "message": "Prescription already exists for this encounter.",
                "errors": {},
                "prescription_id": str(enc.prescription.id),
            }, status=409)

        # rx_number: a real, sequential, quotable-at-the-counter token —
        from core.utils.nntm import get_next_number
        from apps.opd.models import HospitalPatient
        rx_number = None
        try:
            patient = HospitalPatient.objects.using(db).get(uuid=enc.patient_id)
            rx_number, _ = get_next_number(branch_id=patient.branch_id or 1, entity="prescription", using=db)
        except Exception as e:
            logger.warning("Could not generate rx_number for encounter %s: %s", enc.id, e)

        rx = Prescription.objects.using(db).create(
            encounter=enc,
            patient_id=enc.patient_id,
            doctor_user_id=enc.doctor_user_id,
            notes=request.data.get("notes", ""),
            rx_number=rx_number,
        )
        return Response(PrescriptionSerializer(rx).data, status=201)


class PrescriptionDetailView(APIView):
    permission_classes = [IsHospitalStaff]

    def get(self, request, pk):
        db = request.hospital_db
        try:
            rx = Prescription.objects.using(db).prefetch_related("items").get(pk=pk)
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


class FavouriteListCreateView(APIView):
    permission_classes = [IsDoctor]

    def get(self, request):
        db = request.hospital_db
        favs = PrescriptionFavourite.objects.using(db).filter(
            doctor_user_id=request.user.id
        ).order_by("name")
        return Response(PrescriptionFavouriteSerializer(favs, many=True).data)

    def post(self, request):
        db = request.hospital_db
        serializer = PrescriptionFavouriteSerializer(data={
            **request.data, "doctor_user_id": str(request.user.id)
        })
        serializer.is_valid(raise_exception=True)
        fav = PrescriptionFavourite.objects.using(db).create(**serializer.validated_data)
        return Response(PrescriptionFavouriteSerializer(fav).data, status=201)


class FavouriteDeleteView(APIView):
    permission_classes = [IsDoctor]

    def delete(self, request, pk):
        db = request.hospital_db
        try:
            fav = PrescriptionFavourite.objects.using(db).get(pk=pk, doctor_user_id=request.user.id)
        except PrescriptionFavourite.DoesNotExist:
            return api_not_found("Not found.")
        fav.delete(using=db)
        return Response(status=204)
