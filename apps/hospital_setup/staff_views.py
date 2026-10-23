"""apps/org/views.py"""

import base64
import mimetypes
import re
import secrets
import string
import logging
from datetime import datetime
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated


from core.api.permissions import IsHospitalAdmin, IsHospitalStaff, IsDoctor, RequireFeature
from core.api.response import success, created, error, not_found
from core.api.pagination import paginate_queryset
from core.utils.file_validation import validate_data_uri, FileValidationError
from core import storage as blob_storage
from apps.patients.models import StaffMobileIndex
from apps.hospital_master.services import parameters_of

from apps.hospital_setup.models import Branch, Room
from apps.hospital_setup.models import StaffUser, Role, Permission
from apps.hospital_setup.rbac import acts_as_q, resolve_acts_as, system_role
from apps.hospital_setup.branch_utils import (
    PLACE_PREFETCH, default_place, ensure_default_place, forget_places, place_for, primary_branch_id, primary_department_id,
    set_primary_place, set_staff_branches,
)
from apps.hospital_setup import room_utils

logger = logging.getLogger(__name__)


from apps.hospital_setup.staff_services import next_employee_id

from apps.hospital_setup.staff_serializers import (
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
    RoomAssignmentSerializer,
)

# Rough cap on the base64 photo payload — keeps us comfortably under DRF's
_MAX_PHOTO_BASE64_CHARS = 1_900_000


def _gen_temp_password(length=12) -> str:
    """Generate a readable temporary password."""
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(chars) for _ in range(length))


def _email_collision(email, hospital_db, exclude_staff_id=None):
    """Returns an error message if `email` is already in use somewhere it"""
    if not email:
        return ""
    from apps.patients.models import StaffMobileIndex
    qs = StaffUser.objects.using(hospital_db).filter(email__iexact=email)
    if exclude_staff_id:
        qs = qs.exclude(pk=exclude_staff_id)
    if qs.exists():
        return f"Email {email} is already used by another staff member at this hospital."

    idx_qs = StaffMobileIndex.objects.using("default").filter(email__iexact=email)
    if exclude_staff_id:
        # The reactivation path's own index row (same mobile) is allowed to
        existing_mobile = StaffUser.objects.using(hospital_db).filter(pk=exclude_staff_id).values_list("phone", flat=True).first()
        if existing_mobile:
            idx_qs = idx_qs.exclude(mobile=existing_mobile)
    if idx_qs.exists():
        return f"Email {email} is already registered to a staff account at another hospital."
    return ""


def _send_new_account_email(staff, temp_password):
    """Best-effort — a delivery failure must not fail the invite/reset itself."""
    if not staff.email:
        return
    from core.messaging.email import send_temp_password_email
    send_temp_password_email(
        to=staff.email, full_name=staff.get_full_name() or staff.phone,
        temp_password=temp_password, login_hint=staff.phone,
    )


def _profile_filled(staff, serializer_class):
    """True once any of the profile fields the serializer covers has a value (the profile is part of the staff row, so "exists" means "filled in")."""
    return any(getattr(staff, name) not in (None, "", {}) for name in serializer_class().fields)


# ── Staff ─────────────────────────────────────────────────────────────────────

