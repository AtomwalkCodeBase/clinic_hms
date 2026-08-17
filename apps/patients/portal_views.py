"""
apps/patients/portal_views.py
------------------------------
Patient portal endpoints (patient JWT, no tenant context).

  POST /api/v1/portal/register/                       — create portal account
  GET  /api/v1/portal/hospitals/                      — list active hospitals
  GET  /api/v1/portal/hospitals/<tenant_id>/doctors/  — doctors at a hospital
  POST /api/v1/portal/book/                           — book an OPD slot
  GET  /api/v1/portal/my-bookings/                    — patient's bookings (live status)
"""

import re
import logging
from datetime import date, datetime, time as dtime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from core.permissions import IsPatient
from core.response import success, error, not_found
from core.pagination import paginate_list, paginate_queryset
from core.file_validation import validate_data_uri, FileValidationError
from apps.tenants.models import Tenant
from apps.registry.models import PatientAccount, PatientIdentity

logger = logging.getLogger(__name__)


def _ensure_db(db_name):
    if db_name not in settings.DATABASES:
        from apps.tenants.utils import _make_db_config
        settings.DATABASES[db_name] = _make_db_config(db_name)


# What actually gets pulled from the Registry DB into a new hospital's view —
# shown to the patient verbatim in the consent prompt, and kept in sync with
# PatientService.get_shared_history()'s five categories (plus documents).
HIE_SHARE_CATEGORIES = [
    "Past diagnoses and clinical notes",
    "Allergies on record",
    "Vitals history (BP, pulse, temperature, etc.)",
    "Prescriptions from other visits",
    "Lab test results and reports",
    "Documents you've uploaded (old reports, scans, discharge summaries)",
]


def _patient_app_enabled(tenant):
    """
    True only if this hospital's subscription has feat_patient_app on.
    Patients authenticate with a tenant-independent JWT (no MockUser.subscription
    to lean on — that's only populated for staff, see core/authentication.py),
    so every portal endpoint that touches a specific hospital re-checks this
    directly rather than trusting a JWT claim.
    """
    from apps.tenants.models import Subscription
    sub = Subscription.objects.using("default").filter(tenant=tenant).first()
    return bool(sub and sub.feat_patient_app)


# ── Register ─────────────────────────────────────────────────────────────────

class PortalRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from apps.registry.models import PatientIdentity
        from core.utils.hashing import hash_mobile, normalize_mobile
        from core.utils.awpid import generate_unique_awpid

        d = request.data
        required = ["full_name", "mobile", "password"]
        missing = [f for f in required if not str(d.get(f, "")).strip()]
        if missing:
            return error(f"Missing fields: {', '.join(missing)}")

        mobile = d["mobile"].strip()
        if not re.match(r"^\d{10}$", mobile):
            return error("Enter a valid 10-digit mobile number.", errors={"mobile": "Invalid format."})
        if PatientAccount.objects.using("default").filter(mobile=mobile).exists():
            return error("An account with this mobile number already exists. Please log in.")

        email = (d.get("email") or "").strip().lower() or None
        if email and PatientAccount.objects.using("default").filter(email__iexact=email).exists():
            return error("An account with this email already exists.")

        # ── Reuse (or create) this person's global PatientIdentity ─────────
        # Self-registering here used to only create a PatientAccount (the
        # login) and generate its own one-off AWPID, never touching
        # PatientIdentity — the registry table every hospital's front desk
        # actually searches (see PatientService.lookup_by_mobile). That made
        # every self-registered patient invisible to front-desk dedup, so
        # the same person could get registered a second time as a "new"
        # walk-in with no link back to their portal account, and vice versa:
        # someone already registered as a walk-in at some hospital before
        # ever signing up here would get a second, disconnected AWPID on
        # sign-up instead of claiming their existing one. get_or_create on
        # mobile_hash — the same dedup key PatientService.register() uses
        # for front-desk registration — fixes both directions at once.
        mobile_norm = normalize_mobile(mobile)
        mobile_hash = hash_mobile(mobile_norm)
        gender = (d.get("gender") or "")[:1].upper()
        with transaction.atomic(using="default"):
            identity, _ = PatientIdentity.objects.using("default").get_or_create(
                mobile_hash=mobile_hash,
                defaults={
                    "awpid":         generate_unique_awpid(),
                    "full_name":     d["full_name"].strip(),
                    "date_of_birth": d.get("date_of_birth") or None,
                    "gender":        gender,
                    "email":         email or "",
                },
            )

            acct = PatientAccount(
                awpid=identity.awpid,
                full_name=d["full_name"].strip(),
                email=email,
                mobile=mobile,
                gender=gender,
                date_of_birth=d.get("date_of_birth") or None,
            )
            acct.set_password(d["password"])
            acct.save(using="default")

        return success(
            data={"awpid": acct.awpid, "mobile": acct.mobile},
            message="Account created. You can now log in.",
        )


# ── Hospitals & doctors ──────────────────────────────────────────────────────

class PortalHospitalListView(APIView):
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.tenants.models import Subscription
        enabled_tenant_ids = set(
            Subscription.objects.using("default")
            .filter(feat_patient_app=True)
            .values_list("tenant_id", flat=True)
        )
        hospitals = [
            {
                "tenant_id": t.id,
                "name": t.name,
                "city": t.city or "",
                "state": t.state or "",
                "accreditations": [a.strip() for a in (t.accreditations or "").split(",") if a.strip()],
                "about": t.about or "",
            }
            for t in Tenant.objects.using("default").filter(is_active=True, id__in=enabled_tenant_ids).order_by("name")
        ]
        return Response({"results": hospitals})


class PortalPlatformStatsView(APIView):
    """
    GET /api/v1/portal/stats/ — real counts for the dashboard's hero panel
    (hospitals on the platform, doctors across all of them). No made-up
    marketing numbers — this is a live count from the registry + each
    active tenant's own staff table.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.org.models import StaffUser

        active_tenants = list(Tenant.objects.using("default").filter(is_active=True))
        doctor_count = 0
        for tenant in active_tenants:
            try:
                _ensure_db(tenant.db_name)
                doctor_count += StaffUser.objects.using(tenant.db_name).filter(
                    role="doctor", is_active=True
                ).count()
            except Exception as exc:
                logger.warning("portal stats: skipped %s (%s)", tenant.db_name, exc)

        return Response({
            "hospitals": len(active_tenants),
            "doctors": doctor_count,
        })


# Lay terms → the substrings that actually show up in a free-text
# `specialisation` field (hospital admins type this in, no fixed list) —
# lets "heart surgeon" or "opthalmologist" (misspelled, patients will
# misspell this) actually find "Cardiothoracic Surgeon" / "Ophthalmologist".
_SPECIALITY_SYNONYMS = {
    "generalist":        ["general physician", "general medicine", "gp"],
    "general physician": ["general medicine", "gp"],
    "family doctor":     ["general physician", "general medicine", "gp"],
    "eye doctor":        ["ophthalmolog"],
    "opthalmologist":    ["ophthalmolog"],
    "ophthalmologist":   ["ophthalmolog"],
    "heart doctor":      ["cardiolog", "cardiac"],
    "heart surgeon":     ["cardiac surg", "cardiothorac", "cardiovascular surg"],
    "cardiologist":      ["cardiolog"],
    "skin doctor":       ["dermatolog"],
    "dermatologist":     ["dermatolog"],
    "bone doctor":       ["orthoped"],
    "orthopedic":        ["orthoped"],
    "orthopaedic":       ["orthoped"],
    "child specialist":  ["pediatric", "paediatric"],
    "children doctor":   ["pediatric", "paediatric"],
    "pediatrician":      ["pediatric", "paediatric"],
    "paediatrician":     ["pediatric", "paediatric"],
    "kidney doctor":     ["nephrolog"],
    "brain doctor":      ["neurolog"],
    "neurologist":       ["neurolog"],
    "cancer doctor":     ["oncolog"],
    "womens doctor":     ["gynaecolog", "gynecolog", "obstetric"],
    "gynecologist":      ["gynaecolog", "gynecolog"],
    "gynaecologist":     ["gynaecolog", "gynecolog"],
    "ent":               ["ear nose throat", "otolaryngolog", "ent"],
    "dentist":           ["dental"],
    "psychiatrist":      ["psychiatr", "mental health"],
    "lung doctor":       ["pulmonolog", "respiratory"],
    "stomach doctor":    ["gastroenterolog"],
    "gastroenterologist":["gastroenterolog"],
    "urologist":         ["urolog"],
}


def _expand_search_terms(q):
    """A plain substring match plus any lay-term synonyms that apply."""
    ql = q.lower().strip()
    terms = {ql}
    for key, synonyms in _SPECIALITY_SYNONYMS.items():
        if key in ql or ql in key:
            terms.update(synonyms)
    return terms


class PortalSearchView(APIView):
    """
    GET /api/v1/portal/search/?q=<term>
    One search box for the whole platform. A patient can type a hospital
    name, a doctor's name, or a reason/specialisation ("cardiologist",
    "eye doctor", "generalist") and get matching doctors from EVERY active
    hospital — not just one they've already picked — plus matching
    hospitals. This is the entry point the redesigned dashboard search uses.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        specialty = (request.query_params.get("specialty") or "").strip()
        city = (request.query_params.get("city") or "").strip()
        sort = (request.query_params.get("sort") or "").strip()  # "experience" | "fee" | "name"
        if len(q) < 2 and not specialty and not city:
            return Response({"hospitals": [], "doctors": []})

        terms = _expand_search_terms(q) if q else set()

        hosp_q = Q()
        for t in terms:
            hosp_q |= Q(name__icontains=t) | Q(city__icontains=t) | Q(state__icontains=t)
        tenant_qs = Tenant.objects.using("default").filter(is_active=True)
        if hosp_q:
            tenant_qs = tenant_qs.filter(hosp_q)
        if city:
            tenant_qs = tenant_qs.filter(city__icontains=city)
        hospitals = [
            {
                "tenant_id": t.id,
                "name": t.name,
                "city": t.city or "",
                "state": t.state or "",
                "accreditations": [a.strip() for a in (t.accreditations or "").split(",") if a.strip()],
                "about": t.about or "",
            }
            for t in tenant_qs.order_by("name")[:20]
        ]

        from apps.org.models import StaffUser, DoctorProfile

        specialty_terms = _expand_search_terms(specialty) if specialty else set()

        doctors = []
        for tenant in Tenant.objects.using("default").filter(is_active=True):
            if city and city.lower() not in (tenant.city or "").lower():
                continue
            db = tenant.db_name
            try:
                _ensure_db(db)

                name_q = Q()
                for t in terms:
                    name_q |= Q(first_name__icontains=t) | Q(last_name__icontains=t)
                name_matches = set(
                    StaffUser.objects.using(db).filter(role="doctor", is_active=True)
                    .filter(name_q).values_list("id", flat=True)
                ) if terms else set()

                profile_q = Q()
                for t in terms:
                    profile_q |= (Q(specialisation__icontains=t) | Q(qualification__icontains=t)
                                  | Q(known_for__icontains=t))
                profile_matches = set(
                    DoctorProfile.objects.using(db).filter(profile_q).values_list("staff_id", flat=True)
                ) if terms else set()

                matched_ids = name_matches | profile_matches

                if specialty_terms:
                    spec_q = Q()
                    for t in specialty_terms:
                        spec_q |= (Q(specialisation__icontains=t) | Q(known_for__icontains=t))
                    spec_matches = set(
                        DoctorProfile.objects.using(db).filter(spec_q).values_list("staff_id", flat=True)
                    )
                    matched_ids = (matched_ids & spec_matches) if matched_ids else spec_matches
                elif not terms:
                    # No text query — city-only browse: every active doctor at this hospital.
                    matched_ids = set(
                        StaffUser.objects.using(db).filter(role="doctor", is_active=True)
                        .values_list("id", flat=True)
                    )

                if not matched_ids:
                    continue

                staff_by_id = {
                    s.id: s for s in
                    StaffUser.objects.using(db).filter(id__in=matched_ids, role="doctor", is_active=True)
                }
                profiles_by_staff = {
                    p.staff_id: p for p in
                    DoctorProfile.objects.using(db).filter(staff_id__in=staff_by_id.keys())
                }
                for sid, staff in staff_by_id.items():
                    card = _doctor_card(staff, profiles_by_staff.get(sid))
                    card["tenant_id"] = tenant.id
                    card["hospital"] = tenant.name
                    card["hospital_city"] = tenant.city or ""
                    doctors.append(card)
            except Exception as exc:
                logger.warning("portal search: skipped %s (%s)", db, exc)

        if sort == "experience":
            doctors.sort(key=lambda d: d["experience_years"] or 0, reverse=True)
        elif sort == "fee":
            doctors.sort(key=lambda d: float(d["consultation_fee"]) if d["consultation_fee"] else float("inf"))
        elif sort == "name":
            doctors.sort(key=lambda d: d["name"].lower())

        return Response({"hospitals": hospitals, "doctors": doctors[:40]})


