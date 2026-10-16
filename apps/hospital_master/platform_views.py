"""
apps/hospital_master/platform_views.py
-----------------------------
API views accessible only to the Atomwalk platform admin (is_platform=True).

Endpoints:
  GET  /api/v1/platform/hospitals/         — list all hospitals + subscription status
  POST /api/v1/platform/hospitals/         — provision a new hospital
  GET  /api/v1/platform/hospitals/{id}/    — hospital detail
  PATCH /api/v1/platform/hospitals/{id}/   — update subscription tier / is_active

No management commands required — everything is done via API.
"""

import re
import secrets
import string
import logging
from datetime import date

from django.db.models import Q
from django.utils.text import slugify
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.api.permissions import IsPlatformAdmin
from core.api.response import success, created, error, not_found
from core.api.pagination import paginate_list
from apps.hospital_master.models import Hospital, Subscription, HospitalAuditLog
from apps.hospital_master.services import create_hospital_database, run_hospital_migrations, drop_hospital_database
from apps.hospital_master.services import TIER_FEATURE_DEFAULTS
from apps.hospital_master.services import get_usage_counts
from apps.hospital_master.services import parameters_of
from apps.hospital_setup.models import StaffUser
from apps.hospital_setup.models import Branch
from apps.patients.models import StaffMobileIndex

logger = logging.getLogger(__name__)


def _gen_password(length=14):
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


def _teardown_failed_hospital(hospital):
    """
    Roll back a partially-provisioned hospital (see HospitalListCreateView.post
    Steps 3/4). Subscription.hospital is a OneToOneField with on_delete=
    PROTECT, so a bare hospital.delete() raises ProtectedError as long as its
    Subscription row still exists — Subscription must go first.
    """
    Subscription.objects.filter(hospital=hospital).delete()
    hospital.delete()


def _hospital_to_dict(hospital):
    try:
        sub = Subscription.objects.get(hospital=hospital)
        subscription = {
            "license_tier": sub.license_tier,
            "status": sub.status,
            "max_doctors": sub.max_doctors,
            "max_branches": sub.max_branches,
            "max_staff": sub.max_staff,
            "feat_lab": sub.feat_lab,
            "feat_pharmacy": sub.feat_pharmacy,
            "feat_whatsapp": sub.feat_whatsapp,
            "feat_multi_branch": sub.feat_multi_branch,
            "feat_ai_voice": sub.feat_ai_voice,
            "feat_patient_app": sub.feat_patient_app,
            "feat_analytics": sub.feat_analytics,
            "feat_video": sub.feat_video,
            "feat_face_recog": sub.feat_face_recog,
            "feat_custom_roles": sub.feat_custom_roles,
        }
    except Subscription.DoesNotExist:
        subscription = None

    return {
        "id":         hospital.id,
        "name":       hospital.name,
        "hospital_code":  hospital.hospital_code,
        "db_name":    hospital.db_name,
        "city":       hospital.city,
        "state":      hospital.state,
        "gstin":      hospital.gstin,
        "accreditations": parameters_of(hospital).accreditations,
        "about":      parameters_of(hospital).about,
        "latitude":   parameters_of(hospital).latitude,
        "longitude":  parameters_of(hospital).longitude,
        "is_active":  hospital.is_active,
        "created_at": hospital.created_at.isoformat(),
        "subscription": subscription,
    }


def _usage_counts(hospital):
    """
    Live doctor/branch/staff counts from the hospital's own database, for
    comparing against Subscription.max_doctors/max_branches/max_staff on the
    platform-admin UI. Thin wrapper over apps.hospital_master.services.get_usage_counts
    (the same helper the write-time limit checks use) — best-effort: a
    hospital DB that's unreachable or not yet migrated (e.g. mid-provisioning)
    shouldn't break the whole hospital list, so any failure here just reports
    unknown usage rather than raising.
    """
    try:
        return get_usage_counts(hospital.db_name)
    except Exception as exc:
        logger.warning("Usage count failed for %s: %s", hospital.db_name, exc)
        return {"doctors": None, "branches": None, "staff": None}


