"""
apps/platform_admin/views.py
-----------------------------
API views accessible only to the Atomwalk platform admin (is_platform=True).

Endpoints:
  GET  /api/v1/platform/tenants/         — list all hospitals + subscription status
  POST /api/v1/platform/tenants/         — provision a new hospital
  GET  /api/v1/platform/tenants/{id}/    — tenant detail
  PATCH /api/v1/platform/tenants/{id}/   — update subscription tier / is_active

No management commands required — everything is done via API.
"""

import re
import secrets
import string
import logging
from datetime import date

from django.conf import settings
from django.utils.text import slugify
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsPlatformAdmin
from core.response import success, created, error, not_found
from core.pagination import paginate_queryset, paginate_list
from apps.tenants.models import Tenant, Subscription, TenantAuditLog
from apps.tenants.utils import create_tenant_database, run_tenant_migrations
from apps.tenants.constants import TIER_FEATURE_DEFAULTS
from apps.tenants.limits import get_usage_counts
from apps.org.models import StaffUser, Branch
from apps.registry.models import StaffMobileIndex

logger = logging.getLogger(__name__)


def _gen_password(length=14):
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


def _tenant_to_dict(tenant):
    try:
        sub = Subscription.objects.get(tenant=tenant)
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
        "id":         tenant.id,
        "name":       tenant.name,
        "subdomain":  tenant.subdomain,
        "db_name":    tenant.db_name,
        "city":       tenant.city,
        "state":      tenant.state,
        "gstin":      tenant.gstin,
        "accreditations": tenant.accreditations,
        "about":      tenant.about,
        "is_active":  tenant.is_active,
        "created_at": tenant.created_at.isoformat(),
        "subscription": subscription,
    }


def _usage_counts(tenant):
    """
    Live doctor/branch/staff counts from the tenant's own database, for
    comparing against Subscription.max_doctors/max_branches/max_staff on the
    platform-admin UI. Thin wrapper over apps.tenants.limits.get_usage_counts
    (the same helper the write-time limit checks use) — best-effort: a
    tenant DB that's unreachable or not yet migrated (e.g. mid-provisioning)
    shouldn't break the whole tenant list, so any failure here just reports
    unknown usage rather than raising.
    """
    try:
        return get_usage_counts(tenant.db_name)
    except Exception as exc:
        logger.warning("Usage count failed for %s: %s", tenant.db_name, exc)
        return {"doctors": None, "branches": None, "staff": None}


def _log_change(tenant, action, before, after, actor_email):
    TenantAuditLog.objects.create(
        tenant=tenant, action=action,
        before_value=str(before) if before is not None else "",
        after_value=str(after) if after is not None else "",
        actor_email=actor_email or "",
    )


