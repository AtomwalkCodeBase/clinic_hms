"""
apps/org/views.py
-----------------
Org management APIs for hospital admin setup.

Hospital admin flow:
  1. Create branches (physical locations)
  2. Create departments within branches
  3. Invite staff (generates invite token → staff sets own password)
  4. Create/update doctor profiles

All views require IsAuthenticated + IsHospitalAdmin unless noted.
IsHospitalStaff allows read-only access where indicated.
"""

import jwt
import secrets
import string
import logging
from datetime import timedelta, datetime

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsHospitalAdmin, IsHospitalStaff, IsDoctor, RequireFeature
from core.response import success, created, error, not_found
from core.pagination import paginate_queryset
from apps.registry.models import StaffMobileIndex

from .models import Branch, Department, StaffUser, DoctorProfile, StaffProfile, Role, Permission, UserRole

logger = logging.getLogger(__name__)


# NNTM entity config: (entity_key, prefix, pad_length)
_NNTM_ENTITIES = [
    ("uhid",         "UHID-", 6),
    ("invoice",      "INV-",  6),
    ("lab_report",   "LAB-",  6),
    ("lab_test",     "LT-",   4),
    ("prescription", "RX-",   6),
    ("queue",        "Q-",    4),
]


def _seed_next_numbers(branch_id: int, db_name: str) -> None:
    """Create NNTM counter rows for a new branch (idempotent — skips if already exist)."""
    from apps.org.models import NextNumber
    for entity, prefix, pad in _NNTM_ENTITIES:
        NextNumber.objects.using(db_name).get_or_create(
            branch_id=branch_id,
            entity=entity,
            defaults={"prefix": prefix, "pad_length": pad, "last_number": 0},
        )


def _next_employee_id(db_name: str) -> str:
    """
    Auto-generate the next Employee ID via NNTM — see core/utils/nntm.py and
    docs/onboarding_auth_rbac_architecture.md 3.1.2. Unlike UHID/invoice/etc,
    Employee ID is a hospital-WIDE sequence (a staff member isn't tied to one
    branch the way a UHID is), so it uses the sentinel branch_id=0 rather
    than being seeded per-branch in _seed_next_numbers above. Lazily
    get_or_create's its counter row on first use so this self-heals for
    tenants provisioned before this feature existed, with no migration or
    provisioning-script change required.

    Never manually editable — see StaffInviteSerializer / StaffDetailView.
    """
    from apps.org.models import NextNumber
    from core.utils.nntm import get_next_number

    NextNumber.objects.using(db_name).get_or_create(
        branch_id=0, entity="employee_id",
        defaults={"prefix": "EMP-", "pad_length": 6, "last_number": 0},
    )
    formatted_id, _ = get_next_number(0, "employee_id", using=db_name)
    return formatted_id


from .serializers import (
    BranchSerializer,
    DepartmentSerializer,
    StaffSerializer,
    StaffInviteSerializer,
    DoctorProfileSerializer,
    DoctorSelfProfileSerializer,
    StaffMeSerializer,
    StaffProfileSerializer,
    StaffProfileSelfSerializer,
    PermissionSerializer,
    RoleSerializer,
    RoleWriteSerializer,
)

# Rough cap on the base64 photo payload — keeps us comfortably under DRF's
# default 2.5MB request-body limit (DATA_UPLOAD_MAX_MEMORY_SIZE) while still
# allowing a reasonably sized profile photo. ~1.4MB of actual image data.
_MAX_PHOTO_BASE64_CHARS = 1_900_000


def _gen_temp_password(length=12) -> str:
    """Generate a readable temporary password."""
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


def _make_invite_token(staff_id: int, tenant_db: str) -> str:
    """
    Generate a signed invite token for the setup-password flow.
    Valid for 48 hours. Accepted only by /api/v1/auth/setup-password/.
    """
    payload = {
        "staff_id":   staff_id,
        "tenant_db":  tenant_db,
        "token_type": "invite",
        "exp":        timezone.now() + timedelta(hours=48),
        "jti":        secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm="HS256")


# ── Branches ──────────────────────────────────────────────────────────────────