def _log_change(hospital, action, before, after, actor_email):
    HospitalAuditLog.objects.create(
        hospital=hospital, action=action,
        before_value=str(before) if before is not None else "",
        after_value=str(after) if after is not None else "",
        actor_email=actor_email or "",
    )


class HospitalListCreateView(APIView):
    """
    GET  /api/v1/platform/hospitals/  — list all hospitals
    POST /api/v1/platform/hospitals/  — provision a new hospital
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        search = (request.query_params.get("search") or "").strip()
        tier_filter = (request.query_params.get("tier") or "").strip()
        status_filter = (request.query_params.get("status") or "").strip()

        hospitals = Hospital.objects.all().order_by("-created_at")
        if search:
            hospitals = hospitals.filter(name__icontains=search) | hospitals.filter(city__icontains=search)
            hospitals = hospitals.order_by("-created_at")

        # Stats are computed over the full search-matched set (before tier/
        # status filtering) so the summary cards stay a platform-wide picture
        # even while the list below is narrowed down.
        all_matching = list(hospitals)
        tier_counts = {}
        status_counts = {}
        subs_by_hospital = {}
        for t in all_matching:
            try:
                sub = Subscription.objects.get(hospital=t)
                subs_by_hospital[t.id] = sub
                tier_counts[sub.license_tier] = tier_counts.get(sub.license_tier, 0) + 1
                status_counts[sub.status] = status_counts.get(sub.status, 0) + 1
            except Subscription.DoesNotExist:
                pass
        stats = {
            "total": len(all_matching),
            "active": sum(1 for t in all_matching if t.is_active),
            "tiers": tier_counts,
            "statuses": status_counts,
        }

        if tier_filter:
            hospitals = [t for t in all_matching
                       if subs_by_hospital.get(t.id) and subs_by_hospital[t.id].license_tier == tier_filter]
        if status_filter:
            base = hospitals if tier_filter else all_matching
            hospitals = [t for t in base
                       if subs_by_hospital.get(t.id) and subs_by_hospital[t.id].status == status_filter]
        if not tier_filter and not status_filter:
            hospitals = all_matching

        page_items, meta = paginate_list(request, hospitals)
        results = []
        for t in page_items:
            row = _hospital_to_dict(t)
            row["usage"] = _usage_counts(t)
            results.append(row)
        return success(data={
            "results": results,
            "pagination": meta,
            "stats": stats,
        })

    def post(self, request):
        d = request.data

        # ── Validate required fields ─────────────────────────────────────────
        name = (d.get("name") or "").strip()
        if not name:
            return error("Hospital name is required.", errors={"name": "Required."})

        admin_mobile = (d.get("admin_mobile") or "").strip()
        if not admin_mobile:
            return error("Admin mobile number is required.", errors={"admin_mobile": "Required."})
        if not re.match(r"^\d{10}$", admin_mobile):
            return error("Enter a valid 10-digit mobile number.", errors={"admin_mobile": "Invalid format."})

        # A mobile number already routed to another hospital must not be
        # silently reassigned — that would hijack that person's login there.
        if StaffMobileIndex.objects.using("default").filter(mobile=admin_mobile).exists():
            return error(
                f"Mobile number {admin_mobile} is already registered at another hospital.",
                errors={"admin_mobile": "Already in use."},
            )

        admin_email = (d.get("admin_email") or "").strip()
        if not admin_email:
            return error("Admin email is required.", errors={"admin_email": "Required."})
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", admin_email):
            return error("Enter a valid email address.", errors={"admin_email": "Invalid format."})
        from core.utils.realworld_validation import validate_email_domain
        email_ok, email_reason = validate_email_domain(admin_email)
        if not email_ok:
            return error(email_reason, errors={"admin_email": email_reason})

        tier = (d.get("tier") or "starter").strip()
        if tier not in TIER_FEATURE_DEFAULTS:
            return error(f"Invalid tier. Choose: {', '.join(TIER_FEATURE_DEFAULTS)}")

        # ── Derive hospital_code and db_name ─────────────────────────────────────
        hospital_code = (d.get("hospital_code") or slugify(name)).strip().lower()[:20]
        db_name = "aw_" + hospital_code.replace("-", "_")

        city  = (d.get("city") or "").strip()
        state = (d.get("state") or "").strip()
        gstin = (d.get("gstin") or "").strip()

        # ── Uniqueness checks ─────────────────────────────────────────────────
        if Hospital.objects.filter(hospital_code=hospital_code).exists():
            return error(f"Hospital code '{hospital_code}' is already taken.",
                         errors={"hospital_code": "Already exists."})
        if Hospital.objects.filter(db_name=db_name).exists():
            return error(f"DB name '{db_name}' conflicts with an existing hospital.",
                         errors={"hospital_code": "Already exists."})

        # ── Step 1: Create Hospital record ──────────────────────────────────────
        hospital = Hospital.objects.create(
            name=name, hospital_code=hospital_code, db_name=db_name,
            city=city, state=state, gstin=gstin, is_active=True,
        )
        logger.info("Hospital created: %s (id=%s)", name, hospital.id)

        # ── Step 2: Create Subscription ───────────────────────────────────────
        feats = TIER_FEATURE_DEFAULTS[tier]
        Subscription.objects.create(hospital=hospital, license_tier=tier, status="active", **feats)

        # ── Step 3: Provision PostgreSQL database ─────────────────────────────
        try:
            create_hospital_database(db_name)
        except Exception as exc:
            _teardown_failed_hospital(hospital)
            logger.error("DB creation failed for %s: %s", db_name, exc)
            return error(f"Failed to create hospital database: {exc}", status=500)

        # ── Step 4: Run migrations ─────────────────────────────────────────────
        try:
            run_hospital_migrations(db_name)
        except Exception as exc:
            logger.error("Migrations failed for %s: %s", db_name, exc)
            # Unlike the DB-creation failure above, this step runs against a
            # database that DOES exist by now — leaving it and the Hospital/
            # Subscription rows behind (as this used to) permanently reserves
            # the hospital_code/db_name and makes every retry fail with
            # "Hospital code already taken" instead of the real underlying error,
            # with no way to retry short of a manual DB cleanup. Tear both
            # down so a retry (even with the same name) starts clean.
            drop_hospital_database(db_name)
            _teardown_failed_hospital(hospital)
            return error(f"Database setup failed: {exc}", status=500)

        # ── Step 5: Create hospital_admin StaffUser ────────────────────────────
        temp_password = _gen_password()
        admin_employee_id = None
        email_sent = False
        try:
            from apps.hospital_setup.staff_services import next_employee_id
            admin_staff = StaffUser(
                phone=admin_mobile,
                email=admin_email,
                employee_id=next_employee_id(db_name),
                first_name="Hospital",
                last_name="Admin",
                role="hospital_admin",
                must_change_password=True,
            )
            admin_staff.set_password(temp_password)
            admin_staff.save(using=db_name)
            admin_employee_id = admin_staff.employee_id

            # Write to atomwalk index — login uses mobile, not hospital_code
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=admin_mobile,
                defaults={"hospital_id": hospital.id},
            )
            logger.info("hospital_admin created and indexed for hospital %s", hospital_code)

            # Email is the only place the raw temp password goes — the
            # provisioning UI deliberately doesn't display it on screen (see
            # DashboardPage.jsx ProvisionModal). A delivery failure must not
            # fail provisioning itself; the API response still carries the
            # password as a fallback so the platform admin can hand it over
            # another way if the email bounces.
            from core.messaging.email import send_hospital_provisioned_email
            email_sent = send_hospital_provisioned_email(
                to=admin_email, hospital_name=name, hospital_code=hospital_code,
                employee_id=admin_employee_id, admin_mobile=admin_mobile,
                temp_password=temp_password,
            )
        except Exception as exc:
            logger.error("StaffUser creation failed: %s", exc)
            temp_password = None

        _log_change(hospital, "created", "", f"{tier} tier", getattr(request.user, "email", "") or "")

        response_data = {
            **_hospital_to_dict(hospital),
            "credentials": {
                "hospital_code":     hospital_code,
                "admin_email":   admin_email,
                "admin_mobile":  admin_mobile,
                "employee_id":   admin_employee_id,
                "temp_password": temp_password,
                "email_sent":    email_sent,
                "note": (
                    (f"A login email with the temporary password was sent to {admin_email}. "
                     if email_sent else
                     "We couldn't send the login email automatically — share the "
                     "temporary password below with the hospital admin directly. ")
                    + "They should change the password on first login. Mobile + "
                    "password is enough to log in — the Employee ID + Hospital "
                    "Code is an alternative if they'd rather not use their "
                    "mobile number."
                ),
            } if temp_password else {
                "note": "Admin account creation failed — create via /api/v1/org/staff/."
            },
        }

        return created(data=response_data,
                       message=f"Hospital '{name}' provisioned successfully.")


class HospitalDetailView(APIView):
    """
    GET   /api/v1/platform/hospitals/{id}/ — hospital detail
    PATCH /api/v1/platform/hospitals/{id}/ — update tier or active status
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _get_hospital(self, pk):
        try:
            return Hospital.objects.get(pk=pk)
        except Hospital.DoesNotExist:
            return None

    def get(self, request, pk):
        hospital = self._get_hospital(pk)
        if not hospital:
            return not_found("Hospital not found.")
        data = _hospital_to_dict(hospital)
        data["usage"] = _usage_counts(hospital)
        return success(data=data)

    def patch(self, request, pk):
        hospital = self._get_hospital(pk)
        if not hospital:
            return not_found("Hospital not found.")

        d = request.data
        updated_fields = []
        actor_email = getattr(request.user, "email", "") or ""

        # ── Hospital Code (hospital_code) — separate from the plain profile
        # fields below because it needs validation + a uniqueness check, and
        # because it's login-relevant (see core.auth.views.StaffLoginView's
        # employee-ID path) rather than purely cosmetic. Safe to change any
        # time after creation — it's looked up live at login, and db_name
        # (fixed forever once the hospital DB is created) never derives from
        # it after the initial provisioning step.
        if "hospital_code" in d:
            new_hospital_code = slugify((d["hospital_code"] or "").strip())
            if not new_hospital_code:
                return error("Hospital Code is required.", errors={"hospital_code": "Required."})
            if not re.match(r"^[a-z0-9-]+$", new_hospital_code):
                return error("Hospital Code can only contain lowercase letters, numbers, and hyphens.",
                             errors={"hospital_code": "Invalid format."})
            if Hospital.objects.exclude(pk=hospital.pk).filter(hospital_code=new_hospital_code).exists():
                return error(f"Hospital Code '{new_hospital_code}' is already taken.",
                             errors={"hospital_code": "Already exists."})
            before_hospital_code = hospital.hospital_code
            hospital.hospital_code = new_hospital_code
            hospital.save(update_fields=["hospital_code"])
            updated_fields.append("hospital_code")
            if before_hospital_code != new_hospital_code:
                _log_change(hospital, "code_change", before_hospital_code, new_hospital_code, actor_email)

        # ── Profile fields — plain edits, no audit-log entry (that's reserved
        # for tier/status/active lifecycle changes; a name/city typo fix isn't
        # a "hospital lifecycle" event worth showing in that trail). ─────────
        params = parameters_of(hospital)
        profile_updated = []
        for field in ["name", "city", "state", "gstin"]:
            if field in d:
                setattr(hospital, field, (d[field] or "").strip())
                profile_updated.append(field)
        if profile_updated:
            hospital.save(update_fields=profile_updated)
        parameter_updated = []
        for field in ["accreditations", "about"]:
            if field in d:
                setattr(params, field, (d[field] or "").strip() if field != "about" else (d[field] or ""))
                parameter_updated.append(field)
        if parameter_updated:
            params.save(update_fields=parameter_updated)
        if profile_updated or parameter_updated:
            updated_fields.append("profile")

        # ── Coordinates — power the patient app's "hospitals near me"
        # (apps.patients.views, core.utils.geo.haversine_km). Sent as
        # numbers, not the free-text profile fields above: validated to
        # real-world lat/lng ranges so a typo can't quietly break every
        # distance sort. Either key alone clears just that one field
        # (empty string/null → None) rather than requiring both at once.
        geo_updated = []
        if "latitude" in d or "longitude" in d:
            for field, lo, hi in (("latitude", -90, 90), ("longitude", -180, 180)):
                if field not in d:
                    continue
                raw = d[field]
                if raw in (None, ""):
                    setattr(params, field, None)
                    geo_updated.append(field)
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    return error(f"{field.capitalize()} must be a number.", errors={field: "Invalid number."})
                if not (lo <= value <= hi):
                    return error(f"{field.capitalize()} must be between {lo} and {hi}.", errors={field: "Out of range."})
                setattr(params, field, value)
                geo_updated.append(field)
        if geo_updated:
            params.save(update_fields=geo_updated)
            updated_fields.append("coordinates")

        if "is_active" in d:
            before = hospital.is_active
            hospital.is_active = bool(d["is_active"])
            hospital.save(update_fields=["is_active"])
            updated_fields.append("is_active")
            _log_change(hospital, "active_change",
                        "Active" if before else "Suspended",
                        "Active" if hospital.is_active else "Suspended",
                        actor_email)

        new_tier = d.get("tier")
        if new_tier:
            if new_tier not in TIER_FEATURE_DEFAULTS:
                return error(f"Invalid tier. Choose: {', '.join(TIER_FEATURE_DEFAULTS)}")
            feats = TIER_FEATURE_DEFAULTS[new_tier]
            try:
                sub = Subscription.objects.get(hospital=hospital)
                before_tier = sub.license_tier
                sub.license_tier = new_tier
                for k, v in feats.items():
                    setattr(sub, k, v)
                sub.save()
            except Subscription.DoesNotExist:
                before_tier = None
                Subscription.objects.create(hospital=hospital, license_tier=new_tier,
                                            status="active", **feats)
            updated_fields.append("subscription")
            _log_change(hospital, "tier_change", before_tier, new_tier, actor_email)

        # Manually move a hospital through the subscription lifecycle — e.g.
        # mark them 'suspended' for a serious issue, or roll back a mistaken
        # 'frozen' state, without having to touch/reset their tier. Enforced
        # in core/api/authentication.py: frozen/suspended blocks all API access
        # for that hospital's staff, read_only blocks writes only.
        new_status = d.get("status")
        if new_status:
            valid_statuses = dict(Subscription.STATUS_CHOICES)
            if new_status not in valid_statuses:
                return error(f"Invalid status. Choose: {', '.join(valid_statuses)}")
            try:
                sub = Subscription.objects.get(hospital=hospital)
            except Subscription.DoesNotExist:
                return error("This hospital has no subscription record yet — set a tier first.")
            before_status = sub.status
            sub.status = new_status
            sub.save(update_fields=["status"])
            updated_fields.append("status")
            _log_change(hospital, "status_change", before_status, new_status, actor_email)

        return success(data=_hospital_to_dict(hospital),
                       message=f"Updated: {', '.join(updated_fields) or 'nothing'}.")