class StaffListView(APIView):
    """GET /api/v1/org/staff/ — list all staff members."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        qs = StaffUser.objects.using(request.hospital_db).select_related("group").prefetch_related(*PLACE_PREFETCH)
        role_filter = request.query_params.get("role")
        if role_filter == "custom":
            qs = qs.filter(group__is_system_role=False)
        elif role_filter:
            qs = qs.filter(group__is_system_role=True, group__system_role_key=role_filter)
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
    """POST /api/v1/org/staff/invite/"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request):
        s = StaffInviteSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data

        # ── Resolve the user group: a system role, or a role the hospital defined ──
        group = None
        acts_as = set()
        if d["role"] == "custom":
            if not d.get("custom_role_id"):
                return error("Select a custom role.", errors={"custom_role_id": "Required."})
            try:
                group = Role.objects.using(request.hospital_db).get(
                    pk=d["custom_role_id"], is_system_role=False,
                )
            except Role.DoesNotExist:
                return error("Custom role not found.", errors={"custom_role_id": "Invalid."})
            acts_as = set(group.acts_as or [])
        else:
            try:
                group = system_role(request.hospital_db, d["role"])
            except Role.DoesNotExist:
                return error("That role is not set up for this hospital.", errors={"role": "Invalid."})
        is_doctor_equivalent = d["role"] == "doctor" or "doctor" in acts_as

        # ── Subscription limit check (fails CLOSED — see apps.hospital_master.services) ──
        from apps.hospital_master.models import Hospital
        from apps.hospital_master.services import check_limit, LimitCheckFailed
        resource = "doctors" if is_doctor_equivalent else "staff"
        try:
            hospital = Hospital.objects.using("default").get(pk=request.hospital_id)
            check_limit(hospital, request.hospital_db, resource)
        except Hospital.DoesNotExist:
            return error("Unable to verify your plan limits right now. Please try again shortly.", status=503)
        except LimitCheckFailed as exc:
            return error(exc.message, status=exc.status)

        # A mobile number already routed to a *different* hospital must not be
        existing_index = StaffMobileIndex.objects.using("default").filter(mobile=d["phone"]).first()
        if existing_index and existing_index.hospital.db_name != request.hospital_db:
            return error(
                f"Mobile number {d['phone']} is already registered at another hospital.",
                errors={"phone": "Already in use."},
            )

        existing = StaffUser.objects.using(request.hospital_db).filter(phone=d["phone"]).first()
        if existing:
            if existing.is_active:
                return error(f"Staff with mobile number {d['phone']} already exists.")
            # Reactivate a previously deactivated staff member
            email_error = _email_collision(d.get("email"), request.hospital_db, exclude_staff_id=existing.id)
            if email_error:
                return error(email_error, errors={"email": "Already in use."})
            temp_password = _gen_temp_password()
            existing.is_active            = True
            existing.first_name           = d["first_name"]
            existing.last_name            = d.get("last_name", existing.last_name)
            existing.group                = group
            existing.email                = d.get("email") or existing.email
            # Employee ID is auto-generated via NNTM, never typed in — see
            if not existing.employee_id:
                existing.employee_id = next_employee_id(request.hospital_db)
            existing.must_change_password = True
            existing.set_password(temp_password)
            existing.save(using=request.hospital_db)
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=d["phone"],
                defaults={
                    "hospital_id": request.hospital_id,
                    "email": existing.email or None,
                },
            )
            if "branch_ids" in d:
                set_staff_branches(existing, d.get("branch_ids") or [], d.get("branch_id"), request.hospital_db)
            _send_new_account_email(existing, temp_password)
            return created(data={
                **StaffSerializer(existing).data,
                "temp_password": temp_password,
                "note": "Account reactivated. Share these credentials with the staff member."
                        + (" A copy was also emailed to them." if existing.email else ""),
            }, message=f"{existing.get_full_name()} reactivated.")

        # Resolve where they work: a department at a branch (the branch's default department when none is named)
        branch = None
        place = None
        if d.get("branch_id"):
            try:
                branch = Branch.objects.using(request.hospital_db).get(
                    pk=d["branch_id"], is_active=True
                )
            except Branch.DoesNotExist:
                return error("Branch not found.", errors={"branch_id": "Invalid."})
            if d.get("department_id"):
                place = place_for(request.hospital_db, branch.id, d["department_id"])
                if place is None:
                    return error("That branch does not offer this department.", errors={"department_id": "Invalid."})
            else:
                place = default_place(request.hospital_db, branch.id) or ensure_default_place(request.hospital_db, branch)
        elif d.get("department_id"):
            return error("Choose a branch for the department.", errors={"branch_id": "Required with a department."})

        email_error = _email_collision(d.get("email"), request.hospital_db)
        if email_error:
            return error(email_error, errors={"email": "Already in use."})

        temp_password = _gen_temp_password()
        staff = StaffUser(
            phone=d["phone"],
            email=d.get("email") or None,
            employee_id=next_employee_id(request.hospital_db),
            first_name=d["first_name"],
            last_name=d.get("last_name", ""),
            group=group,
            must_change_password=True,
        )
        staff.set_password(temp_password)
        staff.save(using=request.hospital_db)
        if place is not None:
            set_primary_place(staff, place, request.hospital_db)

        # Extra branches beyond the primary — meaningful for doctors who
        if d.get("branch_ids"):
            set_staff_branches(staff, d["branch_ids"], branch.id if branch else None, request.hospital_db)

        # Professional basics — admin enters these now so patient-facing cards are
        profile_values = {}
        if is_doctor_equivalent and any(
            d.get(f) for f in ("registration_no", "specialisation", "qualification", "experience_years",
                               "consultation_fee", "followup_fee")
        ):
            # consultation_fee / followup_fee are only written when the
            from apps.hospital_master.models import Hospital as _Hospital
            try:
                _hospital = _Hospital.objects.using("default").get(pk=request.hospital_id)
                from apps.hospital_master.services import parameters_of as _parameters_of
                hospital_owns_fee = _parameters_of(_hospital).fee_ownership == "hospital"
                fee_value = d.get("consultation_fee") if hospital_owns_fee else None
                followup_fee_value = d.get("followup_fee") if hospital_owns_fee else None
            except _Hospital.DoesNotExist:
                fee_value = None
                followup_fee_value = None

            profile_values = dict(
                registration_no=d.get("registration_no", ""),
                specialisation=d.get("specialisation", ""),
                qualification=d.get("qualification", ""),
                experience_years=d.get("experience_years"),
                consultation_fee=fee_value,
                followup_fee=followup_fee_value,
            )

        # Working-hours schedule — optional at registration; doctor can also
        if is_doctor_equivalent and d.get("schedule"):
            sched = room_utils.schedule_of(staff.id, request.hospital_db, create=True)
            if sched is not None:
                room_utils.set_hours(sched, d["schedule"].get("slot_duration_minutes", 15), d["schedule"]["days"], request.hospital_db)
        # Same basics for every other role — nursing/pharmacy council
        elif not is_doctor_equivalent and any(
            d.get(f) for f in ("registration_no", "council_name", "registration_expiry",
                               "qualification", "experience_years")
        ):
            profile_values = dict(
                registration_no=d.get("registration_no", ""),
                council_name=d.get("council_name", ""),
                registration_expiry=d.get("registration_expiry"),
                qualification=d.get("qualification", ""),
                experience_years=d.get("experience_years"),
            )
        if profile_values:
            for field, value in profile_values.items():
                setattr(staff, field, value)
            staff.save(using=request.hospital_db)

        # Write to atomwalk index so login can route by mobile (no hospital_code needed)
        StaffMobileIndex.objects.using("default").update_or_create(
            mobile=d["phone"],
            defaults={
                "hospital_id": request.hospital_id,
                "email": staff.email or None,
            },
        )

        _send_new_account_email(staff, temp_password)
        return created(data={
            **StaffSerializer(staff).data,
            "temp_password": temp_password,
            "note": "Share these credentials with the staff member. They will be prompted to change the password on first login."
                    + (" A copy was also emailed to them." if staff.email else ""),
        }, message=f"{staff.get_full_name()} invited.")


