"""
OPD API Views

Queue:
  GET    /api/v1/opd/appointments/             — today's queue (by doctor)
  POST   /api/v1/opd/appointments/             — book appointment
  GET    /api/v1/opd/appointments/<id>/        — appointment detail
  POST   /api/v1/opd/appointments/<id>/status/ — move queue state

Encounters:
  POST   /api/v1/opd/encounters/               — create/open encounter
  GET    /api/v1/opd/encounters/<id>/          — get encounter
  PATCH  /api/v1/opd/encounters/<id>/          — update SOAP
  POST   /api/v1/opd/encounters/<id>/sign/     — sign off encounter

Prescriptions:
  POST   /api/v1/opd/prescriptions/            — create Rx for encounter
  GET    /api/v1/opd/prescriptions/<id>/       — get Rx
  POST   /api/v1/opd/prescriptions/<id>/items/ — add drug items
  DELETE /api/v1/opd/prescriptions/<id>/items/<item_id>/ — remove item

  GET    /api/v1/opd/favourites/               — list doctor's Rx favourites
  POST   /api/v1/opd/favourites/               — save favourite
  DELETE /api/v1/opd/favourites/<id>/          — delete favourite
"""

import logging
from datetime import date, timedelta
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from core.permissions import IsHospitalStaff as IsTenantStaff, IsDoctor, IsDoctorOrNurse, IsFrontDesk, RequireFeature
from core.pagination import paginate_queryset
from core.response import error as api_error, not_found as api_not_found, forbidden as api_forbidden, success

from .models import Appointment, OPDEncounter, Prescription, PrescriptionItem, PrescriptionFavourite, Vitals
from .serializers import (
    AppointmentSerializer, AppointmentCreateSerializer, AppointmentStatusUpdateSerializer,
    OPDEncounterSerializer, OPDEncounterCreateSerializer,
    PrescriptionSerializer, PrescriptionItemSerializer,
    PrescriptionFavouriteSerializer, VitalsSerializer,
    FollowUpActionSerializer,
)

logger = logging.getLogger(__name__)


def _nurse_assigned_doctor_ids(request, db):
    """
    Doctor id(s) this nurse is rostered to (see apps.org.NurseDoctorAssignment
    / StaffDoctorsView, admin-configured via the Staff page's "Assign
    Doctors" action) — the nurse counterpart of the doctor self-scoping
    block above (`doctor_user_id=request.user.id`). A nurse who isn't
    literally role="nurse" but acts_as one (custom role) gets this too.
    Returns None for anyone who isn't a nurse, meaning "don't scope by this".
    A nurse with zero assignments gets `set()` back — deliberately: their
    queue/vitals/upcoming-schedule/monitoring views show no patients until
    an admin assigns them at least one doctor, the same "nothing until
    configured" behavior an unassigned doctor's own queue would show.
    """
    acts_as = getattr(request.user, "acts_as", [])
    if request.user.role != "nurse" and "nurse" not in acts_as:
        return None
    from apps.org.nurse_doctor_utils import get_nurse_doctor_ids
    return get_nurse_doctor_ids(request.user.id, db)


# ──────────────────────────────────────────────────────────────────────────────
# Appointments / Queue
# ──────────────────────────────────────────────────────────────────────────────