class HospitalAuditLogView(APIView):
    """
    GET /api/v1/platform/hospitals/{id}/audit-log/ — history of tier/status/
    active changes for one hospital, most recent first.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, pk):
        try:
            hospital = Hospital.objects.get(pk=pk)
        except Hospital.DoesNotExist:
            return not_found("Hospital not found.")

        logs = HospitalAuditLog.objects.filter(hospital=hospital)[:100]
        return success(data=[{
            "id": log.id,
            "action": log.action,
            "action_label": dict(HospitalAuditLog.ACTION_CHOICES).get(log.action, log.action),
            "before_value": log.before_value,
            "after_value": log.after_value,
            "actor_email": log.actor_email,
            "created_at": log.created_at.isoformat(),
        } for log in logs])


class PlatformStatsView(APIView):
    """
    GET /api/v1/platform/stats/ — platform-wide usage metrics for the
    Dashboard's hero panel, plus a cross-hospital recent-activity feed.

    Every number here is a live count from a real table — no revenue,
    system-health, or other figures are included since nothing in the
    codebase currently tracks pricing, payments, or infrastructure health.
    Best-effort per hospital: an unreachable hospital DB is skipped for the
    usage totals (and logged) rather than failing the whole request.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.opd.models import HospitalPatient
        from apps.opd.models import Appointment

        hospitals = list(Hospital.objects.all())
        today = date.today()
        month_start = today.replace(day=1)

        totals = {"doctors": 0, "staff": 0, "patients": 0, "appointments_today": 0}
        unreachable = 0
        for t in hospitals:
            try:
                totals["doctors"] += StaffUser.objects.using(t.db_name).filter(
                    role="doctor", is_active=True).count()
                totals["staff"] += StaffUser.objects.using(t.db_name).filter(is_active=True).count()
                totals["patients"] += HospitalPatient.objects.using(t.db_name).count()
                totals["appointments_today"] += Appointment.objects.using(t.db_name).filter(
                    scheduled_date=today).count()
            except Exception as exc:
                unreachable += 1
                logger.warning("Stats aggregation skipped hospital %s: %s", t.db_name, exc)

        new_this_month = sum(1 for t in hospitals if t.created_at.date() >= month_start)

        recent_logs = HospitalAuditLog.objects.select_related("hospital").order_by("-created_at")[:15]
        activity = [{
            "id": log.id,
            "hospital_name": log.hospital.name if log.hospital else "",
            "action": log.action,
            "action_label": dict(HospitalAuditLog.ACTION_CHOICES).get(log.action, log.action),
            "before_value": log.before_value,
            "after_value": log.after_value,
            "actor_email": log.actor_email,
            "created_at": log.created_at.isoformat(),
        } for log in recent_logs]

        return success(data={
            "usage": totals,
            "new_this_month": new_this_month,
            "unreachable_hospitals": unreachable,
            "recent_activity": activity,
        })