class StaffDetailView(APIView):
    """GET   /api/v1/org/staff/{id}/  — staff member detail"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return StaffUser.objects.using(request.hospital_db).select_related("group").prefetch_related(*PLACE_PREFETCH).get(pk=pk)
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

        if "phone" in d and d["phone"] and not re.match(r"^\d{10}$", d["phone"]):
            return error("Enter a valid 10-digit mobile number.", errors={"phone": "Invalid format."})

        # Changing the login mobile number needs the atomwalk-wide index kept
        if "phone" in d and d["phone"] != staff.phone:
            clash = StaffMobileIndex.objects.using("default").filter(mobile=d["phone"]).exclude(
                hospital_id=request.hospital_id
            ).exists()
            if clash:
                return error(
                    f"Mobile number {d['phone']} is already registered at another hospital.",
                    errors={"phone": "Already in use."},
                )

        # Refuse to role-change away the last active hospital_admin — see the
        staff_old_acts_as = resolve_acts_as(staff)
        staff_is_admin = "hospital_admin" in staff_old_acts_as
        if "role" in d and d["role"] != "hospital_admin" and staff_is_admin and staff.is_active:
            other_admins = StaffUser.objects.using(request.hospital_db).filter(
                acts_as_q("hospital_admin"), is_active=True
            ).exclude(pk=staff.id).exists()
            if not other_admins:
                return error(
                    "This is the only active hospital admin — changing their role "
                    "would lock the hospital out of its own admin panel. Promote "
                    "another staff member to hospital_admin first.",
                )

        # Resolve the group being moved TO, if the role changes — needed both for
        new_group = None
        if "role" in d:
            if d["role"] == "custom":
                if not d.get("custom_role_id"):
                    return error("Select a custom role.", errors={"custom_role_id": "Required."})
                try:
                    new_group = Role.objects.using(request.hospital_db).get(
                        pk=d["custom_role_id"], is_system_role=False,
                    )
                except Role.DoesNotExist:
                    return error("Custom role not found.", errors={"custom_role_id": "Invalid."})
            else:
                try:
                    new_group = system_role(request.hospital_db, d["role"])
                except Role.DoesNotExist:
                    return error("That role is not set up for this hospital.", errors={"role": "Invalid."})

        # A role change that crosses the doctor / non-doctor line moves this
        if new_group is not None and staff.is_active and new_group.id != staff.group_id:
            old_is_doctor = "doctor" in staff_old_acts_as
            new_is_doctor = "doctor" in resolve_acts_as(StaffUser(group=new_group))
            old_resource = "doctors" if old_is_doctor else "staff"
            new_resource = "doctors" if new_is_doctor else "staff"
            if new_resource != old_resource:
                from apps.hospital_master.models import Hospital
                from apps.hospital_master.services import check_limit, LimitCheckFailed
                try:
                    hospital = Hospital.objects.using("default").get(pk=request.hospital_id)
                    check_limit(hospital, request.hospital_db, new_resource)
                except Hospital.DoesNotExist:
                    return error("Unable to verify your plan limits right now. Please try again shortly.", status=503)
                except LimitCheckFailed as exc:
                    return error(exc.message, status=exc.status)

        # employee_id is deliberately NOT in this list — it's auto-generated
        if not staff.employee_id:
            staff.employee_id = next_employee_id(request.hospital_db)

        # Where they work: a change of branch and/or department moves them to that department at that branch
        new_place, clear_place = None, False
        if "branch_id" in d or "department_id" in d:
            target_branch_id = d["branch_id"] if "branch_id" in d else primary_branch_id(staff, request.hospital_db)
            target_department_id = d["department_id"] if "department_id" in d else (primary_department_id(staff, request.hospital_db) if "branch_id" not in d else None)
            if target_branch_id is None:
                if target_department_id:
                    return error("Choose a branch for the department.", errors={"branch_id": "Required with a department."})
                clear_place = True
            else:
                if not Branch.objects.using(request.hospital_db).filter(pk=target_branch_id).exists():
                    return error("Branch not found.")
                new_place = place_for(request.hospital_db, target_branch_id, target_department_id)
                if new_place is None:
                    return error("That branch does not offer this department." if target_department_id else "Branch has no department yet.")

        for field in ["first_name", "last_name", "phone"]:
            if field in d:
                setattr(staff, field, d[field])
        if "date_of_birth" in d:
            dob = d.get("date_of_birth") or None
            if dob:
                try:
                    dob = datetime.strptime(dob, "%Y-%m-%d").date()
                except ValueError:
                    return error("Date of birth must be YYYY-MM-DD.", errors={"date_of_birth": "Invalid format."})
            staff.date_of_birth = dob
        if new_group is not None:
            staff.group = new_group

        staff.save(using=request.hospital_db)
        if new_place is not None or clear_place:
            set_primary_place(staff, new_place, request.hospital_db)

        if "phone" in d:
            # NOTE: "email" is deliberately not in `allowed` above (no endpoint
            StaffMobileIndex.objects.using("default").update_or_create(
                mobile=staff.phone,
                defaults={
                    "hospital_id": request.hospital_id,
                    "email": staff.email or None,
                },
            )

        return success(data=StaffSerializer(staff).data, message="Staff updated.")

    def delete(self, request, pk):
        staff = self._get(request, pk)
        if not staff:
            return not_found("Staff member not found.")

        staff_is_admin = "hospital_admin" in resolve_acts_as(staff)
        if staff_is_admin and staff.is_active:
            other_admins = StaffUser.objects.using(request.hospital_db).filter(
                acts_as_q("hospital_admin"), is_active=True
            ).exclude(pk=staff.id).exists()
            if not other_admins:
                return error(
                    "This is the only active hospital admin — deactivating them "
                    "would lock the hospital out of its own admin panel. Promote "
                    "another staff member to hospital_admin first.",
                )

        staff.is_active = False
        staff.save(using=request.hospital_db, update_fields=["is_active"])
        return success(message="Staff member deactivated.")


class StaffBranchesView(APIView):
    """GET /api/v1/org/staff/{id}/branches/ — this staff member's full branch"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get_staff(self, request, pk):
        try:
            return StaffUser.objects.using(request.hospital_db).get(pk=pk)
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
                Branch.objects.using(request.hospital_db)
                .filter(pk__in=branch_ids, is_active=True)
                .values_list("id", flat=True)
            )
            invalid = set(int(b) for b in branch_ids) - valid_ids
            if invalid:
                return error(f"Unknown or inactive branch id(s): {sorted(invalid)}", errors={"branch_ids": "Invalid."})
            if primary_branch_id is not None and int(primary_branch_id) not in valid_ids:
                return error("primary_branch_id must be one of branch_ids.", errors={"primary_branch_id": "Invalid."})

        set_staff_branches(staff, branch_ids, primary_branch_id, request.hospital_db)

        return success(data=StaffSerializer(staff).data["branches"], message="Branch assignment updated.")


