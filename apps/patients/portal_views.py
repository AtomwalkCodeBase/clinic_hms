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
import secrets
import logging
from datetime import date, datetime, time as dtime, timedelta

from django.conf import settings
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


def _new_awpid():
    return f"AWPID-{date.today().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()[:8]}"


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
        d = request.data
        required = ["full_name", "mobile", "password"]
        missing = [f for f in required if not str(d.get(f, "")).strip()]
        if missing:
            return error(f"Missing fields: {', '.join(missing)}")

        mobile = d["mobile"].strip()
        if not re.match(r"^\+?\d{7,15}$", mobile):
            return error("Enter a valid mobile number.", errors={"mobile": "Invalid format."})
        if PatientAccount.objects.using("default").filter(mobile=mobile).exists():
            return error("An account with this mobile number already exists. Please log in.")

        email = (d.get("email") or "").strip().lower() or None
        if email and PatientAccount.objects.using("default").filter(email__iexact=email).exists():
            return error("An account with this email already exists.")

        acct = PatientAccount(
            awpid=_new_awpid(),
            full_name=d["full_name"].strip(),
            email=email,
            mobile=mobile,
            gender=(d.get("gender") or "")[:1].upper(),
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

# OPD slot grid: 09:00–13:00 and 14:00–18:00, 15-minute slots.
def _slot_grid():
    slots = []
    for start_h, end_h in ((9, 13), (14, 18)):
        t = dtime(start_h, 0)
        while t < dtime(end_h, 0):
            slots.append(t.strftime("%H:%M"))
            t = (datetime.combine(date.today(), t) + timedelta(minutes=15)).time()
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
        for s in _slot_grid():
            past = is_today and s <= now.strftime("%H:%M")
            results.append({
                "time": s,
                "available": (s not in booked) and not past,
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
            try:
                _ensure_db(b.db_name)
                appt = Appointment.objects.using(b.db_name).get(pk=b.appointment_id)
                status_now = _auto_expire_if_stale(appt, b.db_name)
                token = appt.token_number
                slot_time = appt.scheduled_time.strftime("%H:%M") if appt.scheduled_time else None
                doctor_id = appt.doctor_user_id
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
                # Blank on bookings made before family members existed —
                # those were always for the account owner.
                "patient_name": b.patient_name or None,
                "patient_awpid": b.patient_awpid or None,
            })
        return Response({"results": results, "pagination": meta})


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

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        qs = (SharedDocument.objects.using("default")
              .filter(awpid=acct.awpid)
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

        acct = PatientAccount.objects.using("default").get(pk=request.user.id)
        results = []

        for tenant in Tenant.objects.using("default").filter(is_active=True):
            db = tenant.db_name
            try:
                _ensure_db(db)
                patient = Patient.objects.using(db).filter(awpid=acct.awpid).first()
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
                               .filter(awpid=acct.awpid, source_ref=f"labreq:{db}:{r.id}")
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
        if lab_req.patient.awpid != acct.awpid:
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
        if lab_req.patient.awpid != acct.awpid:
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
            mobile = (d.get("mobile") or "").strip()
            if mobile and not re.match(r"^\+?\d{7,15}$", mobile):
                return error("Enter a valid mobile number.", errors={"mobile": "Invalid format."})
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
            if phone and not re.match(r"^\+?\d{7,15}$", phone):
                return error("Enter a valid emergency contact number.", errors={"emergency_contact_phone": "Invalid format."})
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