_DR_PREFIX_RE = re.compile(r"^dr\.?\s+", re.IGNORECASE)


def _doctor_display_name(staff):
    """
    Always "Dr. <name>", exactly once — regardless of whether whoever set
    up the staff account already typed "Dr." into the first name field
    (front desk / hospital admin invite forms don't forbid it, so some
    accounts have first_name="Dr. Riya" and some just "Riya").
    """
    full_name = staff.get_full_name()
    stripped = _DR_PREFIX_RE.sub("", full_name).strip()
    return f"Dr. {stripped}" if stripped else full_name


def _doctor_card(staff, profile):
    """Shared shape for doctor list + doctor detail — keeps the two endpoints in sync."""
    return {
        "id": staff.id,
        "name": _doctor_display_name(staff),
        "photo":            staff.photo or None,
        "specialisation":   profile.specialisation if profile else "",
        "qualification":    profile.qualification if profile else "",
        "experience_years": profile.experience_years if profile else None,
        "consultation_fee": str(profile.consultation_fee) if profile and profile.consultation_fee is not None else None,
        "bio":              profile.bio if profile else "",
        "languages":        profile.languages if profile else "",
        "known_for":        profile.known_for if profile else "",
    }


class PortalDoctorListView(APIView):
    permission_classes = [IsPatient]

    def get(self, request, tenant_id):
        try:
            tenant = Tenant.objects.using("default").get(pk=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(tenant):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        _ensure_db(tenant.db_name)
        from apps.org.models import StaffUser, DoctorProfile

        staff_list = list(
            StaffUser.objects.using(tenant.db_name)
            .filter(role="doctor", is_active=True).order_by("first_name")
        )
        profiles = {
            p.staff_id: p
            for p in DoctorProfile.objects.using(tenant.db_name)
                .filter(staff_id__in=[s.id for s in staff_list])
        }
        doctors = [_doctor_card(s, profiles.get(s.id)) for s in staff_list]
        return Response({"results": doctors})


class PortalDoctorDetailView(APIView):
    """GET /api/v1/portal/hospitals/<tenant_id>/doctors/<doctor_id>/ — single doctor profile."""
    permission_classes = [IsPatient]

    def get(self, request, tenant_id, doctor_id):
        try:
            tenant = Tenant.objects.using("default").get(pk=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(tenant):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        _ensure_db(tenant.db_name)
        from apps.org.models import StaffUser, DoctorProfile

        try:
            staff = StaffUser.objects.using(tenant.db_name).get(
                pk=doctor_id, role="doctor", is_active=True
            )
        except StaffUser.DoesNotExist:
            return Response({"error": "Doctor not found at this hospital."}, status=404)

        profile = DoctorProfile.objects.using(tenant.db_name).filter(staff_id=staff.id).first()
        data = _doctor_card(staff, profile)
        data["hospital"] = {
            "tenant_id": tenant.id, "name": tenant.name, "city": tenant.city or "",
            "accreditations": [a.strip() for a in (tenant.accreditations or "").split(",") if a.strip()],
        }

        # Real count, not a marketing number — signed (finalized) consultations
        # this doctor has completed at THIS hospital. No cross-tenant total
        # (each hospital only knows its own encounters), and no fabricated
        # rating/review numbers — we don't have a reviews system.
        from apps.opd.models import OPDEncounter
        data["consultations_count"] = OPDEncounter.objects.using(tenant.db_name).filter(
            doctor_user_id=staff.id, status=OPDEncounter.STATUS_SIGNED
        ).count()

        return Response(data)


class PortalNextTokenView(APIView):
    """
    GET /api/v1/portal/hospitals/<tenant_id>/doctors/<doctor_id>/next-token/?date=YYYY-MM-DD
    Preview only — the real token is assigned atomically at booking time in
    PortalBookView, so this can be off by one if someone else books in between.
    Shown to the patient as "you'll likely be token #N" before they confirm.
    """
    permission_classes = [IsPatient]

    def get(self, request, tenant_id, doctor_id):
        from apps.opd.models import Appointment

        try:
            tenant = Tenant.objects.using("default").get(pk=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(tenant):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        db = tenant.db_name
        _ensure_db(db)
        target_date = request.query_params.get("date") or str(date.today())

        tokens = Appointment.objects.using(db).filter(
            scheduled_date=target_date, doctor_user_id=doctor_id,
        ).exclude(status="cancelled").values_list("token_number", flat=True)
        next_token = (max(tokens) + 1) if tokens else 1

        return Response({"date": target_date, "next_token": next_token})


# ── Slots ────────────────────────────────────────────────────────────────────

def _generic_slot_grid():
    """
    Fallback grid — 09:00-13:00 and 14:00-18:00, 15-minute slots. Only used
    when a doctor has no working-hours schedule configured at all (see
    org.DoctorSchedule), so booking doesn't break entirely for accounts
    that predate that feature or haven't been set up yet.
    """
    slots = []
    for start_h, end_h in ((9, 13), (14, 18)):
        t = dtime(start_h, 0)
        while t < dtime(end_h, 0):
            slots.append(t.strftime("%H:%M"))
            t = (datetime.combine(date.today(), t) + timedelta(minutes=15)).time()
    return slots


def _slot_grid(doctor_id, db, slot_date):
    """
    Per-doctor, per-day time grid — reads the doctor's own configured
    working hours (org.DoctorSchedule / DoctorAvailabilitySlot, set by the
    hospital admin at invite time or edited later) for slot_date's weekday,
    instead of a fixed generic grid. This is what actually determines the
    booking window and slot size (slot_duration_minutes) shown to patients
    and front desk — previously this function ignored the doctor's
    configured hours entirely and always returned the generic grid below,
    which is why a doctor set up for 09:00-20:00 only ever showed slots
    up to 17:45.
    """
    from apps.org.models import DoctorSchedule, DoctorAvailabilitySlot

    schedule = DoctorSchedule.objects.using(db).filter(doctor_id=doctor_id).first()
    if not schedule:
        return _generic_slot_grid()

    try:
        weekday = date.fromisoformat(slot_date).weekday()
    except ValueError:
        weekday = date.today().weekday()

    day = DoctorAvailabilitySlot.objects.using(db).filter(
        schedule=schedule, day_of_week=weekday
    ).first()
    if not day or not day.is_available:
        return []  # doctor doesn't work this day — no slots, not an error

    slots = []
    t = day.start_time
    step = max(schedule.slot_duration_minutes, 1)
    while t < day.end_time:
        slots.append(t.strftime("%H:%M"))
        t = (datetime.combine(date.today(), t) + timedelta(minutes=step)).time()
    return slots


class PortalSlotListView(APIView):
    """
    GET /api/v1/portal/hospitals/<tenant_id>/doctors/<doctor_id>/slots/?date=YYYY-MM-DD
    Available to patients AND hospital staff (front desk uses it too).
    """
    permission_classes = []  # JWT already validated by middleware

    def get(self, request, tenant_id, doctor_id):
        from apps.opd.models import Appointment

        try:
            tenant = Tenant.objects.using("default").get(pk=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)

        db = tenant.db_name
        _ensure_db(db)
        slot_date = request.query_params.get("date") or str(date.today())

        booked = {
            t.strftime("%H:%M")
            for t in Appointment.objects.using(db).filter(
                scheduled_date=slot_date, doctor_user_id=doctor_id,
            ).exclude(status="cancelled").values_list("scheduled_time", flat=True)
            if t
        }

        now = timezone.localtime()
        is_today = slot_date == str(now.date())
        results = []
        for s in _slot_grid(doctor_id, db, slot_date):
            past = is_today and s <= now.strftime("%H:%M")
            results.append({
                "time": s,
                "available": (s not in booked) and not past,
                "past": past,
            })
        return Response({"results": results})


# ── Booking ──────────────────────────────────────────────────────────────────

class PortalBookView(APIView):
    permission_classes = [IsPatient]

    def post(self, request):
        from apps.registry.models import PortalBooking
        from apps.org.models import StaffUser, Branch
        from apps.patients.models import Patient
        from apps.opd.models import Appointment

        d = request.data
        tenant_id       = d.get("tenant_id")
        doctor_id       = d.get("doctor_id")
        scheduled_date  = d.get("scheduled_date") or str(date.today())
        scheduled_time  = (d.get("scheduled_time") or "").strip() or None
        chief_complaint = (d.get("chief_complaint") or "").strip()
        payment_preference = d.get("payment_preference") or Appointment.PAYMENT_PAY_AT_DESK
        if payment_preference not in dict(Appointment.PAYMENT_PREFERENCE_CHOICES):
            payment_preference = Appointment.PAYMENT_PAY_AT_DESK

        if not tenant_id or not doctor_id:
            return Response({"error": "tenant_id and doctor_id are required."}, status=400)

        # Booking window capped at 2 months out (mirrors the date picker's
        # own max= on the frontend) — enforced here too since the frontend
        # limit is trivial to bypass by calling this endpoint directly.
        try:
            requested_date = date.fromisoformat(scheduled_date)
        except ValueError:
            return Response({"error": "Invalid date."}, status=400)
        if requested_date < date.today():
            return Response({"error": "Can't book a date in the past."}, status=400)
        if requested_date > date.today() + timedelta(days=62):
            return Response({"error": "Appointments can only be booked up to 2 months in advance."}, status=400)

        # scheduled_time is optional — the patient portal is token/queue-based
        # (pick a date, get the next token) rather than fixed-time-slot booking.
        # Front desk's own booking flow still uses PortalSlotListView/exact times.

        try:
            tenant = Tenant.objects.using("default").get(pk=tenant_id, is_active=True)
        except Tenant.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(tenant):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        db = tenant.db_name
        _ensure_db(db)

        try:
            doctor = StaffUser.objects.using(db).get(pk=doctor_id, role="doctor", is_active=True)
        except StaffUser.DoesNotExist:
            return Response({"error": "Doctor not found at this hospital."}, status=404)
        # Appointment.doctor_name is a plain snapshot string (not a live FK
        # lookup), so it must not inherit a "Dr." some hospital already typed
        # into the staff account's first name — see _doctor_display_name().
        doctor_name = _doctor_display_name(doctor).replace("Dr. ", "", 1) or doctor.email

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)

        # ── Who is this booking actually for? ──────────────────────────────
        # Defaults to the account owner. If patient_awpid is given and isn't
        # the account's own, it must be a linked family member (see
        # PortalFamilyListCreateView) — never an arbitrary AWPID, so one
        # patient can't book under someone else's identity.
        target_awpid = (d.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid == acct.awpid:
            target_name, target_gender, target_dob = acct.full_name, acct.gender, acct.date_of_birth
        else:
            from apps.registry.models import PatientRelationship, PatientIdentity
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=target_awpid,
            ).exists()
            if not is_family:
                return Response({"error": "That patient isn't linked to your account."}, status=403)
            dep_identity = PatientIdentity.objects.using("default").filter(awpid=target_awpid).first()
            if not dep_identity:
                return Response({"error": "Family member record not found."}, status=404)
            target_name, target_gender, target_dob = dep_identity.full_name, dep_identity.gender, dep_identity.date_of_birth

        # ── Find-or-create the tenant-local Patient record ────────────────
        patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
        if not patient:
            # First time this patient is being registered at THIS hospital —
            # this is exactly the moment their shared cross-hospital history
            # becomes visible to a new set of doctors, so consent is required
            # before anything is created. Once given, it's on record for this
            # hospital going forward (not asked again on later bookings here).
            if not d.get("data_sharing_consent"):
                return Response({
                    "consent_required": True,
                    "hospital_name": tenant.name,
                    "share_categories": HIE_SHARE_CATEGORIES,
                    "message": f"This is {'your' if target_awpid == acct.awpid else target_name + chr(39) + 's'} first booking at {tenant.name}. Please confirm you're okay sharing this medical history with them.",
                }, status=428)

            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            if not branch:
                return Response({"error": "Hospital is not accepting registrations yet."}, status=400)
            # next UHID number
            max_num = 0
            for uhid in Patient.objects.using(db).values_list("uhid", flat=True):
                try:
                    max_num = max(max_num, int(uhid.split("-")[-1]))
                except (ValueError, IndexError):
                    pass
            patient = Patient.objects.using(db).create(
                awpid=target_awpid,
                uhid=f"UHID-{max_num + 1:06d}",
                branch=branch,
                full_name=target_name,
                gender=target_gender,
                date_of_birth=target_dob,
                mobile=acct.mobile if target_awpid == acct.awpid else "",
                email=acct.email if target_awpid == acct.awpid else "",
                is_dependent=target_awpid != acct.awpid,
                guardian_name=acct.full_name if target_awpid != acct.awpid else "",
                guardian_mobile=acct.mobile if target_awpid != acct.awpid else "",
                guardian_awpid=acct.awpid if target_awpid != acct.awpid else "",
                hie_consent_given=True,
                hie_consent_at=timezone.now(),
                payer_type="self",
                dpdp_consent_captured=True,
                dpdp_consent_at=timezone.now(),
            )
            # Durable proof trail behind the two booleans above — patient
            # granted both by submitting data_sharing_consent through the
            # portal itself (no staff intermediary), see
            # apps.compliance.services.record_consent.
            from apps.compliance.services import record_consent
            from apps.compliance.models import ConsentRecord
            record_consent(db, patient, ConsentRecord.CONSENT_DPDP_PROCESSING,
                            ConsentRecord.SOURCE_PORTAL, request=request)
            record_consent(db, patient, ConsentRecord.CONSENT_HIE_SHARING,
                            ConsentRecord.SOURCE_PORTAL, request=request)

        # ── If a specific time was given (front-desk flow), it must still be free ──
        if scheduled_time:
            taken = Appointment.objects.using(db).filter(
                scheduled_date=scheduled_date, doctor_user_id=doctor.id,
                scheduled_time=scheduled_time,
            ).exclude(status="cancelled").exists()
            if taken:
                return Response({"error": "That slot was just taken. Please pick another."}, status=409)

        # ── Create the appointment (scheduled — front desk checks in) ─────
        tokens = Appointment.objects.using(db).filter(
            scheduled_date=scheduled_date, doctor_user_id=doctor.id,
        ).values_list("token_number", flat=True)
        next_token = (max(tokens) + 1) if tokens else 1

        # Resolve room/floor the same way front desk's own booking flow does
        # (apps.opd.views.AppointmentListCreateView.post) — this is a second,
        # separate creation path for the same Appointment model, so it needs
        # the same room-resolution logic rather than inheriting it.
        room_fields = {}
        if scheduled_time:
            from apps.org.room_utils import resolve_room_for_slot
            match = resolve_room_for_slot(db, doctor.id, requested_date.weekday(), scheduled_time)
            if match:
                room_fields = {
                    "room_id": match.room_id,
                    "room_name": match.room.name,
                    "floor": match.room.floor,
                }

        appt = Appointment.objects.using(db).create(
            patient_id=patient.uuid,
            patient_awpid=patient.awpid,
            doctor_user_id=doctor.id,
            doctor_name=doctor_name,
            appointment_type="opd",
            status=Appointment.STATUS_SCHEDULED,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            token_number=next_token,
            chief_complaint=chief_complaint,
            # Front desk/nurse queues are branch-scoped (AppointmentListCreateView,
            # MonitoringListView default to the staff member's own branch_id when
            # no explicit filter is given) — without this, patient-portal bookings
            # were invisible to both, since branch_id was left null.
            branch_id=doctor.branch_id,
            payment_preference=payment_preference,
            **room_fields,
        )

        booking = PortalBooking.objects.using("default").create(
            account=acct,
            tenant_id=tenant.id,
            db_name=db,
            hospital_name=tenant.name,
            appointment_id=appt.id,
            doctor_name=doctor_name,
            scheduled_date=scheduled_date,
            chief_complaint=chief_complaint,
            status="scheduled",
            patient_awpid=target_awpid,
            patient_name=target_name,
        )

        return Response({
            "booking_id": booking.id,
            "hospital": tenant.name,
            "doctor": doctor_name,
            "date": str(scheduled_date),
            "time": scheduled_time,
            "token_number": next_token,
            "status": "scheduled",
            "payment_preference": payment_preference,
            "patient_name": target_name,
            # Only resolved when scheduled_time was given (a specific slot) —
            # pure token-based bookings (no fixed time yet) have no room to
            # show until the doctor actually gets to them, same as any
            # other slot-dependent lookup.
            "room_name": room_fields.get("room_name") or None,
            "floor": room_fields.get("floor") or None,
        }, status=201)


# ── My records (prescriptions, tests, advice from consults) ─────────────────

class PortalMyRecordsView(APIView):
    """
    GET /api/v1/portal/my-records/?patient_awpid=
    Everything the doctor recorded for this patient, across all hospitals:
    diagnoses, prescription drugs, investigations (tests to do), advice, follow-up.
    patient_awpid defaults to the account owner; pass a linked family
    member's AWPID (see PortalFamilyListCreateView) to view their records
    instead — validated the same way as PortalBookView, so one account can't
    read another patient's records by guessing an AWPID.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.patients.models import Patient
        from apps.opd.models import Appointment, OPDEncounter, Prescription, Vitals

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)

        target_awpid = (request.query_params.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid != acct.awpid:
            from apps.registry.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=target_awpid,
            ).exists()
            if not is_family:
                return error("That patient isn't linked to your account.", status=403)

        results = []

        for tenant in Tenant.objects.using("default").filter(is_active=True):
            db = tenant.db_name
            try:
                _ensure_db(db)
                patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                appts = (Appointment.objects.using(db)
                         .filter(patient_id=patient.uuid)
                         .order_by("-scheduled_date", "-created_at")[:50])
                for appt in appts:
                    enc = OPDEncounter.objects.using(db).filter(appointment_id=appt.id).first()
                    record = {
                        "hospital":        tenant.name,
                        "date":            str(appt.scheduled_date),
                        "time":            appt.scheduled_time.strftime("%H:%M") if appt.scheduled_time else None,
                        "doctor":          appt.doctor_name,
                        "status":          appt.status,
                        "chief_complaint": appt.chief_complaint,
                        "diagnoses":       [],
                        "prescription":    [],
                        "investigations":  "",
                        "advice":          "",
                        "follow_up_in_days": None,
                        "signed":          False,
                        "vitals":          None,
                    }
                    v = Vitals.objects.using(db).filter(appointment_id=appt.id).first()
                    if v:
                        record["vitals"] = {
                            "bp": f"{v.systolic_bp}/{v.diastolic_bp}" if v.systolic_bp and v.diastolic_bp else None,
                            "pulse": v.pulse_rate,
                            "spo2": v.spo2,
                            "temperature": str(v.temperature) if v.temperature else None,
                            "weight_kg": str(v.weight_kg) if v.weight_kg else None,
                        }
                    if enc:
                        record.update({
                            "diagnoses":         enc.diagnoses or [],
                            "investigations":    enc.investigations or "",
                            "advice":            enc.advice_to_patient or "",
                            "follow_up_in_days": enc.follow_up_in_days,
                            "signed":            enc.status == "signed",
                        })
                        rx = Prescription.objects.using(db).filter(encounter_id=enc.id).first()
                        if rx:
                            record["prescription"] = [
                                {
                                    "drug_name":     i.drug_name,
                                    "dosage":        i.dosage,
                                    "frequency":     i.frequency,
                                    "route":         i.route,
                                    "duration_days": i.duration_days,
                                    "instructions":  i.instructions,
                                }
                                for i in rx.items.using(db).all()
                            ]
                    results.append(record)
            except Exception as e:
                logger.warning("my-records: skipped %s (%s)", db, e)

        results.sort(key=lambda r: r["date"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return Response({"results": page_items, "pagination": meta})


# ── My bookings ──────────────────────────────────────────────────────────────

# How long past the scheduled time an appointment is given before it's
# treated as a no-show. Clinics run late; someone booked for 3:15 PM
# genuinely might still be seen at 4:30. Two hours mirrors what most OPD
# workflows tolerate before assuming the patient never came in.
_NO_SHOW_GRACE = timedelta(hours=2)
_STALE_IF_PAST = ("scheduled", "waiting", "vitals_done")


def _auto_expire_if_stale(appt, db_name):
    """
    An appointment left in a pre-consultation status well past its slot
    time isn't "upcoming" anymore — nobody checked the patient in and no
    consultation started, so silently keep showing it as confirmed/waiting
    is actively misleading. There's no background job runner in this stack
    yet, so this evaluates lazily: whenever a booking is read (patient's
    "My Appointments", and anywhere else that later reuses this), stale
    ones get corrected to no_show right then, once, and persisted — same
    end result as a periodic sweep, no extra infrastructure required.
    Mutates `appt.status` in place and returns it.
    """
    if appt.status not in _STALE_IF_PAST:
        return appt.status
    appt_time = appt.scheduled_time or dtime(23, 59)
    appt_dt = timezone.make_aware(datetime.combine(appt.scheduled_date, appt_time))
    if timezone.now() > appt_dt + _NO_SHOW_GRACE:
        appt.status = "no_show"
        appt.save(using=db_name, update_fields=["status"])
    return appt.status


class PortalMyBookingsView(APIView):
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.registry.models import PortalBooking
        from apps.opd.models import Appointment

        qs = PortalBooking.objects.using("default").filter(
            account_id=request.user.id
        ).order_by("-scheduled_date", "-id")
        bookings, meta = paginate_queryset(request, qs)

        today = str(date.today())
        # States where the patient is still "in the queue" — before this,
        # nothing to wait for (not checked in); at/after in_progress or done,
        # the wait is over (either being seen or already finished).
        QUEUE_PENDING = (Appointment.STATUS_SCHEDULED, Appointment.STATUS_WAITING, Appointment.STATUS_VITALS_DONE)
        NOT_ACTIVE = (Appointment.STATUS_DONE, Appointment.STATUS_CANCELLED, Appointment.STATUS_NO_SHOW)

        results = []
        for b in bookings:
            status_now = b.status
            token = None
            slot_time = None
            people_ahead = None
            now_serving = None
            doctor_id = None
            room_name = None
            floor = None
            try:
                _ensure_db(b.db_name)
                appt = Appointment.objects.using(b.db_name).get(pk=b.appointment_id)
                status_now = _auto_expire_if_stale(appt, b.db_name)
                token = appt.token_number
                slot_time = appt.scheduled_time.strftime("%H:%M") if appt.scheduled_time else None
                doctor_id = appt.doctor_user_id
                room_name = appt.room_name or None
                floor = appt.floor or None
                if status_now != b.status:
                    b.status = status_now
                    b.save(using="default", update_fields=["status"])

                # Real, live queue position — only meaningful same-day, and
                # only while this appointment hasn't itself been called yet.
                if str(appt.scheduled_date) == today and status_now in QUEUE_PENDING and token is not None:
                    same_day_doctor = Appointment.objects.using(b.db_name).filter(
                        doctor_user_id=appt.doctor_user_id, scheduled_date=appt.scheduled_date,
                    )
                    people_ahead = same_day_doctor.filter(
                        token_number__lt=token
                    ).exclude(status__in=NOT_ACTIVE).count()
                    in_progress = same_day_doctor.filter(
                        status=Appointment.STATUS_IN_PROGRESS
                    ).exclude(token_number=token).order_by("token_number").first()
                    now_serving = in_progress.token_number if in_progress else None
            except Exception:
                # Best-effort by design (booking.tenant_db may be temporarily
                # unreachable) — the patient still sees the booking with
                # whatever was last saved to the registry row, just without
                # live token/queue data. Logged so a systemic issue (e.g. a
                # schema change breaking this join tenant-wide) is visible
                # somewhere instead of just presenting as "missing token".
                logger.debug("PortalMyBookingsView: live status lookup failed for booking_id=%s db=%s", b.id, b.db_name, exc_info=True)
            results.append({
                "id": b.id,
                "tenant_id": b.tenant_id,
                "hospital": b.hospital_name,
                "doctor": b.doctor_name,
                # So "Book follow-up" can deep-link straight to this same
                # doctor's profile instead of dropping the patient back at
                # the generic hospital doctor-list to re-find who they saw.
                # None if the underlying appointment row is gone/unreachable
                # (e.g. tenant DB down) — frontend falls back to the browse
                # page in that case.
                "doctor_id": doctor_id,
                "date": str(b.scheduled_date),
                "time": slot_time,
                "chief_complaint": b.chief_complaint,
                "status": status_now,
                "token_number": token,
                "people_ahead": people_ahead,
                "now_serving_token": now_serving,
                "room_name": room_name,
                "floor": floor,
                # Blank on bookings made before family members existed —
                # those were always for the account owner.
                "patient_name": b.patient_name or None,
                "patient_awpid": b.patient_awpid or None,
            })
        return Response({"results": results, "pagination": meta})


class PortalCancelBookingView(APIView):
    """
    POST /api/v1/portal/my-bookings/<id>/cancel/

    Patient self-service cancellation. <id> is the registry-DB
    PortalBooking pk (what PortalMyBookingsView hands back as "id"), not the
    tenant-DB Appointment id — the portal only ever deals in PortalBooking
    rows since a single account can have bookings across many hospitals.
    Resolves through to the real tenant-DB Appointment, cancels it there,
    then writes the same status back to the registry row so the two stay in
    sync (mirrors what PortalMyBookingsView.get() already does opportunistically).
    """
    permission_classes = [IsPatient]

    def post(self, request, pk):
        from apps.registry.models import PortalBooking
        from apps.opd.models import Appointment

        try:
            booking = PortalBooking.objects.using("default").get(pk=pk, account_id=request.user.id)
        except PortalBooking.DoesNotExist:
            return not_found("Booking not found.")

        _ensure_db(booking.db_name)
        try:
            appt = Appointment.objects.using(booking.db_name).get(pk=booking.appointment_id)
        except Appointment.DoesNotExist:
            return not_found("Appointment record not found.")

        CANCELLABLE = (Appointment.STATUS_SCHEDULED, Appointment.STATUS_WAITING, Appointment.STATUS_VITALS_DONE)
        if appt.status not in CANCELLABLE:
            return error(f"Can't cancel an appointment that's already {appt.get_status_display().lower()}.")

        appt.status = Appointment.STATUS_CANCELLED
        appt.save(using=booking.db_name, update_fields=["status"])
        booking.status = Appointment.STATUS_CANCELLED
        booking.save(using="default", update_fields=["status"])
        return Response({"status": "cancelled"})


class PortalRescheduleBookingView(APIView):
    """
    POST /api/v1/portal/my-bookings/<id>/reschedule/  {scheduled_date, scheduled_time?}

    Moves an existing booking to a new date/time instead of cancel + rebook.
    Same window/slot rules as PortalBookView, keyed by PortalBooking pk like
    PortalCancelBookingView above, and keeps both the tenant-DB Appointment
    and the registry-DB PortalBooking row in sync.
    """
    permission_classes = [IsPatient]

    def post(self, request, pk):
        from apps.registry.models import PortalBooking
        from apps.opd.models import Appointment

        try:
            booking = PortalBooking.objects.using("default").get(pk=pk, account_id=request.user.id)
        except PortalBooking.DoesNotExist:
            return not_found("Booking not found.")

        new_date_raw = request.data.get("scheduled_date")
        new_time = (request.data.get("scheduled_time") or "").strip() or None
        if not new_date_raw:
            return error("scheduled_date is required.")
        try:
            new_date = date.fromisoformat(str(new_date_raw))
        except ValueError:
            return error("Invalid date.")
        if new_date < date.today():
            return error("Can't reschedule to a date in the past.")
        if new_date > date.today() + timedelta(days=62):
            return error("Appointments can only be booked up to 2 months in advance.")

        _ensure_db(booking.db_name)
        db = booking.db_name
        try:
            appt = Appointment.objects.using(db).get(pk=booking.appointment_id)
        except Appointment.DoesNotExist:
            return not_found("Appointment record not found.")

        RESCHEDULABLE = (Appointment.STATUS_SCHEDULED, Appointment.STATUS_WAITING)
        if appt.status not in RESCHEDULABLE:
            return error(f"Can't reschedule an appointment that's already {appt.get_status_display().lower()}.")

        if new_time:
            taken = Appointment.objects.using(db).filter(
                scheduled_date=new_date, doctor_user_id=appt.doctor_user_id, scheduled_time=new_time,
            ).exclude(status="cancelled").exclude(pk=appt.pk).exists()
            if taken:
                return error("That slot was just taken. Please pick another.", status=409)

        last_token = Appointment.objects.using(db).filter(
            scheduled_date=new_date, doctor_user_id=appt.doctor_user_id,
        ).exclude(pk=appt.pk).values_list("token_number", flat=True)
        next_token = (max(last_token) + 1) if last_token else 1

        room_fields = {"room_id": None, "room_name": "", "floor": ""}
        if new_time:
            from apps.org.room_utils import resolve_room_for_slot
            match = resolve_room_for_slot(db, appt.doctor_user_id, new_date.weekday(), new_time)
            if match:
                room_fields = {"room_id": match.room_id, "room_name": match.room.name, "floor": match.room.floor}

        appt.scheduled_date = new_date
        appt.scheduled_time = new_time
        appt.token_number = next_token
        appt.status = Appointment.STATUS_SCHEDULED
        for k, v in room_fields.items():
            setattr(appt, k, v)
        appt.save(using=db)

        booking.scheduled_date = new_date
        booking.status = Appointment.STATUS_SCHEDULED
        booking.save(using="default", update_fields=["scheduled_date", "status"])

        return Response({
            "status": "scheduled", "date": str(new_date), "time": new_time,
            "token_number": next_token,
            "room_name": room_fields.get("room_name") or None,
            "floor": room_fields.get("floor") or None,
        })


# ── My documents ─────────────────────────────────────────────────────────────

_MAX_DOC_BASE64_CHARS = 7_000_000  # ≈5MB raw file, comfortable for a scanned PDF/photo

class PortalDocumentListCreateView(APIView):
    """
    GET  /api/v1/portal/documents/  — patient's own uploaded documents (no file_data)
    POST /api/v1/portal/documents/  — attach a report (base64 data URI)

    Written to the registry (not a tenant DB) keyed by awpid, same as the
    other Shared* HIE tables, so any hospital's doctor sees it via
    get_shared_history() regardless of which hospital the patient uploaded
    it from.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.registry.models import SharedDocument

        target_awpid, _dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err

        qs = (SharedDocument.objects.using("default")
              .filter(awpid=target_awpid)
              .order_by("-created_at"))
        page_items, meta = paginate_queryset(request, qs)
        results = [{
            "id":         d.id,
            "title":      d.title,
            "doc_type":   d.doc_type,
            "file_name":  d.file_name,
            "mime_type":  d.mime_type,
            "uploaded_by": d.uploaded_by,
            "created_at": d.created_at,
        } for d in page_items]
        return Response({"results": results, "pagination": meta})

    def post(self, request):
        from apps.registry.models import SharedDocument

        d = request.data
        title     = (d.get("title") or "").strip()
        doc_type  = d.get("doc_type") or "other"
        file_data = d.get("file_data") or ""
        file_name = (d.get("file_name") or "").strip()
        mime_type = (d.get("mime_type") or "").strip()

        if not title:
            return error("Title is required.", errors={"title": "Required."})
        if not file_data:
            return error("No file provided.", errors={"file_data": "Required."})
        if len(file_data) > _MAX_DOC_BASE64_CHARS:
            return error("File is too large. Please upload a smaller file (under ~5MB).")
        # Verify the payload's real magic bytes match an allowed type instead
        # of trusting the client-supplied mime_type — this file gets shared
        # across every hospital the patient consents to via the HIE flow, so
        # a mislabeled upload would follow it everywhere.
        try:
            mime_type = validate_data_uri(file_data)
        except FileValidationError as exc:
            return error(str(exc), errors={"file_data": str(exc)})
        if doc_type not in dict(SharedDocument.DOC_TYPE_CHOICES):
            doc_type = "other"

        # Optional — set when this upload is attaching the outside report for
        # a specific doctor-ordered test, so that order's card can show the
        # attachment inline instead of only in the generic documents list.
        source_ref = (d.get("source_ref") or "").strip()

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        doc = SharedDocument.objects.using("default").create(
            awpid=acct.awpid, title=title, doc_type=doc_type,
            file_name=file_name, mime_type=mime_type, file_data=file_data,
            uploaded_by="patient", source_tenant_id=None, source_ref=source_ref,
        )
        return Response({
            "id": doc.id, "title": doc.title, "doc_type": doc.doc_type,
            "file_name": doc.file_name, "mime_type": doc.mime_type,
            "source_ref": doc.source_ref, "created_at": doc.created_at,
        }, status=201)


# ── My lab orders ────────────────────────────────────────────────────────────

class PortalLabOrderListView(APIView):
    """
    GET /api/v1/portal/lab-orders/
    Every test any doctor (at any hospital) has ordered for this patient,
    with enough to render the choice/payment/result flow entirely from the
    portal: price, turnaround estimate, current choice, payment state, and
    the result once an in-house lab delivers it.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.patients.models import Patient
        from apps.lab.models import LabRequest

        target_awpid, _dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err
        results = []

        for tenant in Tenant.objects.using("default").filter(is_active=True):
            db = tenant.db_name
            try:
                _ensure_db(db)
                patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                # select_related("report") pulls the LabReport in the SAME
                # .using(db) query. Accessing r.report lazily instead (a bare
                # reverse-OneToOne lookup) would go through the tenant DB
                # router, which resolves the db from thread-local state set
                # by JWTTenantMiddleware — never populated on this patient-
                # portal request, so it silently queried the wrong database
                # (or none) and swallowed the result as "no report yet",
                # which is what made delivered results look stuck on "choose
                # an option" here even after a lab tech had delivered them.
                reqs = (LabRequest.objects.using(db)
                        .select_related("test", "report")
                        .filter(patient=patient)
                        .order_by("-ordered_at")[:50])
                for r in reqs:
                    report = None
                    try:
                        rep = r.report
                        report = {
                            "id": rep.id,
                            "status": rep.status,
                            "result_summary": rep.result_summary,
                            "has_file": bool(rep.file_url),
                            "delivered_at": rep.delivered_at,
                        }
                    except Exception:
                        # r.report is a OneToOne reverse accessor — this most
                        # commonly just means "no report uploaded yet" for
                        # this request, which is normal and expected. Any
                        # other underlying cause would look identical from
                        # the outside, so log at debug level rather than a
                        # bare pass, without treating it as a warning.
                        logger.debug("PortalLabOrderListView: lab report lookup failed for request_id=%s", r.id, exc_info=True)

                    attached_doc = None
                    if r.patient_choice == "outside":
                        from apps.registry.models import SharedDocument
                        doc = (SharedDocument.objects.using("default")
                               .filter(awpid=target_awpid, source_ref=f"labreq:{db}:{r.id}")
                               .order_by("-created_at").first())
                        if doc:
                            attached_doc = {"id": doc.id, "title": doc.title, "created_at": doc.created_at}

                    results.append({
                        "id": r.id,
                        "tenant_db": db,
                        "hospital": tenant.name,
                        "test_name": r.test.name,
                        "price": str(r.test.price) if r.test.price is not None else None,
                        "turnaround_hours": r.test.turnaround_hours,
                        "status": r.status,
                        # request_number: the real token to quote at the
                        # lab counter — see LabRequest.request_number.
                        # Previously nothing was ever shown here, despite
                        # the frontend copy already promising one ("visit
                        # the lab with your token").
                        "request_number": r.request_number,
                        "patient_choice": r.patient_choice,
                        "payment_preference": r.payment_preference,
                        "payment_status": r.payment_status,
                        "ordered_at": r.ordered_at,
                        "report": report,
                        "attached_document": attached_doc,
                        "source_ref": f"labreq:{db}:{r.id}",
                    })
            except Exception as e:
                logger.warning("lab-orders: skipped %s (%s)", db, e)

        results.sort(key=lambda r: r["ordered_at"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return Response({"results": page_items, "pagination": meta})


class PortalLabOrderChoiceView(APIView):
    """
    POST /api/v1/portal/lab-orders/choice/
    Body: { tenant_db, request_id, patient_choice, payment_preference? }
    Patient picks in-house vs outside (and, if in-house, how they'll pay).
    Ownership is verified via awpid before anything is written — tenant_db
    and request_id alone aren't enough to prove this is the caller's order.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from apps.lab.models import LabRequest

        d = request.data
        tenant_db  = d.get("tenant_db")
        request_id = d.get("request_id")
        choice     = d.get("patient_choice")
        payment_preference = d.get("payment_preference", "")

        if not tenant_db or not request_id:
            return error("tenant_db and request_id are required.")
        if choice not in ("in_house", "outside"):
            return error("patient_choice must be in_house or outside.", errors={"patient_choice": "Invalid."})
        if payment_preference and payment_preference not in ("pay_online", "pay_at_lab"):
            return error("Invalid payment_preference.", errors={"payment_preference": "Invalid."})

        if not Tenant.objects.using("default").filter(db_name=tenant_db, is_active=True).exists():
            return error("Unknown hospital.")
        _ensure_db(tenant_db)

        try:
            lab_req = LabRequest.objects.using(tenant_db).select_related("patient").get(pk=request_id)
        except LabRequest.DoesNotExist:
            return error("Lab order not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        order_awpid = lab_req.patient.awpid
        if order_awpid != acct.awpid:
            # Not the account owner's own order — still valid if it belongs
            # to a linked family member (same check _resolve_target_awpid_
            # and_dob / PortalMyRecordsView use elsewhere). This was missing
            # here, so choosing in-house/outside on a family member's lab
            # order always failed with "This order does not belong to you."
            from apps.registry.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=order_awpid,
            ).exists()
            if not is_family:
                return error("This order does not belong to you.")

        from django.utils import timezone
        lab_req.patient_choice = choice
        lab_req.payment_preference = payment_preference
        lab_req.choice_made_by = "patient"
        lab_req.choice_made_at = timezone.now()
        if choice == "in_house" and payment_preference == "pay_online":
            lab_req.payment_status = "pending_online"
        lab_req.save(using=tenant_db, update_fields=[
            "patient_choice", "payment_preference", "choice_made_by",
            "choice_made_at", "payment_status",
        ])
        return success(message="Choice saved.")


class PortalPrescriptionListView(APIView):
    """
    GET /api/v1/portal/prescriptions/
    Every prescription any doctor (at any hospital) has written for this
    patient, with rx_number, items, and current choice/payment state — the
    same shape as PortalLabOrderListView, so the patient gets one
    consistent "buy in-house or take it elsewhere" pattern for both labs
    and prescriptions.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.opd.models import Prescription
        from apps.org.models import StaffUser
        from apps.patients.models import Patient
        import uuid as _uuid

        target_awpid, _dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err
        results = []

        for tenant in Tenant.objects.using("default").filter(is_active=True):
            db = tenant.db_name
            try:
                _ensure_db(db)
                patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                rxs = (Prescription.objects.using(db)
                       .prefetch_related("items")
                       .filter(patient_id=patient.uuid)
                       .order_by("-created_at")[:50])
                for rx in rxs:
                    doctor_name = None
                    try:
                        raw = rx.doctor_user_id.int if isinstance(rx.doctor_user_id, _uuid.UUID) else rx.doctor_user_id
                        doc = StaffUser.objects.using(db).get(pk=raw)
                        doctor_name = doc.get_full_name()
                    except Exception:
                        logger.debug("PortalPrescriptionListView: doctor lookup failed for rx=%s", rx.id, exc_info=True)

                    results.append({
                        "id": str(rx.id),
                        "tenant_db": db,
                        "hospital": tenant.name,
                        "rx_number": rx.rx_number,
                        "doctor_name": doctor_name,
                        "status": rx.status,
                        "patient_choice": rx.patient_choice,
                        "payment_preference": rx.payment_preference,
                        "payment_status": rx.payment_status,
                        "created_at": rx.created_at,
                        "items": [{
                            "drug_name": it.drug_name,
                            "dosage": it.dosage,
                            "frequency": it.frequency,
                            "quantity": it.quantity,
                        } for it in rx.items.all()],
                    })
            except Exception as e:
                logger.warning("prescriptions: skipped %s (%s)", db, e)

        results.sort(key=lambda r: r["created_at"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return Response({"results": page_items, "pagination": meta})


class PortalPrescriptionChoiceView(APIView):
    """
    POST /api/v1/portal/prescriptions/choice/
    Body: { tenant_db, prescription_id, patient_choice, payment_preference? }
    Patient picks in-house vs outside (and, if in-house, how they'll pay) —
    identical shape and ownership logic to PortalLabOrderChoiceView,
    including family-member support from the start (the lab endpoint this
    was modelled on originally shipped without it and had to be patched in
    later — not repeating that here).
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from apps.opd.models import Prescription
        from apps.patients.models import Patient

        d = request.data
        tenant_db        = d.get("tenant_db")
        prescription_id  = d.get("prescription_id")
        choice           = d.get("patient_choice")
        payment_preference = d.get("payment_preference", "")

        if not tenant_db or not prescription_id:
            return error("tenant_db and prescription_id are required.")
        if choice not in (Prescription.CHOICE_IN_HOUSE, Prescription.CHOICE_OUTSIDE):
            return error("patient_choice must be in_house or outside.", errors={"patient_choice": "Invalid."})
        if payment_preference and payment_preference not in (Prescription.PAY_ONLINE, Prescription.PAY_AT_PHARMACY):
            return error("Invalid payment_preference.", errors={"payment_preference": "Invalid."})

        if not Tenant.objects.using("default").filter(db_name=tenant_db, is_active=True).exists():
            return error("Unknown hospital.")
        _ensure_db(tenant_db)

        try:
            rx = Prescription.objects.using(tenant_db).get(pk=prescription_id)
        except Prescription.DoesNotExist:
            return error("Prescription not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        try:
            rx_patient = Patient.objects.using(tenant_db).get(uuid=rx.patient_id)
        except Patient.DoesNotExist:
            return error("Prescription not found.")
        rx_awpid = rx_patient.awpid
        if rx_awpid != acct.awpid:
            from apps.registry.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=rx_awpid,
            ).exists()
            if not is_family:
                return error("This prescription does not belong to you.")

        from django.utils import timezone
        rx.patient_choice = choice
        rx.payment_preference = payment_preference
        rx.choice_made_by = "patient"
        rx.choice_made_at = timezone.now()
        if choice == Prescription.CHOICE_IN_HOUSE and payment_preference == Prescription.PAY_ONLINE:
            rx.payment_status = Prescription.PAY_PENDING_ONLINE
        rx.save(using=tenant_db, update_fields=[
            "patient_choice", "payment_preference", "choice_made_by",
            "choice_made_at", "payment_status",
        ])
        return success(message="Choice saved.")


class PortalLabReportFileView(APIView):
    """
    GET /api/v1/portal/lab-orders/<tenant_db>/<request_id>/report/
    Full content (file_data/mime_type) for an in-house lab report the patient
    has been notified is ready — the list endpoint only sends has_file so the
    payload stays light, same reasoning as PatientDocumentDetailView. Ownership
    is verified via awpid, same as the choice endpoint above.
    """
    permission_classes = [IsPatient]

    def get(self, request, tenant_db, request_id):
        from apps.lab.models import LabRequest, LabReport

        if not Tenant.objects.using("default").filter(db_name=tenant_db, is_active=True).exists():
            return error("Unknown hospital.")
        _ensure_db(tenant_db)

        try:
            # select_related("report") — see the identical fix + comment on
            # PortalLabOrderListView above. A bare lazy `lab_req.report`
            # reverse lookup routes through the tenant DB router's
            # thread-local, which is never set on patient-portal requests,
            # so it silently misses even a delivered report.
            lab_req = LabRequest.objects.using(tenant_db).select_related("patient", "report").get(pk=request_id)
        except LabRequest.DoesNotExist:
            return not_found("Lab order not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        order_awpid = lab_req.patient.awpid
        if order_awpid != acct.awpid:
            from apps.registry.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=order_awpid,
            ).exists()
            if not is_family:
                return error("This order does not belong to you.")

        try:
            report = lab_req.report
        except LabReport.DoesNotExist:
            return not_found("No report has been uploaded for this order yet.")
        if report.status != "delivered":
            return error("This report hasn't been released yet.")

        return success(data={
            "file_data": report.file_url,
            "file_name": report.file_name,
            "mime_type": report.mime_type,
            "result_summary": report.result_summary,
        })


# ── My Profile ──────────────────────────────────────────────────────────────

class PortalProfileView(APIView):
    """
    GET  /api/v1/portal/profile/  — the logged-in patient's own account details.
    PATCH /api/v1/portal/profile/ — update name / mobile / gender / DOB.
    Email and AWPID are identity keys tied to PatientIdentity records across
    every hospital this patient has consented at, so they're read-only here —
    changing them would break the cross-hospital identity match that HIE
    sharing relies on.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.registry.models import PatientIdentity
        try:
            acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        except PatientAccount.DoesNotExist:
            return not_found("Account not found.")
        identity = PatientIdentity.objects.using("default").filter(awpid=acct.awpid).first()
        return success(data={
            "awpid":         acct.awpid,
            "full_name":     acct.full_name,
            "email":         acct.email,
            "mobile":        acct.mobile,
            "gender":        acct.gender,
            "date_of_birth": acct.date_of_birth,
            "created_at":    acct.created_at,
            "last_login":    acct.last_login,
            "blood_group":   identity.blood_group if identity else "",
            "photo":         acct.photo,
            "emergency_contact_name":     acct.emergency_contact_name,
            "emergency_contact_phone":    acct.emergency_contact_phone,
            "emergency_contact_relation": acct.emergency_contact_relation,
        })

    def patch(self, request):
        try:
            acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        except PatientAccount.DoesNotExist:
            return not_found("Account not found.")

        d = request.data
        fields = []
        if "full_name" in d:
            full_name = (d.get("full_name") or "").strip()
            if not full_name:
                return error("Name cannot be blank.", errors={"full_name": "Required."})
            acct.full_name = full_name
            fields.append("full_name")
        if "mobile" in d:
            from apps.registry.models import PatientIdentity
            from core.utils.hashing import hash_mobile, normalize_mobile

            mobile = (d.get("mobile") or "").strip()
            if mobile and not re.match(r"^\d{10}$", mobile):
                return error("Enter a valid 10-digit mobile number.", errors={"mobile": "Invalid format."})
            if mobile and PatientAccount.objects.using("default").filter(mobile=mobile).exclude(pk=acct.id).exists():
                return error("Another account already uses this mobile number.", errors={"mobile": "Already in use."})

            # Keep the network-wide PatientIdentity.mobile_hash in sync — it's
            # what front desk's cross-hospital dedup search actually queries
            # (see PatientService.lookup_by_mobile). Without this, a patient
            # who changes their number here still shows up to every
            # hospital's "Find Patient" search under their OLD number, and a
            # search for their new number comes back "No patient found" even
            # though their portal profile displays it correctly.
            if mobile:
                mobile_hash = hash_mobile(normalize_mobile(mobile))
                # mobile_hash is unique at the DB level — check for a
                # collision against another identity (e.g. a walk-in-only
                # patient with no portal account of their own) before
                # writing, so this returns a clean 400 instead of a 500.
                if PatientIdentity.objects.using("default").filter(mobile_hash=mobile_hash).exclude(awpid=acct.awpid).exists():
                    return error("Another patient record already uses this mobile number.", errors={"mobile": "Already in use."})
                PatientIdentity.objects.using("default").filter(awpid=acct.awpid).update(mobile_hash=mobile_hash)

            acct.mobile = mobile
            fields.append("mobile")
        if "gender" in d:
            gender = (d.get("gender") or "").strip().upper()
            if gender and gender not in ("M", "F", "O"):
                return error("Gender must be M, F, or O.", errors={"gender": "Invalid."})
            acct.gender = gender
            fields.append("gender")
        if "date_of_birth" in d:
            dob = d.get("date_of_birth") or None
            if dob:
                try:
                    dob = datetime.strptime(dob, "%Y-%m-%d").date()
                except ValueError:
                    return error("Date of birth must be YYYY-MM-DD.", errors={"date_of_birth": "Invalid format."})
                if dob > date.today():
                    return error("Date of birth can't be in the future.", errors={"date_of_birth": "Invalid."})
            acct.date_of_birth = dob
            fields.append("date_of_birth")
        if "emergency_contact_name" in d:
            acct.emergency_contact_name = (d.get("emergency_contact_name") or "").strip()
            fields.append("emergency_contact_name")
        if "emergency_contact_phone" in d:
            phone = (d.get("emergency_contact_phone") or "").strip()
            if phone and not re.match(r"^\d{10}$", phone):
                return error("Enter a valid 10-digit emergency contact number.", errors={"emergency_contact_phone": "Invalid format."})
            acct.emergency_contact_phone = phone
            fields.append("emergency_contact_phone")
        if "emergency_contact_relation" in d:
            acct.emergency_contact_relation = (d.get("emergency_contact_relation") or "").strip()
            fields.append("emergency_contact_relation")
        if "photo" in d:
            acct.photo = d.get("photo") or ""
            fields.append("photo")

        if not fields:
            return error("No editable fields provided.")

        acct.save(using="default", update_fields=fields)
        return success(message="Profile updated.", data={
            "awpid":         acct.awpid,
            "full_name":     acct.full_name,
            "email":         acct.email,
            "mobile":        acct.mobile,
            "gender":        acct.gender,
            "date_of_birth": acct.date_of_birth,
            "emergency_contact_name":     acct.emergency_contact_name,
            "emergency_contact_phone":    acct.emergency_contact_phone,
            "emergency_contact_relation": acct.emergency_contact_relation,
            "photo":         acct.photo,
        })


class PortalHealthSummaryView(APIView):
    """
    GET /api/v1/portal/health-summary/?patient_awpid=
    Feeds the "Health Summary" and "Linked Hospitals" cards on My Profile —
    everything here is real, already-recorded data (no invented "primary
    doctor" or "chronic conditions" fields, since nothing in this system
    tracks either of those concepts yet):
      - blood_group        from PatientIdentity (set at registration)
      - active_allergies    from SharedAllergy (same HIE table doctors see)
      - active_diagnoses    from SharedDiagnosis where clinical_status="active"
      - last_visit          most recent PortalBooking for this patient
      - linked_hospitals    every hospital this patient has a booking record
                             at, with their most recent visit there — this
                             is also, today, the full extent of "who your
                             records are shared with" (consent is captured
                             once per hospital at first booking; there's no
                             separate revoke/manage-access flow yet).
    patient_awpid defaults to the account owner; pass a linked family
    member's AWPID to view their summary instead — validated the same way
    as PortalMyRecordsView.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.registry.models import PortalBooking, SharedAllergy, SharedDiagnosis, PatientRelationship

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)

        target_awpid = (request.query_params.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid != acct.awpid:
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=target_awpid,
            ).exists()
            if not is_family:
                return error("That patient isn't linked to your account.", status=403)

        identity = PatientIdentity.objects.using("default").filter(awpid=target_awpid).first()

        allergies = list(
            SharedAllergy.objects.using("default")
            .filter(awpid=target_awpid, is_active=True)
            .values("substance", "reaction", "severity")
        )
        diagnoses = list(
            SharedDiagnosis.objects.using("default")
            .filter(awpid=target_awpid, clinical_status="active")
            .values("description", "onset_date")
            .order_by("-onset_date")[:5]
        )

        bookings = list(
            PortalBooking.objects.using("default")
            .filter(patient_awpid=target_awpid)
            .order_by("-scheduled_date")
        )
        # Older rows (before family-member booking existed) left patient_awpid
        # blank to mean "the account owner" — include those too when we're
        # looking at the account's own summary.
        if target_awpid == acct.awpid:
            bookings += list(
                PortalBooking.objects.using("default")
                .filter(account_id=acct.id, patient_awpid="")
                .order_by("-scheduled_date")
            )

        last_visit = None
        hospitals = {}
        for b in bookings:
            if last_visit is None or b.scheduled_date > last_visit:
                last_visit = b.scheduled_date
            existing = hospitals.get(b.hospital_name)
            if not existing or b.scheduled_date > existing["last_visit"]:
                hospitals[b.hospital_name] = {
                    "hospital_name": b.hospital_name,
                    "tenant_id": b.tenant_id,
                    "last_visit": b.scheduled_date,
                }
        linked_hospitals = sorted(hospitals.values(), key=lambda h: h["last_visit"], reverse=True)

        return success(data={
            "patient_name":     identity.full_name if identity else (acct.full_name if target_awpid == acct.awpid else ""),
            "blood_group":      identity.blood_group if identity else "",
            "active_allergies": allergies,
            "active_diagnoses": diagnoses,
            "last_visit":       last_visit,
            "last_hospital":    linked_hospitals[0]["hospital_name"] if linked_hospitals else None,
            "linked_hospitals": linked_hospitals,
        })


# ── Growth ───────────────────────────────────────────────────────────────────

class PortalGrowthView(APIView):
    """
    GET /api/v1/portal/growth/?patient_awpid=
    Height/weight/BMI over time from the registry's SharedVital table (every
    hospital's finalized visits) — cross-hospital by nature since the portal
    has no single tenant DB to read from, unlike PatientGrowthView (staff
    side), which also blends in that one hospital's own local Vitals.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.registry.models import SharedVital

        target_awpid, dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err

        series = []
        for v in (SharedVital.objects.using("default")
                  .filter(awpid=target_awpid).order_by("recorded_at")):
            if v.height_cm or v.weight_kg:
                series.append({
                    "date": str(v.recorded_at.date()),
                    "height_cm": float(v.height_cm) if v.height_cm else None,
                    "weight_kg": float(v.weight_kg) if v.weight_kg else None,
                    # "clinic" (recorded during a hospital visit) or "home"
                    # (self-reported) — real field on SharedVital, shown on
                    # the growth chart so a clicked point can honestly say
                    # where the measurement came from instead of inventing
                    # a source.
                    "source": v.source,
                })

        age_years = None
        if dob:
            today = date.today()
            age_years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        return success(data={
            "date_of_birth": dob,
            "age_years": age_years,
            "is_minor": age_years is not None and age_years < 18,
            "series": series,
            "latest": series[-1] if series else None,
            "percentile_available": False,
        })


# ── Vaccinations ─────────────────────────────────────────────────────────────

_MAX_VAX_BASE64_CHARS = 7_000_000  # ≈5MB, same cap as document uploads


def _parse_portal_date(value, field_label):
    """
    Strictly parses a "YYYY-MM-DD" string and rejects implausible dates,
    returning (parsed_date, error_response).

    Why this exists: PortalVaccinationUploadView used to hand the raw
    client string straight to SharedVaccination.objects.create(). A native
    <input type="date"> lets a fast/fat-fingered year entry produce a
    technically-well-formed-looking but wrong string like "82026-10-02"
    (year 82026). Django's DateField only converts that value to SQL at
    INSERT time, deep inside the ORM — a 5-digit year doesn't match its
    YYYY-MM-DD parser, so it raises a bare django.core.exceptions.
    ValidationError that DRF's exception handler doesn't catch, which
    surfaces to the patient as an opaque 500 / generic "Something went
    wrong" toast instead of a clear "check the date" message. Validating
    up front turns a typo into an honest 400.
    """
    if not value:
        return None, None
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, error(
            f"{field_label} must be a valid date.",
            errors={"administered_date": "Enter a valid date."},
        )
    if parsed.year < 1900 or parsed > date.today():
        return None, error(
            f"{field_label} ({parsed.isoformat()}) doesn't look right — please check the year.",
            errors={"administered_date": "Check the year — that date is out of range."},
        )
    return parsed, None


def _resolve_target_awpid_and_dob(request):
    """
    Shared helper — resolves which patient (self or a linked family member)
    a portal request is about, and returns (awpid, date_of_birth, error_response).
    Mirrors the ownership check already used by PortalMyRecordsView /
    PortalHealthSummaryView: a family member's AWPID is only valid here if
    PatientRelationship actually links it to this account.
    """
    acct = PatientAccount.objects.using("default").get(pk=request.user.id)
    target_awpid = (request.query_params.get("patient_awpid") or request.data.get("patient_awpid") or "").strip() or acct.awpid

    if target_awpid == acct.awpid:
        return target_awpid, acct.date_of_birth, None

    from apps.registry.models import PatientRelationship
    is_family = PatientRelationship.objects.using("default").filter(
        guardian_awpid=acct.awpid, dependent_awpid=target_awpid,
    ).exists()
    if not is_family:
        return None, None, error("That patient isn't linked to your account.", status=403)

    identity = PatientIdentity.objects.using("default").filter(awpid=target_awpid).first()
    return target_awpid, (identity.date_of_birth if identity else None), None


def _portal_schedule_rules():
    """
    Which VaccinationSchedule's rules to use for the patient-portal's
    cross-hospital aggregated vaccination views (PortalVaccinationListView,
    PortalHealthTimelineView).

    The portal doesn't scope a request to one hospital — a patient's
    records can come from any tenant in the network — so there's no single
    "current hospital" whose active_vaccination_schedule_id is obviously
    correct the way there is on the staff side (see
    apps/patients/growth_vaccination_views.py). Determining "the tenant of
    the patient's most recent visit/booking" would require a fan-out scan
    across every active tenant DB (same pattern as PortalHealthTimelineView's
    visits section) just to pick a schedule for display purposes, which is
    a lot of cross-DB cost for what is ultimately a reference roadmap, not
    a billing-critical computation — so this pass takes the simpler,
    explicitly-allowed fallback: always resolve to the global system
    "Default Schedule" template (owner_tenant_id=None, is_template=True)
    for every patient-portal view. Revisit if a hospital's custom schedule
    needs to show up here too.
    """
    from apps.registry.models import VaccinationSchedule, VaccinationScheduleRule

    schedule = (
        VaccinationSchedule.objects.using("default")
        .filter(owner_tenant_id__isnull=True, is_template=True, active=True)
        .order_by("id")
        .first()
    )
    if not schedule:
        return []
    return list(
        VaccinationScheduleRule.objects.using("default")
        .filter(schedule=schedule)
        .order_by("sort_order")
    )


class PortalVaccinationListView(APIView):
    """
    GET /api/v1/portal/vaccinations/?patient_awpid=
    Same roadmap staff see, for the account owner or a linked family member.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.registry.vaccine_schedule import build_roadmap, summarize_roadmap

        target_awpid, dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err

        rules = _portal_schedule_rules()
        roadmap = build_roadmap(target_awpid, dob, rules)
        summary = summarize_roadmap(roadmap)
        return success(data={
            "date_of_birth": dob,
            "roadmap": roadmap,
            "completed_count": summary["completed_count"],
            "total_count": summary["total_count"],
            "next_recommended": summary["next_recommended"],
            "next_due": summary["next_due"],  # deprecated alias, see summarize_roadmap()
            "stats": summary["stats"],
        })


class PortalVaccinationUploadView(APIView):
    """
    POST /api/v1/portal/vaccinations/upload/
    Body: { vaccine_name, administered_date, scheduled_label?, patient_awpid?,
            file_data?, file_name?, mime_type? }
    A parent self-reports a vaccination given outside the network (a
    government camp, another clinic) — with an optional certificate photo.
    Always lands as verification_status="pending_review", never "verified" —
    only a doctor/nurse reviewing it (PatientVaccinationVerifyView) can
    upgrade it. This is the whole point of tracking verification separately:
    a self-reported entry must never render identically to a clinic record
    until someone clinical has actually looked at it.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from apps.registry.models import SharedVaccination

        target_awpid, _dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err

        d = request.data
        vaccine_name = (d.get("vaccine_name") or "").strip()
        administered_date = d.get("administered_date")
        scheduled_label = (d.get("scheduled_label") or "").strip()
        file_data = d.get("file_data") or ""
        file_name = (d.get("file_name") or "").strip()
        mime_type = (d.get("mime_type") or "").strip()

        if not vaccine_name:
            return error("Vaccine name is required.", errors={"vaccine_name": "Required."})
        if not administered_date:
            return error("Administered date is required.", errors={"administered_date": "Required."})

        administered_date, date_err = _parse_portal_date(administered_date, "Administered date")
        if date_err:
            return date_err

        if file_data:
            if len(file_data) > _MAX_VAX_BASE64_CHARS:
                return error("File is too large. Please upload a smaller file (under ~5MB).")
            try:
                mime_type = validate_data_uri(file_data)
            except FileValidationError as exc:
                return error(str(exc), errors={"file_data": str(exc)})

        record = SharedVaccination.objects.using("default").create(
            awpid=target_awpid,
            vaccine_name=vaccine_name,
            scheduled_label=scheduled_label,
            administered_date=administered_date,
            source=SharedVaccination.SOURCE_SELF_REPORTED,
            verification_status=SharedVaccination.STATUS_PENDING,
            file_name=file_name,
            mime_type=mime_type,
            file_data=file_data,
            recorded_by="patient",
        )
        return success(data={
            "id": record.id,
            "vaccine_name": record.vaccine_name,
            "administered_date": str(record.administered_date),
            "verification_status": record.verification_status,
        }, message="Submitted. This will show as pending review until a doctor confirms it.")


class PortalVaccinationFileView(APIView):
    """
    GET /api/v1/portal/vaccinations/<record_id>/file/
    Full content (file_data/mime_type) for one vaccination certificate — the
    roadmap list only ever sends has_certificate (a boolean) to keep that
    payload light, same reasoning/pattern as PortalLabReportFileView and
    PatientDocumentDetailView. Ownership is checked against the account
    owner or a linked family member, same as everywhere else on the portal.
    """
    permission_classes = [IsPatient]

    def get(self, request, record_id):
        from apps.registry.models import SharedVaccination, PatientRelationship

        try:
            record = SharedVaccination.objects.using("default").get(pk=record_id)
        except SharedVaccination.DoesNotExist:
            return not_found("Vaccination record not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        if record.awpid != acct.awpid:
            is_family = PatientRelationship.objects.using("default").filter(
                guardian_awpid=acct.awpid, dependent_awpid=record.awpid,
            ).exists()
            if not is_family:
                return error("This record does not belong to you.", status=403)

        if not record.file_data:
            return not_found("No certificate has been uploaded for this record.")

        return success(data={
            "file_data": record.file_data,
            "file_name": record.file_name,
            "mime_type": record.mime_type,
        })


_TIMELINE_DEFAULT_LIMIT = 30


class PortalHealthTimelineView(APIView):
    """
    GET /api/v1/portal/timeline/?patient_awpid=&limit=
    Unified chronological feed for the Records page — merges visits,
    vaccinations, growth checks, lab results, and documents into one
    reverse-chronological list so the patient/parent gets a single "what's
    happened" view instead of five separate sections to cross-reference.

    Reuses the same five sources as PortalMyRecordsView, PortalVaccinationListView
    (via build_roadmap), PortalGrowthView, PortalLabOrderListView, and
    PortalDocumentListCreateView — trimmed down to just what a timeline card
    needs (date/title/subtitle/an optional detail for a "view" action),
    not the full payload each of those dedicated endpoints returns.

    `limit` caps how many entries come back (default 30) — this is a feed,
    not an export, and visits/lab-results both fan out across every active
    tenant DB, so an unbounded merge would be needlessly expensive for what
    is ultimately a "recent activity" widget. The tenant queryset is fetched
    once and reused for both fan-outs rather than querying it twice.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.patients.models import Patient
        from apps.opd.models import Appointment, OPDEncounter
        from apps.lab.models import LabRequest
        from apps.registry.models import SharedVital, SharedDocument
        from apps.registry.vaccine_schedule import build_roadmap

        target_awpid, dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err

        try:
            limit = int(request.query_params.get("limit") or _TIMELINE_DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _TIMELINE_DEFAULT_LIMIT
        limit = max(1, min(limit, 100))

        entries = []

        tenants = list(Tenant.objects.using("default").filter(is_active=True))

        # ── Visits ──────────────────────────────────────────────────────
        for tenant in tenants:
            db = tenant.db_name
            try:
                _ensure_db(db)
                patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                appts = (Appointment.objects.using(db)
                         .filter(patient_id=patient.uuid)
                         .order_by("-scheduled_date", "-created_at")[:limit])
                for appt in appts:
                    enc = OPDEncounter.objects.using(db).filter(appointment_id=appt.id).first()
                    diagnoses = (enc.diagnoses or []) if enc else []
                    subtitle_bits = []
                    if appt.chief_complaint:
                        subtitle_bits.append(appt.chief_complaint)
                    elif diagnoses:
                        subtitle_bits.append(", ".join(d.get("description", "") for d in diagnoses if d.get("description")))
                    entries.append({
                        "date":      str(appt.scheduled_date),
                        "type":      "visit",
                        "icon_hint": "stethoscope",
                        "title":     f"Visit — {tenant.name}",
                        "subtitle":  (f"Dr. {appt.doctor_name}" + (f" · {subtitle_bits[0]}" if subtitle_bits else "")) if appt.doctor_name else (subtitle_bits[0] if subtitle_bits else None),
                        "detail":    None,  # no dedicated single-visit viewer on the portal yet
                    })
            except Exception as e:
                logger.warning("timeline: skipped visits for %s (%s)", db, e)

        # ── Vaccinations (only administered ones — pending/due aren't "history") ──
        try:
            roadmap = build_roadmap(target_awpid, dob, _portal_schedule_rules())
            for item in roadmap:
                if not item.get("administered_date"):
                    continue
                entries.append({
                    "date":      item["administered_date"],
                    "type":      "vaccination",
                    "icon_hint": "syringe",
                    "title":     item["vaccine_name"],
                    "subtitle":  item.get("scheduled_label") or None,
                    "detail":    (
                        {"record_id": item["record_id"], "has_certificate": bool(item.get("has_certificate"))}
                        if item.get("record_id") else None
                    ),
                })
        except Exception as e:
            logger.warning("timeline: skipped vaccinations (%s)", e)

        # ── Growth ──────────────────────────────────────────────────────
        try:
            for v in SharedVital.objects.using("default").filter(awpid=target_awpid).order_by("-recorded_at")[:limit]:
                if not (v.height_cm or v.weight_kg):
                    continue
                bits = []
                if v.height_cm:
                    bits.append(f"Height {v.height_cm} cm")
                if v.weight_kg:
                    bits.append(f"Weight {v.weight_kg} kg")
                entries.append({
                    "date":      str(v.recorded_at.date()),
                    "type":      "growth",
                    "icon_hint": "trending-up",
                    "title":     "Growth check",
                    "subtitle":  " · ".join(bits) if bits else None,
                    "detail":    None,
                })
        except Exception as e:
            logger.warning("timeline: skipped growth (%s)", e)

        # ── Lab results ─────────────────────────────────────────────────
        for tenant in tenants:
            db = tenant.db_name
            try:
                _ensure_db(db)
                patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                reqs = (LabRequest.objects.using(db)
                        .select_related("test", "report")
                        .filter(patient=patient)
                        .order_by("-ordered_at")[:limit])
                for r in reqs:
                    rep = None
                    try:
                        rep = r.report
                    except Exception:
                        logger.debug("timeline: no lab report for request_id=%s", r.id, exc_info=True)

                    if rep and rep.delivered_at:
                        entries.append({
                            "date":      str(rep.delivered_at.date() if hasattr(rep.delivered_at, "date") else rep.delivered_at),
                            "type":      "lab",
                            "icon_hint": "flask",
                            "title":     r.test.name,
                            "subtitle":  f"Result delivered — {tenant.name}",
                            "detail":    (
                                {"tenant_db": db, "request_id": r.id, "has_file": bool(rep.file_url)}
                                if rep.file_url else None
                            ),
                        })
                    else:
                        entries.append({
                            "date":      str(r.ordered_at.date() if hasattr(r.ordered_at, "date") else r.ordered_at),
                            "type":      "lab",
                            "icon_hint": "flask",
                            "title":     r.test.name,
                            "subtitle":  f"Ordered — {tenant.name} ({r.status})",
                            "detail":    None,
                        })
            except Exception as e:
                logger.warning("timeline: skipped lab-results for %s (%s)", db, e)

        # ── Documents ───────────────────────────────────────────────────
        try:
            docs = (SharedDocument.objects.using("default")
                    .filter(awpid=target_awpid)
                    .order_by("-created_at")[:limit])
            for d in docs:
                entries.append({
                    "date":      str(d.created_at.date() if hasattr(d.created_at, "date") else d.created_at),
                    "type":      "document",
                    "icon_hint": "file",
                    "title":     d.title,
                    "subtitle":  d.doc_type.replace("_", " ").title() if d.doc_type else None,
                    "detail":    {"id": d.id},
                })
        except Exception as e:
            logger.warning("timeline: skipped documents (%s)", e)

        entries.sort(key=lambda e: e["date"], reverse=True)
        entries = entries[:limit]

        return success(data={"results": entries, "count": len(entries)})


# ── Notifications / reminders (HMS-10g) ────────────────────────────────────

class PortalNotificationsView(APIView):
    """
    GET /api/v1/portal/notifications/?patient_awpid=

    Merges two different kinds of reminder into one in-app list (HMS-10g):
      - Appointment / follow-up reminders — pre-generated rows in each
        tenant DB's NotificationLog (see apps.notifications.services, run by
        `python manage.py generate_reminders` on a schedule). Fanned out
        across every active tenant the same way PortalMyRecordsView does,
        since a patient's hospitals aren't known in advance.
      - Vaccination-due reminders — NOT stored anywhere. Computed live from
        apps.registry.vaccine_schedule.build_roadmap() every time this is
        called, because due-ness is just today's date vs. the patient's age
        against the schedule — persisting it would just be a second copy
        that could silently go stale (e.g. after a dose gets logged).

    No real SMS/email/push is sent for any of these — see the module
    docstring on apps/notifications/services.py for why that's out of scope
    without a provider account. This is the in-app fallback.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.patients.models import Patient
        from apps.notifications.models import NotificationLog
        from apps.registry.vaccine_schedule import build_roadmap

        target_awpid, dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err

        results = []

        # ── Appointment / follow-up reminders — fan out across tenants ──
        for tenant in Tenant.objects.using("default").filter(is_active=True):
            db = tenant.db_name
            try:
                _ensure_db(db)
                patient = Patient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                logs = (NotificationLog.objects.using(db)
                        .filter(patient=patient, channel="in_app")
                        .order_by("-created_at")[:50])
                for log in logs:
                    results.append({
                        "id":         f"{db}:{log.id}",
                        "type":       "appointment_reminder" if log.reference.startswith("appt_reminder:") else "followup_reminder",
                        "hospital":   tenant.name,
                        "body":       log.body,
                        "date":       str(log.created_at.date()),
                        "created_at": log.created_at,
                        "read":       log.read_at is not None,
                    })
            except Exception as e:
                logger.warning("notifications: skipped %s (%s)", db, e)

        # ── Vaccination-due reminders — computed live, not stored ───────
        # Only "due_now" (the window is actually open right now — see
        # build_roadmap()'s _DUE_LEAD_DAYS) surfaces here, not "upcoming":
        # the roadmap doesn't expose a concrete "window opens on" date for
        # upcoming slots (it's derived inline from age-in-days, not stored
        # as a date), so there's nothing honest to compare against a
        # "due soon" cutoff without re-deriving that math here too.
        try:
            roadmap = build_roadmap(target_awpid, dob, _portal_schedule_rules())
            for item in roadmap:
                if item.get("status") == "unknown" and item.get("timing") == "due_now":
                    results.append({
                        "id":         f"vaccine:{item.get('scheduled_label') or item['vaccine_name']}",
                        "type":       "vaccination_due",
                        "hospital":   None,
                        "body":       f"{item['vaccine_name']} is due now.",
                        "date":       timezone.localdate().isoformat(),
                        "created_at": None,
                        "read":       False,
                    })
        except Exception as e:
            logger.warning("notifications: skipped vaccination-due (%s)", e)

        results.sort(key=lambda r: r["date"], reverse=True)
        return success(data={
            "results": results,
            "unread_count": sum(1 for r in results if not r["read"]),
        })


class PortalNotificationMarkReadView(APIView):
    """
    POST /api/v1/portal/notifications/<tenant_db>/<id>/read/
    Only applies to real NotificationLog rows (appointment/follow-up) — the
    "id" composite from the list above is "<tenant_db>:<log_id>", split back
    apart by the frontend before calling this. Vaccination-due entries have
    no backing row (computed live) so there's nothing to mark read.
    """
    permission_classes = [IsPatient]

    def post(self, request, tenant_db, pk):
        from apps.patients.models import Patient
        from apps.notifications.models import NotificationLog

        if not Tenant.objects.using("default").filter(db_name=tenant_db, is_active=True).exists():
            return error("Unknown hospital.")
        _ensure_db(tenant_db)

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        try:
            log = NotificationLog.objects.using(tenant_db).select_related("patient").get(pk=pk)
        except NotificationLog.DoesNotExist:
            return not_found("Notification not found.")
        if not log.patient or log.patient.awpid != acct.awpid:
            # Family-member notifications aren't surfaced by this endpoint
            # today (the list view resolves one target_awpid at a time), so
            # ownership here is intentionally strict to the account itself.
            return error("This notification does not belong to you.", status=403)

        if not log.read_at:
            log.read_at = timezone.now()
            log.save(using=tenant_db, update_fields=["read_at"])
        return success(data={"read": True})


class PortalForgotPasswordView(APIView):
    """
    POST /api/v1/portal/forgot-password/
    Body: {mobile_or_awpid, date_of_birth (YYYY-MM-DD), new_password, confirm_password}

    Same reasoning as StaffForgotPasswordView (auth_app) — no email/SMS
    gateway exists in this stack, so this verifies identity with mobile
    number (or AWPID) plus date of birth on file, instead of pretending to
    send a reset link that would never arrive. If date_of_birth was never
    set on the account, this can't verify them.
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        login_id = (request.data.get("mobile_or_awpid") or request.data.get("mobile") or "").strip()
        dob      = (request.data.get("date_of_birth") or "").strip()
        new_password     = request.data.get("new_password") or ""
        confirm_password = request.data.get("confirm_password") or ""

        if not login_id or not dob:
            return error("Mobile number (or Patient ID) and date of birth are required.")
        if new_password != confirm_password:
            return error("Passwords do not match.", errors={"confirm_password": "Passwords do not match."})
        if len(new_password) < 8:
            return error("New password must be at least 8 characters.", errors={"new_password": "Too short."})

        try:
            if login_id.upper().startswith("AWPID-"):
                acct = PatientAccount.objects.using("default").get(awpid=login_id, is_active=True)
            else:
                acct = PatientAccount.objects.using("default").get(mobile=login_id, is_active=True)
        except PatientAccount.DoesNotExist:
            return error("We couldn't verify those details.")

        if not acct.date_of_birth:
            return error(
                "We can't verify your identity without a date of birth on file. "
                "Add it from My Profile after signing in with your current password, "
                "or contact support for help."
            )
        if str(acct.date_of_birth) != dob:
            return error("We couldn't verify those details.")

        acct.set_password(new_password)
        acct.save(using="default", update_fields=["password"])
        return success(message="Password reset successfully. You can now log in.")


class PortalChangePasswordView(APIView):
    """POST /api/v1/portal/profile/change-password/"""
    permission_classes = [IsPatient]

    def post(self, request):
        current = request.data.get("current_password") or ""
        new = request.data.get("new_password") or ""
        if not current or not new:
            return error("Current and new password are required.")
        if len(new) < 8:
            return error("New password must be at least 8 characters.", errors={"new_password": "Too short."})

        try:
            acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        except PatientAccount.DoesNotExist:
            return not_found("Account not found.")

        if not acct.check_password(current):
            return error("Current password is incorrect.", errors={"current_password": "Incorrect."})

        acct.set_password(new)
        acct.save(using="default", update_fields=["password"])
        return success(message="Password changed successfully.")


# ── Family members ────────────────────────────────────────────────────────

class PortalFamilyListCreateView(APIView):
    """
    GET  /api/v1/portal/family/  — dependents linked to the logged-in account
                                    (children, or anyone with no login of
                                    their own — see PatientRelationship).
    POST /api/v1/portal/family/  — add a new family member. Reuses the same
                                    dedup logic as front-desk registration
                                    (PatientService.resolve_dependent_identity)
                                    keyed on (this account, name, DOB), so a
                                    family member added here and one added by
                                    a hospital's front desk under the same
                                    person resolve to the same AWPID.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.patients.services import PatientService
        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        members = PatientService.list_family_members(acct.awpid)
        return success(data={"results": members})

    def post(self, request):
        from apps.patients.services import PatientService
        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        d = request.data
        try:
            member = PatientService.add_family_member(
                guardian_awpid=acct.awpid,
                guardian_mobile_raw=acct.mobile,
                data={
                    "full_name": (d.get("full_name") or "").strip(),
                    "date_of_birth": d.get("date_of_birth"),
                    "gender": d.get("gender", ""),
                    "relationship": d.get("relationship", "other"),
                },
            )
        except ValueError as exc:
            return error(str(exc))
        return success(data=member, message="Family member added.")