class StaffDoctorsView(APIView):
    """GET /api/v1/org/staff/{id}/doctors/ — the doctor(s) this nurse is"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get_staff(self, request, pk):
        try:
            return StaffUser.objects.using(request.hospital_db).get(pk=pk)
        except StaffUser.DoesNotExist:
            return None

    def get(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        return success(data=StaffSerializer(staff).data["assigned_doctors"])

    def put(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        if staff.role != "nurse":
            return error("Doctor assignment only applies to nurses.", errors={"role": "Not a nurse."})

        doctor_ids = request.data.get("doctor_ids")
        if doctor_ids is None or not isinstance(doctor_ids, list):
            return error("doctor_ids (a list) is required.", errors={"doctor_ids": "Required."})

        if doctor_ids:
            valid_ids = set(
                StaffUser.objects.using(request.hospital_db)
                .filter(acts_as_q("doctor"), pk__in=doctor_ids, is_active=True)
                .values_list("id", flat=True)
            )
            invalid = set(int(d) for d in doctor_ids) - valid_ids
            if invalid:
                return error(f"Unknown or inactive doctor id(s): {sorted(invalid)}", errors={"doctor_ids": "Invalid."})

        from apps.hospital_setup.nurse_doctor_utils import set_nurse_doctors
        set_nurse_doctors(staff, doctor_ids, request.hospital_db)

        return success(data=StaffSerializer(staff).data["assigned_doctors"], message="Doctor assignment updated.")


class MyBranchesView(APIView):
    """GET /api/v1/org/me/branches/ — the logged-in staff member's own branch"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        try:
            staff = StaffUser.objects.using(request.hospital_db).get(pk=request.user.id)
        except StaffUser.DoesNotExist:
            return not_found("Staff account not found.")
        return success(data=StaffSerializer(staff).data["branches"])


class StaffResendInviteView(APIView):
    """POST /api/v1/org/staff/{id}/resend-invite/ — regenerate invite token."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def post(self, request, pk):
        try:
            staff = StaffUser.objects.using(request.hospital_db).get(pk=pk, is_active=True)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        temp_password = _gen_temp_password()
        staff.set_password(temp_password)
        staff.must_change_password = True
        staff.save(using=request.hospital_db, update_fields=["password", "must_change_password"])

        _send_new_account_email(staff, temp_password)
        return success(data={
            "temp_password": temp_password,
            "note": "New temporary password generated. Share with the staff member."
                    + (" A copy was also emailed to them." if staff.email else ""),
        }, message="New temporary password generated.")


# ── Table-driven RBAC ──────────────────────────────────────────────────────────

class PermissionListView(APIView):
    """GET /api/v1/org/permissions/ — the fixed, deploy-time permission catalog."""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def get(self, request):
        perms = Permission.objects.using(request.hospital_db).all()
        return success(data=PermissionSerializer(perms, many=True).data)


class RoleListCreateView(APIView):
    """GET  /api/v1/org/roles/  — every role (6 system + any custom), each with"""
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsHospitalAdmin(), RequireFeature("feat_custom_roles")()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        roles = Role.objects.using(request.hospital_db).prefetch_related("permissions").all()
        return success(data=RoleSerializer(roles, many=True).data)

    def post(self, request):
        s = RoleWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        if Role.objects.using(request.hospital_db).filter(name__iexact=d["name"]).exists():
            return error("A role with this name already exists.", errors={"name": "Already in use."})

        valid_codes = set(
            Permission.objects.using(request.hospital_db).values_list("code", flat=True)
        )
        requested_codes = set(d.get("permission_codes") or [])
        unknown = requested_codes - valid_codes
        if unknown:
            return error(f"Unknown permission code(s): {', '.join(sorted(unknown))}.",
                         errors={"permission_codes": "Contains unknown code(s)."})

        role = Role.objects.using(request.hospital_db).create(
            name=d["name"], description=d.get("description", ""), is_system_role=False,
            acts_as=d.get("acts_as") or [],
        )
        if requested_codes:
            perms = Permission.objects.using(request.hospital_db).filter(code__in=requested_codes)
            role.permissions.set(perms)

        return created(data=RoleSerializer(role).data, message="Role created.")


class RoleDetailView(APIView):
    """PATCH  /api/v1/org/roles/{id}/  — edit a custom role's name/description/"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin, RequireFeature("feat_custom_roles")]

    def _get_role(self, request, pk):
        try:
            return Role.objects.using(request.hospital_db).get(pk=pk)
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
            if Role.objects.using(request.hospital_db).filter(name__iexact=d["name"]).exclude(pk=role.pk).exists():
                return error("A role with this name already exists.", errors={"name": "Already in use."})
            role.name = d["name"]
        if "description" in d:
            role.description = d["description"]
        if "acts_as" in d:
            role.acts_as = d["acts_as"] or []
        role.save(using=request.hospital_db)

        if "permission_codes" in d:
            valid_codes = set(
                Permission.objects.using(request.hospital_db).values_list("code", flat=True)
            )
            requested_codes = set(d.get("permission_codes") or [])
            unknown = requested_codes - valid_codes
            if unknown:
                return error(f"Unknown permission code(s): {', '.join(sorted(unknown))}.",
                             errors={"permission_codes": "Contains unknown code(s)."})
            perms = Permission.objects.using(request.hospital_db).filter(code__in=requested_codes)
            role.permissions.set(perms)

        return success(data=RoleSerializer(role).data, message="Role updated.")

    def delete(self, request, pk):
        role = self._get_role(request, pk)
        if not role:
            return not_found("Role not found.")
        if role.is_system_role:
            return error("System roles can't be deleted.")
        # Unlike extra_roles (extra roles — CASCADE is fine, losing an extra
        holders = StaffUser.objects.using(request.hospital_db).filter(
            group=role, is_active=True
        ).count()
        if holders:
            plural = "" if holders == 1 else "s"
            return error(
                f"{holders} active staff member{plural} currently use this as their primary "
                "role. Reassign them to a different role first, then delete this one.",
            )
        role.delete()
        return success(message="Role deleted.")