class HospitalOverviewView(APIView):
    """
    GET /api/v1/platform/hospitals/{id}/overview/ — counts backing the
    hospital detail page's Overview tab: branches, doctors, staff,
    patients, and today's appointments. No storage figure is returned —
    nothing in this project tracks per-hospital storage usage.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, pk):
        from apps.opd.models import HospitalPatient
        from apps.opd.models import Appointment

        try:
            hospital = Hospital.objects.get(pk=pk)
        except Hospital.DoesNotExist:
            return not_found("Hospital not found.")

        try:
            data = {
                "branches": Branch.objects.using(hospital.db_name).filter(is_active=True).count(),
                "doctors": StaffUser.objects.using(hospital.db_name).filter(
                    role="doctor", is_active=True).count(),
                "staff": StaffUser.objects.using(hospital.db_name).filter(is_active=True).count(),
                "patients": HospitalPatient.objects.using(hospital.db_name).count(),
                "appointments_today": Appointment.objects.using(hospital.db_name).filter(
                    scheduled_date=date.today()).count(),
            }
        except Exception as exc:
            logger.warning("Overview failed for %s: %s", hospital.db_name, exc)
            return error("This hospital's database couldn't be reached.", status=502)

        return success(data=data)


class HospitalStaffListView(APIView):
    """
    GET /api/v1/platform/hospitals/{id}/staff/ — every staff member at one
    hospital, for the hospital detail page's Users & Roles tab.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, pk):
        try:
            hospital = Hospital.objects.get(pk=pk)
        except Hospital.DoesNotExist:
            return not_found("Hospital not found.")

        try:
            staff = StaffUser.objects.using(hospital.db_name).all().order_by("role", "first_name")
        except Exception as exc:
            logger.warning("Staff list failed for %s: %s", hospital.db_name, exc)
            return error("This hospital's database couldn't be reached.", status=502)

        return success(data=[{
            "id": s.id,
            "full_name": s.get_full_name(),
            "email": s.email,
            "role": s.role,
            "phone": s.phone,
            "is_active": s.is_active,
            "must_change_password": s.must_change_password,
            "date_joined": s.date_joined.isoformat() if s.date_joined else None,
            "last_login": s.last_login.isoformat() if s.last_login else None,
        } for s in staff])


