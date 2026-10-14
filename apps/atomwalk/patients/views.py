"""Views of the patient portal, the emergency summary, the consult pad and record sharing."""
import re
import uuid
import logging
import hashlib
import secrets
import base64
import threading
from datetime import date, datetime, time as dtime, timedelta
from django.conf import settings
from django.db import transaction, connections
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from apps.atomwalk.documents.services import rules_for
from core.permissions import IsPatient
from core.response import success, error, not_found
from core.pagination import paginate_list, paginate_queryset
from apps.atomwalk.patients.services import resolve_target_awpid_and_dob
from apps.atomwalk.hospital_master.services import ensure_hospital_db
from core.file_validation import validate_data_uri, FileValidationError
from core.geo import haversine_km, parse_lat_lng
from apps.atomwalk.documents import services as doc_rules
from core import storage as blob_storage
from apps.atomwalk.hospital_master.models import Hospital
from apps.atomwalk.patients.models import (
    PatientAccount,
    Patient,
    PatientRelationship,
    EmergencyAccessLog,
    RecordsShareRequest,
    RecordsPrivacy,
    ConsultSession,
)
from core.emergency_access import decode_emergency_token, EmergencyTokenError
from apps.atomwalk.documents.models import LabResult, ImmunizationRecord, MedicalDocument
from core.utils.age import age_years_months as _age_years_months
from apps.atomwalk.documents.services import DOCUMENT_TYPES
from apps.atomwalk.documents.services import awaiting_review_q
from collections import Counter


logger = logging.getLogger(__name__)
# Matches literal doctors AND custom-role staff whose Role.acts_as includes
# "doctor" (e.g. a solo-clinic role bundling doctor+nurse+front_desk) — see
# apps.hospital_master.staff.rbac.resolve_acts_as. Reused everywhere this module looks up
# "doctors" for patient-facing search/booking, so a patient can find and
# book this person the same as any literal doctor.
DOCTOR_Q = Q(role="doctor") | Q(role="custom", custom_role__acts_as__contains=["doctor"])
# What actually gets pulled from the Atomwalk DB into a new hospital's view —
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
def _patient_app_enabled(hospital):
    """
    True only if this hospital's subscription has feat_patient_app on.
    Patients authenticate with a hospital-independent JWT (no MockUser.subscription
    to lean on — that's only populated for staff, see core/authentication.py),
    so every portal endpoint that touches a specific hospital re-checks this
    directly rather than trusting a JWT claim.
    """
    from apps.atomwalk.hospital_master.models import Subscription
    sub = Subscription.objects.using("default").filter(hospital=hospital).first()
    return bool(sub and sub.feat_patient_app)
# ── Register ─────────────────────────────────────────────────────────────────