class BranchListCreateView(APIView):
    """
    GET  /api/v1/org/branches/ — list all branches (any staff)
    POST /api/v1/org/branches/ — create branch (hospital admin only)
    """
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        branches = Branch.objects.using(request.tenant_db).filter(is_active=True)
        return success(data=BranchSerializer(branches, many=True).data)

    def post(self, request):
        # ── Subscription limit check (fails CLOSED — see apps.tenants.limits) ──
        from apps.tenants.models import Tenant
        from apps.tenants.limits import check_limit, LimitCheckFailed
        try:
            tenant = Tenant.objects.using("default").get(pk=request.tenant_id)
            check_limit(tenant, request.tenant_db, "branches")
        except Tenant.DoesNotExist:
            return error("Unable to verify your plan limits right now. Please try again shortly.", status=503)
        except LimitCheckFailed as exc:
            return error(exc.message, status=exc.status)

        s = BranchSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        # Instantiate without save, then save with explicit `using=`
        branch = Branch(**s.validated_data)
        branch.save(using=request.tenant_db)

        # Seed NNTM rows so UHID / invoice / lab / Rx / queue numbers work immediately
        _seed_next_numbers(branch.id, request.tenant_db)

        return created(data=BranchSerializer(branch).data, message="Branch created.")


class BranchDetailView(APIView):
    """
    GET   /api/v1/org/branches/{id}/ — branch detail
    PATCH /api/v1/org/branches/{id}/ — update branch
    DELETE /api/v1/org/branches/{id}/ — deactivate (soft delete)
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return Branch.objects.using(request.tenant_db).get(pk=pk)
        except Branch.DoesNotExist:
            return None

    def get(self, request, pk):
        branch = self._get(request, pk)
        if not branch:
            return not_found("Branch not found.")
        return success(data=BranchSerializer(branch).data)

    def patch(self, request, pk):
        branch = self._get(request, pk)
        if not branch:
            return not_found("Branch not found.")
        s = BranchSerializer(branch, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(branch, attr, val)
        branch.save(using=request.tenant_db)
        return success(data=BranchSerializer(branch).data, message="Branch updated.")

    def delete(self, request, pk):
        branch = self._get(request, pk)
        if not branch:
            return not_found("Branch not found.")
        branch.is_active = False
        branch.save(using=request.tenant_db, update_fields=["is_active"])
        return success(message="Branch deactivated.")


# ── Departments ───────────────────────────────────────────────────────────────

class DepartmentListCreateView(APIView):
    """
    GET  /api/v1/org/departments/?branch_id=1  — list departments
    POST /api/v1/org/departments/              — create department
    """
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = Department.objects.using(request.tenant_db).filter(is_active=True)
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return success(data=DepartmentSerializer(qs, many=True).data)

    def post(self, request):
        s = DepartmentSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        # Verify branch belongs to this tenant
        branch_id = s.validated_data["branch"].id
        try:
            branch = Branch.objects.using(request.tenant_db).get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            return error("Branch not found.", errors={"branch": "Invalid branch."})

        dept = Department(branch=branch, name=s.validated_data["name"])
        dept.save(using=request.tenant_db)
        return created(data=DepartmentSerializer(dept).data, message="Department created.")


class DepartmentDetailView(APIView):
    """PATCH /api/v1/org/departments/{id}/ — rename or deactivate."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return Department.objects.using(request.tenant_db).get(pk=pk)
        except Department.DoesNotExist:
            return None

    def patch(self, request, pk):
        dept = self._get(request, pk)
        if not dept:
            return not_found("Department not found.")
        s = DepartmentSerializer(dept, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(dept, attr, val)
        dept.save(using=request.tenant_db)
        return success(data=DepartmentSerializer(dept).data, message="Department updated.")

    def delete(self, request, pk):
        dept = self._get(request, pk)
        if not dept:
            return not_found("Department not found.")
        dept.is_active = False
        dept.save(using=request.tenant_db, update_fields=["is_active"])
        return success(message="Department deactivated.")


# ── Staff ─────────────────────────────────────────────────────────────────────

class StaffListView(APIView):
    """GET /api/v1/org/staff/ — list all staff members."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        qs = StaffUser.objects.using(request.tenant_db).select_related(
            "branch", "department"
        ).prefetch_related("doctor_profile")
        role_filter = request.query_params.get("role")
        if role_filter:
            qs = qs.filter(role=role_filter)
        active_only = request.query_params.get("active", "true")
        if active_only.lower() != "false":
            qs = qs.filter(is_active=True)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(phone__icontains=search) |
                Q(email__icontains=search)
            )
        qs = qs.order_by("first_name", "last_name")
        page_items, meta = paginate_queryset(request, qs)
        return success(data={
            "results": StaffSerializer(page_items, many=True).data,
            "pagination": meta,
        })


class StaffInviteView(APIView):
    """
    POST /api/v1/org/staff/invite/
    Creates a staff user with unusable password.
    Returns an invite_token for the staff member to set their own password via
    POST /api/v1/auth/setup-password/.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request):
        s = StaffInviteSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data

        # ── Subscription limit check (fails CLOSED — see apps.tenants.limits) ──
        # Applies whether this ends up creating a brand-new StaffUser or
        # reactivating a previously-deactivated one below — either way the
        # active headcount for this role goes up by one, and a deactivated
        # account isn't counted in current usage, so the same check (with its
        # default increment=1) is correct for both paths.
        from apps.tenants.models import Tenant
        from apps.tenants.limits import check_limit, LimitCheckFailed
        resource = "doctors" if d["role"] == "doctor" else "staff"
        try:
            tenant = Tenant.objects.using("default").get(pk=request.tenant_id)
            check_limit(tenant, request.tenant_db, resource)
        except Tenant.DoesNotExist:
            return error("Unable to verify your plan limits right now. Please try again shortly.", status=503)
        except LimitCheckFailed as exc:
            return error(exc.message, status=exc.status)

        # A mobile number already routed to a *different* hospital must not be
        # silently reassigned here — that would hijack that person's login at
        # their existing hospital. Only proceed if it's unused, or already
        # points at this same tenant (the reactivation path below).
        existing_index = StaffMobileIndex.objects.using("default").filter(mobile=d["phone"]).first()
        if existing_index and existing_index.db_name != request.tenant_db:
            return error(
                f"Mobile number {d['phone']} is already registered at another hospital.",
                errors={"phone": "Already in use."},
            )

        existing = StaffUser.objects.using(request.tenant_db).filter(phone=d["phone"]).first()
        if existing:
            if existing.is_active:
                return error(f"Staff with mobile number {d['phone']} already exists.")
            # Reactivate a previously deactivated staff member
            temp_password = _gen_temp_password()
            existing.is_active            = True
            existing.first_name           = d["first_name"]
            existing.last_name            = d.get("last_name", existing.last_name)
            existing.role                 = d["role"]
            existing.email                = d.get("email") or existing.email
            # Employee ID is auto-generated via NNTM, never typed in — see
            # _next_employee_id. Someone predating this feature (or created
            # before it) may not have one yet; assign it now rather than
            # leaving it permanently blank. Once set it never changes.
            if not existing.employee_id:
                existing.employee_id = _next_employee_id(request.tenant_db)
            existing.must_change_password = True
            existing.set_password(temp_password)
            existing.save(using=request.tenant_db)
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=d["phone"],
                defaults={"tenant_id": request.tenant_id, "db_name": request.tenant_db},
            )
            if "branch_ids" in d:
                from .branch_utils import set_staff_branches
                set_staff_branches(existing, d.get("branch_ids") or [], d.get("branch_id"), request.tenant_db)
                existing.save(using=request.tenant_db, update_fields=["branch"])
            return created(data={
                **StaffSerializer(existing).data,
                "temp_password": temp_password,
                "note": "Account reactivated. Share these credentials with the staff member.",
            }, message=f"{existing.get_full_name()} reactivated.")

        # Resolve branch
        branch = None
        if d.get("branch_id"):
            try:
                branch = Branch.objects.using(request.tenant_db).get(
                    pk=d["branch_id"], is_active=True
                )
            except Branch.DoesNotExist:
                return error("Branch not found.", errors={"branch_id": "Invalid."})

        # Resolve department (optional)
        department = None
        if d.get("department_id"):
            try:
                department = Department.objects.using(request.tenant_db).get(
                    pk=d["department_id"], is_active=True
                )
            except Department.DoesNotExist:
                return error("Department not found.", errors={"department_id": "Invalid."})

        temp_password = _gen_temp_password()
        staff = StaffUser(
            phone=d["phone"],
            email=d.get("email") or None,
            employee_id=_next_employee_id(request.tenant_db),
            first_name=d["first_name"],
            last_name=d.get("last_name", ""),
            role=d["role"],
            branch=branch,
            department=department,
            must_change_password=True,
        )
        staff.set_password(temp_password)
        staff.save(using=request.tenant_db)

        # Extra branches beyond the primary — meaningful for doctors who
        # work more than one location; harmless single-row equivalent to
        # the legacy branch FK for every other role. Only acts if the
        # caller actually sent branch_ids (most invites won't).
        if d.get("branch_ids"):
            from .branch_utils import set_staff_branches
            set_staff_branches(staff, d["branch_ids"], branch.id if branch else None, request.tenant_db)
            staff.save(using=request.tenant_db, update_fields=["branch"])

        # Doctor basics — admin enters these now so patient-facing cards are
        # never blank; the doctor fills in the rest themselves after login.
        if d["role"] == "doctor" and any(
            d.get(f) for f in ("registration_no", "specialisation", "qualification", "experience_years")
        ):
            DoctorProfile.objects.using(request.tenant_db).create(
                staff=staff,
                registration_no=d.get("registration_no", ""),
                specialisation=d.get("specialisation", ""),
                qualification=d.get("qualification", ""),
                experience_years=d.get("experience_years"),
            )
        # Same basics for every other role — nursing/pharmacy council
        # registration is legally required before those accounts should be
        # treated as active, and nobody should end up with a blank profile.
        elif d["role"] != "doctor" and any(
            d.get(f) for f in ("registration_no", "council_name", "registration_expiry",
                               "qualification", "experience_years")
        ):
            StaffProfile.objects.using(request.tenant_db).create(
                staff=staff,
                registration_no=d.get("registration_no", ""),
                council_name=d.get("council_name", ""),
                registration_expiry=d.get("registration_expiry"),
                qualification=d.get("qualification", ""),
                experience_years=d.get("experience_years"),
            )

        # Write to registry index so login can route by mobile (no subdomain needed)
        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=d["phone"],
            defaults={"tenant_id": request.tenant_id, "db_name": request.tenant_db},
        )

        return created(data={
            **StaffSerializer(staff).data,
            "temp_password": temp_password,
            "note": "Share these credentials with the staff member. They will be prompted to change the password on first login.",
        }, message=f"{staff.get_full_name()} invited.")