class TenantListCreateView(APIView):
    """
    GET  /api/v1/platform/tenants/  — list all tenants
    POST /api/v1/platform/tenants/  — provision a new hospital
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        search = (request.query_params.get("search") or "").strip()
        tier_filter = (request.query_params.get("tier") or "").strip()
        status_filter = (request.query_params.get("status") or "").strip()

        tenants = Tenant.objects.all().order_by("-created_at")
        if search:
            tenants = tenants.filter(name__icontains=search) | tenants.filter(city__icontains=search)
            tenants = tenants.order_by("-created_at")

        # Stats are computed over the full search-matched set (before tier/
        # status filtering) so the summary cards stay a platform-wide picture
        # even while the list below is narrowed down.
        all_matching = list(tenants)
        tier_counts = {}
        status_counts = {}
        subs_by_tenant = {}
        for t in all_matching:
            try:
                sub = Subscription.objects.get(tenant=t)
                subs_by_tenant[t.id] = sub
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
            tenants = [t for t in all_matching
                       if subs_by_tenant.get(t.id) and subs_by_tenant[t.id].license_tier == tier_filter]
        if status_filter:
            base = tenants if tier_filter else all_matching
            tenants = [t for t in base
                       if subs_by_tenant.get(t.id) and subs_by_tenant[t.id].status == status_filter]
        if not tier_filter and not status_filter:
            tenants = all_matching

        page_items, meta = paginate_list(request, tenants)
        results = []
        for t in page_items:
            row = _tenant_to_dict(t)
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

        admin_email = (d.get("admin_email") or "").strip() or None

        tier = (d.get("tier") or "starter").strip()
        if tier not in TIER_FEATURE_DEFAULTS:
            return error(f"Invalid tier. Choose: {', '.join(TIER_FEATURE_DEFAULTS)}")

        # ── Derive subdomain and db_name ─────────────────────────────────────
        subdomain = (d.get("subdomain") or slugify(name)).strip().lower()
        db_name = "aw_" + subdomain.replace("-", "_")

        city  = (d.get("city") or "").strip()
        state = (d.get("state") or "").strip()
        gstin = (d.get("gstin") or "").strip()

        # ── Uniqueness checks ─────────────────────────────────────────────────
        if Tenant.objects.filter(subdomain=subdomain).exists():
            return error(f"Subdomain '{subdomain}' is already taken.",
                         errors={"subdomain": "Already exists."})
        if Tenant.objects.filter(db_name=db_name).exists():
            return error(f"DB name '{db_name}' conflicts with an existing tenant.",
                         errors={"subdomain": "Already exists."})

        # ── Step 1: Create Tenant record ──────────────────────────────────────
        tenant = Tenant.objects.create(
            name=name, subdomain=subdomain, db_name=db_name,
            city=city, state=state, gstin=gstin, is_active=True,
        )
        logger.info("Tenant created: %s (id=%s)", name, tenant.id)

        # ── Step 2: Create Subscription ───────────────────────────────────────
        feats = TIER_FEATURE_DEFAULTS[tier]
        Subscription.objects.create(tenant=tenant, license_tier=tier, status="active", **feats)

        # ── Step 3: Provision PostgreSQL database ─────────────────────────────
        try:
            create_tenant_database(db_name)
        except Exception as exc:
            tenant.delete()
            logger.error("DB creation failed for %s: %s", db_name, exc)
            return error(f"Failed to create tenant database: {exc}", status=500)

        # ── Step 4: Run migrations ─────────────────────────────────────────────
        try:
            run_tenant_migrations(db_name)
        except Exception as exc:
            logger.error("Migrations failed for %s: %s", db_name, exc)
            return error(f"Database setup failed: {exc}", status=500)

        # ── Step 5: Create hospital_admin StaffUser ────────────────────────────
        temp_password = _gen_password()
        admin_employee_id = None
        try:
            from apps.org.views import _next_employee_id
            admin_staff = StaffUser(
                phone=admin_mobile,
                email=admin_email,
                employee_id=_next_employee_id(db_name),
                first_name="Hospital",
                last_name="Admin",
                role="hospital_admin",
                must_change_password=True,
            )
            admin_staff.set_password(temp_password)
            admin_staff.save(using=db_name)
            admin_employee_id = admin_staff.employee_id

            # Write to registry index — login uses mobile, not subdomain
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=admin_mobile,
                defaults={"tenant_id": tenant.id, "db_name": db_name},
            )
            logger.info("hospital_admin created and indexed for tenant %s", subdomain)
        except Exception as exc:
            logger.error("StaffUser creation failed: %s", exc)
            temp_password = None

        _log_change(tenant, "created", "", f"{tier} tier", getattr(request.user, "email", "") or "")

        response_data = {
            **_tenant_to_dict(tenant),
            "credentials": {
                "subdomain":     subdomain,
                "admin_mobile":  admin_mobile,
                "employee_id":   admin_employee_id,
                "temp_password": temp_password,
                "note": (
                    "Share these credentials with the hospital admin. "
                    "They should change the password on first login. Mobile + "
                    "password is enough to log in — the Employee ID is only "
                    "needed if they'd rather log in with subdomain + "
                    "Employee ID instead of their mobile number."
                ),
            } if temp_password else {
                "note": "Admin account creation failed — create via /api/v1/org/staff/."
            },
        }

        return created(data=response_data,
                       message=f"Hospital '{name}' provisioned successfully.")


class TenantDetailView(APIView):
    """
    GET   /api/v1/platform/tenants/{id}/ — tenant detail
    PATCH /api/v1/platform/tenants/{id}/ — update tier or active status
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _get_tenant(self, pk):
        try:
            return Tenant.objects.get(pk=pk)
        except Tenant.DoesNotExist:
            return None

    def get(self, request, pk):
        tenant = self._get_tenant(pk)
        if not tenant:
            return not_found("Tenant not found.")
        data = _tenant_to_dict(tenant)
        data["usage"] = _usage_counts(tenant)
        return success(data=data)

    def patch(self, request, pk):
        tenant = self._get_tenant(pk)
        if not tenant:
            return not_found("Tenant not found.")

        d = request.data
        updated_fields = []
        actor_email = getattr(request.user, "email", "") or ""

        # ── Hospital Code (subdomain) — separate from the plain profile
        # fields below because it needs validation + a uniqueness check, and
        # because it's login-relevant (see auth_app.views.StaffLoginView's
        # employee-ID path) rather than purely cosmetic. Safe to change any
        # time after creation — it's looked up live at login, and db_name
        # (fixed forever once the tenant DB is created) never derives from
        # it after the initial provisioning step.
        if "subdomain" in d:
            new_subdomain = slugify((d["subdomain"] or "").strip())
            if not new_subdomain:
                return error("Hospital Code is required.", errors={"subdomain": "Required."})
            if not re.match(r"^[a-z0-9-]+$", new_subdomain):
                return error("Hospital Code can only contain lowercase letters, numbers, and hyphens.",
                             errors={"subdomain": "Invalid format."})
            if Tenant.objects.exclude(pk=tenant.pk).filter(subdomain=new_subdomain).exists():
                return error(f"Hospital Code '{new_subdomain}' is already taken.",
                             errors={"subdomain": "Already exists."})
            before_subdomain = tenant.subdomain
            tenant.subdomain = new_subdomain
            tenant.save(update_fields=["subdomain"])
            updated_fields.append("subdomain")
            if before_subdomain != new_subdomain:
                _log_change(tenant, "subdomain_change", before_subdomain, new_subdomain, actor_email)

        # ── Profile fields — plain edits, no audit-log entry (that's reserved
        # for tier/status/active lifecycle changes; a name/city typo fix isn't
        # a "hospital lifecycle" event worth showing in that trail). ─────────
        profile_fields = ["name", "city", "state", "gstin", "accreditations", "about"]
        profile_updated = []
        for field in profile_fields:
            if field in d:
                setattr(tenant, field, (d[field] or "").strip() if field != "about" else (d[field] or ""))
                profile_updated.append(field)
        if profile_updated:
            tenant.save(update_fields=profile_updated)
            updated_fields.append("profile")

        if "is_active" in d:
            before = tenant.is_active
            tenant.is_active = bool(d["is_active"])
            tenant.save(update_fields=["is_active"])
            updated_fields.append("is_active")
            _log_change(tenant, "active_change",
                        "Active" if before else "Suspended",
                        "Active" if tenant.is_active else "Suspended",
                        actor_email)

        new_tier = d.get("tier")
        if new_tier:
            if new_tier not in TIER_FEATURE_DEFAULTS:
                return error(f"Invalid tier. Choose: {', '.join(TIER_FEATURE_DEFAULTS)}")
            feats = TIER_FEATURE_DEFAULTS[new_tier]
            try:
                sub = Subscription.objects.get(tenant=tenant)
                before_tier = sub.license_tier
                sub.license_tier = new_tier
                for k, v in feats.items():
                    setattr(sub, k, v)
                sub.save()
            except Subscription.DoesNotExist:
                before_tier = None
                Subscription.objects.create(tenant=tenant, license_tier=new_tier,
                                            status="active", **feats)
            updated_fields.append("subscription")
            _log_change(tenant, "tier_change", before_tier, new_tier, actor_email)

        # Manually move a tenant through the subscription lifecycle — e.g.
        # mark them 'suspended' for a serious issue, or roll back a mistaken
        # 'frozen' state, without having to touch/reset their tier. Enforced
        # in core/authentication.py: frozen/suspended blocks all API access
        # for that hospital's staff, read_only blocks writes only.
        new_status = d.get("status")
        if new_status:
            valid_statuses = dict(Subscription.STATUS_CHOICES)
            if new_status not in valid_statuses:
                return error(f"Invalid status. Choose: {', '.join(valid_statuses)}")
            try:
                sub = Subscription.objects.get(tenant=tenant)
            except Subscription.DoesNotExist:
                return error("This tenant has no subscription record yet — set a tier first.")
            before_status = sub.status
            sub.status = new_status
            sub.save(update_fields=["status"])
            updated_fields.append("status")
            _log_change(tenant, "status_change", before_status, new_status, actor_email)

        return success(data=_tenant_to_dict(tenant),
                       message=f"Updated: {', '.join(updated_fields) or 'nothing'}.")