class StaffRolesView(APIView):
    """GET /api/v1/org/staff/{id}/roles/ — this staff member's primary role"""
    def get_permissions(self):
        if self.request.method == "PUT":
            return [IsAuthenticated(), IsHospitalAdmin(), RequireFeature("feat_custom_roles")()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request, pk):
        try:
            staff = StaffUser.objects.using(request.hospital_db).get(pk=pk)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")
        return success(data={
            "primary_role": staff.role,
            "extra_roles": [RoleSerializer(role).data for role in staff.extra_roles.all()],
        })

    def put(self, request, pk):
        try:
            staff = StaffUser.objects.using(request.hospital_db).get(pk=pk)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        role_ids = request.data.get("role_ids")
        if role_ids is None or not isinstance(role_ids, list):
            return error("role_ids (a list) is required.", errors={"role_ids": "Required."})

        valid_roles = Role.objects.using(request.hospital_db).filter(pk__in=role_ids)
        valid_ids = set(valid_roles.values_list("id", flat=True))
        invalid = set(int(r) for r in role_ids) - valid_ids
        if invalid:
            return error(f"Unknown role id(s): {sorted(invalid)}.", errors={"role_ids": "Contains unknown id(s)."})

        staff.extra_roles.set(valid_roles)
        return success(message="Roles updated.")


# ── Doctor Profile ────────────────────────────────────────────────────────────

class DoctorProfileView(APIView):
    """GET  /api/v1/org/staff/{id}/doctor-profile/ — get profile"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get_staff(self, request, pk):
        try:
            return StaffUser.objects.using(request.hospital_db).get(pk=pk, is_active=True)
        except StaffUser.DoesNotExist:
            return None

    def get(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        return success(data=DoctorProfileSerializer(staff).data)

    def post(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        if staff.role != "doctor":
            return error("Doctor profile can only be created for staff with role 'doctor'.")
        if _profile_filled(staff, DoctorProfileSerializer):
            return error("Doctor profile already exists. Use PATCH to update.")

        s = DoctorProfileSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        for attr, val in s.validated_data.items():
            setattr(staff, attr, val)
        staff.save(using=request.hospital_db)
        return created(data=DoctorProfileSerializer(staff).data, message="Doctor profile created.")

    def patch(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        s = DoctorProfileSerializer(staff, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(staff, attr, val)
        staff.save(using=request.hospital_db)
        return success(data=DoctorProfileSerializer(staff).data, message="Doctor profile updated.")


class MyDoctorProfileView(APIView):
    """GET   /api/v1/org/me/doctor-profile/ — the logged-in doctor's own profile"""
    permission_classes = [IsAuthenticated, IsDoctor]

    def _fee_editable(self, request):
        """Returns True when this hospital delegates fee-setting to the doctor."""
        from apps.hospital_master.models import Hospital as _Hospital
        try:
            t = _Hospital.objects.using("default").get(pk=request.hospital_id)
            from apps.hospital_master.services import parameters_of as _parameters_of
            return _parameters_of(t).fee_ownership == "doctor"
        except _Hospital.DoesNotExist:
            return False

    def get(self, request):
        profile = StaffUser.objects.using(request.hospital_db).get(pk=request.user.id)
        ctx = {"fee_editable": self._fee_editable(request)}
        return success(data=DoctorSelfProfileSerializer(profile, context=ctx).data)

    def patch(self, request):
        profile = StaffUser.objects.using(request.hospital_db).get(pk=request.user.id)
        ctx = {"fee_editable": self._fee_editable(request)}

        # digital_signature is handled separately from the generic serializer
        old_sig_key = profile.digital_signature
        if "digital_signature" in request.data:
            sig = request.data.get("digital_signature") or ""
            if not sig:
                profile.digital_signature = ""
            else:
                try:
                    mime_type = validate_data_uri(sig)
                except FileValidationError as exc:
                    return error(str(exc), errors={"digital_signature": str(exc)})
                from apps.hospital_master.models import Hospital as _Hospital
                _hospital = _Hospital.objects.using("default").filter(pk=request.hospital_id).first()
                folder = blob_storage.hospital_folder(_hospital) if _hospital else request.hospital_db
                _staff = StaffUser.objects.using(request.hospital_db).filter(pk=request.user.id).first()
                identity = blob_storage.identity_slug(
                    name=_staff.get_full_name() if _staff else "", identifier=request.user.email,
                )
                try:
                    profile.digital_signature = blob_storage.upload_data_uri(
                        sig, prefix=f"doctor-signatures/{folder}", mime_type=mime_type,
                        category="doctor-signature", identity=identity,
                    )
                except blob_storage.StorageError as exc:
                    return error(str(exc), errors={"digital_signature": str(exc)})

        s = DoctorSelfProfileSerializer(profile, data=request.data, partial=True, context=ctx)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(profile, attr, val)
        profile.save(using=request.hospital_db)
        if "digital_signature" in request.data and old_sig_key and old_sig_key != profile.digital_signature:
            blob_storage.delete(old_sig_key)
        return success(data=DoctorSelfProfileSerializer(profile, context=ctx).data, message="Profile updated.")