class AppointmentListCreateView(APIView):
    """
    GET  — Today's OPD queue. Doctors see their own; admin sees all.
    POST — Book a new appointment (assigns next token number).
    """
    permission_classes = [IsTenantStaff]

    def get(self, request):
        db = request.tenant_db
        qs = Appointment.objects.using(db)

        # Filter by date
        appt_date = request.query_params.get("date", str(date.today()))
        qs = qs.filter(scheduled_date=appt_date)

        # Doctor sees only their queue unless admin. Checks acts_as too, not
        # just the literal role — a custom role bundling "doctor" (e.g. a
        # solo-clinic role) must get the same self-scoping a literal doctor
        # gets, not the unscoped whole-clinic view meant for admin/front-desk.
        acts_as = getattr(request.user, "acts_as", [])
        if request.user.role == "doctor" or "doctor" in acts_as:
            qs = qs.filter(doctor_user_id=request.user.id)

        # Nurse sees only the queue for doctor(s) the hospital admin has
        # assigned them to (see NurseDoctorAssignment) — same idea as the
        # doctor self-scoping above, just admin-configured. An unassigned
        # nurse gets an empty queryset, not the whole hospital's queue.
        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_user_id__in=nurse_doctor_ids)

        # Branch scoping — explicit ?branch_id= wins; otherwise front-desk/nurse
        # default to their own branch so a multi-branch hospital doesn't see
        # every branch's queue mixed together. "all" opts out explicitly.
        #
        # A doctor passing an explicit branch_id must actually be assigned to
        # it (see apps.org.branch_utils / StaffBranchMapping) — this is what
        # makes a doctor's branch switcher on the frontend a real access
        # boundary instead of just a UI filter; nothing previously stopped a
        # doctor from requesting any other hospital branch's queue by simply
        # passing its id.
        branch_param = request.query_params.get("branch_id")
        if branch_param and branch_param != "all":
            if request.user.role == "doctor" or "doctor" in acts_as:
                from apps.org.models import StaffUser
                from apps.org.branch_utils import is_staff_in_branch
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
        # AppointmentUpcomingView so a frontend filter bar can share one
        # set of controls across both "today" and "upcoming" views.
        doctor_param = request.query_params.get("doctor_user_id")
        if doctor_param:
            qs = qs.filter(doctor_user_id=doctor_param)
        room_param = request.query_params.get("room_id")
        if room_param:
            qs = qs.filter(room_id=room_param)

        # Free-text search across every header the front-desk queue table
        # shows: patient name/UHID/AWPID/mobile (via Patient), plus doctor
        # name, chief complaint, and room — all plain fields on Appointment
        # itself so no extra join is needed for those.
        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            from apps.patients.models import Patient
            matching_awpids = list(
                Patient.objects.using(db).filter(
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
        # cards stay accurate regardless of which page is currently loaded.
        status_counts = {
            "total":       qs.count(),
            "waiting":     qs.filter(status__in=["waiting", "scheduled"]).count(),
            "vitals_done": qs.filter(status="vitals_done").count(),
            "in_progress": qs.filter(status="in_progress").count(),
            "done":        qs.filter(status="done").count(),
        }

        # Active patients first (in consult > vitals ready > waiting > scheduled),
        # finished ones at the bottom; ties broken by token number.
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
        qs = qs.select_related("vitals").annotate(
            _prio=status_priority
        ).order_by("_prio", "token_number")
        db = request.tenant_db
        page_items, meta = paginate_queryset(request, qs)
        serializer = AppointmentSerializer(page_items, many=True, context={"db": db})
        return Response({
            "results": serializer.data,
            "count": meta["total_count"],
            "pagination": meta,
            "status_counts": status_counts,
        })

    def post(self, request):
        db = request.tenant_db
        serializer = AppointmentCreateSerializer(data=request.data)
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
        # is registered at, not wherever the booking staff member happens to
        # be assigned. Using the booker's own branch_id here was the bug
        # behind "patient not appearing in any queue": in a multi-branch
        # hospital (or whenever the booking staff account has no branch_id
        # set at all, e.g. a freshly provisioned hospital_admin), the
        # appointment could end up on a different branch_id — or None — than
        # the branch a queue view explicitly filters to, so the newly
        # registered patient silently never shows up in anyone's queue.
        # Falls back to the query param (explicit override) then the
        # booking user's branch only if the patient itself has none on file.
        from apps.patients.models import Patient
        patient = Patient.objects.using(db).filter(uuid=data["patient_id"]).first()
        branch_id = (
            (patient.branch_id if patient else None)
            or request.query_params.get("branch_id")
            or getattr(request.user, "branch_id", None)
        )

        # Resolve room/floor from org.RoomAssignment, if the hospital has set
        # any up — a doctor sharing a room with others at different times of
        # day (see apps.org.models.RoomAssignment) is looked up by day-of-week
        # + the booked time and baked into the appointment now, rather than
        # looked up live later, so it doesn't retroactively change if room
        # assignments are edited after the fact. No assignment configured for
        # this doctor/slot just leaves the appointment roomless — opt-in.
        room_fields = {}
        if scheduled_time:
            from apps.org.room_utils import resolve_room_for_slot
            day_of_week = appt_date.weekday()
            match = resolve_room_for_slot(db, data["doctor_user_id"], day_of_week, scheduled_time)
            if match:
                room_fields = {
                    "room_id": match.room_id,
                    "room_name": match.room.name,
                    "floor": match.room.floor,
                }

        # Only a same-day booking means the patient is physically here now —
        # that's the one case "Waiting" is true the moment it's booked (a
        # walk-in front-desk is registering on the spot). A future-dated
        # booking is not "waiting" at all yet; it's scheduled, and only
        # becomes "waiting" when the patient actually checks in on the day
        # (see AppointmentStatusView / QueuePage's "Check In" action). Every
        # appointment used to get STATUS_WAITING unconditionally here, which
        # made a booking made today for next week show as "waiting" — as if
        # the patient were already sitting in the hospital — on both the
        # doctor's dashboard and queue, days before they'd even arrive.
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
        # their guardian, for a dependent) have one — front-desk/nurse
        # bookings used to never appear there at all, since only the portal's
        # own booking flow wrote the registry-side PortalBooking row that
        # "My Bookings" actually reads from. See apps.registry.portal_sync.
        from apps.registry.portal_sync import sync_portal_booking
        sync_portal_booking(appointment, db)

        return Response(AppointmentSerializer(appointment, context={"db": db}).data, status=status.HTTP_201_CREATED)


class AppointmentHistoryView(APIView):
    """
    GET /api/v1/opd/history/?patient=&date_from=&date_to=&status=&page=&page_size=

    Searchable visit history — NOT limited to today like the live queue.
    Search by patient name / UHID / AWPID, optionally narrowed to a date
    range. Doctors see only their own past patients (same scoping as their
    live queue); nurse sees only their assigned doctor(s)' past patients
    (see NurseDoctorAssignment); front desk sees the whole hospital.
    """
    permission_classes = [IsTenantStaff]

    def get(self, request):
        from apps.patients.models import Patient

        db = request.tenant_db
        qs = Appointment.objects.using(db).select_related("vitals")

        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            qs = qs.filter(doctor_user_id=request.user.id)

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            qs = qs.filter(doctor_user_id__in=nurse_doctor_ids)

        patient_q = (request.query_params.get("patient") or "").strip()
        if patient_q:
            matching_awpids = list(
                Patient.objects.using(db).filter(
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
        serializer = AppointmentSerializer(page_items, many=True, context={"db": db})
        data = serializer.data

        # Per-visit indicators for the History module: does this visit have a
        # prescription, and does it have an internal (clinical) note? So the
        # UI can show an explicit "No prescription issued" / "No internal note
        # recorded" instead of just an empty space.
        enc_ids = [row["encounter"]["id"] for row in data if row.get("encounter")]
        if enc_ids:
            from apps.registry.models import SharedDocument
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
            # Three archived PDFs can hang off one encounter (see
            # apps.opd.views._store_prescription_pdf / _store_handwriting_pdfs):
            #   encounter:<id>                  -> typeset prescription  [pt + dr]
            #   encounter:<id>:handwritten:rx   -> handwritten Rx        [pt + dr]
            #   encounter:<id>:handwritten:note -> handwritten SOAP note [dr only]
            # Fetch all three in one query and bucket by ref shape.
            typeset_rx_docs, hw_rx_docs, note_docs = {}, {}, {}
            wanted_refs = []
            for i in enc_ids:
                wanted_refs += [f"encounter:{i}",
                                f"encounter:{i}:handwritten:rx",
                                f"encounter:{i}:handwritten:note"]
            for d in (SharedDocument.objects.using("default")
                      .filter(source_ref__in=wanted_refs)
                      .values("id", "source_ref", "doc_type")):
                ref = d["source_ref"]
                eid = ref.split(":", 2)[1]
                if ref.endswith(":handwritten:rx"):
                    hw_rx_docs[eid] = d["id"]
                elif ref.endswith(":handwritten:note"):
                    note_docs[eid] = d["id"]
                elif d["doc_type"] == "prescription":
                    typeset_rx_docs[eid] = d["id"]
            for row in data:
                eid = row["encounter"]["id"] if row.get("encounter") else None
                e = encs.get(eid) if eid else None
                row["prescription_doc_id"] = typeset_rx_docs.get(eid)
                row["handwritten_prescription_doc_id"] = hw_rx_docs.get(eid)
                row["internal_note_doc_id"] = note_docs.get(eid)
                row["has_internal_note"] = bool(row["internal_note_doc_id"]) or bool(e and (
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
                row["internal_note_doc_id"] = None

        return Response({"results": data, "pagination": meta})


class AppointmentUpcomingView(APIView):
    """
    GET /api/v1/opd/appointments/upcoming/?date_from=&date_to=&status=&room_id=&branch_id=&patient=

    Every appointment from today onward (ascending date/time), NOT limited
    to a single day like AppointmentListCreateView's queue — this is what
    powers the doctor's "know my whole upcoming schedule" dashboard, not
    just today's. Doctor sees only their own (same acts_as-aware scoping as
    the live queue); nurse sees only their assigned doctor(s)' upcoming
    schedule (see NurseDoctorAssignment); other staff see the whole
    hospital, narrowable to one branch/room. date_from defaults to today; passing an earlier date_from
    lets the same endpoint show a recent-past window too if ever needed,
    but the frontend dashboard only ever asks for today-forward.

    Deliberately a flat, filterable, paginated list rather than pre-grouped
    "today/tomorrow/this week" buckets server-side — the frontend groups by
    scheduled_date client-side, which stays correct across timezones/DST
    without this endpoint needing to know the caller's "today" separately
    from scheduled_date's.
    """
    permission_classes = [IsTenantStaff]

    def get(self, request):
        from apps.patients.models import Patient

        db = request.tenant_db
        qs = Appointment.objects.using(db).select_related("vitals")

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
            # coming up" — still reachable via an explicit ?status= filter.
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
                Patient.objects.using(db).filter(
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
        # the opposite of AppointmentHistoryView's newest-first "what
        # already happened" ordering. Nulls (no time picked — a walk-in
        # slot) sort after timed appointments on the same day so a
        # doctor's fixed-time bookings aren't pushed down by untimed ones.
        from django.db.models import F
        qs = qs.order_by("scheduled_date", F("scheduled_time").asc(nulls_last=True), "token_number")

        page_items, meta = paginate_queryset(request, qs)
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
    """
    POST /api/v1/opd/transcribe/  (multipart, field: audio)
    Transcribes doctor dictation using Whisper (faster-whisper, local CPU).
    Returns {"text": "..."} — the frontend shows it for review before inserting.
    """
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
            # (library internals, file paths) has no business reaching the
            # doctor's browser. They just need to know dictation didn't work.
            logger.exception("Transcription failed")
            return api_error("Transcription failed. Please try again or type the note manually.", status=500)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


class OPDStatsView(APIView):
    """
    GET /api/v1/opd/stats/?days=7
    Per-day appointment counts for the last N days (default 7, max 30).
    Doctors see only their own; other staff see the whole clinic.
    Response: {"results": [{"date": "2026-08-03", "day": "Mon", "total": 5, "done": 2}, ...]}
    """
    permission_classes = [IsTenantStaff]

    def get(self, request):
        db = request.tenant_db
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
    """
    GET /api/v1/opd/monitoring/?date=YYYY-MM-DD  (default today)
    Nurse's patient-monitoring list: every patient seen (or being seen) today
    with the doctor's orders — investigations to chase, prescriptions given,
    advice and follow-up. Lets nursing staff track patient condition post-consult.
    A nurse only sees encounters for their assigned doctor(s) (see
    NurseDoctorAssignment) — same scoping as their live queue.
    """
    permission_classes = [IsTenantStaff]

    def get(self, request):
        from apps.patients.models import Patient

        db = request.tenant_db
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
        # summary strip stays accurate regardless of which page is loaded.
        summary = {
            "total":            encounters.count(),
            "with_tests":       encounters.exclude(investigations="").exclude(investigations__isnull=True).count(),
            "with_followup":    encounters.exclude(follow_up_in_days__isnull=True).count(),
        }

        page_items, meta = paginate_queryset(request, encounters)

        # Batched lookups for the whole page instead of 3-4 separate queries
        # PER ROW (patient, prescription, prescription items, vitals) — that
        # pattern was fine at demo scale but scales linearly with a hospital's
        # daily patient count, making the nurse monitoring feed progressively
        # slower as volume grows.
        enc_ids = [enc.id for enc in page_items]
        appt_ids = [enc.appointment_id for enc in page_items]
        patient_uuids = [enc.patient_id for enc in page_items if enc.patient_id]

        patients_by_uuid = {
            p.uuid: p for p in Patient.objects.using(db).filter(uuid__in=patient_uuids)
        }
        rx_by_encounter = {
            rx.encounter_id: rx
            for rx in Prescription.objects.using(db).filter(encounter_id__in=enc_ids)
        }
        items_by_rx = {}
        for item in PrescriptionItem.objects.using(db).filter(prescription_id__in=[rx.id for rx in rx_by_encounter.values()]):
            items_by_rx.setdefault(item.prescription_id, []).append(item)
        vitals_appt_ids = set(
            Vitals.objects.using(db).filter(appointment_id__in=appt_ids).values_list("appointment_id", flat=True)
        )

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
                # not the pk) — same convention as OPDEncounterSerializer's
                # get_patient_pk(). The nurse monitoring feed needs this to
                # fetch this patient's vaccination roadmap per row.
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
    permission_classes = [IsTenantStaff]

    def get(self, request, pk):
        db = request.tenant_db
        try:
            appt = Appointment.objects.using(db).select_related("vitals").get(pk=pk)
        except Appointment.DoesNotExist:
            return api_not_found("Appointment not found.")
        return Response(AppointmentSerializer(appt, context={"db": db}).data)


class AppointmentStatusView(APIView):
    """POST /api/v1/opd/appointments/<id>/status/"""
    permission_classes = [IsTenantStaff]

    VALID_TRANSITIONS = {
        Appointment.STATUS_SCHEDULED:   [Appointment.STATUS_WAITING, Appointment.STATUS_CANCELLED],
        Appointment.STATUS_WAITING:     [Appointment.STATUS_VITALS_DONE, Appointment.STATUS_IN_PROGRESS, Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW],
        Appointment.STATUS_VITALS_DONE: [Appointment.STATUS_IN_PROGRESS, Appointment.STATUS_WAITING],
        Appointment.STATUS_IN_PROGRESS: [Appointment.STATUS_DONE, Appointment.STATUS_WAITING],
    }

    def post(self, request, pk):
        db = request.tenant_db
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
    """
    POST /api/v1/opd/appointments/<id>/reschedule/  {scheduled_date, scheduled_time?}

    Moves an appointment to a new date/time in place instead of front desk
    having to cancel and rebook. Only allowed while still SCHEDULED/WAITING
    (once vitals are taken or the doctor's started, rescheduling doesn't make
    sense — cancel and book a fresh visit instead). Re-runs the same
    slot-conflict check, token-number assignment, and room resolution used at
    booking time (see AppointmentListCreateView.post).
    """
    permission_classes = [IsTenantStaff]

    def post(self, request, pk):
        db = request.tenant_db
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
            from apps.org.room_utils import resolve_room_for_slot
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
    """POST /api/v1/opd/appointments/<id>/vitals/"""
    permission_classes = [IsTenantStaff]

    def post(self, request, pk):
        db = request.tenant_db
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

        vitals, created = Vitals.objects.using(db).update_or_create(
            appointment=appt,
            defaults={**serializer.validated_data, "recorded_by_user_id": request.user.id},
        )

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


# ──────────────────────────────────────────────────────────────────────────────
# OPD Encounters
# ──────────────────────────────────────────────────────────────────────────────

class EncounterCreateView(APIView):
    """GET/POST /api/v1/opd/encounters/"""
    permission_classes = [IsTenantStaff]

    def get(self, request):
        db = request.tenant_db
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
        # solo-clinic role that's also nurse/front-desk) must be able to
        # open a consultation, the same as a literal doctor. Before this,
        # any custom-role staff hit a hard "Only doctors can create
        # encounters" wall here even when invited specifically to act as one.
        if request.user.role != "doctor" and "doctor" not in getattr(request.user, "acts_as", []):
            return api_forbidden("Only doctors can create encounters.")
        db = request.tenant_db
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
    permission_classes = [IsTenantStaff]

    def get(self, request, pk):
        db = request.tenant_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")
        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)

    def patch(self, request, pk):
        db = request.tenant_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Not found.")

        if enc.status == OPDEncounter.STATUS_SIGNED:
            return api_error("Cannot edit a signed encounter.")

        # A follow-up "in 0 days" isn't a real follow-up (it's just today,
        # the same visit) — only a positive day count or clearing the field
        # entirely (null) make sense, so reject 0/negative here rather than
        # silently accepting a value the rest of the flow can't sensibly act
        # on (e.g. front-desk's follow-up booking).
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


def _open_consult_session(encounter_id, tenant_id):
    from apps.registry.models import ConsultSession
    return (ConsultSession.objects.using("default")
            .filter(encounter_id=encounter_id, tenant_id=tenant_id, status=ConsultSession.STATUS_OPEN)
            .order_by("-created_at").first())


def _fold_session_into_encounter(sess, enc, db):
    """
    Belt-and-suspenders: if the doctor signs without pressing "Load
    handwritten note", pull whatever the session's Internal-Note tab
    recognised into any still-empty encounter field, and its Prescription
    tab into Prescription rows. A field the doctor already filled is left
    alone. Returns True if anything changed.
    """
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
        # keep the verbatim text rather than dropping it on sign.
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
        # "Load handwritten note" already inserted, and the recognised dose text
        # wobbles between OCR runs, so a (name, dose) key re-adds the same drug.
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
    from apps.patients.models import Patient
    rx_number = None
    try:
        patient = Patient.objects.using(db).get(uuid=enc.patient_id)
        rx_number, _ = get_next_number(branch_id=patient.branch_id or 1, entity="prescription", using=db)
    except Exception:
        pass
    return Prescription.objects.using(db).create(
        encounter=enc, patient_id=enc.patient_id, doctor_user_id=enc.doctor_user_id, rx_number=rx_number,
    )


def _store_prescription_pdf(enc, db, tenant_id):
    """After sign: mirror the prescription to a registry
    SharedDocument(doc_type='prescription') so it shows in the doctor's
    history and the patient's My Reports. Delegates to
    apps.opd.archive.store_prescription_document, which the
    backfill_documents_from_records command reuses for existing rows."""
    rx = Prescription.objects.using(db).filter(encounter_id=enc.id).first()
    if rx is None:
        return
    try:
        from apps.opd.archive import store_prescription_document
        store_prescription_document(rx, db, tenant_id)
    except Exception:
        logger.exception("prescription PDF store failed for encounter=%s", enc.id)


def _store_handwriting_pdfs(enc, db, tenant_id, session_id):
    """
    After sign: archive the consult pad's RAW HANDWRITING as permanent PDFs
    in object storage — the original-source record behind the typeset
    prescription and the OCR'd SOAP note.

      rx_pages   -> SharedDocument(doc_type="prescription")   [patient + doctor]
      note_pages -> SharedDocument(doc_type="consult_note")   [doctor only —
                    STAFF_ONLY_DOC_TYPES, excluded from every portal query]

    Best-effort: any failure here is logged and swallowed, never blocks the
    sign. On success the now-redundant base64 canvas is cleared from the
    ConsultSession row. Idempotent via source_ref.
    """
    if not session_id:
        return
    try:
        import base64
        from apps.opd.pdf import images_to_pdf
        from apps.patients.models import Patient
        from apps.tenants.models import Tenant
        from apps.registry.models import SharedDocument, ConsultSession
        from core import storage as blob_storage

        sess = ConsultSession.objects.using("default").filter(id=session_id).first()
        if not sess:
            return
        patient = Patient.objects.using(db).filter(uuid=enc.patient_id).first()
        if not patient:
            return
        tenant = Tenant.objects.using("default").filter(pk=tenant_id).first()
        hospital = tenant.name if tenant else "Hospital"
        appt = enc.appointment if enc.appointment_id else None
        visit_date = appt.scheduled_date if appt else timezone.now().date()
        slug = blob_storage.identity_slug(
            name=patient.full_name if patient else "", identifier=getattr(patient, "awpid", ""),
        )
        rx = Prescription.objects.using(db).filter(encounter_id=enc.id).first()
        rx_label = (rx.rx_number if rx and rx.rx_number else "")

        # (tab, pages, doc_type, s3_prefix, s3_category, title)
        #   doc_type    -> SharedDocument.doc_type (drives portal visibility)
        #   s3_category -> a key from core.storage.UPLOAD_CATEGORIES (drives
        #                  the stored file name segment)
        specs = [
            ("rx", sess.rx_pages, "prescription", "prescriptions", "prescription",
             f"Handwritten Prescription{(' ' + rx_label) if rx_label else ''} — {visit_date}"),
            ("note", sess.note_pages, "consult_note", "consult-notes", "consult-note",
             f"Handwritten Consultation Note — {visit_date}"),
        ]
        cleared = {}
        for tab, pages, doc_type, prefix, category, title in specs:
            if not pages:
                continue
            ref = f"encounter:{enc.id}:handwritten:{tab}"
            if SharedDocument.objects.using("default").filter(source_ref=ref).exists():
                cleared[tab] = True  # already archived on a prior attempt
                continue
            pdf_bytes = images_to_pdf(pages, header=f"{title}  ·  {hospital}")
            if not pdf_bytes:
                continue
            pdf_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
            try:
                file_ref = blob_storage.upload_data_uri(
                    pdf_uri, prefix=prefix, mime_type="application/pdf",
                    category=category, identity=slug,
                )
            except blob_storage.StorageError:
                file_ref = pdf_uri  # local dev / no S3 — inline
            SharedDocument.objects.using("default").create(
                awpid=getattr(patient, "awpid", ""), title=title, doc_type=doc_type,
                file_name=f"{title}.pdf", mime_type="application/pdf", file_data=file_ref,
                uploaded_by="staff", source_tenant_id=tenant_id, source_ref=ref,
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


class EncounterConsultSessionView(APIView):
    """
    POST /api/v1/opd/encounters/<id>/consult-session/                 — start /
         resume the handwriting session for this encounter, returns the QR.
    POST same URL  {"action": "recognise"}                            — compile
         the handwriting NOW (lazy transcription — runs only on demand, and
         only over pages not already transcribed). Then poll GET for the result.
    GET  same URL                                                     — the
         session's current recognised state, for "Load handwritten note".
    """
    permission_classes = [IsDoctor]

    def _enc(self, request, pk):
        return OPDEncounter.objects.using(request.tenant_db).get(pk=pk)

    def post(self, request, pk):
        if (request.data or {}).get("action") == "recognise":
            return self._recognise(request, pk)
        import secrets
        from django.conf import settings
        from apps.registry.models import PatientIdentity, ConsultSession
        from apps.patients.models import Patient
        from core.qr import render_qr_data_uri

        try:
            enc = self._enc(request, pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        patient = Patient.objects.using(request.tenant_db).filter(uuid=enc.patient_id).first()
        if not patient:
            return api_not_found("Patient not found.")
        identity = PatientIdentity.objects.using("default").filter(awpid=patient.awpid).first()
        if not identity:
            return api_not_found("This patient has no registry identity yet.")

        if not identity.consult_pad_token:
            identity.consult_pad_token = secrets.token_urlsafe(32)
        identity.consult_pad_owner_tenant_id = request.tenant_id
        identity.save(using="default", update_fields=["consult_pad_token", "consult_pad_owner_tenant_id", "updated_at"])

        sess = _open_consult_session(enc.id, request.tenant_id)
        if not sess:
            sess = ConsultSession.objects.using("default").create(
                awpid=patient.awpid, tenant_id=request.tenant_id, encounter_id=enc.id,
                doctor_user_id=request.user.id,
                expires_at=timezone.now() + timedelta(hours=12),
            )

        pad_url = f"{settings.FRONTEND_URL.rstrip('/')}/consult-pad/{identity.consult_pad_token}"
        return success(data={
            "session_id": sess.id, "status": sess.status,
            "pad_url": pad_url, "qr_image": render_qr_data_uri(pad_url),
        })

    def _recognise(self, request, pk):
        """Kick off transcription on demand. Only tabs with un-transcribed
        pages (or a prior failure) actually run the model; a page whose bytes
        are already in the tab's page-text cache is re-used for free. The
        client then polls GET until status is done/empty/failed."""
        import threading
        from apps.registry.models import ConsultSession
        from apps.patients.consult_pad_views import _run_tab_recognition, _decode_pages
        from apps.patients.consult_pad_recognition import _page_key

        try:
            enc = self._enc(request, pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")
        sess = _open_consult_session(enc.id, request.tenant_id)
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
        sess = _open_consult_session(enc.id, request.tenant_id)
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
            # actual handwriting next to what was read.
            "rx_pages": sess.rx_pages or [],
            "note_pages": sess.note_pages or [],
        })


class EncounterSignView(APIView):
    """POST /api/v1/opd/encounters/<id>/sign/"""
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        db = request.tenant_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Not found.")

        if enc.status == OPDEncounter.STATUS_SIGNED:
            return api_error("Already signed.")

        # Fold in any handwriting-session content the doctor didn't explicitly
        # "Load" — so signing never silently drops what was written on the phone.
        sess = _open_consult_session(enc.id, request.tenant_id)
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
        from apps.patients.models import Patient
        try:
            patient = Patient.objects.using(db).get(uuid=enc.patient_id)
        except Patient.DoesNotExist:
            patient = None

        # Auto-generate invoice for this encounter
        _auto_generate_invoice(enc, db, request.user, patient, tenant_id=request.tenant_id)

        # Write-through to the cross-hospital HIE shared tables (registry DB).
        # This is the platform's single write-through path for shared history —
        # apps.clinical/apps.prescriptions are legacy duplicate models kept only
        # for their billing/lab/pharmacy foreign keys and are not written to by
        # the live OPD flow, so their own signals never fire. Writing straight
        # to the registry Shared* tables here is the actual source of truth.
        _sync_to_hie(enc, db, patient)

        # Store the prescription as a PDF (doctor history + patient portal),
        # archive the consult-pad's raw handwriting as PDFs, then close the
        # handwriting session for this consultation.
        _store_prescription_pdf(enc, db, request.tenant_id)
        if sess:
            _store_handwriting_pdfs(enc, db, request.tenant_id, sess.id)
            from apps.registry.models import ConsultSession
            ConsultSession.objects.using("default").filter(id=sess.id).update(
                status=ConsultSession.STATUS_SIGNED, signed_at=timezone.now(),
            )

        from core.audit import log_action
        log_action(request, db, action="encounter.sign", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.patient_id)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


class FollowUpActionView(APIView):
    """
    POST /api/v1/opd/encounters/<id>/follow-up/
    body: {"mode": "nurse", "note": "..."} or {"mode": "reminder", "follow_up_in_days": 7}

    Deliberately its OWN endpoint, separate from EncounterDetailView.patch —
    that PATCH refuses to touch a signed encounter at all, but a doctor
    needs to be able to decide the follow-up plan even AFTER sign & close
    (that's the whole point: signing locks the clinical record, not the
    doctor's ability to say what happens next for this patient).

    mode="nurse" hands the actual booking to a nurse (see
    FollowupNurseWorklistView / FollowupMarkBookedView below) instead of the
    doctor booking it themselves — there's no in-app doctor-booking flow for
    this and the nurse already coordinates with the patient/front desk.
    mode="reminder" is the pre-existing, unchanged path: just sets
    follow_up_in_days, and apps.notifications generates the patient-facing
    reminder as before.
    """
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        db = request.tenant_db
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

        from core.audit import log_action
        log_action(request, db, action=f"encounter.followup.{v['mode']}", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.patient_id)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


def _reconstruct_shared_reference(enc, db):
    """
    Best-effort "most recent documented visit" summary built from the
    cross-hospital HIE shared tables, for when this hospital has no local
    encounter for the patient at all. Only used as a fallback by
    PreviousEncounterView — see its docstring.
    """
    from apps.patients.models import Patient
    from apps.patients.services import PatientService

    try:
        patient = Patient.objects.using(db).get(uuid=enc.patient_id)
    except Patient.DoesNotExist:
        return None
    if not patient.hie_consent_given:
        return None

    history = PatientService.get_shared_history(awpid=patient.awpid)

    # Don't reference this same visit's own not-yet-signed data — only
    # records strictly before today's appointment count as "past".
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
    # what happened on that date — "the last documented visit", not a
    # jumble of every past record at once.
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
    """
    GET /api/v1/opd/encounters/<id>/previous/
    Most recent OTHER signed encounter for the same patient at this
    hospital — powers the "Past Consultation" tab on a follow-up visit.

    Only signed encounters qualify as a citable "past consultation" — a
    draft could still change. When none is found we still check for an
    unsigned prior encounter so the frontend can tell the doctor WHY
    ("nothing signed yet" vs "genuinely no visit here at this hospital"),
    rather than a flat, unexplained "not found" on what the doctor knows
    is a follow-up.

    "Follow-up" as an appointment type does NOT mean "has a prior visit at
    THIS hospital" — a patient can be following up on care from elsewhere
    (another hospital in the network, or outside it entirely). So when
    there's no local encounter at all (signed or draft) but the patient has
    consented to cross-hospital sharing and DOES have shared history on
    file, we reconstruct the most recent documented visit from that shared
    data (diagnoses/labs/prescriptions dated strictly before this visit)
    and return it as `shared_reference` — a real, useful answer instead of
    a dead end, clearly labeled as coming from shared records rather than
    a full local SOAP note.

    Returns {"data": <local encounter or null>, "unsigned_pending": bool,
    "shared_reference": <reconstructed cross-hospital visit summary or null>}.
    """
    permission_classes = [IsDoctorOrNurse]

    def get(self, request, pk):
        db = request.tenant_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        # Match on patient_id OR the appointment's own patient_awpid.
        # patient_id is a plain UUID field set independently at encounter
        # creation time (OPDEncounterCreateSerializer takes it straight from
        # the frontend, not derived from the appointment) — so two
        # encounters for the very same patient can end up with different
        # patient_id values if anything upstream (booking flow, a stale
        # cached lookup) resolved the patient differently. patient_awpid is
        # the same stable person-identifier used for cross-hospital
        # matching, stored redundantly on every Appointment, so OR-ing it in
        # catches the same person even when patient_id alone would miss it.
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
        # before despite the query logic looking correct, so rather than
        # patch blind again, surface exactly what's actually in this tenant
        # db to compare against. NOT filtered by `match` — deliberately
        # broader than the query above — so a genuine mismatch between two
        # encounters' patient_id/awpid is directly visible side by side,
        # instead of silently vanishing from a filtered debug list too.
        from apps.patients.models import Patient as _DebugPatient

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
        # patient_id fields on every row, plus this encounter's own, so a
        # UHID match with a different patient_id/awpid — a duplicate-
        # identity bug — is directly visible instead of just raw UUIDs.
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
            row["patient_identity"] = patients_by_id.get(row["patient_id"])
            row["appointment_patient_identity"] = patients_by_id.get(row["appointment__patient_id"])

        debug = {
            "this_encounter_id": str(enc.pk),
            "this_patient_id": str(enc.patient_id),
            "this_patient_identity": patients_by_id.get(str(enc.patient_id)),
            "this_appointment_patient_id": str(getattr(enc.appointment, "patient_id", "")),
            "this_appointment_awpid": awpid,
            "recent_encounters_this_tenant": recent,
        }

        return Response({
            "data": None, "unsigned_pending": unsigned_pending,
            "shared_reference": shared_reference, "debug": debug,
        })


class FollowupNurseWorklistView(APIView):
    """
    GET /api/v1/opd/followups/nurse-worklist/
    Every encounter where a doctor asked a nurse to book the patient's next
    visit and it hasn't been marked booked yet. Same nurse-to-doctor
    assignment scoping as MonitoringListView.
    """
    permission_classes = [IsTenantStaff]

    def get(self, request):
        from apps.patients.models import Patient
        from apps.org.models import StaffUser

        db = request.tenant_db
        encounters = (OPDEncounter.objects.using(db)
                      .filter(followup_ask_nurse=True, followup_nurse_booked=False)
                      .order_by("-followup_nurse_requested_at"))

        nurse_doctor_ids = _nurse_assigned_doctor_ids(request, db)
        if nurse_doctor_ids is not None:
            encounters = encounters.filter(doctor_user_id__in=nurse_doctor_ids)

        patients_by_uuid = {
            p.uuid: p for p in Patient.objects.using(db).filter(
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
    """POST /api/v1/opd/followups/<id>/mark-booked/ — nurse confirms they've
    coordinated the patient's next appointment; drops it off the worklist."""
    permission_classes = [IsTenantStaff]

    def post(self, request, pk):
        db = request.tenant_db
        try:
            enc = OPDEncounter.objects.using(db).get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        enc.followup_nurse_booked = True
        enc.followup_nurse_booked_at = timezone.now()
        enc.save(using=db)

        from core.audit import log_action
        log_action(request, db, action="encounter.followup.marked_booked", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.patient_id)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


class EncounterSummaryPDFView(APIView):
    """
    GET /api/v1/opd/encounters/<id>/pdf/

    Real, printable consultation-summary PDF for a doctor to hand a patient
    or keep for their own records — replaces the old "Download Summary"
    button, which built a plain-text .txt file entirely client-side (no
    server round trip, so it could never reflect anything not already
    sitting in the browser's own state). Same reportlab-generated,
    base64-data-URI pattern as InvoicePDFView/PortalPrescriptionReceiptPDFView.
    """
    permission_classes = [IsTenantStaff]

    def get(self, request, pk):
        import base64
        import uuid as _uuid
        from apps.opd.pdf import generate_encounter_summary_pdf
        from apps.patients.models import Patient
        from apps.org.models import StaffUser, Branch

        db = request.tenant_db
        try:
            enc = OPDEncounter.objects.using(db).select_related("appointment").get(pk=pk)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Not found.")

        appointment = enc.appointment
        try:
            patient = Patient.objects.using(db).get(uuid=enc.patient_id)
        except Patient.DoesNotExist:
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
        from apps.tenants.models import Tenant
        tenant = Tenant.objects.using("default").filter(pk=request.tenant_id).first()
        hospital_name = tenant.name if tenant else "Hospital"

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


def _sync_to_hie(encounter, db, patient):
    """
    Push a sanitized copy of this encounter's diagnoses, vitals, and
    prescription to the registry's shared HIE tables so other hospitals can
    see this patient's cross-provider history. Never blocks sign-off —
    all failures are logged and swallowed.
    """
    if patient is None or not getattr(patient, "awpid", None):
        logger.warning("HIE sync skipped for encounter %s: no patient/awpid.", encounter.id)
        return

    from core.db_router import _thread_local
    from apps.registry.models import SharedDiagnosis, SharedVital, SharedPrescription, SharedPrescriptionItem

    source_tenant_id = getattr(_thread_local, "tenant_id", 0) or 0
    awpid = patient.awpid

    # ── Diagnoses (OPDEncounter.diagnoses is a JSON list of {code, description}) ──
    for diag in (encounter.diagnoses or []):
        try:
            SharedDiagnosis.objects.using("default").update_or_create(
                awpid=awpid,
                source_tenant_id=source_tenant_id,
                icd10_code=diag.get("code", ""),
                defaults={
                    "description":     diag.get("description", ""),
                    "clinical_status": "active",
                    "onset_date":      encounter.encounter_date if hasattr(encounter, "encounter_date") else None,
                },
            )
        except Exception as exc:
            logger.error("HIE SharedDiagnosis write failed for encounter=%s: %s", encounter.id, exc)

    # ── Vitals (one row per appointment, via OneToOne) ─────────────────────
    try:
        vitals = encounter.appointment.vitals
    except Exception:
        vitals = None
    if vitals is not None:
        try:
            SharedVital.objects.using("default").update_or_create(
                awpid=awpid,
                recorded_at=vitals.recorded_at,
                defaults={
                    "source":            "clinic",
                    "bp_systolic":       vitals.systolic_bp,
                    "bp_diastolic":      vitals.diastolic_bp,
                    "pulse_rate":        vitals.pulse_rate,
                    "spo2":              vitals.spo2,
                    "temperature":       vitals.temperature,
                    "weight_kg":         vitals.weight_kg,
                    "height_cm":         vitals.height_cm,
                    "resp_rate":         vitals.respiratory_rate,
                    "blood_sugar_mgdl":  vitals.blood_sugar_rbs,
                    "source_tenant_id":  source_tenant_id,
                },
            )
        except Exception as exc:
            logger.error("HIE SharedVital write failed for encounter=%s: %s", encounter.id, exc)

    # ── Prescription (opd.Prescription is OneToOne on the encounter) ───────
    try:
        rx = encounter.prescription
    except Exception:
        rx = None
    if rx is not None:
        try:
            shared_rx, _ = SharedPrescription.objects.using("default").update_or_create(
                awpid=awpid,
                source_tenant_id=source_tenant_id,
                prescribed_on=(rx.created_at.date() if rx.created_at else timezone.now().date()),
            )
            SharedPrescriptionItem.objects.using("default").filter(prescription=shared_rx).delete()
            for item in rx.items.all():
                SharedPrescriptionItem.objects.using("default").create(
                    prescription=shared_rx,
                    drug_name=item.drug_name,
                    dose=item.dosage,
                    unit="",
                    frequency=item.frequency,
                    route=item.route,
                    duration_days=item.duration_days,
                )
        except Exception as exc:
            logger.error("HIE SharedPrescription write failed for encounter=%s: %s", encounter.id, exc)


def _resolve_doctor_consultation_fee(db, doctor_user_id, appointment_type=None):
    """
    encounter.doctor_user_id is a UUIDField, but the value actually stored
    in it is the StaffUser's plain integer pk — Django's UUIDField silently
    wraps a plain int via uuid.UUID(int=value) (see e.g. auth_app.views'
    "user_id": staff.id, saved straight into these UUID columns). Unwrap
    either form back to the integer pk so DoctorProfile can be looked up.

    For a "followup" visit, prefers DoctorProfile.followup_fee — but only
    if the doctor actually set one; otherwise falls back to their regular
    consultation_fee, so doctors who never configured a separate follow-up
    rate keep charging the same flat fee for every visit type (unchanged
    behaviour for them). Returns None if there's no doctor profile or no
    fee resolvable at all.
    """
    import uuid as _uuid
    from apps.org.models import StaffUser
    from apps.opd.models import Appointment

    raw = doctor_user_id.int if isinstance(doctor_user_id, _uuid.UUID) else doctor_user_id
    try:
        staff = StaffUser.objects.using(db).select_related("doctor_profile").get(pk=raw)
        profile = staff.doctor_profile
        if appointment_type == Appointment.TYPE_FOLLOWUP and profile.followup_fee is not None:
            return profile.followup_fee
        return profile.consultation_fee
    except Exception:
        return None


def _tenant_default_tax_rate(tenant_id):
    from decimal import Decimal
    from apps.tenants.models import Tenant
    if not tenant_id:
        return Decimal("0")
    try:
        return Tenant.objects.using("default").get(pk=tenant_id).default_tax_rate
    except Tenant.DoesNotExist:
        return Decimal("0")


def _auto_generate_invoice(encounter, db, user, patient=None, tenant_id=None):
    """
    Create a draft invoice after encounter sign-off. Never blocks sign-off.

    Uses the doctor's actual DoctorProfile fee (falls back to ₹0 — not a
    guessed flat amount — if the doctor never set one) and the tenant's
    configured default_tax_rate, instead of the old hardcoded ₹500.

    Picks consultation_fee vs followup_fee based on the appointment's
    appointment_type (see _resolve_doctor_consultation_fee), and labels the
    invoice line accordingly — so a follow-up visit is no longer charged
    and described identically to a first consultation.
    """
    from decimal import Decimal
    from apps.billing.models import Invoice, InvoiceItem
    from apps.billing.views import _recompute_invoice_totals
    from apps.patients.models import Patient
    from apps.opd.models import Appointment
    from core.utils.nntm import get_next_number

    try:
        if patient is None:
            patient = Patient.objects.using(db).get(uuid=encounter.patient_id)

        appointment_type = getattr(encounter.appointment, "appointment_type", None)
        fee = _resolve_doctor_consultation_fee(db, encounter.doctor_user_id, appointment_type)
        if fee is None:
            fee = Decimal("0")
        tax_rate = _tenant_default_tax_rate(tenant_id)
        description = (
            "Follow-up Consultation" if appointment_type == Appointment.TYPE_FOLLOWUP
            else "OPD Consultation"
        )

        invoice_number, _ = get_next_number(branch_id=patient.branch_id or 1, entity="invoice", using=db)
        invoice = Invoice.objects.using(db).create(
            patient=patient,
            branch=patient.branch,
            invoice_number=invoice_number,
            status="draft",
            created_by_id=user.id,
            notes=f"Auto-generated for OPD encounter {encounter.id}",
        )
        InvoiceItem.objects.using(db).create(
            invoice=invoice,
            description=description,
            quantity=1,
            unit_price=fee,
            tax_rate=tax_rate,
            total=fee,
        )
        _recompute_invoice_totals(invoice, db)
        logger.info("Auto-generated invoice %s for encounter %s (type=%s, fee=%s, tax_rate=%s%%)",
                    invoice.invoice_number, encounter.id, appointment_type, fee, tax_rate)
    except Exception as e:
        logger.warning("Could not auto-generate invoice: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Prescriptions
# ──────────────────────────────────────────────────────────────────────────────

class PrescriptionCreateView(APIView):
    """POST /api/v1/opd/prescriptions/"""
    permission_classes = [IsDoctor]

    def post(self, request):
        db = request.tenant_db
        encounter_id = request.data.get("encounter_id")
        if not encounter_id:
            return api_error("encounter_id required.")

        try:
            enc = OPDEncounter.objects.using(db).get(pk=encounter_id)
        except OPDEncounter.DoesNotExist:
            return api_not_found("Encounter not found.")

        if hasattr(enc, "prescription"):
            # Carries an extra `prescription_id` field alongside the standard
            # message/errors shape — the frontend uses it to redirect straight
            # to the existing prescription instead of just showing the error.
            return Response({
                "success": False,
                "message": "Prescription already exists for this encounter.",
                "errors": {},
                "prescription_id": str(enc.prescription.id),
            }, status=409)

        # rx_number: a real, sequential, quotable-at-the-counter token —
        # NNTM entity="prescription" (prefix "RX-", seeded per branch, same
        # infrastructure invoice_number/lab report_number already use).
        # Never blocks prescription creation if it fails — the doctor's
        # note-taking must not be held hostage by a numbering hiccup; the
        # rare row left with rx_number=None just isn't quotable/searchable
        # by token, same as it wasn't before this field existed.
        from core.utils.nntm import get_next_number
        from apps.patients.models import Patient
        rx_number = None
        try:
            patient = Patient.objects.using(db).get(uuid=enc.patient_id)
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
    permission_classes = [IsTenantStaff]

    def get(self, request, pk):
        db = request.tenant_db
        try:
            rx = Prescription.objects.using(db).prefetch_related("items").get(pk=pk)
        except Prescription.DoesNotExist:
            return api_not_found("Not found.")
        return Response(PrescriptionSerializer(rx).data)


class PrescriptionItemView(APIView):
    """
    POST   /api/v1/opd/prescriptions/<pk>/items/           — add drug item
    DELETE /api/v1/opd/prescriptions/<pk>/items/<item_id>/ — remove drug item
    """
    permission_classes = [IsDoctor]

    def post(self, request, pk):
        db = request.tenant_db
        try:
            rx = Prescription.objects.using(db).get(pk=pk)
        except Prescription.DoesNotExist:
            return api_not_found("Prescription not found.")

        # `drug` is looked up manually against the tenant DB rather than left
        # to the serializer's auto-generated PrimaryKeyRelatedField, which
        # would validate against the default connection — wrong database
        # entirely under per-tenant physical DBs. Same pattern as LabRequest's
        # `test` FK in apps/lab/views.py. A missing/invalid id is treated as
        # "no catalog match" rather than a hard error, so a doctor can still
        # save a free-text drug the pharmacist hasn't catalogued yet.
        payload = dict(request.data)
        drug_id = payload.pop("drug", None)
        drug_obj = None
        if drug_id:
            from apps.prescriptions.models import Drug
            drug_obj = Drug.objects.using(db).filter(pk=drug_id, is_active=True).first()

        serializer = PrescriptionItemSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        item = PrescriptionItem.objects.using(db).create(
            prescription=rx, drug=drug_obj, **serializer.validated_data
        )
        return Response(PrescriptionItemSerializer(item).data, status=201)

    def delete(self, request, pk, item_id):
        db = request.tenant_db
        try:
            item = PrescriptionItem.objects.using(db).get(pk=item_id, prescription_id=pk)
        except PrescriptionItem.DoesNotExist:
            return api_not_found("Item not found.")
        item.delete(using=db)
        return Response(status=204)


class FavouriteListCreateView(APIView):
    permission_classes = [IsDoctor]

    def get(self, request):
        db = request.tenant_db
        favs = PrescriptionFavourite.objects.using(db).filter(
            doctor_user_id=request.user.id
        ).order_by("name")
        return Response(PrescriptionFavouriteSerializer(favs, many=True).data)

    def post(self, request):
        db = request.tenant_db
        serializer = PrescriptionFavouriteSerializer(data={
            **request.data, "doctor_user_id": str(request.user.id)
        })
        serializer.is_valid(raise_exception=True)
        fav = PrescriptionFavourite.objects.using(db).create(**serializer.validated_data)
        return Response(PrescriptionFavouriteSerializer(fav).data, status=201)


class FavouriteDeleteView(APIView):
    permission_classes = [IsDoctor]

    def delete(self, request, pk):
        db = request.tenant_db
        try:
            fav = PrescriptionFavourite.objects.using(db).get(pk=pk, doctor_user_id=request.user.id)
        except PrescriptionFavourite.DoesNotExist:
            return api_not_found("Not found.")
        fav.delete(using=db)
        return Response(status=204)