class HospitalStaffDetailView(APIView):
    """
    PATCH /api/v1/platform/hospitals/{id}/staff/{staff_id}/ — deactivate/
    reactivate a staff member or change their role, from the platform side.

    POST  /api/v1/platform/hospitals/{id}/staff/{staff_id}/reset-password/
    — generate a new temp password and force a change on next login, same
    mechanism used at hospital provisioning time.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _get(self, hospital_id, staff_id):
        try:
            hospital = Hospital.objects.get(pk=hospital_id)
        except Hospital.DoesNotExist:
            return None, None
        try:
            staff = StaffUser.objects.using(hospital.db_name).get(pk=staff_id)
        except StaffUser.DoesNotExist:
            return hospital, None
        return hospital, staff

    def patch(self, request, pk, staff_id):
        hospital, staff = self._get(pk, staff_id)
        if not hospital:
            return not_found("Hospital not found.")
        if not staff:
            return not_found("Staff member not found.")

        d = request.data

        # Refuse to deactivate or role-change away the last active
        # hospital_admin at this hospital — that would lock the hospital out
        # of its own admin panel with no one able to invite a replacement.
        # Checks acts_as too — a custom role bundling "hospital_admin" counts
        # as an effective admin here just like a literal one (see the
        # matching fix in apps/org/views.py).
        staff_acts_as = set((staff.custom_role.acts_as if staff.custom_role else []) or [])
        staff_is_admin = staff.role == "hospital_admin" or "hospital_admin" in staff_acts_as
        would_lose_admin_status = (
            staff_is_admin and staff.is_active and (
                ("is_active" in d and not bool(d["is_active"])) or
                ("role" in d and d["role"] != "hospital_admin")
            )
        )
        if would_lose_admin_status:
            ADMIN_Q = Q(role="hospital_admin") | Q(role="custom", custom_role__acts_as__contains=["hospital_admin"])
            other_admins = StaffUser.objects.using(hospital.db_name).filter(
                ADMIN_Q, is_active=True
            ).exclude(pk=staff.id).exists()
            if not other_admins:
                return error(
                    "This is the only active hospital admin at this hospital — "
                    "deactivating or changing their role would lock the hospital "
                    "out of its own admin panel. Promote another staff member to "
                    "hospital_admin first.",
                )

        # ── Subscription limit check (fails CLOSED — see apps.hospital_master.services) ──
        # Reactivating a deactivated staff member, or role-changing an active
        # one across the doctor/non-doctor line, both put a new person into a
        # capacity bucket (max_doctors / max_staff) without freeing a slot
        # anywhere else — check before committing either change.
        was_active  = staff.is_active
        final_active = bool(d["is_active"]) if "is_active" in d else was_active
        new_role = d.get("role")
        if new_role:
            valid_roles = dict(StaffUser.ROLE_CHOICES)
            if new_role not in valid_roles:
                return error(f"Invalid role. Choose: {', '.join(valid_roles)}")
        final_role = new_role or staff.role
        # Checks acts_as too — a custom role bundling "doctor" must count
        # against max_doctors, not max_staff, same as a literal doctor (see
        # the matching is_doctor_equivalent pattern in apps/org/views.py).
        # This endpoint doesn't assign custom roles itself (new_role is
        # always one of the 6 system roles), so only the OLD side can be
        # role="custom" here.
        old_is_doctor = staff.role == "doctor" or "doctor" in staff_acts_as
        old_resource = "doctors" if old_is_doctor else "staff"
        new_resource = "doctors" if final_role == "doctor" else "staff"
        needs_limit_check = (
            (not was_active and final_active) or
            (was_active and final_active and old_resource != new_resource)
        )
        if needs_limit_check:
            from apps.hospital_master.services import check_limit, LimitCheckFailed
            try:
                check_limit(hospital, hospital.db_name, new_resource)
            except LimitCheckFailed as exc:
                return error(exc.message, status=exc.status)

        updated = []
        if "is_active" in d:
            staff.is_active = final_active
            updated.append("is_active")
        if new_role:
            staff.role = new_role
            updated.append("role")
        if updated:
            staff.save(using=hospital.db_name, update_fields=updated)
        return success(data={"id": staff.id, "is_active": staff.is_active, "role": staff.role},
                       message=f"Updated: {', '.join(updated) or 'nothing'}.")


class HospitalStaffResetPasswordView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request, pk, staff_id):
        try:
            hospital = Hospital.objects.get(pk=pk)
        except Hospital.DoesNotExist:
            return not_found("Hospital not found.")
        try:
            staff = StaffUser.objects.using(hospital.db_name).get(pk=staff_id)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        temp_password = _gen_password()
        staff.set_password(temp_password)
        staff.must_change_password = True
        staff.save(using=hospital.db_name, update_fields=["password", "must_change_password"])
        return success(data={"temp_password": temp_password},
                       message=f"Password reset for {staff.email}. Share the temp password securely.")


class PlatformUserListView(APIView):
    """
    GET /api/v1/platform/users/ — global cross-hospital staff directory.
    Loops every hospital DB (fine at the current handful-of-hospitals scale;
    would need a atomwalk-side mirror table to stay fast at real scale).
    Supports ?search=, ?role=, ?status=(active|inactive), ?hospital_id=.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        search = (request.query_params.get("search") or "").strip().lower()
        role_filter = (request.query_params.get("role") or "").strip()
        status_filter = (request.query_params.get("status") or "").strip()
        hospital_id = request.query_params.get("hospital_id")

        hospitals = Hospital.objects.all()
        if hospital_id:
            hospitals = hospitals.filter(pk=hospital_id)

        results = []
        for t in hospitals:
            try:
                qs = StaffUser.objects.using(t.db_name).all()
                if role_filter:
                    qs = qs.filter(role=role_filter)
                if status_filter == "active":
                    qs = qs.filter(is_active=True)
                elif status_filter == "inactive":
                    qs = qs.filter(is_active=False)
                for s in qs:
                    full_name = s.get_full_name()
                    if search and search not in full_name.lower() and search not in s.email.lower():
                        continue
                    results.append({
                        "id": s.id,
                        "hospital_id": t.id,
                        "hospital_name": t.name,
                        "full_name": full_name,
                        "email": s.email,
                        "role": s.role,
                        "is_active": s.is_active,
                        "last_login": s.last_login.isoformat() if s.last_login else None,
                    })
            except Exception as exc:
                logger.warning("User directory skipped hospital %s: %s", t.db_name, exc)

        results.sort(key=lambda r: (r["hospital_name"], r["full_name"]))
        page_items, meta = paginate_list(request, results, default_page_size=50, max_page_size=200)
        return success(data={"results": page_items, "pagination": meta})


class PlanListView(APIView):
    """
    GET /api/v1/platform/plans/ — the 4 license tiers' feature sets and
    limits, for the Subscriptions page's comparison table. No pricing is
    included — there is no pricing model anywhere in this system (no price
    field on Subscription, no billing/invoicing feature at all), so nothing
    here should imply a dollar/rupee figure that isn't real.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        return success(data=[{
            "tier": tier,
            **feats,
        } for tier, feats in TIER_FEATURE_DEFAULTS.items()])