# ── Staff Profile (every non-doctor role) ─────────────────────────────────────

class StaffProfileView(APIView):
    """GET   /api/v1/org/staff/{id}/profile/ — get profile"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get_staff(self, request, pk):
        try:
            return StaffUser.objects.using(request.hospital_db).get(pk=pk, is_active=True)
        except StaffUser.DoesNotExist:
            return None

    def get(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        return success(data=StaffProfileSerializer(staff).data)

    def post(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        from apps.hospital_setup.rbac import resolve_acts_as
        if "doctor" in resolve_acts_as(staff):
            return error("Doctors use /doctor-profile/, not /profile/.")
        if _profile_filled(staff, StaffProfileSerializer):
            return error("Profile already exists. Use PATCH to update.")

        s = StaffProfileSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        for attr, val in s.validated_data.items():
            setattr(staff, attr, val)
        staff.save(using=request.hospital_db)
        return created(data=StaffProfileSerializer(staff).data, message="Profile created.")

    def patch(self, request, pk):
        staff = self._get_staff(request, pk)
        if not staff:
            return not_found("Staff member not found.")
        s = StaffProfileSerializer(staff, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(staff, attr, val)
        staff.save(using=request.hospital_db)
        return success(data=StaffProfileSerializer(staff).data, message="Profile updated.")


class MyStaffProfileDetailsView(APIView):
    """GET   /api/v1/org/me/staff-profile/ — the logged-in (non-doctor) staff"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            return error("Doctors use /me/doctor-profile/, not /me/staff-profile/.")
        profile = StaffUser.objects.using(request.hospital_db).get(pk=request.user.id)
        return success(data=StaffProfileSelfSerializer(profile).data)

    def patch(self, request):
        if request.user.role == "doctor" or "doctor" in getattr(request.user, "acts_as", []):
            return error("Doctors use /me/doctor-profile/, not /me/staff-profile/.")
        profile = StaffUser.objects.using(request.hospital_db).get(pk=request.user.id)
        s = StaffProfileSelfSerializer(profile, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(profile, attr, val)
        profile.save(using=request.hospital_db)
        return success(data=StaffProfileSelfSerializer(profile).data, message="Profile updated.")


class MyStaffProfileView(APIView):
    """GET   /api/v1/org/me/profile/ — the logged-in staff member's own basic profile"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        try:
            staff = StaffUser.objects.using(request.hospital_db).get(pk=request.user.id)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")
        return success(data=StaffMeSerializer(staff).data)

    def patch(self, request):
        try:
            staff = StaffUser.objects.using(request.hospital_db).get(pk=request.user.id)
        except StaffUser.DoesNotExist:
            return not_found("Staff member not found.")

        # photo is handled separately from the generic serializer loop below
        old_photo_key = staff.photo
        if "photo" in request.data:
            photo = request.data.get("photo") or ""
            if not photo:
                staff.photo = ""
            else:
                if len(photo) > _MAX_PHOTO_BASE64_CHARS:
                    return error("Photo is too large. Please use an image under ~1.5MB.",
                                 errors={"photo": "Too large."})
                try:
                    mime_type = validate_data_uri(photo)
                except FileValidationError as exc:
                    return error(str(exc), errors={"photo": str(exc)})
                from apps.hospital_master.models import Hospital as _Hospital
                _hospital = _Hospital.objects.using("default").filter(pk=request.hospital_id).first()
                folder = blob_storage.hospital_folder(_hospital) if _hospital else request.hospital_db
                identity = blob_storage.identity_slug(name=staff.get_full_name(), identifier=staff.email)
                try:
                    staff.photo = blob_storage.upload_data_uri(
                        photo, prefix=f"staff-photos/{folder}", mime_type=mime_type,
                        category="staff-photo", identity=identity,
                    )
                except blob_storage.StorageError as exc:
                    return error(str(exc), errors={"photo": str(exc)})

        s = StaffMeSerializer(staff, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(staff, attr, val)
        staff.save(using=request.hospital_db)
        if "photo" in request.data and old_photo_key and old_photo_key != staff.photo:
            blob_storage.delete(old_photo_key)
        return success(data=StaffMeSerializer(staff).data, message="Profile updated.")


# ── Doctors list (for scheduling dropdown etc.) ───────────────────────────────

class DoctorListView(APIView):
    """GET /api/v1/org/doctors/?q=&specialisation=&branch_id= — list doctors"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        qs = StaffUser.objects.using(request.hospital_db).filter(
            acts_as_q("doctor"),
            is_active=True,
        ).select_related("group").prefetch_related(*PLACE_PREFETCH)

        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q)
                | Q(specialisation__icontains=q)
                | Q(known_for__icontains=q)
            )

        specialisation = (request.query_params.get("specialisation") or "").strip()
        if specialisation:
            qs = qs.filter(specialisation__iexact=specialisation)

        branch_id = request.query_params.get("branch_id")
        if branch_id:
            from apps.hospital_setup.branch_utils import get_staff_ids_in_branch
            qs = qs.filter(pk__in=get_staff_ids_in_branch(branch_id, request.hospital_db))

        return success(data=StaffSerializer(qs.distinct(), many=True).data)


