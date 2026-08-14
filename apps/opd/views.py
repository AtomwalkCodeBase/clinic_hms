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
from core.response import error as api_error, not_found as api_not_found, forbidden as api_forbidden

from .models import Appointment, OPDEncounter, Prescription, PrescriptionItem, PrescriptionFavourite, Vitals
from .serializers import (
    AppointmentSerializer, AppointmentCreateSerializer, AppointmentStatusUpdateSerializer,
    OPDEncounterSerializer, OPDEncounterCreateSerializer,
    PrescriptionSerializer, PrescriptionItemSerializer,
    PrescriptionFavouriteSerializer, VitalsSerializer,
)

logger = logging.getLogger(__name__)


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

        # Doctor sees only their queue unless admin
        if request.user.role == "doctor":
            qs = qs.filter(doctor_user_id=request.user.id)

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
            if request.user.role == "doctor":
                from apps.org.models import StaffUser
                from apps.org.branch_utils import is_staff_in_branch
                doctor = StaffUser.objects.using(db).filter(pk=request.user.id).first()
                if not doctor or not is_staff_in_branch(doctor, branch_param, db):
                    return api_forbidden("You are not assigned to that branch.")
            qs = qs.filter(branch_id=branch_param)
        elif not branch_param and request.user.role in ("front_desk", "nurse") and request.user.branch_id:
            qs = qs.filter(branch_id=request.user.branch_id)

        # Status filter
        appt_status = request.query_params.get("status")
        if appt_status:
            qs = qs.filter(status=appt_status)

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

        appointment = Appointment.objects.using(db).create(
            **data,
            token_number=next_token,
            status=Appointment.STATUS_WAITING,
            booked_by_user_id=request.user.id,
            branch_id=branch_id,
        )
        return Response(AppointmentSerializer(appointment, context={"db": db}).data, status=status.HTTP_201_CREATED)


class AppointmentHistoryView(APIView):
    """
    GET /api/v1/opd/history/?patient=&date_from=&date_to=&status=&page=&page_size=

    Searchable visit history — NOT limited to today like the live queue.
    Search by patient name / UHID / AWPID, optionally narrowed to a date
    range. Doctors see only their own past patients (same scoping as their
    live queue); front desk and nurse see the whole hospital.
    """
    permission_classes = [IsTenantStaff]

    def get(self, request):
        from apps.patients.models import Patient

        db = request.tenant_db
        qs = Appointment.objects.using(db).select_related("vitals")

        if request.user.role == "doctor":
            qs = qs.filter(doctor_user_id=request.user.id)

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
        if request.user.role == "doctor":
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
        if request.user.role == "doctor":
            qs = qs.filter(doctor_user_id=request.user.id)
        qs = qs.order_by("-created_at")
        page_items, meta = paginate_queryset(request, qs)
        return Response({
            "results": OPDEncounterSerializer(page_items, many=True, context={"db": db}).data,
            "pagination": meta,
        })

    def post(self, request):
        if request.user.role not in ("doctor",):
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

        allowed_fields = ["subjective", "objective", "assessment", "plan",
                          "investigations", "advice_to_patient", "follow_up_in_days",
                          "diagnoses", "referred_to", "referral_notes"]
        for field in allowed_fields:
            if field in request.data:
                setattr(enc, field, request.data[field])
        enc.save(using=db)
        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


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
        _auto_generate_invoice(enc, db, request.user, patient)

        # Write-through to the cross-hospital HIE shared tables (registry DB).
        # This is the platform's single write-through path for shared history —
        # apps.clinical/apps.prescriptions are legacy duplicate models kept only
        # for their billing/lab/pharmacy foreign keys and are not written to by
        # the live OPD flow, so their own signals never fire. Writing straight
        # to the registry Shared* tables here is the actual source of truth.
        _sync_to_hie(enc, db, patient)

        from core.audit import log_action
        log_action(request, db, action="encounter.sign", resource_type="OPDEncounter",
                    resource_id=enc.id, patient_id=enc.patient_id)

        return Response(OPDEncounterSerializer(enc, context={"db": db}).data)


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


def _auto_generate_invoice(encounter, db, user, patient=None):
    """Create a draft invoice after encounter sign-off. Never blocks sign-off."""
    import secrets
    from apps.billing.models import Invoice, InvoiceItem
    from apps.patients.models import Patient

    try:
        if patient is None:
            patient = Patient.objects.using(db).get(uuid=encounter.patient_id)
        invoice_number = f"INV-{timezone.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
        invoice = Invoice.objects.using(db).create(
            patient=patient,
            branch=patient.branch,
            invoice_number=invoice_number,
            status="draft",
            subtotal=500,       # Default consultation fee; configurable in Phase 2
            total_amount=500,
            created_by_id=user.id,
            notes=f"Auto-generated for OPD encounter {encounter.id}",
        )
        InvoiceItem.objects.using(db).create(
            invoice=invoice,
            description="OPD Consultation",
            quantity=1,
            unit_price=500,
            total=500,
        )
        logger.info("Auto-generated invoice %s for encounter %s", invoice.invoice_number, encounter.id)
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

        rx = Prescription.objects.using(db).create(
            encounter=enc,
            patient_id=enc.patient_id,
            doctor_user_id=enc.doctor_user_id,
            notes=request.data.get("notes", ""),
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