class StaffDetailView(APIView):
    """
    GET   /api/v1/org/staff/{id}/  — staff member detail
    PATCH /api/v1/org/staff/{id}/  — update role, branch, department, phone
    DELETE /api/v1/org/staff/{id}/ — deactivate (soft)
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return StaffUser.objects.using(request.tenant_db).get(pk=pk)
        except StaffUser.DoesNotExist:
            return None

    def get(self, request, pk):
        staff = self._get(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        return success(data=StaffSerializer(staff).data)

    def patch(self, request, pk):
        staff = self._get(request, pk)
        if not staff:
            return not_found("Staff member not found.")

        d = request.data

        # Changing the login mobile number needs the registry-wide index kept
        # in sync — otherwise the old number stays routed here and the new
        # one isn't routed anywhere, breaking this person's login either way.
        # Reject up front if it's already claimed by someone else.
        if "phone" in d and d["phone"] != staff.phone:
            clash = StaffMobileIndex.objects.using("default").filter(mobile=d["phone"]).exclude(
                tenant_id=request.tenant_id
            ).exists()
            if clash:
                return error(
                    f"Mobile number {d['phone']} is already registered at another hospital.",
                    errors={"phone": "Already in use."},
                )

        # Refuse to role-change away the last active hospital_admin — see the
        # matching check in apps/platform_admin/views.py for the deactivate
        # case (this view's DELETE, below, does the deactivate check).
        if "role" in d and d["role"] != "hospital_admin" and staff.role == "hospital_admin" and staff.is_active:
            other_admins = StaffUser.objects.using(request.tenant_db).filter(
                role="hospital_admin", is_active=True
            ).exclude(pk=staff.id).exists()
            if not other_admins:
                return error(
                    "This is the only active hospital admin — changing their role "
                    "would lock the hospital out of its own admin panel. Promote "
                    "another staff member to hospital_admin first.",
                )

        # A role change that crosses the doctor / non-doctor line moves this
        # person into a different capacity bucket (max_doctors vs max_staff)
        # without freeing up a slot anywhere — check the bucket they'd be
        # moving INTO before allowing it. No check needed for a role change
        # within the same bucket (e.g. nurse → front_desk) since the total
        # headcount in that bucket doesn't change.
        if "role" in d and staff.is_active and d["role"] != staff.role:
            old_resource = "doctors" if staff.role == "doctor" else "staff"
            new_resource = "doctors" if d["role"] == "doctor" else "staff"
            if new_resource != old_resource:
                from apps.tenants.models import Tenant
                from apps.tenants.limits import check_limit, LimitCheckFailed
                try:
                    tenant = Tenant.objects.using("default").get(pk=request.tenant_id)
                    check_limit(tenant, request.tenant_db, new_resource)
                except Tenant.DoesNotExist:
                    return error("Unable to verify your plan limits right now. Please try again shortly.", status=503)
                except LimitCheckFailed as exc:
                    return error(exc.message, status=exc.status)

        # employee_id is deliberately NOT in this list — it's auto-generated
        # via NNTM at creation time and never editable afterward (matches
        # how UHID/invoice numbers work). Assign one now if this record
        # predates the feature and somehow still doesn't have one.
        if not staff.employee_id:
            staff.employee_id = _next_employee_id(request.tenant_db)

        allowed = ["first_name", "last_name", "role", "phone", "date_of_birth", "branch_id", "department_id"]
        for field in allowed:
            if field in d:
                if field == "branch_id":
                    try:
                        staff.branch = Branch.objects.using(request.tenant_db).get(pk=d[field])
                    except Branch.DoesNotExist:
                        return error("Branch not found.")
                elif field == "department_id":
                    try:
                        staff.department = Department.objects.using(request.tenant_db).get(pk=d[field])
                    except Department.DoesNotExist:
                        return error("Department not found.")
                elif field == "date_of_birth":
                    dob = d.get("date_of_birth") or None
                    if dob:
                        try:
                            dob = datetime.strptime(dob, "%Y-%m-%d").date()
                        except ValueError:
                            return error("Date of birth must be YYYY-MM-DD.", errors={"date_of_birth": "Invalid format."})
                    staff.date_of_birth = dob
                else:
                    setattr(staff, field, d[field])

        staff.save(using=request.tenant_db)

        if "phone" in d:
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=staff.phone,
                defaults={"tenant_id": request.tenant_id, "db_name": request.tenant_db},
            )

        if "branch_id" in d:
            # Keep the mapping table's primary row matching the legacy FK
            # this endpoint just changed — see apps.org.branch_utils. Extra
            # (non-primary) branches, if any, are managed separately via
            # StaffBranchesView, not through this plain field.
            from .branch_utils import sync_primary_branch
            sync_primary_branch(staff, request.tenant_db)

        return success(data=StaffSerializer(staff).data, message="Staff updated.")

    def delete(self, request, pk):
        staff = self._get(request, pk)
        if not staff:
            return not_found("Staff member not found.")

        if staff.role == "hospital_admin" and staff.is_active:
            other_admins = StaffUser.objects.using(request.tenant_db).filter(
                role="hospital_admin", is_active=True
            ).exclude(pk=staff.id).exists()
            if not other_admins:
                return error(
                    "This is the only active hospital admin — deactivating them "
                    "would lock the hospital out of its own admin panel. Promote "
                    "another staff member to hospital_admin first.",
                )

        staff.is_active = False
        staff.save(using=request.tenant_db, update_fields=["is_active"])
        return success(message="Staff member deactivated.")


class StaffBranchesView(APIView):
    """
    GET /api/v1/org/staff/{id}/branches/ — this staff member's full branch
    assignment (usually just the one primary — see StaffBranchMapping).
    PUT /api/v1/org/staff/{id}/branches/  — replace it.
    Body: {"branch_ids": [1, 2], "primary_branch_id": 1}
    Meaningful for doctors who work more than one branch; harmless to use
    for any role (a single-entry list is equivalent to the legacy
    single-branch assignment).
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get_staff(self, request, pk):
        try:
            return StaffUser.objects.using(request.tenant_db).get(pk=pk)
        except StaffUser.DoesNotExist:
            return None

    def get(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        return success(data=StaffSerializer(staff).data["branches"])

    def put(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")

        branch_ids = request.data.get("branch_ids")
        if branch_ids is None or not isinstance(branch_ids, list):
            return error("branch_ids (a list) is required.", errors={"branch_ids": "Required."})
        primary_branch_id = request.data.get("primary_branch_id")

        if branch_ids:
            valid_ids = set(
                Branch.objects.using(request.tenant_db)
                .filter(pk__in=branch_ids, is_active=True)
                .values_list("id", flat=True)
            )
            invalid = set(int(b) for b in branch_ids) - valid_ids
            if invalid:
                return error(f"Unknown or inactive branch id(s): {sorted(invalid)}", errors={"branch_ids": "Invalid."})
            if primary_branch_id is not None and int(primary_branch_id) not in valid_ids:
                return error("primary_branch_id must be one of branch_ids.", errors={"primary_branch_id": "Invalid."})

        from .branch_utils import set_staff_branches
        set_staff_branches(staff, branch_ids, primary_branch_id, request.tenant_db)
        staff.save(using=request.tenant_db, update_fields=["branch"])

        return success(data=StaffSerializer(staff).data["branches"], message="Branch assignment updated.")


class MyBranchesView(APIView):
    """
    GET /api/v1/org/me/branches/ — the logged-in staff member's own branch
    assignment (self-service, read-only — branches are assigned by the
    hospital admin, see StaffBranchesView). Used by the frontend to decide
    whether to show a branch switcher: one entry (or zero, for staff who
    predate branch assignment entirely) means no switcher is needed.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        try:
            staff = StaffUser.objects.using(request.tenant_db).get(pk=request.user.id)
        except StaffUser.DoesNotExist:
            return not_found("Staff account not found.")
        return success(data=StaffSerializer(staff).data["branches"])


class StaffResendInviteView(APIView):
    """POST /api/v1/org/staff/{id}/resend-invite/ — regenerate invite token."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request, pk):
        try:
            staff = StaffUser.objects.using(request.tenant_db).get(pk=pk, is_active=True)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        temp_password = _gen_temp_password()
        staff.set_password(temp_password)
        staff.must_change_password = True
        staff.save(using=request.tenant_db, update_fields=["password", "must_change_password"])

        return success(data={
            "temp_password": temp_password,
            "note": "New temporary password generated. Share with the staff member.",
        }, message="New temporary password generated.")


# ── Table-driven RBAC ──────────────────────────────────────────────────────────
# See apps.org.rbac / docs/onboarding_auth_rbac_architecture.md 4.3. Every
# tenant DB is seeded (migration 0013) with the 6 system roles and the fixed
# permission catalog. Viewing is available to any hospital admin regardless
# of tier — creating/editing a CUSTOM role requires feat_custom_roles
# (enterprise). System roles are always read-only via this API; they exist
# to describe the hardcoded Is* checks, not to be edited around them.

class PermissionListView(APIView):
    """GET /api/v1/org/permissions/ — the fixed, deploy-time permission catalog."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        perms = Permission.objects.using(request.tenant_db).all()
        return success(data=PermissionSerializer(perms, many=True).data)


class RoleListCreateView(APIView):
    """
    GET  /api/v1/org/roles/  — every role (6 system + any custom), each with
                                its granted permission codes.
    POST /api/v1/org/roles/  — create a custom role. Requires feat_custom_roles.
    """
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsHospitalAdmin(), RequireFeature("feat_custom_roles")()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        roles = Role.objects.using(request.tenant_db).prefetch_related("permissions").all()
        return success(data=RoleSerializer(roles, many=True).data)

    def post(self, request):
        s = RoleWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        if Role.objects.using(request.tenant_db).filter(name__iexact=d["name"]).exists():
            return error("A role with this name already exists.", errors={"name": "Already in use."})

        valid_codes = set(
            Permission.objects.using(request.tenant_db).values_list("code", flat=True)
        )
        requested_codes = set(d.get("permission_codes") or [])
        unknown = requested_codes - valid_codes
        if unknown:
            return error(f"Unknown permission code(s): {', '.join(sorted(unknown))}.",
                         errors={"permission_codes": "Contains unknown code(s)."})

        role = Role.objects.using(request.tenant_db).create(
            name=d["name"], description=d.get("description", ""), is_system_role=False,
        )
        if requested_codes:
            perms = Permission.objects.using(request.tenant_db).filter(code__in=requested_codes)
            role.permissions.set(perms)

        return created(data=RoleSerializer(role).data, message="Role created.")


class RoleDetailView(APIView):
    """
    PATCH  /api/v1/org/roles/{id}/  — edit a custom role's name/description/
                                       permission_codes. System roles can't be
                                       edited (400). Requires feat_custom_roles.
    DELETE /api/v1/org/roles/{id}/  — delete a custom role. System roles can't
                                       be deleted. Any staff still holding this
                                       role (via UserRole) simply loses the
                                       extra grant — their primary StaffUser.role
                                       is untouched.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin, RequireFeature("feat_custom_roles")]

    def _get_role(self, request, pk):
        try:
            return Role.objects.using(request.tenant_db).get(pk=pk)
        except Role.DoesNotExist:
            return None

    def patch(self, request, pk):
        role = self._get_role(request, pk)
        if not role:
            return not_found("Role not found.")
        if role.is_system_role:
            return error("System roles can't be edited.")

        s = RoleWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        if "name" in d:
            if Role.objects.using(request.tenant_db).filter(name__iexact=d["name"]).exclude(pk=role.pk).exists():
                return error("A role with this name already exists.", errors={"name": "Already in use."})
            role.name = d["name"]
        if "description" in d:
            role.description = d["description"]
        role.save(using=request.tenant_db)

        if "permission_codes" in d:
            valid_codes = set(
                Permission.objects.using(request.tenant_db).values_list("code", flat=True)
            )
            requested_codes = set(d.get("permission_codes") or [])
            unknown = requested_codes - valid_codes
            if unknown:
                return error(f"Unknown permission code(s): {', '.join(sorted(unknown))}.",
                             errors={"permission_codes": "Contains unknown code(s)."})
            perms = Permission.objects.using(request.tenant_db).filter(code__in=requested_codes)
            role.permissions.set(perms)

        return success(data=RoleSerializer(role).data, message="Role updated.")

    def delete(self, request, pk):
        role = self._get_role(request, pk)
        if not role:
            return not_found("Role not found.")
        if role.is_system_role:
            return error("System roles can't be deleted.")
        role.delete()
        return success(message="Role deleted.")


class StaffRolesView(APIView):
    """
    GET /api/v1/org/staff/{id}/roles/ — this staff member's primary role
                                         (StaffUser.role, always active) plus
                                         any extra custom roles assigned.
    PUT /api/v1/org/staff/{id}/roles/  — replace the extra-roles set.
                                         Body: {"role_ids": [3, 5]}
                                         Requires feat_custom_roles. The
                                         primary role is unaffected — this
                                         only manages additive grants.
    """
    def get_permissions(self):
        if self.request.method == "PUT":
            return [IsAuthenticated(), IsHospitalAdmin(), RequireFeature("feat_custom_roles")()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request, pk):
        try:
            staff = StaffUser.objects.using(request.tenant_db).get(pk=pk)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")
        extra = (
            UserRole.objects.using(request.tenant_db)
            .filter(staff_id=staff.id).select_related("role")
        )
        return success(data={
            "primary_role": staff.role,
            "extra_roles": [RoleSerializer(ur.role).data for ur in extra],
        })

    def put(self, request, pk):
        try:
            staff = StaffUser.objects.using(request.tenant_db).get(pk=pk)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        role_ids = request.data.get("role_ids")
        if role_ids is None or not isinstance(role_ids, list):
            return error("role_ids (a list) is required.", errors={"role_ids": "Required."})

        valid_roles = Role.objects.using(request.tenant_db).filter(pk__in=role_ids)
        valid_ids = set(valid_roles.values_list("id", flat=True))
        invalid = set(int(r) for r in role_ids) - valid_ids
        if invalid:
            return error(f"Unknown role id(s): {sorted(invalid)}.", errors={"role_ids": "Contains unknown id(s)."})

        UserRole.objects.using(request.tenant_db).filter(staff_id=staff.id).delete()
        UserRole.objects.using(request.tenant_db).bulk_create([
            UserRole(staff_id=staff.id, role_id=rid) for rid in valid_ids
        ])
        return success(message="Roles updated.")


# ── Doctor Profile ────────────────────────────────────────────────────────────

class DoctorProfileView(APIView):
    """
    GET  /api/v1/org/staff/{id}/doctor-profile/ — get profile
    POST /api/v1/org/staff/{id}/doctor-profile/ — create profile (doctor role only)
    PATCH /api/v1/org/staff/{id}/doctor-profile/ — update profile
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get_staff(self, request, pk):
        try:
            return StaffUser.objects.using(request.tenant_db).get(pk=pk, is_active=True)
        except StaffUser.DoesNotExist:
            return None

    def get(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        try:
            profile = DoctorProfile.objects.using(request.tenant_db).get(staff=staff)
            return success(data=DoctorProfileSerializer(profile).data)
        except DoctorProfile.DoesNotExist:
            return not_found("Doctor profile not found.")

    def post(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        if staff.role != "doctor":
            return error("Doctor profile can only be created for staff with role 'doctor'.")
        if DoctorProfile.objects.using(request.tenant_db).filter(staff=staff).exists():
            return error("Doctor profile already exists. Use PATCH to update.")

        s = DoctorProfileSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        profile = DoctorProfile(staff=staff, **s.validated_data)
        profile.save(using=request.tenant_db)
        return created(data=DoctorProfileSerializer(profile).data, message="Doctor profile created.")

    def patch(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        try:
            profile = DoctorProfile.objects.using(request.tenant_db).get(staff=staff)
        except DoctorProfile.DoesNotExist:
            return not_found("Doctor profile not found. Create it first with POST.")

        s = DoctorProfileSerializer(profile, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(profile, attr, val)
        profile.save(using=request.tenant_db)
        return success(data=DoctorProfileSerializer(profile).data, message="Doctor profile updated.")


class MyDoctorProfileView(APIView):
    """
    GET   /api/v1/org/me/doctor-profile/ — the logged-in doctor's own profile
    PATCH /api/v1/org/me/doctor-profile/ — self-service update

    Doctor-only, and always scoped to request.user's own StaffUser row — no
    :pk in the URL, so a doctor can never read or edit anyone else's profile.
    Admin-set basics (registration_no, specialisation, qualification,
    experience_years) are read-only here; use DoctorProfileView (admin-only)
    to change those. Everything else — fee, signature, bio, photo, languages —
    the doctor owns.
    """
    permission_classes = [IsAuthenticated, IsDoctor]

    def get(self, request):
        profile, _ = DoctorProfile.objects.using(request.tenant_db).get_or_create(
            staff_id=request.user.id
        )
        return success(data=DoctorSelfProfileSerializer(profile).data)

    def patch(self, request):
        profile, _ = DoctorProfile.objects.using(request.tenant_db).get_or_create(
            staff_id=request.user.id
        )
        s = DoctorSelfProfileSerializer(profile, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(profile, attr, val)
        profile.save(using=request.tenant_db)
        return success(data=DoctorSelfProfileSerializer(profile).data, message="Profile updated.")


# ── Staff Profile (every non-doctor role) ─────────────────────────────────────

class StaffProfileView(APIView):
    """
    GET   /api/v1/org/staff/{id}/profile/ — get profile
    POST  /api/v1/org/staff/{id}/profile/ — create profile (any non-doctor role)
    PATCH /api/v1/org/staff/{id}/profile/ — update profile

    Admin-only — mirrors DoctorProfileView but for nurse/front desk/lab tech/
    pharmacist/hospital admin, which use StaffProfile instead of DoctorProfile.
    """
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get_staff(self, request, pk):
        try:
            return StaffUser.objects.using(request.tenant_db).get(pk=pk, is_active=True)
        except StaffUser.DoesNotExist:
            return None

    def get(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        try:
            profile = StaffProfile.objects.using(request.tenant_db).get(staff=staff)
            return success(data=StaffProfileSerializer(profile).data)
        except StaffProfile.DoesNotExist:
            return not_found("Profile not found.")

    def post(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        if staff.role == "doctor":
            return error("Doctors use /doctor-profile/, not /profile/.")
        if StaffProfile.objects.using(request.tenant_db).filter(staff=staff).exists():
            return error("Profile already exists. Use PATCH to update.")

        s = StaffProfileSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        profile = StaffProfile(staff=staff, **s.validated_data)
        profile.save(using=request.tenant_db)
        return created(data=StaffProfileSerializer(profile).data, message="Profile created.")

    def patch(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        try:
            profile = StaffProfile.objects.using(request.tenant_db).get(staff=staff)
        except StaffProfile.DoesNotExist:
            return not_found("Profile not found. Create it first with POST.")

        s = StaffProfileSerializer(profile, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(profile, attr, val)
        profile.save(using=request.tenant_db)
        return success(data=StaffProfileSerializer(profile).data, message="Profile updated.")


class MyStaffProfileDetailsView(APIView):
    """
    GET   /api/v1/org/me/staff-profile/ — the logged-in (non-doctor) staff
                                           member's own profile
    PATCH /api/v1/org/me/staff-profile/ — self-service update

    Mirrors MyDoctorProfileView for every other role. Doctors have their own
    richer endpoint (MyDoctorProfileView) and should not hit this one.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        if request.user.role == "doctor":
            return error("Doctors use /me/doctor-profile/, not /me/staff-profile/.")
        profile, _ = StaffProfile.objects.using(request.tenant_db).get_or_create(
            staff_id=request.user.id
        )
        return success(data=StaffProfileSelfSerializer(profile).data)

    def patch(self, request):
        if request.user.role == "doctor":
            return error("Doctors use /me/doctor-profile/, not /me/staff-profile/.")
        profile, _ = StaffProfile.objects.using(request.tenant_db).get_or_create(
            staff_id=request.user.id
        )
        s = StaffProfileSelfSerializer(profile, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(profile, attr, val)
        profile.save(using=request.tenant_db)
        return success(data=StaffProfileSelfSerializer(profile).data, message="Profile updated.")


class MyStaffProfileView(APIView):
    """
    GET   /api/v1/org/me/profile/ — the logged-in staff member's own basic profile
    PATCH /api/v1/org/me/profile/ — self-service update (currently: photo only)

    Open to ANY staff role (doctor, nurse, front desk, lab tech, pharmacist,
    hospital admin) — always scoped to request.user's own StaffUser row.
    This is deliberately separate from MyDoctorProfileView: photo is common
    to every login, bio/signature/languages are doctor-specific.
    """
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        try:
            staff = StaffUser.objects.using(request.tenant_db).get(pk=request.user.id)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")
        return success(data=StaffMeSerializer(staff).data)

    def patch(self, request):
        try:
            staff = StaffUser.objects.using(request.tenant_db).get(pk=request.user.id)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        photo = request.data.get("photo")
        if photo and len(photo) > _MAX_PHOTO_BASE64_CHARS:
            return error("Photo is too large. Please use an image under ~1.5MB.",
                         errors={"photo": "Too large."})

        s = StaffMeSerializer(staff, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(staff, attr, val)
        staff.save(using=request.tenant_db)
        return success(data=StaffMeSerializer(staff).data, message="Profile updated.")


# ── Doctors list (for scheduling dropdown etc.) ───────────────────────────────

class DoctorListView(APIView):
    """GET /api/v1/org/doctors/ — list doctors with profiles (any staff)."""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        qs = StaffUser.objects.using(request.tenant_db).filter(
            role="doctor", is_active=True
        ).prefetch_related("doctor_profile")
        return success(data=StaffSerializer(qs, many=True).data)