class DoctorSpecialisationListView(APIView):
    """GET /api/v1/org/doctors/specialisations/ — distinct, non-blank"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        values = (
            StaffUser.objects.using(request.hospital_db)
            .filter(acts_as_q("doctor"), is_active=True)
            .exclude(specialisation="")
            .values_list("specialisation", flat=True)
            .distinct()
            .order_by("specialisation")
        )
        return success(data=[v for v in values if v])


# ── Hospital-level clinical settings ───────────────────────────────────────────

class HospitalSettingsView(APIView):
    """GET   /api/v1/org/settings/  — read hospital-level clinical config"""
    def get_permissions(self):
        # Any staff role may read (the doctor profile needs fee_ownership);
        perm = IsHospitalStaff if self.request.method == "GET" else IsHospitalAdmin
        return [IsAuthenticated(), perm()]

    def _get_hospital(self, request):
        from apps.hospital_master.models import Hospital as _Hospital
        try:
            return _Hospital.objects.using("default").get(pk=request.hospital_id)
        except _Hospital.DoesNotExist:
            return None

    def get(self, request):
        hospital = self._get_hospital(request)
        if not hospital:
            return not_found("Hospital not found.")
        params = parameters_of(hospital)
        if not IsHospitalAdmin().has_permission(request, self):
            return success(data={"fee_ownership": params.fee_ownership})
        return success(data={
            "fee_ownership": params.fee_ownership,
            # Read-only here — staff need this to log in with Employee ID
            "hospital_code": hospital.hospital_code,
            # ── Billing config ──────────────────────────────────────────
            "registration_fee_enabled": params.registration_fee_enabled,
            "registration_fee_amount": str(params.registration_fee_amount),
            "default_tax_rate": str(params.default_tax_rate),
            # ── Branding ───────────────────────────────────────────────
            "logo": params.logo.url if params.logo else "",
        })

    def patch(self, request):
        hospital = self._get_hospital(request)
        if not hospital:
            return not_found("Hospital not found.")
        params = parameters_of(hospital)
        allowed = {"fee_ownership", "registration_fee_enabled", "registration_fee_amount", "default_tax_rate", "logo"}
        for key, val in request.data.items():
            if key not in allowed:
                return error(f"Field '{key}' is not configurable here.")
        if "fee_ownership" in request.data:
            fo = request.data["fee_ownership"]
            from apps.hospital_master.models import HospitalParameters
            valid = [c[0] for c in HospitalParameters.FEE_OWNERSHIP_CHOICES]
            if fo not in valid:
                return error(f"fee_ownership must be one of: {valid}.")
            params.fee_ownership = fo
        if "registration_fee_enabled" in request.data:
            params.registration_fee_enabled = bool(request.data["registration_fee_enabled"])
        if "registration_fee_amount" in request.data:
            try:
                amt = Decimal(str(request.data["registration_fee_amount"]))
            except Exception:
                return error("registration_fee_amount must be a number.")
            if amt < 0:
                return error("registration_fee_amount can't be negative.")
            params.registration_fee_amount = amt
        if "default_tax_rate" in request.data:
            try:
                rate = Decimal(str(request.data["default_tax_rate"]))
            except Exception:
                return error("default_tax_rate must be a number.")
            if rate < 0 or rate > 100:
                return error("default_tax_rate must be between 0 and 100.")
            params.default_tax_rate = rate
        old_logo_key = params.logo.name
        if "logo" in request.data:
            logo = request.data["logo"] or ""
            # Client resizes before upload (see HospitalLogoUpload.jsx), but
            if len(logo) > 1_500_000:
                return error("Logo image is too large. Please upload a smaller file.")
            if not logo:
                params.logo = ""
            else:
                try:
                    mime_type = validate_data_uri(logo)
                except FileValidationError as exc:
                    return error(str(exc), errors={"logo": str(exc)})
                try:
                    data = base64.b64decode(logo.split(",", 1)[1])
                    ext = mimetypes.guess_extension(mime_type) or ".png"
                    params.logo.save(f"logo{ext}", ContentFile(data), save=False)
                except blob_storage.StorageError as exc:
                    return error(str(exc), errors={"logo": str(exc)})
        params.save(using="default")
        if "logo" in request.data and old_logo_key and old_logo_key != params.logo.name:
            blob_storage.delete(old_logo_key)
        return success(data={
            "fee_ownership": params.fee_ownership,
            "registration_fee_enabled": params.registration_fee_enabled,
            "registration_fee_amount": str(params.registration_fee_amount),
            "default_tax_rate": str(params.default_tax_rate),
            "logo": params.logo.url if params.logo else "",
        }, message="Settings updated.")


# ── Doctor working-hours schedule ─────────────────────────────────────────────

class DoctorScheduleView(APIView):
    """GET   /api/v1/org/staff/<pk>/schedule/[?branch_id=]  — get doctor's working hours at one of their places (default: the primary one)"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def _get_doctor(self, request, pk):
        try:
            staff = StaffUser.objects.using(request.hospital_db).get(pk=pk, is_active=True)
            if staff.role != "doctor":
                return None, error("Schedule is only supported for doctors.")
            return staff, None
        except StaffUser.DoesNotExist:
            return None, not_found("Doctor not found.")

    def _can_edit(self, request, staff):
        """Admin always can; the doctor can edit their own schedule."""
        acts_as = getattr(request.user, "acts_as", [])
        if request.user.role == "hospital_admin" or "hospital_admin" in acts_as:
            return True
        if (request.user.role == "doctor" or "doctor" in acts_as) and request.user.id == staff.id:
            return True
        return False

    def get(self, request, pk):
        staff, err = self._get_doctor(request, pk)
        if err:
            return err
        sched = room_utils.schedule_of(staff.id, request.hospital_db, branch_id=request.query_params.get("branch_id"))
        if sched is None or not room_utils.hours_of(sched):
            return success(data=None)   # no schedule configured yet
        return success(data=room_utils.schedule_json(sched))

    def put(self, request, pk):
        from apps.hospital_setup.staff_serializers import DoctorScheduleSerializer as _SS
        staff, err = self._get_doctor(request, pk)
        if err:
            return err
        if not self._can_edit(request, staff):
            return error("You do not have permission to edit this schedule.", status=403)

        s = _SS(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)

        sched = room_utils.schedule_of(staff.id, request.hospital_db, branch_id=request.query_params.get("branch_id"), create=True)
        if sched is None:
            return error("Give this doctor a branch before setting a schedule.", errors={"branch_id": "No place of work."})
        vd = s.validated_data
        room_utils.set_hours(sched, vd.get("slot_duration_minutes", sched.slot_duration_minutes), vd["days"], request.hospital_db)
        return success(data=room_utils.schedule_json(sched), message="Schedule updated.")