class TenantAuditLogView(APIView):
    """
    GET /api/v1/platform/tenants/{id}/audit-log/ — history of tier/status/
    active changes for one hospital, most recent first.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, pk):
        try:
            tenant = Tenant.objects.get(pk=pk)
        except Tenant.DoesNotExist:
            return not_found("Tenant not found.")

        logs = TenantAuditLog.objects.filter(tenant=tenant)[:100]
        return success(data=[{
            "id": log.id,
            "action": log.action,
            "action_label": dict(TenantAuditLog.ACTION_CHOICES).get(log.action, log.action),
            "before_value": log.before_value,
            "after_value": log.after_value,
            "actor_email": log.actor_email,
            "created_at": log.created_at.isoformat(),
        } for log in logs])


class PlatformStatsView(APIView):
    """
    GET /api/v1/platform/stats/ — platform-wide usage metrics for the
    Dashboard's hero panel, plus a cross-tenant recent-activity feed.

    Every number here is a live count from a real table — no revenue,
    system-health, or other figures are included since nothing in the
    codebase currently tracks pricing, payments, or infrastructure health.
    Best-effort per tenant: an unreachable tenant DB is skipped for the
    usage totals (and logged) rather than failing the whole request.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from apps.patients.models import Patient
        from apps.opd.models import Appointment

        tenants = list(Tenant.objects.all())
        today = date.today()
        month_start = today.replace(day=1)

        totals = {"doctors": 0, "staff": 0, "patients": 0, "appointments_today": 0}
        unreachable = 0
        for t in tenants:
            try:
                totals["doctors"] += StaffUser.objects.using(t.db_name).filter(
                    role="doctor", is_active=True).count()
                totals["staff"] += StaffUser.objects.using(t.db_name).filter(is_active=True).count()
                totals["patients"] += Patient.objects.using(t.db_name).count()
                totals["appointments_today"] += Appointment.objects.using(t.db_name).filter(
                    scheduled_date=today).count()
            except Exception as exc:
                unreachable += 1
                logger.warning("Stats aggregation skipped tenant %s: %s", t.db_name, exc)

        new_this_month = sum(1 for t in tenants if t.created_at.date() >= month_start)

        recent_logs = TenantAuditLog.objects.select_related("tenant").order_by("-created_at")[:15]
        activity = [{
            "id": log.id,
            "hospital_name": log.tenant.name,
            "action": log.action,
            "action_label": dict(TenantAuditLog.ACTION_CHOICES).get(log.action, log.action),
            "before_value": log.before_value,
            "after_value": log.after_value,
            "actor_email": log.actor_email,
            "created_at": log.created_at.isoformat(),
        } for log in recent_logs]

        return success(data={
            "usage": totals,
            "new_this_month": new_this_month,
            "unreachable_tenants": unreachable,
            "recent_activity": activity,
        })