class PortalRegisterView(APIView):
    """
    POST /api/v1/portal/register/
    body: {action_token, full_name, mobile, password, gender?, date_of_birth?}

    Requires a verified `action_token` from
    POST /api/v1/auth/otp/verify/ (purpose="registration_patient") proving
    the caller actually received an OTP at the EMAIL address they're
    registering — see apps/auth_app/otp_views.py. Email-based for now since
    verifying via mobile requires a paid SMS gateway that isn't wired up yet
    (see core/sms.py). The email used to create the account is taken from
    the TOKEN (what was actually verified), not from the request body, so a
    verified-but-different address can't be swapped in at the last step.
    The mobile number is still required (PatientAccount.mobile is the
    primary login identifier) but is NOT OTP-verified in this flow.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from apps.atomwalk.patients.models import Patient
        from apps.atomwalk.patients.models import OTPCode
        from core.utils.hashing import hash_mobile, normalize_mobile
        from core.utils.awpid import generate_unique_awpid
        from core.otp import decode_action_token, OTPError

        d = request.data
        token = d.get("action_token") or ""
        try:
            payload = decode_action_token(token, OTPCode.PURPOSE_REGISTRATION_PATIENT)
        except OTPError as exc:
            return error(str(exc))
        email = (payload.get("identifier") or "").strip().lower()

        required = ["full_name", "password", "mobile"]
        missing = [f for f in required if not str(d.get(f, "")).strip()]
        if missing:
            return error(f"Missing fields: {', '.join(missing)}")

        if "@" not in email:
            return error("Invalid verification token.")
        if PatientAccount.objects.using("default").filter(email__iexact=email).exists():
            return error("An account with this email already exists. Please log in.")

        mobile = (d.get("mobile") or "").strip()
        if not re.match(r"^\d{10}$", mobile):
            return error("Enter a valid 10-digit mobile number.", errors={"mobile": "Invalid format."})
        if PatientAccount.objects.using("default").with_mobile(mobile).exists():
            return error("An account with this mobile number already exists. Please log in.")
        from core.realworld_validation import validate_mobile_real
        is_valid, reason = validate_mobile_real(mobile)
        if not is_valid:
            return error(reason, errors={"mobile": reason})

        # ── Reuse (or create) this person's global Patient ─────────
        # Self-registering here used to only create a PatientAccount (the
        # login) and generate its own one-off AWPID, never touching
        # Patient — the atomwalk table every hospital's front desk
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
            identity, _ = Patient.objects.using("default").get_or_create(
                mobile_hash=mobile_hash,
                defaults={
                    "awpid":         generate_unique_awpid(),
                    "full_name":     d["full_name"].strip(),
                    "date_of_birth": d.get("date_of_birth") or None,
                    "gender":        gender,
                    "email":         email or "",
                },
            )

            # the login goes on the same identity row (a walk-in who signs up claims the AWPID they already have)
            if identity.password:
                return error("An account with this mobile number already exists. Please log in.")
            identity.email = identity.email or email
            identity.gender = identity.gender or gender
            identity.date_of_birth = identity.date_of_birth or d.get("date_of_birth") or None
            identity.set_password(d["password"])
            identity.save(using="default")
            acct = PatientAccount.objects.using("default").get(pk=identity.pk)

        logger.info("Patient account registered via OTP: account_id=%s awpid=%s email_verified=True", acct.id, acct.awpid)
        return success(
            data={"awpid": acct.awpid, "mobile": mobile},
            message="Account created. You can now log in.",
        )
# ── Hospitals & doctors ──────────────────────────────────────────────────────

def _hospital_card(t, lat=None, lng=None):
    """
    Shared shape for every patient-facing hospital listing (browse list +
    cross-hospital search) — keeps "near me" distance math in one place.
    distance_km is None whenever the patient hasn't shared their location
    OR this hospital has no lat/lng on file yet (platform admin hasn't set
    it) — either way that's "unknown", not "far away", so callers sort
    None to the end rather than treating it as infinitely close/far.
    """
    distance_km = None
    if lat is not None and t.latitude is not None and t.longitude is not None:
        distance_km = round(haversine_km(lat, lng, t.latitude, t.longitude), 1)
    return {
        "hospital_id": t.id,
        "name": t.name,
        "city": t.city or "",
        "state": t.state or "",
        "accreditations": [a.strip() for a in (t.accreditations or "").split(",") if a.strip()],
        "about": t.about or "",
        "logo": blob_storage.signed_url(t.logo),
        "distance_km": distance_km,
        # Raw coordinates, for "Get Directions" / map-preview links on the
        # frontend — None when the platform admin hasn't set them yet.
        # Deliberately alongside distance_km rather than replacing it: this
        # is the only place the frontend ever sees a hospital's location.
        "latitude": t.latitude,
        "longitude": t.longitude,
    }
def _sort_by_distance(cards):
    cards.sort(key=lambda c: c["distance_km"] if c["distance_km"] is not None else float("inf"))
    return cards
class PortalHospitalListView(APIView):
    """
    GET /api/v1/portal/hospitals/?lat=&lng=
    lat/lng are optional — pass them (from the browser's Geolocation API)
    to get each hospital's distance and have the nearest sorted first;
    omit them and this behaves exactly as before (alphabetical).
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.atomwalk.hospital_master.models import Subscription
        enabled_hospital_ids = set(
            Subscription.objects.using("default")
            .filter(feat_patient_app=True)
            .values_list("hospital_id", flat=True)
        )
        lat, lng = parse_lat_lng(request)
        hospitals = [
            _hospital_card(t, lat, lng)
            for t in Hospital.objects.using("default").filter(is_active=True, id__in=enabled_hospital_ids).order_by("name")
        ]
        if lat is not None:
            _sort_by_distance(hospitals)
        return Response({"results": hospitals})
class PortalPlatformStatsView(APIView):
    """
    GET /api/v1/portal/stats/ — real counts for the dashboard's hero panel
    (hospitals on the platform, doctors across all of them). No made-up
    marketing numbers — this is a live count from the atomwalk + each
    active hospital's own staff table.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.hospital_master.staff.models import StaffUser

        active_hospitals = list(Hospital.objects.using("default").filter(is_active=True))
        doctor_count = 0
        for hospital in active_hospitals:
            try:
                ensure_hospital_db(hospital.db_name)
                doctor_count += StaffUser.objects.using(hospital.db_name).filter(
                    role="doctor", is_active=True
                ).count()
            except Exception as exc:
                logger.warning("portal stats: skipped %s (%s)", hospital.db_name, exc)

        return Response({
            "hospitals": len(active_hospitals),
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
        sort = (request.query_params.get("sort") or "").strip()  # "experience" | "fee" | "name" | "distance"
        lat, lng = parse_lat_lng(request)

        # Optional numeric refinements — doctors with unknown data on either
        # field are kept rather than hidden (a profile the hospital hasn't
        # finished filling in shouldn't disappear from search just because
        # the patient added a price/experience filter).
        min_experience_raw = (request.query_params.get("min_experience") or "").strip()
        max_fee_raw = (request.query_params.get("max_fee") or "").strip()
        try:
            min_experience = int(min_experience_raw) if min_experience_raw else None
        except ValueError:
            min_experience = None
        try:
            max_fee = float(max_fee_raw) if max_fee_raw else None
        except ValueError:
            max_fee = None

        if len(q) < 2 and not specialty and not city and min_experience is None and max_fee is None:
            return Response({"hospitals": [], "doctors": []})

        terms = _expand_search_terms(q) if q else set()

        hosp_q = Q()
        for t in terms:
            hosp_q |= Q(name__icontains=t) | Q(city__icontains=t) | Q(state__icontains=t)
        hospital_qs = Hospital.objects.using("default").filter(is_active=True)
        if hosp_q:
            hospital_qs = hospital_qs.filter(hosp_q)
        if city:
            hospital_qs = hospital_qs.filter(city__icontains=city)
        hospitals = [_hospital_card(t, lat, lng) for t in hospital_qs.order_by("name")[:20]]
        if lat is not None:
            _sort_by_distance(hospitals)

        from apps.hospital_master.staff.models import StaffUser, DoctorProfile

        specialty_terms = _expand_search_terms(specialty) if specialty else set()

        doctors = []
        for hospital in Hospital.objects.using("default").filter(is_active=True):
            if city and city.lower() not in (hospital.city or "").lower():
                continue
            db = hospital.db_name
            try:
                ensure_hospital_db(db)

                name_q = Q()
                for t in terms:
                    name_q |= Q(first_name__icontains=t) | Q(last_name__icontains=t)
                name_matches = set(
                    StaffUser.objects.using(db).filter(DOCTOR_Q, is_active=True)
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
                        StaffUser.objects.using(db).filter(DOCTOR_Q, is_active=True)
                        .values_list("id", flat=True)
                    )

                if not matched_ids:
                    continue

                staff_by_id = {
                    s.id: s for s in
                    StaffUser.objects.using(db).filter(DOCTOR_Q, id__in=matched_ids, is_active=True)
                }
                profiles_by_staff = {
                    p.staff_id: p for p in
                    DoctorProfile.objects.using(db).filter(staff_id__in=staff_by_id.keys())
                }
                hospital_distance_km = None
                if lat is not None and hospital.latitude is not None and hospital.longitude is not None:
                    hospital_distance_km = round(haversine_km(lat, lng, hospital.latitude, hospital.longitude), 1)
                for sid, staff in staff_by_id.items():
                    card = _doctor_card(staff, profiles_by_staff.get(sid))
                    card["hospital_id"] = hospital.id
                    card["hospital"] = hospital.name
                    card["hospital_city"] = hospital.city or ""
                    card["distance_km"] = hospital_distance_km
                    card["hospital_latitude"] = hospital.latitude
                    card["hospital_longitude"] = hospital.longitude
                    doctors.append(card)
            except Exception as exc:
                logger.warning("portal search: skipped %s (%s)", db, exc)

        if min_experience is not None:
            doctors = [d for d in doctors if d["experience_years"] is None or d["experience_years"] >= min_experience]
        if max_fee is not None:
            doctors = [
                d for d in doctors
                if d["consultation_fee"] is None or float(d["consultation_fee"]) <= max_fee
            ]

        if sort == "experience":
            doctors.sort(key=lambda d: d["experience_years"] or 0, reverse=True)
        elif sort == "fee":
            doctors.sort(key=lambda d: float(d["consultation_fee"]) if d["consultation_fee"] else float("inf"))
        elif sort == "name":
            doctors.sort(key=lambda d: d["name"].lower())
        elif sort == "distance":
            doctors.sort(key=lambda d: d["distance_km"] if d["distance_km"] is not None else float("inf"))

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
        "photo":            blob_storage.signed_url(staff.photo) or None,
        "specialisation":   profile.specialisation if profile else "",
        "qualification":    profile.qualification if profile else "",
        "experience_years": profile.experience_years if profile else None,
        "consultation_fee": str(profile.consultation_fee) if profile and profile.consultation_fee is not None else None,
        "bio":              profile.bio if profile else "",
        "languages":        profile.languages if profile else "",
        "known_for":        profile.known_for if profile else "",
    }
class PortalSpecialtyListView(APIView):
    """
    GET /api/v1/portal/specialties/
    Powers "Find Doctors"' specialty filter. specialisation is a free-typed
    field on DoctorProfile (hospital admins type it in, no fixed choices —
    see _SPECIALITY_SYNONYMS above), so this aggregates the real distinct
    values in use across every active hospital instead of shipping a
    hardcoded list that would drift from what's actually on doctor profiles.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from collections import Counter
        from apps.hospital_master.staff.models import StaffUser, DoctorProfile

        counts = Counter()
        for hospital in Hospital.objects.using("default").filter(is_active=True):
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                doctor_ids = set(
                    StaffUser.objects.using(db).filter(DOCTOR_Q, is_active=True).values_list("id", flat=True)
                )
                if not doctor_ids:
                    continue
                specs = (
                    DoctorProfile.objects.using(db)
                    .filter(staff_id__in=doctor_ids)
                    .exclude(specialisation="")
                    .values_list("specialisation", flat=True)
                )
                for s in specs:
                    name = s.strip()
                    if name:
                        counts[name] += 1
            except Exception:
                logger.debug("PortalSpecialtyListView: skipping hospital %s.", hospital.id, exc_info=True)
                continue

        results = [{"name": name, "doctor_count": count} for name, count in sorted(counts.items())]
        return Response({"results": results})
class PortalDoctorListView(APIView):
    permission_classes = [IsPatient]

    def get(self, request, hospital_id):
        try:
            hospital = Hospital.objects.using("default").get(pk=hospital_id, is_active=True)
        except Hospital.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(hospital):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        ensure_hospital_db(hospital.db_name)
        from apps.hospital_master.staff.models import StaffUser, DoctorProfile

        try:
            staff_list = list(
                StaffUser.objects.using(hospital.db_name)
                .filter(DOCTOR_Q, is_active=True).order_by("first_name")
            )
            profiles = {
                p.staff_id: p
                for p in DoctorProfile.objects.using(hospital.db_name)
                    .filter(staff_id__in=[s.id for s in staff_list])
            }
            doctors = [_doctor_card(s, profiles.get(s.id)) for s in staff_list]
        except Exception:
            # A hospital can exist in the atomwalk (listed, bookable-in-theory)
            # before its own operational database has been provisioned — e.g.
            # a directory listing awaiting full onboarding. That's "no
            # doctors yet", not a platform error, so this degrades to an
            # empty list instead of a 500.
            logger.warning("portal doctors: hospital db %s unreachable", hospital.db_name, exc_info=True)
            doctors = []
        return Response({
            "results": doctors,
            "hospital": {
                "hospital_id": hospital.id, "name": hospital.name, "logo": blob_storage.signed_url(hospital.logo),
                "latitude": hospital.latitude, "longitude": hospital.longitude,
            },
        })
class PortalDoctorDetailView(APIView):
    """GET /api/v1/portal/hospitals/<hospital_id>/doctors/<doctor_id>/ — single doctor profile."""
    permission_classes = [IsPatient]

    def get(self, request, hospital_id, doctor_id):
        try:
            hospital = Hospital.objects.using("default").get(pk=hospital_id, is_active=True)
        except Hospital.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(hospital):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        ensure_hospital_db(hospital.db_name)
        from apps.hospital_master.staff.models import StaffUser, DoctorProfile

        try:
            staff = StaffUser.objects.using(hospital.db_name).get(
                DOCTOR_Q, pk=doctor_id, is_active=True
            )
        except StaffUser.DoesNotExist:
            return Response({"error": "Doctor not found at this hospital."}, status=404)

        profile = DoctorProfile.objects.using(hospital.db_name).filter(staff_id=staff.id).first()
        data = _doctor_card(staff, profile)
        data["hospital"] = {
            "hospital_id": hospital.id, "name": hospital.name, "city": hospital.city or "",
            "accreditations": [a.strip() for a in (hospital.accreditations or "").split(",") if a.strip()],
            "logo": blob_storage.signed_url(hospital.logo),
            "latitude": hospital.latitude, "longitude": hospital.longitude,
        }

        # Which payment modes this hospital currently accepts (hospital admin
        # toggles these in Billing Setup — see apps.hospital_master.billing.OptionList,
        # list_type="payment_mode"; v7 merged the old standalone
        # PaymentModeOption table into this shared dropdown table)
        # so the booking screen's "How will you pay?" step reflects the real
        # choice instead of a hardcoded pair of buttons.
        from apps.hospital_master.billing.models import OptionList
        data["payment_methods"] = list(
            OptionList.objects.using(hospital.db_name)
            .filter(list_type=OptionList.LIST_PAYMENT_MODE, is_active=True)
            .order_by("sort_order", "label")
            .values_list("label", flat=True)
        )

        # Real count, not a marketing number — signed (finalized) consultations
        # this doctor has completed at THIS hospital. No cross-hospital total
        # (each hospital only knows its own encounters), and no fabricated
        # rating/review numbers — we don't have a reviews system.
        from apps.hospital_master.opd.models import OPDEncounter
        data["consultations_count"] = OPDEncounter.objects.using(hospital.db_name).filter(
            doctor_user_id=staff.id, status=OPDEncounter.STATUS_SIGNED
        ).count()

        # Which weekdays this doctor actually works (0=Monday..6=Sunday, same
        # as DoctorAvailabilitySlot.day_of_week) — lets the booking calendar
        # grey out days before the patient picks one, instead of only finding
        # out after picking a date and seeing an empty slot grid (see
        # _slot_grid, which already has this same "no schedule configured"
        # fallback: None here means "no restriction", not "no days work").
        from apps.hospital_master.staff.models import DoctorSchedule, DoctorAvailabilitySlot
        schedule = DoctorSchedule.objects.using(hospital.db_name).filter(doctor_id=staff.id).first()
        if schedule:
            data["working_days"] = sorted(
                DoctorAvailabilitySlot.objects.using(hospital.db_name)
                .filter(schedule=schedule, is_available=True)
                .values_list("day_of_week", flat=True)
            )
        else:
            data["working_days"] = None

        return Response(data)
class PortalNextTokenView(APIView):
    """
    GET /api/v1/portal/hospitals/<hospital_id>/doctors/<doctor_id>/next-token/?date=YYYY-MM-DD
    Preview only — the real token is assigned atomically at booking time in
    PortalBookView, so this can be off by one if someone else books in between.
    Shown to the patient as "you'll likely be token #N" before they confirm.
    """
    permission_classes = [IsPatient]

    def get(self, request, hospital_id, doctor_id):
        from apps.hospital_master.opd.models import Appointment

        try:
            hospital = Hospital.objects.using("default").get(pk=hospital_id, is_active=True)
        except Hospital.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(hospital):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        db = hospital.db_name
        ensure_hospital_db(db)
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
    from apps.hospital_master.staff.models import DoctorSchedule, DoctorAvailabilitySlot

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
    GET /api/v1/portal/hospitals/<hospital_id>/doctors/<doctor_id>/slots/?date=YYYY-MM-DD
    Available to patients AND hospital staff (front desk uses it too).
    """
    permission_classes = []  # JWT already validated by middleware

    def get(self, request, hospital_id, doctor_id):
        from apps.hospital_master.opd.models import Appointment

        try:
            hospital = Hospital.objects.using("default").get(pk=hospital_id, is_active=True)
        except Hospital.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)

        db = hospital.db_name
        ensure_hospital_db(db)
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
        from apps.atomwalk.patients.models import PatientBooking
        from apps.hospital_master.staff.models import StaffUser
        from apps.hospital_master.facility.models import Branch
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.hospital_master.opd.models import Appointment

        d = request.data
        hospital_id       = d.get("hospital_id")
        doctor_id       = d.get("doctor_id")
        scheduled_date  = d.get("scheduled_date") or str(date.today())
        scheduled_time  = (d.get("scheduled_time") or "").strip() or None
        chief_complaint = (d.get("chief_complaint") or "").strip()
        payment_preference = d.get("payment_preference") or Appointment.PAYMENT_PAY_AT_DESK
        if payment_preference not in dict(Appointment.PAYMENT_PREFERENCE_CHOICES):
            payment_preference = Appointment.PAYMENT_PAY_AT_DESK

        # The hospital's own patient row keeps a phone number it can call, but the account stores the mobile only
        # scrambled, so the number comes from the patient here (it must be the number on their account).
        contact_mobile = (d.get("mobile") or "").strip()
        if contact_mobile:
            from apps.atomwalk.patients.models import mobile_hash_of
            acct_hash = PatientAccount.objects.using("default").filter(pk=request.user.id).values_list("mobile_hash", flat=True).first()
            if not re.match(r"^\d{10}$", contact_mobile) or mobile_hash_of(contact_mobile) != acct_hash:
                return Response({"error": "That is not the mobile number on your account."}, status=400)

        if not hospital_id or not doctor_id:
            return Response({"error": "hospital_id and doctor_id are required."}, status=400)

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
            hospital = Hospital.objects.using("default").get(pk=hospital_id, is_active=True)
        except Hospital.DoesNotExist:
            return Response({"error": "Hospital not found."}, status=404)
        if not _patient_app_enabled(hospital):
            return Response({"error": "This hospital isn't available for online booking."}, status=403)

        db = hospital.db_name
        ensure_hospital_db(db)

        try:
            doctor = StaffUser.objects.using(db).get(DOCTOR_Q, pk=doctor_id, is_active=True)
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
            from apps.atomwalk.patients.models import PatientRelationship, Patient
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=target_awpid,
            ).exists()
            if not is_family:
                return Response({"error": "That patient isn't linked to your account."}, status=403)
            dep_identity = Patient.objects.using("default").filter(awpid=target_awpid).first()
            if not dep_identity:
                return Response({"error": "Family member record not found."}, status=404)
            target_name, target_gender, target_dob = dep_identity.full_name, dep_identity.gender, dep_identity.date_of_birth

        # ── Find-or-create the hospital-local Patient record ────────────────
        patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
        if not patient:
            # First time this patient is being registered at THIS hospital —
            # this is exactly the moment their shared cross-hospital history
            # becomes visible to a new set of doctors, so consent is required
            # before anything is created. Once given, it's on record for this
            # hospital going forward (not asked again on later bookings here).
            if not d.get("data_sharing_consent"):
                return Response({
                    "consent_required": True,
                    "hospital_name": hospital.name,
                    "share_categories": HIE_SHARE_CATEGORIES,
                    "message": f"This is {'your' if target_awpid == acct.awpid else target_name + chr(39) + 's'} first booking at {hospital.name}. Please confirm you're okay sharing this medical history with them.",
                }, status=428)

            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            if not branch:
                return Response({"error": "Hospital is not accepting registrations yet."}, status=400)
            # next UHID number
            max_num = 0
            for uhid in HospitalPatient.objects.using(db).values_list("uhid", flat=True):
                try:
                    max_num = max(max_num, int(uhid.split("-")[-1]))
                except (ValueError, IndexError):
                    pass
            # These Patient columns are all NOT NULL (blank=True, no null=True) —
            # a mobile-only portal signup has acct.email = None (and a
            # Patient can carry a null gender), so every value sourced
            # from the account must be coalesced to "" or the INSERT hits a
            # NotNullViolation on the first booking at a hospital.
            patient = HospitalPatient.objects.using(db).create(
                awpid=target_awpid,
                uhid=f"UHID-{max_num + 1:06d}",
                branch=branch,
                full_name=target_name or "",
                gender=target_gender or "",
                date_of_birth=target_dob,
                # Patient.mobile/email are NOT NULL — a portal account that
                # signed up by mobile has email=None, so coalesce to "".
                mobile=contact_mobile if target_awpid == acct.awpid else "",
                email=(acct.email or "") if target_awpid == acct.awpid else "",
                is_dependent=target_awpid != acct.awpid,
                guardian_name=(acct.full_name or "") if target_awpid != acct.awpid else "",
                guardian_mobile=contact_mobile if target_awpid != acct.awpid else "",
                hie_consent_given=True,
                hie_consent_at=timezone.now(),
                payer_type="self",
                dpdp_consent_captured=True,
                dpdp_consent_at=timezone.now(),
            )
            # Durable proof trail behind the two booleans above — patient
            # granted both by submitting data_sharing_consent through the
            # portal itself (no staff intermediary), see
            # apps.hospital_master.compliance.services.record_consent.
            from apps.hospital_master.compliance.services import record_consent
            from apps.hospital_master.compliance.models import ConsentRecord
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
        # (apps.hospital_master.opd.views.AppointmentListCreateView.post) — this is a second,
        # separate creation path for the same Appointment model, so it needs
        # the same room-resolution logic rather than inheriting it.
        room_fields = {}
        if scheduled_time:
            from apps.hospital_master.facility.room_utils import resolve_room_for_slot
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

        booking = PatientBooking.objects.using("default").create(
            booked_by=acct,
            hospital=hospital,
            appointment_id=appt.id,
            doctor_name=doctor_name,
            scheduled_date=scheduled_date,
            chief_complaint=chief_complaint,
            status="scheduled",
            patient=acct if target_awpid == acct.awpid else Patient.objects.using("default").filter(awpid=target_awpid).first(),
        )

        return Response({
            "booking_id": booking.id,
            "hospital_id": hospital.id,
            "hospital": hospital.name,
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
            # For the confirmation screen's "Get Directions" / map preview —
            # same fields _hospital_card() exposes, None if not set yet.
            "latitude": hospital.latitude,
            "longitude": hospital.longitude,
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
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.hospital_master.opd.models import Appointment, OPDEncounter, Prescription
        from apps.atomwalk.documents.services import visit_vitals

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)

        target_awpid = (request.query_params.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid != acct.awpid:
            from apps.atomwalk.patients.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=target_awpid,
            ).exists()
            if not is_family:
                return error("That patient isn't linked to your account.", status=403)

        results = []

        for hospital in Hospital.objects.using("default").filter(is_active=True):
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                appts = (Appointment.objects.using(db)
                         .filter(patient_id=patient.uuid)
                         .order_by("-scheduled_date", "-created_at")[:50])
                for appt in appts:
                    enc = OPDEncounter.objects.using(db).filter(appointment_id=appt.id).first()
                    record = {
                        "hospital":        hospital.name,
                        "hospital_db":       db,
                        "date":            str(appt.scheduled_date),
                        "time":            appt.scheduled_time.strftime("%H:%M") if appt.scheduled_time else None,
                        "doctor":          appt.doctor_name,
                        "status":          appt.status,
                        "chief_complaint": appt.chief_complaint,
                        "diagnoses":       [],
                        "prescription":    [],
                        "prescription_id": None,
                        "rx_number":       None,
                        "investigations":  "",
                        "advice":          "",
                        "follow_up_in_days": None,
                        "signed":          False,
                        "vitals":          None,
                    }
                    v = visit_vitals(appt.id)
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
                            # So the frontend can offer a PDF download right
                            # on this card — PortalPrescriptionReceiptPDFView
                            # takes exactly (hospital_db, prescription pk).
                            record["prescription_id"] = str(rx.id)
                            record["rx_number"] = rx.rx_number
                    results.append(record)
            except Exception as e:
                logger.warning("my-records: skipped %s (%s)", db, e)

        results.sort(key=lambda r: r["date"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return Response({"results": page_items, "pagination": meta})
# ── My bills ─────────────────────────────────────────────────────────────────

class PortalInvoiceListView(APIView):
    """
    GET /api/v1/portal/invoices/?patient_awpid=
    Every invoice raised for this patient (or a linked family member — see
    resolve_target_awpid_and_dob), across all hospitals. Invoice has no
    link back to a specific Appointment/booking in this schema — a hospital
    can bill a patient for a consultation, a walk-in registration fee, or
    anything else, all as the same kind of Invoice row keyed only to the
    patient — so this is a patient-wide bill list, not a per-booking one.
    Draft invoices (not yet issued to the patient by staff) are excluded.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.hospital_master.billing.models import Invoice

        target_awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err

        results = []
        for hospital in Hospital.objects.using("default").filter(is_active=True):
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                invoices = (
                    Invoice.objects.using(db)
                    .filter(patient=patient)
                    .exclude(status=Invoice.STATUS_DRAFT)
                    .order_by("-created_at")[:50]
                )
                for inv in invoices:
                    results.append({
                        "id": inv.id,
                        "hospital_db": db,
                        "hospital": hospital.name,
                        "invoice_number": inv.invoice_number,
                        "status": inv.status,
                        "total_amount": str(inv.total_amount),
                        "paid_amount": str(inv.paid_amount),
                        "issued_at": inv.issued_at,
                        "created_at": inv.created_at,
                    })
            except Exception:
                logger.debug("PortalInvoiceListView: skipped %s.", db, exc_info=True)
                continue

        results.sort(key=lambda r: r["created_at"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return Response({"results": page_items, "pagination": meta})
class PortalInvoiceReceiptPDFView(APIView):
    """
    GET /api/v1/portal/invoices/<hospital_db>/<id>/receipt/
    PDF download of one of the patient's own bills — the same PDF staff get
    from apps.hospital_master.billing.views.InvoicePDFView (reuses generate_invoice_pdf()
    directly so the two never drift apart), just patient-scoped: ownership
    is verified via the invoice's own patient.awpid against the requesting
    account (or a linked family member), the same pattern
    PortalLabReportFileView uses. Returned as a base64 data URI in the
    standard envelope, not a raw application/pdf response — patient auth is
    a JWT bearer header, so a plain <a href> to the API wouldn't carry it
    (see frontend/src/utils/fileViewer.js, the convention every other file
    viewer in this app follows).
    """
    permission_classes = [IsPatient]

    def get(self, request, hospital_db, pk):
        import base64
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.hospital_master.facility.models import Branch
        from apps.hospital_master.billing.models import Invoice
        from apps.hospital_master.billing.pdf import generate_invoice_pdf

        if not Hospital.objects.using("default").filter(db_name=hospital_db, is_active=True).exists():
            return error("Unknown hospital.")
        ensure_hospital_db(hospital_db)

        try:
            # NOT prefetch_related("items", "payments") — under this app's
            # custom multi-db router, Django's prefetch machinery issues the
            # related-object queries against the "default" atomwalk DB
            # instead of hospital_db, which 500s with "relation ... does not
            # exist" (those tables only exist on hospital DBs). Same bug
            # already found and fixed at PortalPrescriptionReceiptPDFView/
            # PortalPrescriptionListView — access inv.items/inv.payments
            # explicitly with .using(hospital_db) below instead of prefetching.
            inv = Invoice.objects.using(hospital_db).get(pk=pk)
        except Invoice.DoesNotExist:
            return not_found("Bill not found.")
        if inv.status == Invoice.STATUS_DRAFT:
            return not_found("Bill not found.")

        patient = HospitalPatient.objects.using(hospital_db).filter(pk=inv.patient_id).first()
        if not patient:
            return not_found("Bill not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        if patient.awpid != acct.awpid:
            from apps.atomwalk.patients.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=patient.awpid,
            ).exists()
            if not is_family:
                return error("This bill does not belong to you.")

        branch = Branch.objects.using(hospital_db).filter(pk=inv.branch_id).first()
        hospital = Hospital.objects.using("default").filter(db_name=hospital_db).first()
        hospital_name = hospital.name if hospital else "Hospital"

        pdf_bytes = generate_invoice_pdf(
            invoice=inv,
            # .using(hospital_db) explicitly — see the comment on the inv
            # fetch above; the plain .all() form is what triggers the
            # cross-DB router bug.
            items=list(inv.items.using(hospital_db).all()),
            payments=list(inv.payments.using(hospital_db).all().order_by("paid_at")),
            patient=patient,
            branch=branch,
            hospital_name=hospital_name,
        )
        data_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
        return success(data={
            "file_data": data_uri,
            "file_name": f"{inv.invoice_number}.pdf",
            "mime_type": "application/pdf",
        })
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
        from apps.atomwalk.patients.models import PatientBooking
        from apps.hospital_master.opd.models import Appointment

        qs = PatientBooking.objects.using("default").filter(
            booked_by_id=request.user.id
        ).select_related("patient", "hospital").order_by("-scheduled_date", "-id")
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
            doctor_photo = None
            doctor_specialisation = ""
            try:
                ensure_hospital_db(b.hospital.db_name)
                appt = Appointment.objects.using(b.hospital.db_name).get(pk=b.appointment_id)
                status_now = _auto_expire_if_stale(appt, b.hospital.db_name)
                token = appt.token_number
                slot_time = appt.scheduled_time.strftime("%H:%M") if appt.scheduled_time else None
                # appt.doctor_user_id is a UUIDField, but the value actually
                # stored in it is StaffUser's plain integer pk — Django's
                # UUIDField silently wraps a plain int via uuid.UUID(int=value)
                # (see apps.hospital_master.opd.services.resolve_doctor_consultation_fee for the
                # same unwrap). Returning it unwrapped sent the frontend a
                # garbage UUID as doctor_id, so "Book follow-up" 404'd the
                # doctor-detail lookup the moment a patient tapped to rebook.
                doctor_id = appt.doctor_user_id.int if isinstance(appt.doctor_user_id, uuid.UUID) else appt.doctor_user_id
                room_name = appt.room_name or None
                floor = appt.floor or None

                # Same doctor detail already shown on "Find Doctors" (see
                # _doctor_card above) — a patient shouldn't lose the doctor's
                # photo/specialisation just because they're viewing a past
                # booking instead of browsing. Best-effort: folded into the
                # same try/except as the rest of this per-booking lookup.
                if doctor_id:
                    from apps.hospital_master.staff.models import StaffUser, DoctorProfile
                    staff_obj = StaffUser.objects.using(b.hospital.db_name).filter(pk=doctor_id).first()
                    if staff_obj and staff_obj.photo:
                        doctor_photo = blob_storage.signed_url(staff_obj.photo) or None
                    profile_obj = DoctorProfile.objects.using(b.hospital.db_name).filter(staff_id=doctor_id).first()
                    if profile_obj:
                        doctor_specialisation = profile_obj.specialisation or ""

                # Self-heal every ledger field that a STAFF-side action can
                # change out from under this row, not just status — front
                # desk's AppointmentRescheduleView/AppointmentStatusView (see
                # apps.hospital_master.opd.views) move the date, change the complaint, or
                # swap the doctor directly on the hospital-DB Appointment, and
                # neither one touches PatientBooking (unlike the patient's own
                # PortalRescheduleBookingView, which does). Without this, a
                # front-desk reschedule would leave the patient's "My
                # Bookings" silently showing the old date forever, same bug
                # class as the original front-desk-booking-invisible issue —
                # just on an existing row instead of a missing one.
                dirty_fields = []
                if status_now != b.status:
                    b.status = status_now
                    dirty_fields.append("status")
                if appt.scheduled_date != b.scheduled_date:
                    b.scheduled_date = appt.scheduled_date
                    dirty_fields.append("scheduled_date")
                if (appt.chief_complaint or "") != b.chief_complaint:
                    b.chief_complaint = appt.chief_complaint or ""
                    dirty_fields.append("chief_complaint")
                if (appt.doctor_name or "") != b.doctor_name:
                    b.doctor_name = appt.doctor_name or ""
                    dirty_fields.append("doctor_name")
                if dirty_fields:
                    b.save(using="default", update_fields=dirty_fields)

                # Real, live queue position — only meaningful same-day, and
                # only while this appointment hasn't itself been called yet.
                if str(appt.scheduled_date) == today and status_now in QUEUE_PENDING and token is not None:
                    same_day_doctor = Appointment.objects.using(b.hospital.db_name).filter(
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
                # Best-effort by design (booking.hospital_db may be temporarily
                # unreachable) — the patient still sees the booking with
                # whatever was last saved to the atomwalk row, just without
                # live token/queue data. Logged so a systemic issue (e.g. a
                # schema change breaking this join hospital-wide) is visible
                # somewhere instead of just presenting as "missing token".
                logger.debug("PortalMyBookingsView: live status lookup failed for booking_id=%s db=%s", b.id, b.hospital.db_name, exc_info=True)
            hospital = b.hospital
            results.append({
                "id": b.id,
                "hospital_id": b.hospital_id,
                "hospital": hospital.name if hospital else "",
                "hospital_city": (hospital.city if hospital else "") or "",
                "hospital_state": (hospital.state if hospital else "") or "",
                "hospital_latitude": hospital.latitude if hospital else None,
                "hospital_longitude": hospital.longitude if hospital else None,
                "doctor": b.doctor_name,
                "doctor_photo": doctor_photo,
                "doctor_specialisation": doctor_specialisation,
                # So "Book follow-up" can deep-link straight to this same
                # doctor's profile instead of dropping the patient back at
                # the generic hospital doctor-list to re-find who they saw.
                # None if the underlying appointment row is gone/unreachable
                # (e.g. hospital DB down) — frontend falls back to the browse
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
                "patient_name": b.patient.full_name if b.patient else None,
                "patient_awpid": b.patient.awpid if b.patient else None,
                # "Booked on" — when this appointment was actually reserved,
                # distinct from the visit date itself (see reference mockup's
                # "Booked on" field).
                "booked_at": b.created_at.isoformat() if b.created_at else None,
            })
        return Response({"results": results, "pagination": meta})
class PortalCancelBookingView(APIView):
    """
    POST /api/v1/portal/my-bookings/<id>/cancel/

    Patient self-service cancellation. <id> is the atomwalk-DB
    PatientBooking pk (what PortalMyBookingsView hands back as "id"), not the
    hospital-DB Appointment id — the portal only ever deals in PatientBooking
    rows since a single account can have bookings across many hospitals.
    Resolves through to the real hospital-DB Appointment, cancels it there,
    then writes the same status back to the atomwalk row so the two stay in
    sync (mirrors what PortalMyBookingsView.get() already does opportunistically).
    """
    permission_classes = [IsPatient]

    def post(self, request, pk):
        from apps.atomwalk.patients.models import PatientBooking
        from apps.hospital_master.opd.models import Appointment

        try:
            booking = PatientBooking.objects.using("default").select_related("hospital").get(pk=pk, booked_by_id=request.user.id)
        except PatientBooking.DoesNotExist:
            return not_found("Booking not found.")

        ensure_hospital_db(booking.hospital.db_name)
        try:
            appt = Appointment.objects.using(booking.hospital.db_name).get(pk=booking.appointment_id)
        except Appointment.DoesNotExist:
            return not_found("Appointment record not found.")

        CANCELLABLE = (Appointment.STATUS_SCHEDULED, Appointment.STATUS_WAITING, Appointment.STATUS_VITALS_DONE)
        if appt.status not in CANCELLABLE:
            return error(f"Can't cancel an appointment that's already {appt.get_status_display().lower()}.")

        appt.status = Appointment.STATUS_CANCELLED
        appt.save(using=booking.hospital.db_name, update_fields=["status"])
        booking.status = Appointment.STATUS_CANCELLED
        booking.save(using="default", update_fields=["status"])
        return Response({"status": "cancelled"})
class PortalRescheduleBookingView(APIView):
    """
    POST /api/v1/portal/my-bookings/<id>/reschedule/  {scheduled_date, scheduled_time?}

    Moves an existing booking to a new date/time instead of cancel + rebook.
    Same window/slot rules as PortalBookView, keyed by PatientBooking pk like
    PortalCancelBookingView above, and keeps both the hospital-DB Appointment
    and the atomwalk-DB PatientBooking row in sync.
    """
    permission_classes = [IsPatient]

    def post(self, request, pk):
        from apps.atomwalk.patients.models import PatientBooking
        from apps.hospital_master.opd.models import Appointment

        try:
            booking = PatientBooking.objects.using("default").select_related("hospital").get(pk=pk, booked_by_id=request.user.id)
        except PatientBooking.DoesNotExist:
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

        ensure_hospital_db(booking.hospital.db_name)
        db = booking.hospital.db_name
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
            from apps.hospital_master.facility.room_utils import resolve_room_for_slot
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
# Uploading is POST /api/v1/records/upload/ (apps/records). These are the
# patient's read / zip endpoints over apps.atomwalk.documents.MedicalDocument.

def _handwritten_siblings(awpid):
    """The consult pad's raw handwritten Rx (source "encounter_handwritten_rx")
    hangs off its typeset prescription instead of being its own row.
    Returns ({encounter id: handwriting doc id}, [handwriting ids to hide])."""
    from apps.atomwalk.documents.models import MedicalDocument
    Source = MedicalDocument.Source
    docs = MedicalDocument.objects.using("default").filter(
        patient__awpid=awpid, source_type__in=(Source.ENCOUNTER, Source.ENCOUNTER_HANDWRITTEN_RX))
    typeset = set(docs.filter(source_type=Source.ENCOUNTER).values_list("source_id", flat=True))
    by_base = {}
    for hid, encounter_id in docs.filter(source_type=Source.ENCOUNTER_HANDWRITTEN_RX).values_list("id", "source_id"):
        if encounter_id in typeset:
            by_base[encounter_id] = hid
    return by_base, list(by_base.values())
def _document_row(d, handwritten_doc_id=None):
    return {
        "id": d.id, "title": d.file_name, "doc_type": d.document_type,
        "file_name": d.file_name, "mime_type": d.mime_type, "size": d.size,
        "uploaded_by": d.uploaded_by, "created_at": d.created_at,
        "document_date": d.document_date, "public_document_id": d.document_ref,
        "source_hospital_id": d.source_hospital_id,
        "processing_status": d.processing_status, "score": doc_rules.score_of(d), "method": doc_rules.method_of(d),
        "suggested_type": doc_rules.suggested_type_of(d), "confirmed": doc_rules.is_confirmed(d),
        "error": d.error_message if d.processing_status == "failed" else "",
        "batch_id": d.batch_id, "handwritten_doc_id": handwritten_doc_id,
    }
def _events(doc):
    """What has happened to a report, oldest first, in words — the Activity tab. Built from what is stored
    (there is no separate event log), so it shows the upload and the latest outcome."""
    S = type(doc).Status
    label = lambda t: t.replace("_", " ").capitalize() if t else "nothing"       # noqa: E731
    events = [{"at": doc.created_at, "text": "Issued by your hospital" if doc.source_hospital_id else "You uploaded this file"}]
    if doc.status == S.FAILED:
        events.append({"at": doc.updated_at, "text": f"We couldn’t read it — {doc.error_message}".rstrip(" —")})
    elif doc.status in (S.COMPLETED, S.REVIEW_REQUIRED) and not doc.source_hospital_id:
        if doc_rules.method_of(doc) == "staff":
            events.append({"at": doc.updated_at, "text": f"You set the type to {label(doc.document_type)}"})
        elif doc.status == S.COMPLETED:
            events.append({"at": doc.updated_at, "text": f"Filed as {label(doc.document_type)} by the rules"})
        else:
            events.append({"at": doc.updated_at, "text": "The rules couldn’t tell what it is - choose its type"})
    elif doc.status in type(doc).IN_PROGRESS:
        events.append({"at": doc.updated_at, "text": "Being read"})
    return events
def _choosable_types():
    """What a patient may file a report under: the fixed document types (apps/records/classification.py)."""
    from apps.atomwalk.documents.services import CHOOSABLE_TYPES
    return list(CHOOSABLE_TYPES)
def _own_document(request, doc_id):
    """(doc, None) if the caller (or a linked family member) owns it, else (None, error)."""
    from apps.atomwalk.documents.models import MedicalDocument
    target_awpid, _dob, err = resolve_target_awpid_and_dob(request)
    if err:
        return None, err
    doc = MedicalDocument.objects.using("default").filter(pk=doc_id, patient__awpid=target_awpid).first()
    if not doc:
        return None, error("Document not found.", status=404)
    return doc, None
class PortalDocumentListCreateView(APIView):
    """
    GET /api/v1/portal/documents/?status=queued,extracting&review=pending|confirmed|all&doc_type=lab_report
    - the patient's documents, newest first, with each one's processing_status / type / score / method.

    review (default "confirmed"): "confirmed" is My Documents - everything except the patient's new uploads that still
    wait for their confirmation; "pending" is exactly those uploads (the Needs Review list); "all" is both.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.atomwalk.documents.models import MedicalDocument

        target_awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        hw_by_base, linked_hw_ids = _handwritten_siblings(target_awpid)
        qs = (MedicalDocument.objects.using("default")
              .filter(patient__awpid=target_awpid)
              .exclude(id__in=linked_hw_ids)
              .select_related("classification")
              .order_by("-created_at"))
        statuses = [s for s in (request.query_params.get("status") or "").split(",") if s]
        if statuses:
            qs = qs.filter(status__in=statuses)
        from apps.atomwalk.documents import services as records_services
        review = (request.query_params.get("review") or "confirmed").lower()
        if review == "pending":
            qs = qs.filter(records_services.awaiting_review_q())
        elif review != "all":
            qs = qs.exclude(records_services.awaiting_review_q())
        doc_type = request.query_params.get("doc_type")
        if doc_type:
            qs = qs.filter(document_type=doc_type)
        page_items, meta = paginate_queryset(request, qs)
        return Response({"results": [_document_row(d, hw_by_base.get(d.source_id) if d.source_type == d.Source.ENCOUNTER else None) for d in page_items],
                         "pagination": meta})
class PortalDocumentCountsView(APIView):
    """GET /api/v1/portal/documents/counts/ - {"total", "awaiting_review", "unclassified", "by_type": {code: n}} for the
    My Documents dropdown and the Needs Review badge. Every type code is present, zeros included."""
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.atomwalk.documents import services as records_services
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        return success(data=records_services.document_counts(awpid))
class PortalDocumentDetailView(APIView):
    """
    GET    /api/v1/portal/documents/<id>/[?download=1]  — metadata + a short-lived signed file URL, and the
           types the patient may choose from (`doc_types`: the fixed document types)
    PATCH  /api/v1/portal/documents/<id>/               — the patient acts on a document they uploaded:
           {doc_type}  correct its type (a human verdict, which the rules never overwrite)
           {action: "retry"}  try a file that failed again
    DELETE /api/v1/portal/documents/<id>/               — remove an upload: a file that failed, or one that has been
           read but not yet confirmed by the patient (removes the row and its stored copy). A file still being read,
           or one already confirmed, is refused with 409: a document in the patient's records is never deleted.
    """
    permission_classes = [IsPatient]

    def delete(self, request, doc_id):
        from apps.atomwalk.documents import services
        doc, err = _own_document(request, doc_id)
        if err:
            return err
        if doc.source_hospital_id or doc.uploaded_by == "staff":
            return error("This report was issued by your hospital, so it can't be removed here.")
        try:
            services.dismiss_document(doc)
        except ValueError as exc:
            return error(str(exc), errors={"code": "not_removable"}, status=409)
        return success(data={"dismissed": True, "id": doc_id})

    def get(self, request, doc_id):
        from apps.atomwalk.documents.models import MedicalDocument
        doc, err = _own_document(request, doc_id)
        if err:
            return err
        want_download = (request.query_params.get("download") or "").lower() in ("1", "true", "yes")
        dl_name = doc.file_name or "document.pdf"
        hw_id = None
        if doc.document_type == "prescription" and doc.source_type == MedicalDocument.Source.ENCOUNTER:
            hw_id = (MedicalDocument.objects.using("default")
                     .filter(patient_id=doc.patient_id, source_type=MedicalDocument.Source.ENCOUNTER_HANDWRITTEN_RX,
                             source_id=doc.source_id)
                     .values_list("id", flat=True).first())
        return success(data={
            **_document_row(doc, hw_id),
            "file_data": blob_storage.signed_url(doc.file.name, download_name=dl_name if want_download else None),
            "download": want_download,
            "doc_types": _choosable_types(),
            "events": _events(doc),
        })

    def patch(self, request, doc_id):
        from apps.atomwalk.documents import services
        doc, err = _own_document(request, doc_id)
        if err:
            return err
        if doc.source_hospital_id or doc.uploaded_by == "staff":
            return error("This report was issued by your hospital, so it can't be changed here.")
        action = request.data.get("action")
        try:
            if action == "retry":
                services.retry_document(doc)
                services.start_processing([doc.id], services.INSTANT_QUEUE)
            else:
                doc_type = request.data.get("doc_type")
                if doc_type not in _choosable_types():
                    return error("Choose one of the available types.")
                services.correct_document(doc, doc_type)
        except doc_rules.DocumentLocked as exc:
            return error(str(exc), errors={"code": "locked"}, status=409)
        except ValueError as exc:
            return error(str(exc))
        return success(data=_document_row(type(doc).objects.using("default").get(pk=doc.pk)))
class PortalDocumentZipView(APIView):
    """
    POST /api/v1/portal/documents/zip/   body: { ids: [<doc_id>, ...] }  (max 100)
    Bundles the caller's selected documents into one ZIP.
    """
    permission_classes = [IsPatient]
    _MAX_IDS = 100

    def post(self, request, *args, **kwargs):
        import io
        import zipfile
        from django.http import HttpResponse
        from apps.atomwalk.documents.models import MedicalDocument

        target_awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return error("Select at least one document.")
        if len(ids) > self._MAX_IDS:
            return error(f"Select at most {self._MAX_IDS} documents.")
        docs = (MedicalDocument.objects.using("default")
                .filter(pk__in=ids, patient__awpid=target_awpid))

        buf, used = io.BytesIO(), set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for d in docs:
                try:
                    content = blob_storage.get_bytes(d.file.name)
                except Exception:
                    logger.warning("zip: could not read document %s", d.id, exc_info=True)
                    continue
                name = d.file_name or f"document-{d.id}.pdf"
                if name in used:
                    name = f"{d.id}-{name}"
                used.add(name)
                zf.writestr(name, content)
        if not used:
            return error("Could not read the selected documents.", status=502)

        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="my-reports-{timezone.now().date()}.zip"'
        return resp
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
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.hospital_master.lab.models import LabRequest

        target_awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        results = []

        for hospital in Hospital.objects.using("default").filter(is_active=True):
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                # select_related("report") pulls the LabReport in the SAME
                # .using(db) query. Accessing r.report lazily instead (a bare
                # reverse-OneToOne lookup) would go through the hospital DB
                # router, which resolves the db from thread-local state set
                # by JWTHospitalMiddleware — never populated on this patient-
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
                            "items": list(rep.items.values(
                                "parameter_name", "result_value", "unit", "reference_range", "is_abnormal",
                            )),
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
                        from apps.atomwalk.documents.models import MedicalDocument
                        doc = (MedicalDocument.objects.using("default")
                               .filter(patient__awpid=target_awpid, source_type=MedicalDocument.Source.LAB_REQUEST, source_id=f"{db}:{r.id}")
                               .order_by("-created_at").first())
                        if doc:
                            attached_doc = {"id": doc.id, "title": doc.file_name, "created_at": doc.created_at}

                    results.append({
                        "id": r.id,
                        "hospital_db": db,
                        "hospital": hospital.name,
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
                        "source_ref": f"lab_request:{db}:{r.id}",
                    })
            except Exception as e:
                logger.warning("lab-orders: skipped %s (%s)", db, e)

        results.sort(key=lambda r: r["ordered_at"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return Response({"results": page_items, "pagination": meta})
class PortalLabOrderChoiceView(APIView):
    """
    POST /api/v1/portal/lab-orders/choice/
    Body: { hospital_db, request_id, patient_choice, payment_preference? }
    Patient picks in-house vs outside (and, if in-house, how they'll pay).
    Ownership is verified via awpid before anything is written — hospital_db
    and request_id alone aren't enough to prove this is the caller's order.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from apps.hospital_master.lab.models import LabRequest

        d = request.data
        hospital_db  = d.get("hospital_db")
        request_id = d.get("request_id")
        choice     = d.get("patient_choice")
        payment_preference = d.get("payment_preference", "")

        if not hospital_db or not request_id:
            return error("hospital_db and request_id are required.")
        if choice not in ("in_house", "outside"):
            return error("patient_choice must be in_house or outside.", errors={"patient_choice": "Invalid."})
        if payment_preference and payment_preference not in ("pay_online", "pay_at_lab"):
            return error("Invalid payment_preference.", errors={"payment_preference": "Invalid."})

        if not Hospital.objects.using("default").filter(db_name=hospital_db, is_active=True).exists():
            return error("Unknown hospital.")
        ensure_hospital_db(hospital_db)

        try:
            lab_req = LabRequest.objects.using(hospital_db).select_related("patient").get(pk=request_id)
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
            from apps.atomwalk.patients.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=order_awpid,
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
        lab_req.save(using=hospital_db, update_fields=[
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
        from apps.hospital_master.opd.models import Appointment, OPDEncounter, Prescription
        from apps.hospital_master.staff.models import StaffUser
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.atomwalk.documents.models import MedicalDocument
        import uuid as _uuid

        target_awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        results = []

        for hospital in Hospital.objects.using("default").filter(is_active=True):
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                # Resolved via Appointment -> OPDEncounter -> Prescription
                # (same relational chain PortalMyRecordsView already uses
                # successfully) rather than trusting Prescription.patient_id
                # directly — that field is set independently at encounter-
                # creation time from whatever the doctor's client sent, so
                # it isn't guaranteed to match the Appointment's patient_id
                # the way this chain is. Going through the same proven path
                # both endpoints use guarantees they agree on which
                # prescriptions belong to this patient.
                appt_ids = Appointment.objects.using(db).filter(patient_id=patient.uuid).values_list("id", flat=True)
                enc_ids = OPDEncounter.objects.using(db).filter(appointment_id__in=list(appt_ids)).values_list("id", flat=True)
                # NOT prefetch_related("items") — under this app's custom
                # multi-db router, Django's prefetch machinery issues the
                # related-object query against the "default" atomwalk DB
                # instead of `db`, which throws "relation
                # opd_prescription_item does not exist" (that table only
                # exists on hospital DBs). That exception was being swallowed
                # by the `except Exception` below, silently dropping this
                # hospital's prescriptions from the response instead of
                # raising. Access rx.items explicitly with .using(db)
                # instead, same as PortalMyRecordsView/
                # PortalPrescriptionReceiptPDFView already do.
                rxs = (Prescription.objects.using(db)
                       .filter(encounter_id__in=list(enc_ids))
                       .order_by("-created_at")[:50])

                # The doctor's handwritten prescription, archived as a PDF on
                # sign (apps.hospital_master.opd.views._store_handwriting_pdfs). Keyed by
                # encounter, doc_type "prescription" (patient-visible).
                hw_by_enc = {
                    d.source_id: d.id
                    for d in MedicalDocument.objects.using("default").filter(
                        patient__awpid=target_awpid, document_type="prescription",
                        source_type=MedicalDocument.Source.ENCOUNTER_HANDWRITTEN_RX,
                    )
                }

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
                        "hospital_db": db,
                        "hospital": hospital.name,
                        "rx_number": rx.rx_number,
                        "doctor_name": doctor_name,
                        "status": rx.status,
                        "patient_choice": rx.patient_choice,
                        "payment_preference": rx.payment_preference,
                        "payment_status": rx.payment_status,
                        "created_at": rx.created_at,
                        # id of the archived handwritten-Rx PDF, if the doctor
                        # used the consult pad — fetch via portal/documents/<id>/
                        "handwritten_document_id": hw_by_enc.get(str(rx.encounter_id)),
                        "items": [{
                            "drug_name": it.drug_name,
                            "dosage": it.dosage,
                            "frequency": it.frequency,
                            "quantity": it.quantity,
                        } for it in rx.items.using(db).all()],
                    })
            except Exception as e:
                logger.warning("prescriptions: skipped %s (%s)", db, e)

        results.sort(key=lambda r: r["created_at"], reverse=True)
        page_items, meta = paginate_list(request, results)
        return Response({"results": page_items, "pagination": meta})
class PortalPrescriptionChoiceView(APIView):
    """
    POST /api/v1/portal/prescriptions/choice/
    Body: { hospital_db, prescription_id, patient_choice, payment_preference? }
    Patient picks in-house vs outside (and, if in-house, how they'll pay) —
    identical shape and ownership logic to PortalLabOrderChoiceView,
    including family-member support from the start (the lab endpoint this
    was modelled on originally shipped without it and had to be patched in
    later — not repeating that here).
    """
    permission_classes = [IsPatient]

    def post(self, request):
        from apps.hospital_master.opd.models import Prescription
        from apps.hospital_master.patients.models import HospitalPatient

        d = request.data
        hospital_db        = d.get("hospital_db")
        prescription_id  = d.get("prescription_id")
        choice           = d.get("patient_choice")
        payment_preference = d.get("payment_preference", "")

        if not hospital_db or not prescription_id:
            return error("hospital_db and prescription_id are required.")
        if choice not in (Prescription.CHOICE_IN_HOUSE, Prescription.CHOICE_OUTSIDE):
            return error("patient_choice must be in_house or outside.", errors={"patient_choice": "Invalid."})
        if payment_preference and payment_preference not in (Prescription.PAY_ONLINE, Prescription.PAY_AT_PHARMACY):
            return error("Invalid payment_preference.", errors={"payment_preference": "Invalid."})

        if not Hospital.objects.using("default").filter(db_name=hospital_db, is_active=True).exists():
            return error("Unknown hospital.")
        ensure_hospital_db(hospital_db)

        try:
            rx = Prescription.objects.using(hospital_db).select_related("encounter").get(pk=prescription_id)
        except Prescription.DoesNotExist:
            return error("Prescription not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        # Ownership resolved via the encounter's appointment, same chain
        # PortalPrescriptionListView uses — not rx.patient_id directly,
        # which is set independently at encounter-creation time and isn't
        # guaranteed to agree with the appointment's patient_id.
        from apps.hospital_master.opd.models import Appointment
        try:
            appt = Appointment.objects.using(hospital_db).get(pk=rx.encounter.appointment_id)
            rx_patient = HospitalPatient.objects.using(hospital_db).get(uuid=appt.patient_id)
        except (Appointment.DoesNotExist, HospitalPatient.DoesNotExist, AttributeError):
            return error("Prescription not found.")
        rx_awpid = rx_patient.awpid
        if rx_awpid != acct.awpid:
            from apps.atomwalk.patients.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=rx_awpid,
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
        rx.save(using=hospital_db, update_fields=[
            "patient_choice", "payment_preference", "choice_made_by",
            "choice_made_at", "payment_status",
        ])
        return success(message="Choice saved.")
class PortalPrescriptionReceiptPDFView(APIView):
    """
    GET /api/v1/portal/prescriptions/<hospital_db>/<pk>/receipt/
    A real, printable PDF of a prescription — same base64-data-URI envelope
    as PortalInvoiceReceiptPDFView (see that view's docstring: patient auth
    is a JWT bearer header, so a plain <a href> to the API URL wouldn't
    carry it). Ownership check follows the exact same encounter -> appointment
    -> patient chain as PortalPrescriptionChoiceView above, for the same
    reason documented there (rx.patient_id isn't guaranteed to agree with
    the appointment's patient_id).
    """
    permission_classes = [IsPatient]

    def get(self, request, hospital_db, pk):
        import base64
        import uuid as _uuid
        from apps.hospital_master.opd.models import Appointment, Prescription
        from apps.hospital_master.staff.models import StaffUser
        from apps.hospital_master.facility.models import Branch
        from apps.hospital_master.opd.pdf import generate_prescription_pdf
        from apps.hospital_master.patients.models import HospitalPatient

        if not Hospital.objects.using("default").filter(db_name=hospital_db, is_active=True).exists():
            return error("Unknown hospital.")
        ensure_hospital_db(hospital_db)

        try:
            # NOT prefetch_related("items") — under this app's custom
            # multi-db router, Django's prefetch machinery issues the
            # related-object query against the "default" atomwalk DB
            # instead of hospital_db (confirmed: it 500s with "relation
            # opd_prescription_item does not exist", because that table
            # only exists on hospital DBs, not the atomwalk one). Every other
            # working call site in this file (PortalMyRecordsView,
            # PortalPrescriptionListView) sidesteps this the same way —
            # access rx.items explicitly with .using(hospital_db) below
            # instead of prefetching.
            rx = Prescription.objects.using(hospital_db).select_related("encounter").get(pk=pk)
        except Prescription.DoesNotExist:
            return not_found("Prescription not found.")

        try:
            appt = Appointment.objects.using(hospital_db).get(pk=rx.encounter.appointment_id)
            patient = HospitalPatient.objects.using(hospital_db).get(uuid=appt.patient_id)
        except (Appointment.DoesNotExist, HospitalPatient.DoesNotExist, AttributeError):
            return not_found("Prescription not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        if patient.awpid != acct.awpid:
            from apps.atomwalk.patients.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=patient.awpid,
            ).exists()
            if not is_family:
                return error("This prescription does not belong to you.")

        doctor_name = None
        try:
            raw = rx.doctor_user_id.int if isinstance(rx.doctor_user_id, _uuid.UUID) else rx.doctor_user_id
            doctor_name = StaffUser.objects.using(hospital_db).get(pk=raw).get_full_name()
        except Exception:
            logger.debug("PortalPrescriptionReceiptPDFView: doctor lookup failed for rx=%s", rx.id, exc_info=True)

        branch = Branch.objects.using(hospital_db).filter(pk=appt.branch_id).first() if appt.branch_id else None
        hospital = Hospital.objects.using("default").filter(db_name=hospital_db).first()
        hospital_name = hospital.name if hospital else "Hospital"

        pdf_bytes = generate_prescription_pdf(
            # .using(hospital_db) explicitly — see the comment on the rx fetch
            # above; the plain rx.items.all() form is what triggers the
            # cross-DB router bug.
            prescription=rx, items=list(rx.items.using(hospital_db).all()), doctor_name=doctor_name,
            patient=patient, branch=branch, hospital_name=hospital_name,
            visit_date=appt.scheduled_date,
        )
        data_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
        rx_label = rx.rx_number or str(rx.id)[:8]
        return success(data={
            "file_data": data_uri,
            "file_name": f"Prescription-{rx_label}.pdf",
            "mime_type": "application/pdf",
        })
class PortalLabReportFileView(APIView):
    """
    GET /api/v1/portal/lab-orders/<hospital_db>/<request_id>/report/
    Full content (file_data/mime_type) for an in-house lab report the patient
    has been notified is ready — the list endpoint only sends has_file so the
    payload stays light, same reasoning as PatientDocumentDetailView. Ownership
    is verified via awpid, same as the choice endpoint above.
    """
    permission_classes = [IsPatient]

    def get(self, request, hospital_db, request_id):
        from apps.hospital_master.lab.models import LabRequest, LabReport

        if not Hospital.objects.using("default").filter(db_name=hospital_db, is_active=True).exists():
            return error("Unknown hospital.")
        ensure_hospital_db(hospital_db)

        try:
            # select_related("report") — see the identical fix + comment on
            # PortalLabOrderListView above. A bare lazy `lab_req.report`
            # reverse lookup routes through the hospital DB router's
            # thread-local, which is never set on patient-portal requests,
            # so it silently misses even a delivered report.
            lab_req = LabRequest.objects.using(hospital_db).select_related("patient", "report").get(pk=request_id)
        except LabRequest.DoesNotExist:
            return not_found("Lab order not found.")

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        order_awpid = lab_req.patient.awpid
        if order_awpid != acct.awpid:
            from apps.atomwalk.patients.models import PatientRelationship
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=order_awpid,
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
            "file_data": blob_storage.signed_url(report.file_url),
            "file_name": report.file_name,
            "mime_type": report.mime_type,
            "result_summary": report.result_summary,
        })
# ── My Profile ──────────────────────────────────────────────────────────────

class PortalMobileChangeRequestOTPView(APIView):
    """
    POST /api/v1/portal/profile/mobile-change/request-otp/
    Authenticated — no body needed. Sends an OTP to the EMAIL address
    currently on file (not a caller-supplied one), so changing a mobile
    number requires proving control of the account first. Email-based for
    now — verifying via the old mobile requires a paid SMS gateway that
    isn't wired up yet (see core/sms.py); email is free to send and just as
    good a proof of account ownership. The follow-up
    PATCH /api/v1/portal/profile/ (mobile field) requires the resulting
    action_token, obtained via POST /api/v1/auth/otp/verify/
    (purpose="contact_change_patient", identifier=<account email>).
    """
    permission_classes = [IsPatient]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp"

    def post(self, request):
        from core.otp import create_otp, mask_identifier, OTPError
        from core.email import send_otp_email
        from apps.atomwalk.patients.models import OTPCode

        try:
            acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        except PatientAccount.DoesNotExist:
            return not_found("Account not found.")

        if not acct.email:
            return error("Add an email address to your profile first — we use it to verify mobile number changes.")

        email = acct.email.strip().lower()
        try:
            otp, code, channel = create_otp(
                OTPCode.PURPOSE_CONTACT_CHANGE_PATIENT, email,
                target_type="patient", target_id=acct.id,
            )
        except OTPError as exc:
            return error(str(exc))

        sent = send_otp_email(email, code, "mobile number change")
        if not sent:
            return error("Couldn't send the verification code right now. Please try again shortly.")

        data = {"masked_identifier": mask_identifier(email)}
        return success(data=data, message=f"Verification code sent to {mask_identifier(email)}.")
class PortalProfileView(APIView):
    """
    GET  /api/v1/portal/profile/  — the logged-in patient's own account details.
    PATCH /api/v1/portal/profile/ — update name / mobile / gender / DOB.
    Email and AWPID are identity keys tied to Patient records across
    every hospital this patient has consented at, so they're read-only here —
    changing them would break the cross-hospital identity match that HIE
    sharing relies on.

    Changing `mobile` to a NEW number requires `action_token` (from
    POST /api/v1/auth/otp/verify/, purpose="contact_change_patient") proving
    the caller verified a code sent to the email on file first — see
    PortalMobileChangeRequestOTPView above. Sending the same mobile back
    unchanged (or omitting it) needs no token.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.atomwalk.patients.models import Patient
        try:
            acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        except PatientAccount.DoesNotExist:
            return not_found("Account not found.")
        identity = Patient.objects.using("default").filter(awpid=acct.awpid).first()
        return success(data={
            "awpid":         acct.awpid,
            "full_name":     acct.full_name,
            "email":         acct.email,
            "mobile":        "",                       # stored only scrambled; the screen says "on file"
            "mobile_on_file": bool(acct.mobile_hash),
            "gender":        acct.gender,
            "date_of_birth": acct.date_of_birth,
            "created_at":    acct.created_at,
            "last_login":    acct.last_login,
            "blood_group":   identity.blood_group if identity else "",
            "photo":         blob_storage.signed_url(acct.photo),
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
            from apps.atomwalk.patients.models import Patient
            from core.utils.hashing import hash_mobile, normalize_mobile
            from apps.atomwalk.patients.models import mobile_hash_of

            mobile = (d.get("mobile") or "").strip()
            if mobile and not re.match(r"^\d{10}$", mobile):
                return error("Enter a valid 10-digit mobile number.", errors={"mobile": "Invalid format."})

            # Only an actual CHANGE needs re-verification — re-sending the
            # same number the frontend already has loaded shouldn't force
            # the patient through an OTP for a no-op.
            mobile_changed = bool(mobile) and mobile_hash_of(mobile) != acct.mobile_hash
            if mobile_changed:
                from core.otp import decode_action_token, OTPError
                from apps.atomwalk.patients.models import OTPCode
                token = d.get("action_token") or ""
                try:
                    payload = decode_action_token(token, OTPCode.PURPOSE_CONTACT_CHANGE_PATIENT)
                except OTPError as exc:
                    return error(str(exc), errors={"mobile": "Verification required."})
                if payload.get("target_id") != acct.id or payload.get("identifier") != (acct.email or "").lower():
                    return error("Verification does not match this account.", errors={"mobile": "Verification required."})

            if mobile and PatientAccount.objects.using("default").with_mobile(mobile).exclude(pk=acct.id).exists():
                return error("Another account already uses this mobile number.", errors={"mobile": "Already in use."})

            # Keep the network-wide Patient.mobile_hash in sync — it's
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
                if Patient.objects.using("default").filter(mobile_hash=mobile_hash).exclude(awpid=acct.awpid).exists():
                    return error("Another patient record already uses this mobile number.", errors={"mobile": "Already in use."})
                Patient.objects.using("default").filter(awpid=acct.awpid).update(mobile_hash=mobile_hash)

            if mobile_changed:
                logger.info("Patient mobile number changed via OTP re-verification: "
                            "account_id=%s awpid=%s", acct.id, acct.awpid)
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
        old_photo_key = acct.photo
        if "photo" in d:
            photo = d.get("photo") or ""
            if not photo:
                acct.photo = ""
            else:
                try:
                    mime_type = validate_data_uri(photo)
                except FileValidationError as exc:
                    return error(str(exc), errors={"photo": str(exc)})
                identity = blob_storage.identity_slug(name=acct.full_name, identifier=acct.awpid)
                try:
                    acct.photo = blob_storage.upload_data_uri(
                        photo, prefix="patient-photos", mime_type=mime_type,
                        category="patient-photo", identity=identity,
                    )
                except blob_storage.StorageError as exc:
                    return error(str(exc), errors={"photo": str(exc)})
            fields.append("photo")

        if not fields:
            return error("No editable fields provided.")

        acct.save(using="default", update_fields=fields)
        if "photo" in d and old_photo_key and old_photo_key != acct.photo:
            blob_storage.delete(old_photo_key)
        return success(message="Profile updated.", data={
            "awpid":         acct.awpid,
            "full_name":     acct.full_name,
            "email":         acct.email,
            "mobile":        "",
            "mobile_on_file": bool(acct.mobile_hash or d.get("mobile")),
            "gender":        acct.gender,
            "date_of_birth": acct.date_of_birth,
            "emergency_contact_name":     acct.emergency_contact_name,
            "emergency_contact_phone":    acct.emergency_contact_phone,
            "emergency_contact_relation": acct.emergency_contact_relation,
            "photo":         blob_storage.signed_url(acct.photo),
        })
class PortalHealthSummaryView(APIView):
    """
    GET /api/v1/portal/health-summary/?patient_awpid=
    Feeds the "Health Summary" and "Linked Hospitals" cards on My Profile —
    everything here is real, already-recorded data (no invented "primary
    doctor" or "chronic conditions" fields, since nothing in this system
    tracks either of those concepts yet):
      - blood_group        from Patient (set at registration)
      - active_allergies    from SharedAllergy (same HIE table doctors see)
      - active_diagnoses    from ClinicalEvent (diagnoses) where clinical_status="active"
      - last_visit          most recent PatientBooking for this patient
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
        from apps.atomwalk.patients.models import PatientBooking
        from apps.atomwalk.documents.models import SharedAllergy, ClinicalEvent
        from apps.atomwalk.patients.models import PatientRelationship

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)

        target_awpid = (request.query_params.get("patient_awpid") or "").strip() or acct.awpid
        if target_awpid != acct.awpid:
            is_family = PatientRelationship.objects.using("default").filter(
                guardian__awpid=acct.awpid, dependent__awpid=target_awpid,
            ).exists()
            if not is_family:
                return error("That patient isn't linked to your account.", status=403)

        identity = Patient.objects.using("default").filter(awpid=target_awpid).first()

        allergies = list(
            SharedAllergy.objects.using("default")
            .filter(patient__awpid=target_awpid, is_active=True)
            .values("substance", "reaction", "severity")
        )
        diagnoses = list(
            ClinicalEvent.objects.using("default")
            .filter(patient__awpid=target_awpid, event_type="DIAGNOSIS", clinical_status="active", is_rejected=False)
            .order_by("-event_date")
            .values(description=F("condition_text"), onset_date=F("event_date"))[:5]
        )

        bookings = list(
            PatientBooking.objects.using("default")
            .filter(patient__awpid=target_awpid)
            .select_related("hospital")
            .order_by("-scheduled_date")
        )

        last_visit = None
        hospitals = {}
        for b in bookings:
            if last_visit is None or b.scheduled_date > last_visit:
                last_visit = b.scheduled_date
            existing = hospitals.get(b.hospital.name)
            if not existing or b.scheduled_date > existing["last_visit"]:
                hospitals[b.hospital.name] = {
                    "hospital_name": b.hospital.name,
                    "hospital_id": b.hospital_id,
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
    hospital DB, so an unbounded merge would be needlessly expensive for what
    is ultimately a "recent activity" widget. The hospital queryset is fetched
    once and reused for both fan-outs rather than querying it twice.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.hospital_master.opd.models import Appointment, OPDEncounter
        from apps.hospital_master.lab.models import LabRequest
        from apps.atomwalk.documents.services import history_readings
        from apps.atomwalk.documents.models import MedicalDocument
        from apps.atomwalk.documents.services import build_roadmap

        target_awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err

        try:
            limit = int(request.query_params.get("limit") or _TIMELINE_DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _TIMELINE_DEFAULT_LIMIT
        limit = max(1, min(limit, 100))

        entries = []

        hospitals = list(Hospital.objects.using("default").filter(is_active=True))

        # ── Visits ──────────────────────────────────────────────────────
        for hospital in hospitals:
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
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
                        "title":     f"Visit — {hospital.name}",
                        "subtitle":  (f"Dr. {appt.doctor_name}" + (f" · {subtitle_bits[0]}" if subtitle_bits else "")) if appt.doctor_name else (subtitle_bits[0] if subtitle_bits else None),
                        "detail":    None,  # no dedicated single-visit viewer on the portal yet
                    })
            except Exception as e:
                logger.warning("timeline: skipped visits for %s (%s)", db, e)

        # ── Vaccinations (only administered ones — pending/due aren't "history") ──
        try:
            roadmap = build_roadmap(target_awpid, dob, rules_for("vaccination"))
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
            for v in history_readings(target_awpid, limit):
                if not (v["height_cm"] or v["weight_kg"]):
                    continue
                bits = []
                if v["height_cm"]:
                    bits.append(f"Height {v['height_cm']} cm")
                if v["weight_kg"]:
                    bits.append(f"Weight {v['weight_kg']} kg")
                entries.append({
                    "date":      str(v["recorded_at"].date()),
                    "type":      "growth",
                    "icon_hint": "trending-up",
                    "title":     "Growth check",
                    "subtitle":  " · ".join(bits) if bits else None,
                    "detail":    None,
                })
        except Exception as e:
            logger.warning("timeline: skipped growth (%s)", e)

        # ── Lab results ─────────────────────────────────────────────────
        for hospital in hospitals:
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
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
                            "subtitle":  f"Result delivered — {hospital.name}",
                            "detail":    (
                                {"hospital_db": db, "request_id": r.id, "has_file": bool(rep.file_url)}
                                if rep.file_url else None
                            ),
                        })
                    else:
                        entries.append({
                            "date":      str(r.ordered_at.date() if hasattr(r.ordered_at, "date") else r.ordered_at),
                            "type":      "lab",
                            "icon_hint": "flask",
                            "title":     r.test.name,
                            "subtitle":  f"Ordered — {hospital.name} ({r.status})",
                            "detail":    None,
                        })
            except Exception as e:
                logger.warning("timeline: skipped lab-results for %s (%s)", db, e)

        # ── Documents ───────────────────────────────────────────────────
        try:
            docs = (MedicalDocument.objects.using("default")
                    .filter(patient__awpid=target_awpid)
                    .order_by("-created_at")[:limit])
            for d in docs:
                entries.append({
                    "date":      str(d.created_at.date() if hasattr(d.created_at, "date") else d.created_at),
                    "type":      "document",
                    "icon_hint": "file",
                    "title":     d.file_name,
                    "subtitle":  d.document_type.replace("_", " ").title() if d.document_type else None,
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
        hospital DB's NotificationLog (see apps.hospital_master.notifications.services, run by
        `python manage.py generate_reminders` on a schedule). Fanned out
        across every active hospital the same way PortalMyRecordsView does,
        since a patient's hospitals aren't known in advance.
      - Vaccination-due reminders — NOT stored anywhere. Computed live from
        apps.atomwalk.documents.services.build_roadmap() every time this is
        called, because due-ness is just today's date vs. the patient's age
        against the schedule — persisting it would just be a second copy
        that could silently go stale (e.g. after a dose gets logged).

    No real SMS/email/push is sent for any of these — see the module
    docstring on apps/notifications/services.py for why that's out of scope
    without a provider account. This is the in-app fallback.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        from apps.hospital_master.patients.models import HospitalPatient
        from apps.hospital_master.notifications.models import NotificationLog
        from apps.atomwalk.documents.services import build_roadmap

        target_awpid, dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err

        results = []

        # ── Appointment / follow-up reminders — fan out across hospitals ──
        for hospital in Hospital.objects.using("default").filter(is_active=True):
            db = hospital.db_name
            try:
                ensure_hospital_db(db)
                patient = HospitalPatient.objects.using(db).filter(awpid=target_awpid).first()
                if not patient:
                    continue
                logs = (NotificationLog.objects.using(db)
                        .filter(patient=patient, channel="in_app")
                        .order_by("-created_at")[:50])
                for log in logs:
                    results.append({
                        "id":         f"{db}:{log.id}",
                        "type":       "appointment_reminder" if log.reference.startswith("appt_reminder:") else "followup_reminder",
                        "hospital":   hospital.name,
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
            roadmap = build_roadmap(target_awpid, dob, rules_for("vaccination"))
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
    POST /api/v1/portal/notifications/<hospital_db>/<id>/read/
    Only applies to real NotificationLog rows (appointment/follow-up) — the
    "id" composite from the list above is "<hospital_db>:<log_id>", split back
    apart by the frontend before calling this. Vaccination-due entries have
    no backing row (computed live) so there's nothing to mark read.
    """
    permission_classes = [IsPatient]

    def post(self, request, hospital_db, pk):
        from apps.hospital_master.notifications.models import NotificationLog
        from apps.atomwalk.patients.models import PatientRelationship

        if not Hospital.objects.using("default").filter(db_name=hospital_db, is_active=True).exists():
            return error("Unknown hospital.")
        ensure_hospital_db(hospital_db)

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        try:
            log = NotificationLog.objects.using(hospital_db).select_related("patient").get(pk=pk)
        except NotificationLog.DoesNotExist:
            return not_found("Notification not found.")
        # PortalNotificationsView (the list this "id" comes from) already
        # resolves a family member's own notifications via
        # resolve_target_awpid_and_dob — mirror the same ownership rule
        # here instead of the stricter account-only check this used to have.
        owner_awpid = log.patient.awpid if log.patient else None
        is_owner = owner_awpid == acct.awpid
        is_family = bool(owner_awpid) and not is_owner and PatientRelationship.objects.using("default").filter(
            guardian__awpid=acct.awpid, dependent__awpid=owner_awpid,
        ).exists()
        if not (is_owner or is_family):
            return error("This notification does not belong to you.", status=403)

        if not log.read_at:
            log.read_at = timezone.now()
            log.save(using=hospital_db, update_fields=["read_at"])
        return success(data={"read": True})
# PortalForgotPasswordView (the old mobile/AWPID + date-of-birth
# verification) has been replaced by OTP verification — see
# apps/auth_app/otp_views.py (OTPRequestView/OTPVerifyView with
# purpose="password_reset_patient", then PatientForgotPasswordResetView to
# consume the resulting action_token). This endpoint was also never
# actually reachable from the frontend (API_ENDPOINTS.PORTAL.FORGOT_PASSWORD
# was referenced by ForgotPasswordPage.jsx but was never defined in
# api.config.js) — the OTP flow replaces it end to end, frontend included.


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
# ── Emergency QR ─────────────────────────────────────────────────────────────
# See core/emergency_access.py for the token mechanics and the security
# reasoning (why the token payload carries only an awpid, never PHI). This
# generation endpoint is patient-authenticated (IsPatient); the endpoint
# that actually serves the summary a scanned QR opens is deliberately
# public/unauthenticated — see apps/hospital_patients/emergency_views.py, mounted
# at /api/v1/emergency/ (NOT under /api/v1/portal/) specifically so it
# reads as the one intentionally-public endpoint in this codebase rather
# than being buried inside a URL prefix that otherwise implies patient auth.
#
# Shown to the patient verbatim in the pre-generation consent prompt, and
# kept in sync with what apps.atomwalk.patients.views.EmergencySummaryView
# actually returns. Deliberately broader than HIE_SHARE_CATEGORIES above —
# this is a full history dump for acute treatment, not the trimmed roadmap
# a passively-consenting hospital sees.
EMERGENCY_SHARE_CATEGORIES = [
    "Diagnoses and clinical notes",
    "Allergies on record",
    "Recent vitals (BP, pulse, temperature, etc.)",
    "Prescriptions, including current medication",
    "Lab test results and reports (viewable, not just listed)",
    "Uploaded documents — old reports, scans, discharge summaries",
    "Vaccination records and certificates",
    "Birth history and any flagged developmental-milestone concerns (for a child)",
    "Your emergency contact's name and phone number",
]
class PortalEmergencyTokenView(APIView):
    """
    POST /api/v1/portal/emergency/token/
    Body: { patient_awpid?, consent_confirmed }  — patient_awpid defaults to
    self (or a linked family member); consent_confirmed must be true or the
    request is rejected with 428 (mirrors PortalBookView's first-booking
    consent gate below — same "explain what's being shared, require an
    explicit yes" shape, reused rather than reinvented).

    Every generation mints a brand-new token and is a fresh disclosure
    decision, so consent is required on every call, not just the first —
    unlike the standing hie_consent_given flag, there is no "already
    consented, don't ask again" state here by design: this shares MORE than
    the passive HIE roadmap (full history + viewable files), and each QR is
    a one-off act the patient chooses to perform for a specific doctor in
    front of them right now.

    Mints a fresh ~20-minute emergency-access token for the target patient
    and returns everything the frontend needs to render the QR screen: the
    raw token (for a "copy link" fallback), the absolute URL a scan should
    open, an expiry timestamp so the UI can show a countdown, and a ready-
    to-display QR code image (server-rendered, same `qrcode` library
    already used for the invoice-receipt QR in apps/billing/pdf.py — no new
    frontend dependency needed).
    """
    permission_classes = [IsPatient]

    def post(self, request):
        target_awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err

        if not request.data.get("consent_confirmed"):
            target_name = ""
            if target_awpid != PatientAccount.objects.using("default").filter(
                pk=request.user.id).values_list("awpid", flat=True).first():
                identity = Patient.objects.using("default").filter(awpid=target_awpid).first()
                target_name = identity.full_name if identity else ""
            return Response({
                "consent_required": True,
                "share_categories": EMERGENCY_SHARE_CATEGORIES,
                "ttl_minutes": 20,
                "message": (
                    f"Generating this code will share {target_name or 'your'} full medical "
                    "history with whoever scans it, for the next 20 minutes. Confirm you want "
                    "to proceed."
                ),
            }, status=428)

        from core.emergency_access import make_emergency_token, EMERGENCY_TOKEN_TTL_MINUTES
        from apps.atomwalk.patients.models import EmergencyAccessLog

        token = make_emergency_token(target_awpid)
        view_url = f"{settings.FRONTEND_URL.rstrip('/')}/emergency/{token}"
        expires_at = timezone.now() + timedelta(minutes=EMERGENCY_TOKEN_TTL_MINUTES)

        qr_image = _render_qr_data_uri(view_url)

        try:
            xff = request.META.get("HTTP_X_FORWARDED_FOR")
            EmergencyAccessLog.objects.using("default").create(
                patient=Patient.objects.using("default").filter(awpid=target_awpid).first(), event=EmergencyAccessLog.EVENT_GENERATED,
                generated_by_id=request.user.id, consent_confirmed=True,
                ip_address=(xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")),
            )
        except Exception:
            logger.exception("EmergencyAccessLog write failed (generated) for awpid=%s", target_awpid)

        return success(data={
            "token": token,
            "view_url": view_url,
            "qr_image": qr_image,
            "expires_at": expires_at,
            "ttl_minutes": EMERGENCY_TOKEN_TTL_MINUTES,
        })
def _render_qr_data_uri(text: str) -> str:
    """
    Renders `text` as a QR code PNG and returns it as a base64 data URI,
    ready to drop straight into an <img src>. Mirrors _generate_qr_image()
    in apps/billing/pdf.py (same qrcode library, same box_size/border) —
    kept separate rather than imported from there since that helper returns
    a PIL Image for embedding in a ReportLab PDF, not a web-ready data URI.
    """
    import base64
    import io
    import qrcode

    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


logger = logging.getLogger(__name__)
def _resolve_emergency_contact(awpid):
    """
    Best-effort "who do we call" for this patient:
      1. Their own portal account's emergency contact fields, if set.
      2. Failing that (common for a dependent whose guardian never filled
         those fields in on the child's behalf, or a dependent with no
         portal account of their own at all), fall back to the guardian
         account that registered them — the guardian IS the practical
         emergency contact for a dependent, even with no explicit fields set.
    Returns None if neither resolves to anything (self-registered adult who
    never filled in an emergency contact, no guardian on file).
    """
    account = PatientAccount.objects.using("default").filter(awpid=awpid).first()
    if account and (account.emergency_contact_name or account.emergency_contact_phone):
        return {
            "name": account.emergency_contact_name,
            "phone": account.emergency_contact_phone,
            "relation": account.emergency_contact_relation or "Emergency contact",
        }

    rel = (
        PatientRelationship.objects.using("default").filter(dependent__awpid=awpid, is_primary=True).first()
        or PatientRelationship.objects.using("default").filter(dependent__awpid=awpid).first()
    )
    if rel:
        guardian = PatientAccount.objects.using("default").filter(awpid=rel.guardian_awpid).first()
        if guardian:
            return {
                "name": guardian.full_name,
                "phone": guardian.emergency_contact_phone or "",    # the guardian's own number is stored only scrambled
                "relation": "Parent/Guardian",
            }
    return None
def _birth_history(awpid):
    """
    A child's birth history, if any hospital has captured it — written
    through from BirthHistoryView (see apps.atomwalk.documents.views) into
    atomwalk.BirthHistory. Returns None (not an empty dict) when
    nothing's on file, so the frontend can tell "no birth history" apart
    from "not applicable" the same way it already does for emergency_contact.
    """
    from apps.atomwalk.documents.models import BirthHistory
    bh = BirthHistory.objects.using("default").filter(patient__awpid=awpid).first()
    if not bh:
        return None
    return {
        "gestational_age_weeks": bh.gestational_age_weeks,
        "birth_weight_kg": bh.birth_weight_kg,
        "delivery_mode": bh.delivery_mode,
        "multiple_birth": bh.multiple_birth,
        "nicu_admission": bh.nicu_admission,
        "nicu_days": bh.nicu_days,
        "birth_complications": bh.birth_complications,
        "congenital_conditions": bh.congenital_conditions,
        "apgar_score_1min": bh.apgar_score_1min,
        "apgar_score_5min": bh.apgar_score_5min,
    }
def _milestone_concerns(awpid):
    """
    Developmental-milestone records flagged "concern" by a doctor/nurse —
    the only milestone information an ER doctor treating an unfamiliar
    child actually needs in an emergency (a full achieved/not-yet roadmap is
    a well-child-visit concern, not an acute-care one; see
    apps.atomwalk.documents.services for that fuller view, used by the
    doctor's own consultation screen and the parent's portal). Sourced
    straight from MilestoneRecord — no schedule merge needed here,
    just "what has a clinician actually flagged."
    """
    from apps.atomwalk.documents.models import MilestoneRecord
    records = (
        MilestoneRecord.objects.using("default")
        .filter(patient__awpid=awpid, status=MilestoneRecord.STATUS_CONCERN)
        .order_by("-assessed_date")[:20]
    )
    return [{
        "domain": r.domain,
        "milestone": r.milestone,
        "assessed_date": r.assessed_date,
        "notes": r.notes,
        "recorded_by_name": r.recorded_by_name,
    } for r in records]
def _vaccination_history(awpid):
    """
    Every vaccination record on file, clinic-administered or self-reported —
    including ones still pending review, clearly labeled, so the scanning
    doctor sees the full picture rather than a silently trimmed one. Mirrors
    the file-access pattern below: certificate images are resolved to a
    signed URL here, not returned as raw base64.
    """
    records = (
        ImmunizationRecord.objects.using("default")
        .filter(patient__awpid=awpid)
        .exclude(verification_status=ImmunizationRecord.STATUS_DECLINED)
        .order_by("-administered_date", "-created_at")[:50]
    )
    out = []
    for v in records:
        out.append({
            "vaccine_name": v.vaccine_name,
            "administered_date": v.administered_date,
            "dose_number": v.dose_number,
            "source": v.source,
            "verification_status": v.verification_status,
            "certificate_url": blob_storage.signed_url(v.file_data),
        })
    return out
class EmergencySummaryView(APIView):
    """
    GET /api/v1/emergency/<token>/

    No auth. Decodes the short-lived token, resolves the awpid it grants
    access to, and returns the patient's full shared clinical history plus
    an emergency contact. Any expired/invalid/malformed token returns a
    plain 400 with a patient-safe message — never a stack trace, since this
    endpoint is reachable by anyone with a camera.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "emergency"

    def get(self, request, token):
        try:
            awpid = decode_emergency_token(token)
        except EmergencyTokenError as exc:
            return error(message=str(exc), status=400)

        identity = Patient.objects.using("default").filter(awpid=awpid).first()
        if not identity:
            # Token was validly signed but the identity it points to is gone
            # — shouldn't happen outside of manual DB tampering, but fail
            # safe rather than 500.
            return error(message="This emergency code is no longer valid.", status=404)

        from apps.hospital_master.patients.services import PatientService
        history = PatientService.get_shared_history(awpid=awpid)

        # get_shared_history() keeps lab results/documents lightweight (an id
        # + metadata, no file content) so the same helper stays cheap for
        # PatientHistoryView's list view. This endpoint has nowhere further
        # for a doctor to click through to (no login to fetch the detail
        # endpoints with), so resolve every file to a signed URL right here.
        lab_result_ids = [r["id"] for r in history["lab_results"] if r.get("has_file")]
        lab_files = {
            r.id: blob_storage.signed_url(r.document.file.name)
            for r in LabResult.objects.using("default").filter(id__in=lab_result_ids, document__isnull=False).select_related("document")
        }
        for r in history["lab_results"]:
            r["file_url"] = lab_files.get(r["id"], "")

        doc_ids = [d["id"] for d in history["documents"]]
        doc_files = {
            d.id: blob_storage.signed_url(d.file.name)
            for d in MedicalDocument.objects.using("default").filter(id__in=doc_ids)
        }
        for d in history["documents"]:
            d["file_url"] = doc_files.get(d["id"], "")

        contact = _resolve_emergency_contact(awpid)
        vaccinations = _vaccination_history(awpid)
        birth_history = _birth_history(awpid)
        milestone_concerns = _milestone_concerns(awpid)

        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        ip_address = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
        try:
            EmergencyAccessLog.objects.using("default").create(
                patient=identity, event=EmergencyAccessLog.EVENT_VIEWED, ip_address=ip_address,
            )
        except Exception:
            logger.exception("EmergencyAccessLog write failed (viewed) for awpid=%s", awpid)

        return success(data={
            "full_name": identity.full_name,
            "age_years": (_age_years_months(identity.date_of_birth) or (None,))[0],
            "age_months": (_age_years_months(identity.date_of_birth) or (None, None))[1],
            "date_of_birth": identity.date_of_birth,
            "gender": identity.gender,
            "blood_group": identity.blood_group,
            "allergies": history["allergies"],
            "diagnoses": history["diagnoses"],
            "vitals": history["vitals"],
            "prescriptions": history["prescriptions"],
            "lab_results": history["lab_results"],
            "documents": history["documents"],
            "vaccinations": vaccinations,
            "birth_history": birth_history,
            "milestone_concerns": milestone_concerns,
            "emergency_contact": contact,
        })


logger = logging.getLogger(__name__)
# ─────────────────────────────────────────────────────────────── helpers

def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
# Pairing codes avoid 0/O/1/I so they read cleanly off a screen and back into
# a phone.
_PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
def _make_pairing(n=6):
    return "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(n))
def _device_token(request):
    return request.META.get("HTTP_X_SHARE_DEVICE", "").strip()
def _device_guard(grant, request):
    """
    Once a laptop has claimed this session, every public read must come from
    that same browser (it holds the device token from the claim response).
    Returns an error Response to bail with, or None to proceed. A leaked link
    or a photographed QR carries no device token, so it reads nothing.
    """
    if grant.opened_at and not grant.device_matches(_device_token(request)):
        from django.conf import settings
        host = settings.FRONTEND_URL.rstrip("/").split("://", 1)[-1]
        return error(
            f"Open this from the code the patient gave you at "
            f"{host}/share — this link is tied to the computer "
            f"that started the session.",
            errors={"reason": "device_mismatch"}, status=403,
        )
    return None
def _get_grant(token):
    """
    Fetch a RecordsShareRequest by its token, or — when the patient typed the
    6-digit pairing code into the app instead of scanning — by that code
    (newest still-pending one wins; codes are only unique among live requests).
    Lapses an expired grant before returning it.
    """
    grant = RecordsShareRequest.objects.using("default").filter(token=token).first()
    if not grant and token and token.isdigit() and len(token) == 6:
        grant = (
            RecordsShareRequest.objects.using("default")
            .filter(code=token, status=RecordsShareRequest.STATUS_PENDING)
            .order_by("-created_at")
            .first()
        )
    if grant:
        grant.lapse_if_due()
    return grant
def _audit(awpid, event, ip=None):
    try:
        EmergencyAccessLog.objects.using("default").create(
            patient=Patient.objects.using("default").filter(awpid=awpid).first(), event=event, ip_address=ip,
        )
    except Exception:
        logger.exception("EmergencyAccessLog write failed (%s) for awpid=%s", event, awpid)
def _self_awpid(request):
    acct = PatientAccount.objects.using("default").filter(pk=request.user.id).first()
    return acct.awpid if acct else None
def _patient_name(awpid):
    """Identity is the source of truth, but a self-registered patient may only
    have a PatientAccount — fall back to it before giving up."""
    identity = Patient.objects.using("default").filter(awpid=awpid).first()
    if identity and identity.full_name:
        return identity.full_name, identity
    acct = PatientAccount.objects.using("default").filter(awpid=awpid).first()
    return (acct.full_name if acct else ""), identity
# The navigable Rx & Reports vault — same row shape PortalDocumentListCreateView
# returns, so the frontend list/detail components are reused unchanged. The
# consult-pad handwritten prescription is folded into its typeset sibling as
# `handwritten_doc_id` rather than showing as its own row.
def _vault_documents(awpid, limit=200):
    Source = MedicalDocument.Source
    hw_rows = list(
        MedicalDocument.objects.using("default")
        .filter(patient__awpid=awpid, source_type=Source.ENCOUNTER_HANDWRITTEN_RX)
        .values_list("id", "source_id")
    )
    base_ids = set(
        MedicalDocument.objects.using("default")
        .filter(patient__awpid=awpid, source_type=Source.ENCOUNTER)
        .values_list("source_id", flat=True)
    )
    hw_by_base, linked_hw_ids = {}, []
    for hid, encounter_id in hw_rows:
        if encounter_id in base_ids:
            hw_by_base[encounter_id] = hid
            linked_hw_ids.append(hid)

    rows = (
        MedicalDocument.objects.using("default")
        .filter(patient__awpid=awpid)
        .exclude(id__in=linked_hw_ids)
        .exclude(awaiting_review_q())          # an upload the patient has not confirmed yet is not theirs to share
        .filter(status="completed")
        .order_by("-created_at")[:limit]
    )
    return [{
        "id":                d.id,
        "title":             d.file_name,
        "doc_type":          d.document_type,
        "file_name":         d.file_name,
        "mime_type":         d.mime_type,
        "uploaded_by":       d.uploaded_by,
        "document_date":     d.document_date,
        "public_document_id": d.document_ref,
        "created_at":        d.created_at,
        "source_hospital_id":  d.source_hospital_id,
        "handwritten_doc_id": hw_by_base.get(d.source_id) if d.source_type == Source.ENCOUNTER else None,
    } for d in rows]
# ─────────────────────────────────────────────────────────── privacy layer
#
# The patient's standing "what a doctor sees" choices (atomwalk.RecordsPrivacy)
# subtract from the vault before it reaches a share session. A record hidden
# here stays hidden in every future share; the only way one reaches a doctor
# is a per-visit reveal that the patient makes on the live grant
# (RecordsShareRequest.shown_private_ids), which is dropped when the visit ends.

def _privacy_for(awpid):
    return RecordsPrivacy.objects.using("default").filter(patient__awpid=awpid).first()
def _privacy_hidden_ids(awpid, docs, privacy=None):
    """
    docs = the dicts returned by _vault_documents(awpid). Returns the set of
    MedicalDocument ids the patient's standing privacy hides from a doctor —
    the union of hide_all, the live kind rules, and individually
    locked ids. Per-visit reveals are added back by the caller.
    """
    p = privacy if privacy is not None else _privacy_for(awpid)
    if not p:
        return set()
    if p.hide_all:
        return {d["id"] for d in docs}
    kinds = set(p.hidden_kinds or [])
    hidden = set(p.hidden_doc_ids or [])
    for d in docs:
        if d["id"] in hidden:
            continue
        if d["doc_type"] in kinds:
            hidden.add(d["id"])
    return hidden
_SECTION_LABELS = {
    "summary":      "Summary",
    "vitals":       "Recent vitals",
    "diagnoses":    "Diagnoses & clinical notes",
    "vaccinations": "Vaccinations",
}
def _pending_download_payload(grant):
    if not grant.pending_download_id:
        return None
    doc = MedicalDocument.objects.using("default").filter(
        id=grant.pending_download_id, patient__awpid=grant.awpid,
    ).first()
    return {
        "id": grant.pending_download_id,
        "title": doc.file_name if doc else "a document",
    }
# ─────────────────────────────────────────────────────────────── patient: create

class RecordsShareCreateView(APIView):
    """
    POST /api/v1/portal/records-share/

    The PATIENT starts the flow from their app: this mints a pending session
    bound to their awpid and returns a link to hand to the doctor. The doctor
    opens that link on a laptop (no account), the laptop shows a QR, the
    patient scans it and confirms — only then does the session go live.

    Body (optional): { "note": "Dr. Rao" }  — a label the patient can attach
    so their "who has access" list is readable later.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        note = (request.data.get("note") or request.data.get("requester_label") or "").strip()[:120]

        token = secrets.token_hex(16)                    # 32 hex chars
        code = f"{secrets.randbelow(1_000_000):06d}"     # spoken fallback

        grant = RecordsShareRequest.objects.using("default").create(
            token=token, code=code, requester_label=note, patient=Patient.objects.using("default").get(awpid=me),
            status=RecordsShareRequest.STATUS_PENDING, created_ip=_client_ip(request),
        )

        from django.conf import settings
        link = f"{settings.FRONTEND_URL.rstrip('/')}/share-records/{token}"

        return success(data={
            "token": grant.token,
            "code": grant.code,
            "link": link,
            "status": grant.status,
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
        }, status=201)
# ─────────────────────────────────────────────────────────────── doctor / public


class RecordsShareClaimView(APIView):
    """
    POST /api/v1/records-share/claim/
      body: { "code": "482193" }   — the doctor types the patient's 6 digits
                                      at clinic.atomwalk.com/share
        or: { "token": "<32 hex>" } — the doctor opened a full share link and
                                      the page is binding itself

    Ties this session to the calling browser: mints a random device token
    (returned once, kept by that browser and sent as X-Share-Device on every
    later read) and a 6-char `pairing` shown on the doctor's screen for the
    patient to scan/type when approving. Only works while the session is still
    pending — a link that leaks after approval cannot claim its way in.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def post(self, request):
        raw = (request.data.get("code") or request.data.get("token") or "").strip()
        by_code = raw.isdigit() and len(raw) == 6

        if by_code:
            grant = (
                RecordsShareRequest.objects.using("default")
                .filter(code=raw, status=RecordsShareRequest.STATUS_PENDING)
                .order_by("-created_at")
                .first()
            )
        else:
            grant = RecordsShareRequest.objects.using("default").filter(token=raw).first()

        if not grant or (by_code and grant.pending_stale):
            return error("That code didn't match a waiting request. Ask the "
                         "patient to create a new share and read you the code.",
                         status=404)
        grant.lapse_if_due()

        if grant.status == RecordsShareRequest.STATUS_APPROVED:
            return error("This session is already open on another computer. Ask "
                         "the patient to share again if you need a fresh one.",
                         errors={"status": grant.status}, status=409)
        if grant.status != RecordsShareRequest.STATUS_PENDING:
            return error("This request has ended. Ask the patient for a new code.",
                         errors={"status": grant.status}, status=409)

        device = secrets.token_hex(16)
        grant.device_hash = hashlib.sha256(device.encode()).hexdigest()
        grant.pairing = _make_pairing()
        grant.opened_at = grant.opened_at or timezone.now()
        grant.save(using="default", update_fields=[
            "device_hash", "pairing", "opened_at",
        ])

        return success(data={
            "token": grant.token,
            "device_token": device,
            "pairing": grant.pairing,
            "requester_label": grant.requester_label,
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
            "status": grant.status,
        }, status=201)
class RecordsShareStatusView(APIView):
    """
    GET /api/v1/records-share/<token>/

    Polled by the doctor's laptop while it waits, and also read by the
    patient's phone right after a scan to show "who is asking" before they
    decide. Returns identifying patient data only once the grant is a live
    approval.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def get(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)

        bail = _device_guard(grant, request)
        if bail:
            return bail

        # Heartbeat so the patient's "who has access" view can show whether
        # the doctor is actively looking right now.
        if grant.is_live:
            RecordsShareRequest.objects.using("default").filter(pk=grant.pk).update(
                last_seen_at=timezone.now())

        data = {
            "token": grant.token,
            "status": grant.status,
            "pairing": grant.pairing,
            "requester_label": grant.requester_label,
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
            "seconds_left": grant.seconds_left() if grant.is_live else 0,
        }
        if grant.status == RecordsShareRequest.STATUS_PENDING:
            from django.conf import settings
            link = f"{settings.FRONTEND_URL.rstrip('/')}/share-records/{grant.token}"
            if grant.pairing:
                link = f"{link}?p={grant.pairing}"
            data["qr_image"] = _render_qr_data_uri(link)
        if grant.is_live:
            data["patient_name"] = _patient_name(grant.awpid)[0]
            data["pending_download"] = _pending_download_payload(grant)
        return success(data=data)
class RecordsShareRecordsView(APIView):
    """
    GET /api/v1/records-share/<token>/records/

    The read-only payload the laptop renders once approved: patient header,
    shared clinical history (allergies / diagnoses / vitals / prescriptions),
    and the navigable Rx & Reports vault. File contents are NOT included —
    every document is "locked" until the patient releases it for download
    (see RecordsShareDownloadView).
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def get(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        bail = _device_guard(grant, request)
        if bail:
            return bail
        if not grant.is_live:
            return error(
                "This access has ended. Ask the patient to grant access again.",
                errors={"status": grant.status}, status=403,
            )

        from apps.hospital_master.patients.services import PatientService
        from apps.atomwalk.patients.views import _resolve_emergency_contact, _vaccination_history
        name, identity = _patient_name(grant.awpid)
        history = PatientService.get_shared_history(awpid=grant.awpid)

        unlocked = set(grant.download_unlocked_ids or [])
        documents = _vault_documents(grant.awpid)

        # ── standing privacy: drop what the patient keeps private, minus the
        #    records they revealed for this one visit — skipped entirely when
        #    the patient chose "share everything" for this grant at approval
        #    time (grant.share_all), same effect as revealing every private
        #    record but without touching standing RecordsPrivacy itself ─────
        shown_now = set(grant.shown_private_ids or [])
        if grant.share_all:
            hidden_ids, withheld, hidden_sections = set(), 0, []
        else:
            privacy = _privacy_for(grant.awpid)
            hidden_ids = _privacy_hidden_ids(grant.awpid, documents, privacy)
            withheld = sum(1 for d in documents if d["id"] in hidden_ids and d["id"] not in shown_now)
            documents = [d for d in documents if d["id"] not in hidden_ids or d["id"] in shown_now]
            hidden_sections = list((privacy.hidden_sections if privacy else []) or [])

        for d in documents:
            d["revealed_for_visit"] = d["id"] in hidden_ids and d["id"] in shown_now
            d["download_state"] = (
                "unlocked" if d["id"] in unlocked
                else "requested" if d["id"] == grant.pending_download_id
                else "locked"
            )

        def _age(dob):
            if not dob:
                return None
            t = timezone.localdate()
            return t.year - dob.year - ((t.month, t.day) < (dob.month, dob.day))

        # Current meds = the drugs on the most recent prescription.
        current_meds = []
        if history["prescriptions"]:
            for it in (history["prescriptions"][0].get("items") or []):
                bits = [it.get("drug_name"), it.get("dose"), it.get("frequency")]
                current_meds.append(" ".join(b for b in bits if b))

        _audit(grant.awpid, EmergencyAccessLog.EVENT_VIEWED, _client_ip(request))

        summary = {
            "current_meds": [] if "summary" in hidden_sections else current_meds,
            "emergency_contact": None if "summary" in hidden_sections
                                 else _resolve_emergency_contact(grant.awpid),
        }
        sections_withheld = [
            _SECTION_LABELS[s] for s in RecordsPrivacy.SECTIONS if s in hidden_sections
        ]

        return success(data={
            "patient": {
                "full_name": name,
                "awpid": grant.awpid,
                "age_years": _age(identity.date_of_birth) if identity else None,
                "gender": identity.gender if identity else "",
                "blood_group": identity.blood_group if identity else "",
            },
            "summary": summary,
            "allergies": history["allergies"],
            "diagnoses": [] if "diagnoses" in hidden_sections else history["diagnoses"],
            "vitals": [] if "vitals" in hidden_sections else history["vitals"],
            "prescriptions": history["prescriptions"],
            "vaccinations": [] if "vaccinations" in hidden_sections
                            else _vaccination_history(grant.awpid),
            "documents": documents,
            # One honest line for the clinician: the record list / sections may
            # be partial. It never says *what* is held back.
            "records_withheld": withheld > 0,
            "sections_withheld": sections_withheld,
            "requester_label": grant.requester_label,
            "seconds_left": grant.seconds_left(),
            "window_hours": RecordsShareRequest.WINDOW_HOURS,
        })
class RecordsShareDownloadView(APIView):
    """
    POST /api/v1/records-share/<token>/downloads/   body: { "doc_id": 123 }

    If the patient has already released this document, returns a signed URL.
    Otherwise records it as the pending download request — the patient sees
    it on their phone and allows or denies (RecordsShareDownloadDecisionView).
    Only one pending request at a time; a new one replaces the last.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def post(self, request, token):
        grant = _get_grant(token)
        bail = grant and _device_guard(grant, request)
        if bail:
            return bail
        if not grant or not grant.is_live:
            return error("This access has ended.", status=403)

        try:
            doc_id = int(request.data.get("doc_id"))
        except (TypeError, ValueError):
            return error("Which document?", errors={"doc_id": "Required."})

        doc = MedicalDocument.objects.using("default").filter(
            id=doc_id, patient__awpid=grant.awpid,
        ).exclude(awaiting_review_q()).first()
        if not doc:
            return error("That document isn't part of this patient's records.", status=404)

        if doc_id in (grant.download_unlocked_ids or []):
            return success(data={"state": "unlocked", "file_url": blob_storage.signed_url(doc.file.name)})

        RecordsShareRequest.objects.using("default").filter(pk=grant.pk).update(
            pending_download_id=doc_id)
        return success(data={"state": "requested"})
class RecordsShareDocumentViewView(APIView):
    """
    GET /api/v1/records-share/<token>/documents/<doc_id>/view/

    Open a document in the browser — instant, no patient approval. The
    patient already granted the whole session; *saving a copy* is the extra
    step, not looking at one (see RecordsShareDownloadView for that).

    That separation only holds if "view" never hands over anything a
    one-click browser action can turn into a saved file. A raw signed PDF
    URL opened in a new tab renders in the browser's own PDF viewer, which
    carries its own Download/Print buttons — a doctor could bypass the
    per-file patient-approval gate entirely just by using those, with no
    audit trail. So for a PDF, this rasterises each page to a PNG
    server-side (same renderer core.ocr uses for OCR) and returns those
    instead of a URL — a page rendered as an <img> in our own page carries
    no native viewer chrome to download or print from. For an image
    document there's no separate "native viewer" risk (the frontend fetches
    it into an <img> itself rather than navigating to the raw URL), so the
    signed URL is still returned directly.

    This doesn't make a screenshot impossible — nothing served to a browser
    ever can. It removes the specific, no-friction, easy-to-stumble-on
    Download icon that made bypassing the consent gate no different from
    just looking.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def get(self, request, token, doc_id):
        grant = _get_grant(token)
        bail = grant and _device_guard(grant, request)
        if bail:
            return bail
        if not grant or not grant.is_live:
            return error("This access has ended.", status=403)
        doc = MedicalDocument.objects.using("default").filter(
            id=doc_id, patient__awpid=grant.awpid,
        ).exclude(awaiting_review_q()).first()
        if not doc:
            return error("That document isn't part of this patient's records.", status=404)

        if doc.mime_type == "application/pdf":
            import base64
            from core import ocr as _ocr

            pages = _ocr.pdf_page_images(blob_storage.get_bytes(doc.file.name), max_pages=12, dpi=150)
            if not pages:
                return error("Couldn't render this document for viewing.", status=500)
            return success(data={
                "mime_type": "application/pdf",
                "pages": [f"data:image/png;base64,{base64.b64encode(p).decode()}" for p in pages],
            })

        return success(data={"mime_type": doc.mime_type, "file_url": blob_storage.signed_url(doc.file.name)})
class RecordsShareCloseView(APIView):
    """
    POST /api/v1/records-share/<token>/close/

    The doctor closing the session from their laptop. Ending access early is
    always safe and the token holder is the doctor, so no auth — unlike the
    patient's /end/ which is inside the portal.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "records_share"

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        bail = _device_guard(grant, request)
        if bail:
            return bail
        if grant.status in (RecordsShareRequest.STATUS_APPROVED, RecordsShareRequest.STATUS_PENDING):
            grant.status = RecordsShareRequest.STATUS_ENDED
            grant.pending_download_id = None
            grant.shown_private_ids = []
            grant.save(using="default", update_fields=["status", "pending_download_id", "shown_private_ids"])
        return success(data={"status": grant.status}, message="Access ended.")
# ─────────────────────────────────────────────────────────────── patient (auth)

class RecordsShareDecisionView(APIView):
    """
    POST /api/v1/records-share/<token>/decision/
      body: { "approve": true, "pairing": "K7M2QP", "consent_confirmed": true }

    Called by the patient after they scan the QR on the doctor's screen. That
    QR carries the session's `pairing` (…/share-records/<token>?p=K7M2QP); the
    app lifts it out and sends it here — or, if the camera won't cooperate,
    the patient reads the 6 characters shown under the QR and types them. It
    proves the patient is looking at the doctor's live screen, not replaying a
    copied link. Too many wrong tries locks the session. `approve:false`
    declines it. The right pairing but no `consent_confirmed` returns 428 with
    the list of what will be shared. The session was created by this same
    patient, so its awpid must match the caller.
    """
    permission_classes = [IsPatient]

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        if grant.status != RecordsShareRequest.STATUS_PENDING:
            return error("This request has already been answered.",
                         errors={"status": grant.status}, status=409)

        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)
        if grant.awpid and grant.awpid != me:
            return error("This share link was created by a different account.", status=403)

        approve = bool(request.data.get("approve"))

        if not approve:
            grant.status = RecordsShareRequest.STATUS_DENIED
            grant.decided_at = timezone.now()
            grant.patient = Patient.objects.using("default").get(awpid=me)
            grant.save(using="default", update_fields=["status", "decided_at", "patient"])
            _audit(me, EmergencyAccessLog.EVENT_GENERATED, _client_ip(request))
            return success(data={"status": grant.status}, message="Request declined.")

        # ── pairing check — the patient lifts it off the doctor's screen ───
        if not grant.opened_at or not grant.pairing:
            return error(
                "Ask the doctor to open the link on their computer first — a "
                "code will appear on their screen for you to scan.",
                errors={"reason": "not_opened"}, status=409,
            )
        submitted = "".join(
            ch for ch in str(request.data.get("pairing") or "").upper()
            if ch in _PAIRING_ALPHABET
        )
        if submitted != grant.pairing:
            grant.code_attempts += 1
            fields = ["code_attempts"]
            locked = grant.code_attempts >= RecordsShareRequest.MAX_CODE_ATTEMPTS
            if locked:
                grant.status = RecordsShareRequest.STATUS_DENIED
                grant.decided_at = timezone.now()
                grant.patient = Patient.objects.using("default").get(awpid=me)
                fields += ["status", "decided_at", "patient"]
            grant.save(using="default", update_fields=fields)
            if locked:
                return error(
                    "Too many wrong tries — this link is now locked. Ask the doctor to open a new one.",
                    errors={"status": grant.status}, status=423,
                )
            return error(
                "That doesn't match the code on the doctor's screen. Check it and try again.",
                errors={"attempts_left": RecordsShareRequest.MAX_CODE_ATTEMPTS - grant.code_attempts},
                status=400,
            )

        if not request.data.get("consent_confirmed"):
            docs = _vault_documents(me)
            private_count = len(_privacy_hidden_ids(me, docs))
            return error(
                "Confirm what you're sharing before granting access.",
                errors={
                    "consent_required": True,
                    "share_categories": EMERGENCY_SHARE_CATEGORIES,
                    "window_hours": RecordsShareRequest.WINDOW_HOURS,
                    # How many records the patient's standing privacy would
                    # withhold from THIS share by default — lets the app skip
                    # showing the all-vs-default choice entirely when it's 0
                    # (nothing private exists yet, so the two are identical).
                    "private_count": private_count,
                },
                status=428,
            )

        # One-time bulk choice, made here instead of one record at a time via
        # RecordsShareRevealView: "all" skips standing RecordsPrivacy for the
        # whole grant, "default" (or anything else / omitted) keeps it. Never
        # touches RecordsPrivacy itself — this is scoped to this one grant.
        share_all = (request.data.get("share_scope") or "default").strip() == "all"

        now = timezone.now()
        grant.patient = Patient.objects.using("default").get(awpid=me)
        grant.status = RecordsShareRequest.STATUS_APPROVED
        grant.decided_at = now
        grant.expires_at = now + timedelta(hours=RecordsShareRequest.WINDOW_HOURS)
        grant.share_all = share_all
        grant.save(using="default", update_fields=[
            "patient", "status", "decided_at", "expires_at", "share_all",
        ])
        _audit(me, EmergencyAccessLog.EVENT_GENERATED, _client_ip(request))

        return success(data={
            "token": grant.token,
            "status": grant.status,
            "requester_label": grant.requester_label,
            "expires_at": grant.expires_at,
            "seconds_left": grant.seconds_left(),
            "share_all": grant.share_all,
        }, message="Access granted for the next 2 hours.")
class RecordsShareEndView(APIView):
    """POST /api/v1/records-share/<token>/end/ — patient ends a live grant early."""
    permission_classes = [IsPatient]

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)

        me = _self_awpid(request)
        if grant.awpid and grant.awpid != me:
            return error("This isn't your access grant.", status=403)
        if grant.status not in (RecordsShareRequest.STATUS_APPROVED, RecordsShareRequest.STATUS_PENDING):
            return success(data={"status": grant.status})

        grant.status = RecordsShareRequest.STATUS_ENDED
        grant.pending_download_id = None
        grant.shown_private_ids = []
        grant.save(using="default", update_fields=["status", "pending_download_id", "shown_private_ids"])
        return success(data={"status": grant.status}, message="Access ended.")
class RecordsShareDownloadDecisionView(APIView):
    """
    POST /api/v1/records-share/<token>/downloads/decision/  body: { "approve": true }

    The patient allows or denies the doctor's pending download request. On
    allow, that document id moves into `download_unlocked_ids` and stays
    downloadable for the rest of the window.
    """
    permission_classes = [IsPatient]

    def post(self, request, token):
        grant = _get_grant(token)
        if not grant or not grant.is_live:
            return error("This access has ended.", status=403)

        me = _self_awpid(request)
        if grant.awpid != me:
            return error("This isn't your access grant.", status=403)
        if not grant.pending_download_id:
            return success(data={"pending_download": None})

        doc_id = grant.pending_download_id
        fields = ["pending_download_id"]
        if bool(request.data.get("approve")):
            unlocked = list(grant.download_unlocked_ids or [])
            if doc_id not in unlocked:
                unlocked.append(doc_id)
            grant.download_unlocked_ids = unlocked
            fields.append("download_unlocked_ids")
        grant.pending_download_id = None
        grant.save(using="default", update_fields=fields)
        return success(data={"pending_download": None, "unlocked_ids": grant.download_unlocked_ids})
class RecordsShareMineView(APIView):
    """
    GET /api/v1/records-share/mine/

    The patient's "who currently has access to my records" surface — every
    live grant they've approved, with any pending download request. The
    mobile app polls this to show the break-glass banner + approval prompts.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        grants = (
            RecordsShareRequest.objects.using("default")
            .filter(patient__awpid=me, status=RecordsShareRequest.STATUS_APPROVED)
            .order_by("-decided_at")
        )
        out = []
        for g in grants:
            if g.lapse_if_due():
                continue
            out.append({
                "token": g.token,
                "requester_label": g.requester_label,
                "approved_at": g.decided_at,
                "expires_at": g.expires_at,
                "seconds_left": g.seconds_left(),
                "last_seen_at": g.last_seen_at,
                "pending_download": _pending_download_payload(g),
                "share_all": g.share_all,
            })
        return success(data={"grants": out})
def _kind_label(kind):
    """The label of a configured type ("lab_report" → "Lab report"); "" means it could not be classified."""
    return kind.replace("_", " ").capitalize() if kind else "Unable to classify"
_PRIVACY_VAULT_MAX = 1000          # one patient's manageable ceiling
_PRIVACY_PAGE_ROWS = 40           # soft per-page target; whole groups, never split
_PRIVACY_PAGE_MAX = 200
def _row_date_key(d):
    v = d.get("document_date") or d.get("created_at")
    return v.isoformat() if hasattr(v, "isoformat") else (v or "")
def _bucket_of(row):
    """(key, label, rank) — the document-type bucket a row is grouped under."""
    k = row.get("doc_type") or ""
    return f"k:{k}", _kind_label(k), 100
def _bucket_groups(rows):
    groups = {}
    for r in rows:
        key, label, rank = _bucket_of(r)
        g = groups.get(key)
        if not g:
            g = groups[key] = {"key": key, "label": label, "rank": rank, "list": []}
        g["list"].append(r)
    ordered = sorted(groups.values(), key=lambda g: g["rank"])
    for g in ordered:
        g["list"].sort(key=_row_date_key, reverse=True)
    return ordered
def _paginate_groups(groups, page, target=_PRIVACY_PAGE_ROWS):
    """Pack ordered groups into pages of ~`target` rows without splitting a
    group; an oversize group takes a page to itself. Returns (rows, meta)."""
    pages, cur, cur_n = [], [], 0
    for g in groups:
        gn = len(g["list"])
        if cur and cur_n + gn > target:
            pages.append(cur); cur, cur_n = [], 0
        cur.append(g); cur_n += gn
        if cur_n >= target:
            pages.append(cur); cur, cur_n = [], 0
    if cur:
        pages.append(cur)
    total_pages = max(1, len(pages))
    page = min(max(page, 1), total_pages)
    sel = pages[page - 1] if pages else []
    rows = [d for g in sel for d in g["list"]]
    return rows, {
        "page": page,
        "page_size": target,
        "total_pages": total_pages,
        "total_count": sum(len(g["list"]) for g in groups),
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }
class RecordsPrivacyView(APIView):
    """
    GET  /api/v1/portal/records-privacy/
    PUT  /api/v1/portal/records-privacy/

    The patient's standing "what a doctor sees when I share my records"
    config, plus the full vault annotated with each row's effective private
    state (for the dedicated privacy screen). GET also reports whether a
    share session is live right now — the frontend asks "just this visit or
    always?" only then, otherwise a plain confirm.
    """
    permission_classes = [IsPatient]

    def get(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        p = RecordsPrivacy.for_awpid(me)
        docs = _vault_documents(me, limit=_PRIVACY_VAULT_MAX)
        hidden = _privacy_hidden_ids(me, docs, p)
        locked_ids = set(p.hidden_doc_ids or [])

        live = (
            RecordsShareRequest.objects.using("default")
            .filter(patient__awpid=me, status=RecordsShareRequest.STATUS_APPROVED)
            .order_by("-decided_at")
            .first()
        )
        if live and not live.is_live:
            live = None
        shown_now = set(live.shown_private_ids or []) if live else set()

        # ── annotate the whole (capped) vault once ───────────────────────────
        rows = [{
            "id":                d["id"],
            "title":             d["title"],
            "doc_type":          d["doc_type"],
            "created_at":        d["created_at"],
            "private":           d["id"] in hidden,
            "private_by_rule":   d["id"] in hidden and d["id"] not in locked_ids,
            "revealed_for_visit": d["id"] in hidden and d["id"] in shown_now,
        } for d in docs]

        # ── whole-vault aggregates (the readout + Hide-all/Show-all + facets) ─
        kind_counts, months = Counter(), set()
        shown_ct = visit_ct = private_ct = 0
        showable_ids, hideable_ids = [], []
        for r in rows:
            seen = (not r["private"]) or r["revealed_for_visit"]
            if seen:
                shown_ct += 1
            if r["revealed_for_visit"]:
                visit_ct += 1
            if r["private"] and not r["revealed_for_visit"]:
                private_ct += 1
            if r["private"] and not r["private_by_rule"]:
                showable_ids.append(r["id"])
            hideable_ids.append(r["id"])
            kind_counts[r["doc_type"]] += 1
            mk = _row_date_key(r)[:7]
            if mk:
                months.add(mk)

        # ── filter (server-authoritative; the client no longer filters) ──────
        q = (request.query_params.get("q") or "").strip().lower()
        kinds_f = {s for s in (request.query_params.get("kind") or "").split(",") if s}
        month_f = (request.query_params.get("month") or "").strip()

        def _keep(r):
            if kinds_f and r["doc_type"] not in kinds_f:
                return False
            if month_f and _row_date_key(r)[:7] != month_f:
                return False
            if q:
                hay = (r["title"] or "").lower()
                if q not in hay:
                    return False
            return True

        filtered = [r for r in rows if _keep(r)]

        try:
            page = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get("page_size", _PRIVACY_PAGE_ROWS))
        except (TypeError, ValueError):
            page_size = _PRIVACY_PAGE_ROWS
        page_size = max(10, min(page_size, _PRIVACY_PAGE_MAX))

        page_rows, pmeta = _paginate_groups(_bucket_groups(filtered), page, page_size)

        return success(data={
            "hide_all":          p.hide_all,
            "hidden_categories": p.hidden_categories or [],
            "hidden_kinds":      p.hidden_kinds or [],
            "hidden_sections":   p.hidden_sections or [],
            "sections":          list(RecordsPrivacy.SECTIONS),
            "section_labels":    _SECTION_LABELS,
            "documents":         page_rows,
            "pagination":        pmeta,
            "summary": {
                "vault_total":     len(rows),
                "filtered_total":  len(filtered),
                "shown":           shown_ct,
                "visit":           visit_ct,
                "private":         private_ct,
                "showable_ids":    showable_ids,
                "hideable_ids":    hideable_ids,
                "filtered_ids":    [r["id"] for r in filtered],
                "kind_counts":     dict(kind_counts),
                "kind_labels":     {k: _kind_label(k) for k in kind_counts},
                "months":          sorted(months, reverse=True),
                "truncated":       len(docs) >= _PRIVACY_VAULT_MAX,
            },
            "active_session": ({
                "token":             live.token,
                "requester_label":   live.requester_label,
                "seconds_left":      live.seconds_left(),
                "shown_private_ids": live.shown_private_ids or [],
                "share_all":         live.share_all,
            } if live else None),
        })

    def put(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)

        p = RecordsPrivacy.for_awpid(me)
        d = request.data
        fields = ["updated_at"]

        if "hide_all" in d:
            p.hide_all = bool(d["hide_all"]); fields.append("hide_all")
        if "hidden_categories" in d:
            p.hidden_categories = [str(s) for s in (d["hidden_categories"] or [])][:60]
            fields.append("hidden_categories")
        if "hidden_kinds" in d:
            p.hidden_kinds = [k for k in (d["hidden_kinds"] or []) if k in DOCUMENT_TYPES]
            fields.append("hidden_kinds")
        if "hidden_sections" in d:
            p.hidden_sections = [s for s in (d["hidden_sections"] or []) if s in RecordsPrivacy.SECTIONS]
            fields.append("hidden_sections")
        if "hidden_doc_ids" in d:
            want = {int(x) for x in (d["hidden_doc_ids"] or []) if str(x).lstrip("-").isdigit()}
            mine = set(
                MedicalDocument.objects.using("default")
                .filter(patient__awpid=me, id__in=want).values_list("id", flat=True)
            )
            p.hidden_doc_ids = sorted(mine); fields.append("hidden_doc_ids")

        # Incremental bulk lock/unlock — the privacy screen is paged now, so the
        # client can't send a full replacement list; it sends deltas instead.
        if "add_hidden_doc_ids" in d or "remove_hidden_doc_ids" in d:
            cur = set(p.hidden_doc_ids or [])
            add = {int(x) for x in (d.get("add_hidden_doc_ids") or []) if str(x).lstrip("-").isdigit()}
            rem = {int(x) for x in (d.get("remove_hidden_doc_ids") or []) if str(x).lstrip("-").isdigit()}
            if add:
                cur |= set(
                    MedicalDocument.objects.using("default")
                    .filter(patient__awpid=me, id__in=add).values_list("id", flat=True)
                )
            cur -= rem
            p.hidden_doc_ids = sorted(cur)
            if "hidden_doc_ids" not in fields:
                fields.append("hidden_doc_ids")

        p.save(using="default", update_fields=fields)
        _audit(me, EmergencyAccessLog.EVENT_PRIVACY, _client_ip(request))
        return success(data={"ok": True})
class RecordsPrivacyToggleView(APIView):
    """
    POST /api/v1/portal/records-privacy/toggle/   body { doc_id, private }

    The single-record lock used from My Reports — add or remove one
    MedicalDocument id from the standing hidden list.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)
        try:
            doc_id = int(request.data.get("doc_id"))
        except (TypeError, ValueError):
            return error("Which report?", errors={"doc_id": "Required."})
        if not MedicalDocument.objects.using("default").filter(patient__awpid=me, id=doc_id).exists():
            return error("That report isn't in your records.", status=404)

        make_private = bool(request.data.get("private"))
        p = RecordsPrivacy.for_awpid(me)
        ids = set(p.hidden_doc_ids or [])
        ids.add(doc_id) if make_private else ids.discard(doc_id)
        p.hidden_doc_ids = sorted(ids)
        p.save(using="default", update_fields=["hidden_doc_ids", "updated_at"])
        _audit(me, EmergencyAccessLog.EVENT_PRIVACY, _client_ip(request))
        return success(data={"doc_id": doc_id, "private": make_private})
class RecordsShareRevealView(APIView):
    """
    POST /api/v1/portal/records-share/<token>/reveal/
      body { doc_ids: [..], scope: "visit" | "always" | "conceal" }

    visit    — show these to the doctor for THIS live visit only; they drop
               back to private when the visit ends.
    always   — also clear them from standing privacy (visible to future
               doctors too).
    conceal  — undo a this-visit reveal now.
    """
    permission_classes = [IsPatient]

    def post(self, request, token):
        me = _self_awpid(request)
        if not me:
            return error("No patient account found.", status=403)
        grant = _get_grant(token)
        if not grant:
            return error("This access code is not valid.", status=404)
        if grant.awpid and grant.awpid != me:
            return error("This isn't your access grant.", status=403)
        if not grant.is_live:
            return error("This access has ended.", status=403)

        scope = (request.data.get("scope") or "visit").strip()
        if scope not in ("visit", "always", "conceal"):
            scope = "visit"
        want = {int(x) for x in (request.data.get("doc_ids") or []) if str(x).lstrip("-").isdigit()}
        ids = set(
            MedicalDocument.objects.using("default")
            .filter(patient__awpid=me, id__in=want).values_list("id", flat=True)
        )

        shown = set(grant.shown_private_ids or [])
        shown = (shown - ids) if scope == "conceal" else (shown | ids)
        grant.shown_private_ids = sorted(shown)
        grant.save(using="default", update_fields=["shown_private_ids"])

        if scope == "always" and ids:
            p = RecordsPrivacy.for_awpid(me)
            p.hidden_doc_ids = sorted(set(p.hidden_doc_ids or []) - ids)
            p.save(using="default", update_fields=["hidden_doc_ids", "updated_at"])

        _audit(me, EmergencyAccessLog.EVENT_PRIVACY, _client_ip(request))
        return success(data={"shown_private_ids": grant.shown_private_ids})


logger = logging.getLogger(__name__)
# Total base64 budget for one tab's page images. Finger strokes on white
# compress tiny; this comfortably fits ~15 pages and just rejects an
# abusive/malformed PUT before we decode it.
_MAX_TAB_BASE64_CHARS = 9_000_000
_TABS = {"rx", "note"}
# Drug-name normalisation. The recognition model is told it MAY fix an
# obvious misspelling of a real drug; this pass then grounds that against the
# hospital's OWN drug catalog (prescriptions.Drug) — the authoritative
# spelling for that clinic. It only ever rewrites the drug NAME; dose,
# frequency, route and duration are never touched, and the doctor still
# reviews every row before signing. `drug_name_raw` keeps what was read so
# the encounter screen can show "read X -> matched Y".
_DRUG_MATCH_MIN = 85     # rapidfuzz WRatio; below this we leave the name alone
_DRUG_MATCH_GAP = 6      # winner must beat the next DIFFERENT drug by at least this
_DRUG_MATCH_STRONG = 90  # a hit this good is accepted even without the gap
_DRUG_MIN_LEN = 5        # don't fuzzy-match short tokens / abbreviations (e.g. "pcm")
_RX_FORM_WORDS = {
    "tab", "tabs", "tablet", "tablets", "cap", "caps", "capsule", "capsules",
    "syp", "syr", "syrup", "susp", "suspension", "inj", "injection", "amp",
    "ampoule", "oint", "ointment", "cream", "gel", "lotion", "drop", "drops",
    "gtt", "soln", "solution", "spray", "inh", "inhaler", "sachet", "powder",
}
def _strip_form_word(name: str) -> str:
    words = (name or "").strip().split()
    while words and words[0].strip(".").lower() in _RX_FORM_WORDS:
        words = words[1:]
    return " ".join(words)
def _candidate_map(rows, alias_pairs_iter=None):
    """
    Build {probe_lower: canonical Drug.name} from catalog rows, plus
    doctor-shorthand aliases whose generic/brand is already present in the
    catalog. Pure (no DB / no network) so it can be unit-tested directly.

    `rows`: iterable of dicts with "name" and "generic_name".
    `alias_pairs_iter`: iterable of (surface_lower, generic_lower) — an alias
    only takes effect when its generic resolves to a real catalog entry.
    """
    candidates = {}
    generics = {}  # generic_lower -> canonical name (first wins)
    for r in rows:
        canon = (r.get("name") or "").strip()
        if not canon:
            continue
        candidates.setdefault(canon.lower(), canon)
        gen = (r.get("generic_name") or "").strip().lower()
        if gen:
            candidates.setdefault(gen, canon)
            generics.setdefault(gen, canon)

    if alias_pairs_iter:
        cat_generics = list(generics.items())
        for surface, seed_gen in alias_pairs_iter:
            if not surface or surface in candidates:
                continue
            canon = generics.get(seed_gen)
            if not canon:
                # tolerate strength suffixes on the catalog generic, e.g. seed
                # "amoxicillin" vs catalog generic "amoxicillin 500 mg"
                for cg, cn in cat_generics:
                    if seed_gen in cg.split() or cg.startswith(seed_gen + " "):
                        canon = cn
                        break
            if canon:
                candidates[surface] = canon
    return candidates
def _resolve_item_name(it, candidates, keys, process, fuzz):
    """Canonicalise one recognised Rx item's drug_name against `candidates`.
    Mutates `it` in place; never changes dose/frequency/route/duration."""
    raw = (it.get("drug_name") or "").strip()
    it["drug_name_raw"] = raw
    it["name_source"] = "verbatim"
    it.setdefault("flags", [])
    probe = _strip_form_word(raw).lower()
    if not probe:
        return

    # Exact catalog hit (canonical name, generic, or a known alias) — safe.
    if len(probe) >= 3 and probe in candidates:
        canon = candidates[probe]
        if canon != raw:
            it["drug_name"] = canon
        it["name_source"] = "catalog"
        return

    # Fuzzy: only for tokens long enough to be meaningful. Accept when the top
    # hit is either near-exact (>= _DRUG_MATCH_STRONG) or clearly ahead of the
    # next DIFFERENT drug (>= _DRUG_MATCH_GAP). Runner-ups that resolve to the
    # same canonical (e.g. "Paracetamol" vs "Paracetamol Syrup" sharing the
    # generic, or a brand alias) don't count as competition. Weaker matches
    # are left verbatim and flagged for the doctor.
    if len(probe) < _DRUG_MIN_LEN:
        it["flags"].append("not found in catalog — check the name")
        return
    hits = process.extract(probe, keys, scorer=fuzz.WRatio, limit=8)
    if not hits or hits[0][1] < _DRUG_MATCH_MIN:
        it["flags"].append("not found in catalog — check the name")
        return
    s1 = hits[0][1]
    win_canon = candidates[hits[0][0]]
    rival = next((sc for (k, sc, *_ ) in hits[1:] if candidates.get(k) != win_canon), 0)
    if s1 >= _DRUG_MATCH_STRONG or (s1 - rival) >= _DRUG_MATCH_GAP:
        if win_canon.lower() != raw.lower():
            it["drug_name"] = win_canon
        it["name_source"] = "catalog_fuzzy"
        it["flags"].append(f'best-guess match for "{raw}" — confirm')
    else:
        it["flags"].append("not found in catalog — check the name")
def _drug_candidate_map(catalog_rows, seed_iter):
    """Build {probe_lower: canonical drug name}. `seed_iter` is
    (surface_lower, canonical) from consult_pad_drug_aliases.seed_name_pairs()
    — the standalone base, so drug names still resolve when the hospital has no
    Drug catalog. `catalog_rows` (dicts with "name"/"generic_name") are layered
    on top and win for spelling — a clinic that stocks "Dolo 650" gets that
    exact string. Pure (no DB / no network)."""
    candidates = {}
    for surface, canon in seed_iter or []:
        surface = (surface or "").strip().lower()
        canon = (canon or "").strip()
        if surface and canon:
            candidates.setdefault(surface, canon)
    for r in catalog_rows or []:
        canon = (r.get("name") or "").strip()
        if not canon:
            continue
        candidates[canon.lower()] = canon            # catalog overrides the seed
        gen = (r.get("generic_name") or "").strip().lower()
        if gen:
            candidates.setdefault(gen, canon)
    return candidates
def _normalise_rx_against_catalog(recognized: dict, hospital_id):
    """Mutate recognized['prescription'] in place: canonicalise each drug_name
    against a standard drug-name table (consult_pad_drug_aliases), enriched
    with the hospital's own Drug catalog when it has one. Best-effort — any
    failure leaves the names exactly as recognised."""
    items = recognized.get("prescription") or []
    if not items:
        return

    # Make sure every item carries these keys even if we bail out early below
    # (rapidfuzz missing) so the encounter page's review panel renders
    # consistently.
    for it in items:
        it.setdefault("drug_name_raw", (it.get("drug_name") or "").strip())
        it.setdefault("name_source", "verbatim")
        it.setdefault("flags", [])

    try:
        from rapidfuzz import process, fuzz
    except Exception:
        return

    # Hospital Drug catalog — nice-to-have, not required. Any failure (no
    # hospital, DB down, empty catalog) just leaves catalog_rows empty and the
    # seed table does the work.
    catalog_rows = []
    if hospital_id:
        try:
            from apps.atomwalk.hospital_master.models import Hospital
            hospital = Hospital.objects.using("default").filter(pk=hospital_id).first()
            if hospital:
                from apps.hospital_master.pharmacy.models import Drug
                catalog_rows = list(Drug.objects.using(hospital.db_name)
                                    .filter(is_active=True).values("name", "generic_name"))
        except Exception:
            logger.debug("consult-pad: drug catalog unavailable for hospital %s — seed table only", hospital_id)

    try:
        from apps.atomwalk.patients.services import seed_name_pairs
        seed_iter = list(seed_name_pairs())
    except Exception:
        seed_iter = []

    candidates = _drug_candidate_map(catalog_rows, seed_iter)
    keys = list(candidates)
    for it in items:
        _resolve_item_name(it, candidates, keys, process, fuzz)
# ── Investigation-name normalisation ────────────────────────────────────────
# Same idea as the drug pass above, for the recognised `investigations` string
# on the Internal Note tab: turn "CBC, LFT, USG abd" into standard test names
# the front desk and lab will recognise. Deterministic and reversible — the
# raw string each token came from is kept, every rewrite is shown to the
# doctor on the review panel, and `raw_text` is never touched.
#
# Unlike drugs, this does NOT require a hospital catalog: the seed alias table
# (apps/hospital_patients/consult_pad_lab_aliases.py) stands on its own because most
# clinics don't maintain a lab_test catalog and a test name carries no dosing
# risk. Where the hospital DOES have one, its names are layered on top and win
# for spelling.
_LAB_MATCH_MIN = 88   # rapidfuzz WRatio; below this the token is left as written
_LAB_MATCH_GAP = 6    # winner must beat the runner-up by at least this much
_LAB_MIN_LEN = 4      # don't fuzzy-match shorter tokens — 3-letter acronyms
                      # (cbc/lft/esr/…) must come through the exact alias path
# Split on comma / semicolon / newline (tight), and on slash, ampersand, plus
# or the word "and" ONLY when surrounded by whitespace — so "Urine R/M",
# "RFT/electrolytes" written solid, "Na+ K+" and "c/s" survive as one token.
_LAB_SPLIT_RE = re.compile(r"\s*[,;\n]\s*|\s+/\s+|\s+&\s+|\s+\+\s+|\s+and\s+", re.I)
_LAB_LIST_PREFIX_RE = re.compile(r"^\s*(?:\d+\s*[.)\-]|[-*•·])\s*")
def _split_investigations(text: str) -> list:
    """A recognised `investigations` string -> ordered, de-duplicated list of
    individual test tokens. Pure; safe on '' (returns [])."""
    if not text or not text.strip():
        return []
    out, seen = [], set()
    for chunk in _LAB_SPLIT_RE.split(text):
        tok = _LAB_LIST_PREFIX_RE.sub("", (chunk or "").strip()).strip(" .:-")
        if not tok:
            continue
        key = tok.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tok)
    return out
def _lab_candidate_map(catalog_names, alias_pairs_iter):
    """Build {probe_lower: canonical test name}. `catalog_names` is an iterable
    of the hospital's LabTest.name strings (may be empty); `alias_pairs_iter` is
    (surface_lower, canonical) from the seed table. Catalog names are added
    last so a clinic's own spelling wins. Pure (no DB / no network)."""
    candidates = {}
    for surface, canon in alias_pairs_iter or []:
        surface = (surface or "").strip().lower()
        canon = (canon or "").strip()
        if surface and canon:
            candidates.setdefault(surface, canon)
    for name in catalog_names or []:
        canon = (name or "").strip()
        if canon:
            candidates[canon.lower()] = canon   # catalog overrides the seed
    return candidates
def _resolve_investigation(raw, candidates, keys, process, fuzz):
    """Canonicalise one investigation token. Returns
    {raw, name, source: verbatim|catalog|catalog_fuzzy, flags:[...]}."""
    raw = (raw or "").strip()
    probe = raw.lower()
    res = {"raw": raw, "name": raw, "source": "verbatim", "flags": []}
    if not probe:
        return res

    if probe in candidates:
        res["name"] = candidates[probe]
        res["source"] = "catalog"
        return res

    if len(probe) < _LAB_MIN_LEN or not keys:
        res["flags"].append("not a recognised investigation — check")
        return res

    hits = process.extract(probe, keys, scorer=fuzz.WRatio, limit=2)
    s1 = hits[0][1] if hits else 0
    s2 = hits[1][1] if len(hits) > 1 else 0
    if hits and s1 >= _LAB_MATCH_MIN and (s1 - s2) >= _LAB_MATCH_GAP:
        res["name"] = candidates[hits[0][0]]
        res["source"] = "catalog_fuzzy"
        res["flags"].append(f'best-guess match for "{raw}" — confirm')
    else:
        res["flags"].append("not a recognised investigation — check")
    return res
def _normalise_investigations_against_catalog(recognized: dict, hospital_id):
    """Mutate recognized in place: rewrite `investigations` to standard test
    names and attach `investigations_resolved` (one entry per token, with the
    raw string and any flag) for the review panel. Best-effort — any failure
    leaves `investigations` exactly as recognised."""
    recognized.setdefault("investigations_resolved", [])
    tokens = _split_investigations(recognized.get("investigations") or "")
    if not tokens:
        return

    # Passthrough shape first, so the review panel renders even if we bail out.
    recognized["investigations_resolved"] = [
        {"raw": t, "name": t, "source": "verbatim", "flags": []} for t in tokens
    ]

    try:
        from rapidfuzz import process, fuzz
    except Exception:
        return
    try:
        from apps.atomwalk.patients.services import consult_pad_lab_aliases_alias_pairs as alias_pairs
        alias_iter = list(alias_pairs())
    except Exception:
        alias_iter = []

    catalog_names = []
    if hospital_id:
        try:
            from apps.atomwalk.hospital_master.models import Hospital
            hospital = Hospital.objects.using("default").filter(pk=hospital_id).first()
            if hospital:
                from apps.hospital_master.lab.models import LabTest
                catalog_names = list(
                    LabTest.objects.using(hospital.db_name)
                    .filter(is_active=True).values_list("name", flat=True)
                )
        except Exception:
            logger.debug("consult-pad: lab catalog unavailable for hospital %s — using seed table only", hospital_id)

    candidates = _lab_candidate_map(catalog_names, alias_iter)
    keys = list(candidates)
    resolved = [_resolve_investigation(t, candidates, keys, process, fuzz) for t in tokens]
    recognized["investigations_resolved"] = resolved
    recognized["investigations"] = ", ".join(dict.fromkeys(r["name"] for r in resolved if r["name"]))
def _decode_pages(page_datauris):
    out = []
    for u in page_datauris or []:
        try:
            out.append(base64.b64decode(u.split(",", 1)[1]))
        except Exception:
            pass
    return out
def _public_recog(blob):
    """Strip the internal per-page transcription cache before a recognised
    blob is returned to any client."""
    if not blob:
        return None
    return {k: v for k, v in blob.items() if k != "_page_texts"}
# One recognition at a time per (session, tab). The phone autosaves every few
# strokes and each spawns a thread; without this they'd fire N concurrent
# vision calls into the provider's small per-minute budget and all get 429'd.
# Threads queue on the lock, and every one but the newest bails instantly once
# it's their turn (their "at" token is stale) — so a burst collapses to a
# single recognition on the freshest pages.
_RECOG_LOCKS = {}
_RECOG_LOCKS_GUARD = threading.Lock()
_RECOG_LOCK_WAIT = 200  # seconds a queued thread will wait its turn before giving up
# done is better than a bare empty, which is better than failed, which is
# better than the pending placeholder. A completed recognition must be allowed
# to replace a WORSE result a sibling thread landed while this one was still
# retrying — otherwise a good transcription is thrown away behind a "failed".
_RESULT_RANK = {"pending": 0, "failed": 1, "empty": 2, "done": 3}
def _session_recog_lock(session_id, tab):
    key = (session_id, tab)
    with _RECOG_LOCKS_GUARD:
        lk = _RECOG_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _RECOG_LOCKS[key] = lk
        return lk
def _land_recognition(session_id, field, blob, pending_token):
    """Compare-and-swap the recognised blob onto the row: land it when it
    outranks (or ties-newer) what's stored, or when we're still the exact
    pending marker we came in on. Retries on a lost CAS."""
    for _ in range(4):
        cur = (ConsultSession.objects.using("default")
               .filter(id=session_id).values(field).first())
        if cur is None:
            return False
        curblob = cur[field] or {}
        cur_at = curblob.get("at") or ""
        my_rank = _RESULT_RANK.get(blob.get("status"), 0)
        cur_rank = _RESULT_RANK.get(curblob.get("status"), 0)
        may_land = (
            curblob.get("at") == pending_token          # we're the newest autosave
            or my_rank > cur_rank                        # we're a better result
            or (my_rank == cur_rank and blob["at"] >= cur_at)  # same, but newer
        )
        if not may_land:
            return False
        updated = ConsultSession.objects.using("default").filter(
            id=session_id, **{f"{field}__at": cur_at}
        ).update(**{field: blob})
        if updated:
            return True
    return False
def _run_tab_recognition(session_id, tab: str, pending_token: str):
    """
    Background worker: recognise one tab's pages and write the structured
    result onto ConsultSession.<tab>_recognised. Runs in a plain thread
    (no task queue in this project). Never raises.

    `pending_token` is the "at" stamp written by the recognise trigger that
    spawned this thread. The thread bails if the stamp changed (the doctor
    hit Load again), queues on a per-tab lock so a double-click can't run two
    at once, and re-uses already-transcribed pages via the page-text cache so
    only NEW pages hit the model. The write-back is rank-aware — a completed
    result replaces a worse one landed meanwhile.
    """
    from apps.atomwalk.patients.services import recognise
    field = "rx_recognised" if tab == "rx" else "note_recognised"
    pages_attr = "rx_pages" if tab == "rx" else "note_pages"
    try:
        row = (ConsultSession.objects.using("default")
               .filter(id=session_id).values(field).first())
        if not row:
            return
        if (row[field] or {}).get("at") != pending_token:
            logger.debug("consult-pad recognition superseded before start (session=%s tab=%s)", session_id, tab)
            return

        lock = _session_recog_lock(session_id, tab)
        if not lock.acquire(timeout=_RECOG_LOCK_WAIT):
            logger.warning("consult-pad recognition gave up waiting for the lock (session=%s tab=%s)", session_id, tab)
            return
        try:
            row = (ConsultSession.objects.using("default")
                   .filter(id=session_id).values(field, pages_attr, "hospital_id").first())
            if not row:
                return
            if (row[field] or {}).get("at") != pending_token:
                logger.debug("consult-pad recognition superseded while queued (session=%s tab=%s)", session_id, tab)
                return

            pages = _decode_pages(row[pages_attr])
            if not pages:
                _land_recognition(session_id, field,
                                  {"status": "empty", "error": "", "at": timezone.now().isoformat()},
                                  pending_token)
                return

            prev_cache = (row[field] or {}).get("_page_texts") or {}
            result = recognise(pages, focus=tab, page_text_cache=prev_cache)
            blob = dict(result.get("recognized") or {})
            if result.get("status") == "done":
                if tab == "rx" and row["hospital_id"]:
                    _normalise_rx_against_catalog(blob, row["hospital_id"])
                if tab != "rx":
                    _normalise_investigations_against_catalog(blob, row["hospital_id"])
            blob["status"] = result["status"]
            blob["error"] = result.get("error", "")
            blob["at"] = timezone.now().isoformat()

            if not _land_recognition(session_id, field, blob, pending_token):
                logger.debug("consult-pad recognition result not landed — a better/newer one is stored (session=%s tab=%s)", session_id, tab)
        finally:
            lock.release()
    except Exception:
        logger.exception("consult-session recognition thread crashed: session=%s tab=%s", session_id, tab)
        _land_recognition(session_id, field,
                          {"status": "failed", "error": "recognition crashed", "at": timezone.now().isoformat()},
                          pending_token)
    finally:
        connections.close_all()
def _open_session_for_token(token: str):
    """token -> (identity, the ConsultSession while it is still open, else None). A token belongs to ONE consultation."""
    session = ConsultSession.objects.using("default").filter(token=token).first()
    identity = Patient.objects.using("default").filter(awpid=session.awpid).first() if session else None
    if not identity:
        return None, None
    if session.status != ConsultSession.STATUS_OPEN:
        return identity, None
    # Auto-expire a stale session so the phone doesn't keep writing to it.
    if session.expires_at and session.expires_at < timezone.now():
        ConsultSession.objects.using("default").filter(id=session.id).update(status=ConsultSession.STATUS_EXPIRED)
        return identity, None
    return identity, session
class ConsultPadView(APIView):
    """
    GET  /api/v1/consult-pad/<token>/   — patient header + both tabs' saved state
    PUT  /api/v1/consult-pad/<token>/   — autosave one tab
                                          Body: { "tab": "rx"|"note", "pages": ["data:image/png;base64,...", ...] }

    No auth. GET's "active" is false when the doctor hasn't started a session
    yet. PUT is a no-op (404-ish) once the session is signed/expired.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "consult_pad"

    def get(self, request, token):
        identity, sess = _open_session_for_token(token)
        if not identity:
            return error(message="This code is not valid. Ask the front desk for a fresh QR.", status=404)
        if not sess:
            return success(data={
                "active": False,
                "patient_name": identity.full_name,
                "patient_awpid": identity.awpid,
            })
        return success(data={
            "active": True,
            # Identifies THIS consultation, so the phone can tell whether crash-saved local writing belongs to the
            # session it's resuming or to a previous one (which it then discards).
            "session_id": sess.id,
            "patient_name": identity.full_name,
            "patient_awpid": identity.awpid,
            "age_years": (_age_years_months(identity.date_of_birth) or (None,))[0],
            "age_months": (_age_years_months(identity.date_of_birth) or (None, None))[1],
            "gender": identity.gender,
            "updated_at": sess.updated_at,
            "tabs": {
                "rx":   {"pages": sess.rx_pages or [],   "recognised": _public_recog(sess.rx_recognised)},
                "note": {"pages": sess.note_pages or [], "recognised": _public_recog(sess.note_recognised)},
            },
        })

    def put(self, request, token):
        identity, sess = _open_session_for_token(token)
        if not identity:
            return error(message="This code is not valid. Ask the front desk for a fresh QR.", status=404)
        if not sess:
            return error(message="This consultation isn't active. The doctor needs to start it.", status=409)

        tab = (request.data.get("tab") or "").strip()
        if tab not in _TABS:
            return error("tab must be 'rx' or 'note'.", errors={"tab": "Required."})

        pages = request.data.get("pages")
        if not isinstance(pages, list):
            return error("pages must be a list.", errors={"pages": "Required."})
        pages = [p for p in pages if p]
        if len(pages) > 20:
            return error("Please keep a note under 20 pages.")
        if sum(len(p) for p in pages) > _MAX_TAB_BASE64_CHARS:
            return error("That tab is too large to save — fewer / simpler pages.")
        for p in pages:
            try:
                validate_data_uri(p, allowed_types=("image/png",))
            except FileValidationError as exc:
                return error(str(exc), errors={"pages": str(exc)})

        pages_field = "rx_pages" if tab == "rx" else "note_pages"
        recog_field = "rx_recognised" if tab == "rx" else "note_recognised"

        # Autosave saves the strokes ONLY — it never triggers recognition.
        # Transcription is lazy: it runs when the doctor presses "Load
        # handwritten note" (EncounterConsultSessionView, action=recognise),
        # re-using pages already transcribed so only new strokes hit the model.
        # Here we just keep any prior compiled result and mark the tab "dirty"
        # so the encounter screen knows there's un-loaded content.
        prev = getattr(sess, recog_field) or {}
        now = timezone.now()
        marker = now.isoformat()
        if pages:
            new_recog = {**prev, "status": "dirty", "at": marker}
        else:
            new_recog = {"status": "idle", "at": marker}
        ConsultSession.objects.using("default").filter(id=sess.id).update(**{
            pages_field: pages,
            recog_field: new_recog,
            # Sliding expiry — an actively-used pad shouldn't lapse mid-write.
            "expires_at": now + timedelta(hours=12),
            "updated_at": now,
        })

        return success(
            data={"tab": tab, "saved_pages": len(pages),
                  "recognise_status": new_recog["status"]},
            message="Saved.",
        )