class RoomAssignmentListCreateView(APIView):
    """GET  /api/v1/org/room-assignments/?room_id=&doctor_id=  — list (any staff)"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        db = request.hospital_db
        blocks = room_utils.room_blocks(db, room_id=request.query_params.get("room_id"), doctor_id=request.query_params.get("doctor_id"),
                                        branch_id=request.query_params.get("branch_id"))
        return success(data=[room_utils.block_json(db, block) for block in blocks])

    def post(self, request):
        from django.db import transaction

        s = RoomAssignmentSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data
        db = request.hospital_db

        try:
            room = Room.objects.using(db).select_related("floor").get(pk=d["room"].id, is_active=True)
        except Room.DoesNotExist:
            return error("Room not found.", errors={"room": "Invalid room."})
        try:
            doctor = StaffUser.objects.using(db).get(acts_as_q("doctor"), pk=d["doctor"].id, is_active=True)
        except StaffUser.DoesNotExist:
            return error("Doctor not found.", errors={"doctor": "Invalid doctor."})

        with transaction.atomic(using=db):
            clash = room_utils.find_overlapping_assignment(db, room.id, d["day_of_week"], d["start_time"], d["end_time"])
            if clash:
                return error(
                    f"{room.name} is already assigned to Dr. {clash['doctor'].get_full_name()} "
                    f"on {dict(room_utils.DoctorSchedule.DAY_CHOICES)[clash['day_of_week']]} from {clash['start_time'].strftime('%H:%M')} "
                    f"to {clash['end_time'].strftime('%H:%M')} — times overlap.",
                    errors={"start_time": "Overlaps an existing assignment."},
                    status=409,
                )
            block = room_utils.save_block(db, room, doctor, d["day_of_week"], d["start_time"], d["end_time"])
            if block is None:
                return error("This doctor does not work at the room's branch.", errors={"doctor": "No place of work at this branch."})

        return created(data=room_utils.block_json(db, block), message="Room assignment created.")


class RoomAssignmentDetailView(APIView):
    """PATCH  /api/v1/org/room-assignments/{id}/ — edit day/time/doctor (re-checks overlap)"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def patch(self, request, pk):
        from django.db import transaction

        db = request.hospital_db
        block = room_utils.get_block(db, pk)
        if not block:
            return not_found("Room assignment not found.")

        s = RoomAssignmentSerializer(data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        d = s.validated_data

        day_of_week = d.get("day_of_week", block["day_of_week"])
        start_time  = d.get("start_time", block["start_time"])
        end_time    = d.get("end_time", block["end_time"])
        is_active   = d.get("is_active", block["is_active"])
        if start_time >= end_time:
            return error("Validation error.", errors={"end_time": ["End time must be after start time."]})
        try:
            room = Room.objects.using(db).select_related("floor").get(pk=d["room"].id if "room" in d else block["room_id"])
            doctor = StaffUser.objects.using(db).get(pk=d["doctor"].id if "doctor" in d else block["doctor_id"])
        except (Room.DoesNotExist, StaffUser.DoesNotExist):
            return not_found("Room or doctor not found.")

        with transaction.atomic(using=db):
            clash = room_utils.find_overlapping_assignment(db, room.id, day_of_week, start_time, end_time, exclude_id=block["id"]) if is_active else None
            if clash:
                return error(
                    f"Overlaps Dr. {clash['doctor'].get_full_name()}'s existing assignment "
                    f"({dict(room_utils.DoctorSchedule.DAY_CHOICES)[clash['day_of_week']]} {clash['start_time'].strftime('%H:%M')}"
                    f"–{clash['end_time'].strftime('%H:%M')}).",
                    errors={"start_time": "Overlaps an existing assignment."},
                    status=409,
                )
            saved = room_utils.save_block(db, room, doctor, day_of_week, start_time, end_time, is_active=is_active, block_id=block["id"])
            if saved is None:
                return error("This doctor does not work at the room's branch.", errors={"doctor": "No place of work at this branch."})

        return success(data=room_utils.block_json(db, saved), message="Room assignment updated.")

    def delete(self, request, pk):
        db = request.hospital_db
        block = room_utils.get_block(db, pk)
        if not block:
            return not_found("Room assignment not found.")
        saved = room_utils.save_block(db, Room.objects.using(db).select_related("floor").get(pk=block["room_id"]), block["doctor"],
                                      block["day_of_week"], block["start_time"], block["end_time"], is_active=False, block_id=block["id"])
        return success(message="Room assignment removed.")