class TenantOverviewView(APIView):
    """
    GET /api/v1/platform/tenants/{id}/overview/ — counts backing the
    hospital detail page's Overview tab: branches, doctors, staff,
    patients, and today's appointments. No storage figure is returned —
    nothing in this project tracks per-tenant storage usage.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, pk):
        from apps.patients.models import Patient
        from apps.opd.models import Appointment

        try:
            tenant = Tenant.objects.get(pk=pk)
        except Tenant.DoesNotExist:
            return not_found("Tenant not found.")

        try:
            data = {
                "branches": Branch.objects.using(tenant.db_name).filter(is_active=True).count(),
                "doctors": StaffUser.objects.using(tenant.db_name).filter(
                    role="doctor", is_active=True).count(),
                "staff": StaffUser.objects.using(tenant.db_name).filter(is_active=True).count(),
                "patients": Patient.objects.using(tenant.db_name).count(),
                "appointments_today": Appointment.objects.using(tenant.db_name).filter(
                    scheduled_date=date.today()).count(),
            }
        except Exception as exc:
            logger.warning("Overview failed for %s: %s", tenant.db_name, exc)
            return error("This hospital's database couldn't be reached.", status=502)

        return success(data=data)


class TenantStaffListView(APIView):
    """
    GET /api/v1/platform/tenants/{id}/staff/ — every staff member at one
    hospital, for the hospital detail page's Users & Roles tab.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, pk):
        try:
            tenant = Tenant.objects.get(pk=pk)
        except Tenant.DoesNotExist:
            return not_found("Tenant not found.")

        try:
            staff = StaffUser.objects.using(tenant.db_name).all().order_by("role", "first_name")
        except Exception as exc:
            logger.warning("Staff list failed for %s: %s", tenant.db_name, exc)
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


class TenantStaffDetailView(APIView):
    """
    PATCH /api/v1/platform/tenants/{id}/staff/{staff_id}/ — deactivate/
    reactivate a staff member or change their role, from the platform side.

    POST  /api/v1/platform/tenants/{id}/staff/{staff_id}/reset-password/
    — generate a new temp password and force a change on next login, same
    mechanism used at hospital provisioning time.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _get(self, tenant_id, staff_id):
        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist:
            return None, None
        try:
            staff = StaffUser.objects.using(tenant.db_name).get(pk=staff_id)
        except StaffUser.DoesNotExist:
            return tenant, None
        return tenant, staff

    def patch(self, request, pk, staff_id):
        tenant, staff = self._get(pk, staff_id)
        if not tenant:
            return not_found("Tenant not found.")
        if not staff:
            return not_found("Staff member not found.")

        d = request.data

        # Refuse to deactivate or role-change away the last active
        # hospital_admin at this tenant — that would lock the hospital out
        # of its own admin panel with no one able to invite a replacement.
        would_lose_admin_status = (
            staff.role == "hospital_admin" and staff.is_active and (
                ("is_active" in d and not bool(d["is_active"])) or
                ("role" in d and d["role"] != "hospital_admin")
            )
        )
        if would_lose_admin_status:
            other_admins = StaffUser.objects.using(tenant.db_name).filter(
                role="hospital_admin", is_active=True
            ).exclude(pk=staff.id).exists()
            if not other_admins:
                return error(
                    "This is the only active hospital admin at this hospital — "
                    "deactivating or changing their role would lock the hospital "
                    "out of its own admin panel. Promote another staff member to "
                    "hospital_admin first.",
                )

        # ── Subscription limit check (fails CLOSED — see apps.tenants.limits) ──
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
        old_resource = "doctors" if staff.role == "doctor" else "staff"
        new_resource = "doctors" if final_role == "doctor" else "staff"
        needs_limit_check = (
            (not was_active and final_active) or
            (was_active and final_active and old_resource != new_resource)
        )
        if needs_limit_check:
            from apps.tenants.limits import check_limit, LimitCheckFailed
            try:
                check_limit(tenant, tenant.db_name, new_resource)
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
            staff.save(using=tenant.db_name, update_fields=updated)
        return success(data={"id": staff.id, "is_active": staff.is_active, "role": staff.role},
                       message=f"Updated: {', '.join(updated) or 'nothing'}.")


class TenantStaffResetPasswordView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request, pk, staff_id):
        try:
            tenant = Tenant.objects.get(pk=pk)
        except Tenant.DoesNotExist:
            return not_found("Tenant not found.")
        try:
            staff = StaffUser.objects.using(tenant.db_name).get(pk=staff_id)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        temp_password = _gen_password()
        staff.set_password(temp_password)
        staff.must_change_password = True
        staff.save(using=tenant.db_name, update_fields=["password", "must_change_password"])
        return success(data={"temp_password": temp_password},
                       message=f"Password reset for {staff.email}. Share the temp password securely.")


class PlatformUserListView(APIView):
    """
    GET /api/v1/platform/users/ — global cross-tenant staff directory.
    Loops every tenant DB (fine at the current handful-of-hospitals scale;
    would need a registry-side mirror table to stay fast at real scale).
    Supports ?search=, ?role=, ?status=(active|inactive), ?hospital_id=.
    """
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        search = (request.query_params.get("search") or "").strip().lower()
        role_filter = (request.query_params.get("role") or "").strip()
        status_filter = (request.query_params.get("status") or "").strip()
        hospital_id = request.query_params.get("hospital_id")

        tenants = Tenant.objects.all()
        if hospital_id:
            tenants = tenants.filter(pk=hospital_id)

        results = []
        for t in tenants:
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
                logger.warning("User directory skipped tenant %s: %s", t.db_name, exc)

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
