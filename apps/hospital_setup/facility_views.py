"""apps/org/views.py"""

import logging

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from django.db import transaction

from core.api.permissions import IsHospitalAdmin, IsHospitalStaff, IsFrontDesk
from core.api.response import success, created, error, not_found

from django.db.models import Q

from apps.hospital_setup.models import Branch, BranchDepartment, Department, Floor, Room, Bed
from apps.hospital_setup.models import StaffUser, DoctorSchedule
from apps.hospital_setup import room_utils
from apps.hospital_setup.branch_utils import ensure_default_place
from apps.hospital_setup.rbac import acts_as_q

logger = logging.getLogger(__name__)


from apps.hospital_setup.staff_services import seed_next_numbers

from apps.hospital_setup.facility_serializers import BranchSerializer, BranchDepartmentSerializer, DepartmentSerializer, FloorSerializer, RoomSerializer, BedSerializer

# Rough cap on the base64 photo payload — keeps us comfortably under DRF's
_MAX_PHOTO_BASE64_CHARS = 1_900_000


# ── Branches ──────────────────────────────────────────────────────────────────

class BranchListCreateView(APIView):
    """GET  /api/v1/org/branches/ — list all branches (any staff)"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        branches = Branch.objects.using(request.hospital_db).filter(is_active=True)
        return success(data=BranchSerializer(branches, many=True).data)

    def post(self, request):
        # ── Subscription limit check (fails CLOSED — see apps.hospital_master.services) ──
        from apps.hospital_master.models import Hospital
        from apps.hospital_master.services import check_limit, LimitCheckFailed
        try:
            hospital = Hospital.objects.using("default").get(pk=request.hospital_id)
            check_limit(hospital, request.hospital_db, "branches")
        except Hospital.DoesNotExist:
            return error("Unable to verify your plan limits right now. Please try again shortly.", status=503)
        except LimitCheckFailed as exc:
            return error(exc.message, status=exc.status)

        s = BranchSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        # Instantiate without save, then save with explicit `using=`
        branch = Branch(**s.validated_data)
        branch.save(using=request.hospital_db)

        # Seed NNTM rows so UHID / invoice / lab / Rx / queue numbers work immediately
        seed_next_numbers(branch.id, request.hospital_db)
        # A branch always offers at least one department, so staff and visits can be placed there before any department is added
        ensure_default_place(request.hospital_db, branch)

        return created(data=BranchSerializer(branch).data, message="Branch created.")


class BranchDetailView(APIView):
    """GET   /api/v1/org/branches/{id}/ — branch detail"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return Branch.objects.using(request.hospital_db).get(pk=pk)
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
        branch.save(using=request.hospital_db)
        return success(data=BranchSerializer(branch).data, message="Branch updated.")

    def delete(self, request, pk):
        branch = self._get(request, pk)
        if not branch:
            return not_found("Branch not found.")
        branch.is_active = False
        branch.save(using=request.hospital_db, update_fields=["is_active"])
        return success(message="Branch deactivated.")


# ── Departments ───────────────────────────────────────────────────────────────

class DepartmentListCreateView(APIView):
    """GET  /api/v1/org/departments/                — the hospital's departments, each with the branches that offer it
    GET  /api/v1/org/departments/?branch_id=1     — the departments that branch offers (`id` is the department id)
    POST /api/v1/org/departments/                 — {branch, name, floor?}: offer a department at a branch, creating the department if it is new"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        db = request.hospital_db
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            places = (BranchDepartment.objects.using(db).filter(branch_id=branch_id, is_active=True, department__is_active=True)
                      .select_related("branch", "department", "floor"))
            return success(data=BranchDepartmentSerializer(places, many=True).data)
        qs = Department.objects.using(db).filter(is_active=True)
        return success(data=DepartmentSerializer(qs, many=True).data)

    def post(self, request):
        db = request.hospital_db
        name = (request.data.get("name") or "").strip()
        if not name:
            return error("Validation error.", errors={"name": "Enter a name."})
        try:
            branch = Branch.objects.using(db).get(pk=request.data.get("branch"), is_active=True)
        except (Branch.DoesNotExist, ValueError, TypeError):
            return error("Branch not found.", errors={"branch": "Invalid branch."})
        floor = None
        if request.data.get("floor"):
            floor = Floor.objects.using(db).filter(pk=request.data["floor"], branch=branch, is_active=True).first()
            if floor is None:
                return error("Floor not found at this branch.", errors={"floor": "Invalid floor."})

        with transaction.atomic(using=db):
            department = Department.objects.using(db).filter(name__iexact=name).first()
            if department is None:
                department = Department(name=name)
                department.save(using=db)
            elif not department.is_active:
                department.is_active = True
                department.save(using=db, update_fields=["is_active", "updated_at"])
            place = BranchDepartment.objects.using(db).filter(branch=branch, department=department).first()
            if place is not None and place.is_active:
                return error("This branch already offers that department.", errors={"name": "Already offered."})
            if place is None:
                # every department sits on a floor; default to the branch's own, creating one if it has none yet
                if floor is None:
                    floor = (Floor.objects.using(db).filter(branch=branch).order_by("level", "id").first()
                             or Floor.objects.using(db).create(branch=branch, name="Ground"))
                place = BranchDepartment(branch=branch, department=department, floor=floor)
            else:
                place.is_active = True
                if floor is not None:
                    place.floor = floor
            place.save(using=db)
        place = BranchDepartment.objects.using(db).select_related("branch", "department", "floor").get(pk=place.pk)
        return created(data=BranchDepartmentSerializer(place).data, message="Department created.")


class DepartmentDetailView(APIView):
    """PATCH  /api/v1/org/departments/{id}/                — rename the department for every branch, or deactivate it
    DELETE /api/v1/org/departments/{id}/?branch_id=   — stop one branch offering it; without branch_id, deactivate it everywhere"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return Department.objects.using(request.hospital_db).get(pk=pk)
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
        dept.save(using=request.hospital_db)
        return success(data=DepartmentSerializer(dept).data, message="Department updated.")

    def delete(self, request, pk):
        db = request.hospital_db
        dept = self._get(request, pk)
        if not dept:
            return not_found("Department not found.")
        branch_id = request.query_params.get("branch_id")
        places = BranchDepartment.objects.using(db).filter(department=dept, is_active=True).select_related("branch")
        if branch_id:
            places = places.filter(branch_id=branch_id)
        # A branch must keep at least one department: staff and visits are placed in one
        for place in places:
            if not BranchDepartment.objects.using(db).filter(branch_id=place.branch_id, is_active=True).exclude(pk=place.pk).exists():
                return error(f"{place.branch.name} would be left with no department. Add another one there first.")
        BranchDepartment.objects.using(db).filter(pk__in=[p.pk for p in places]).update(is_active=False)
        if not branch_id:
            dept.is_active = False
            dept.save(using=db, update_fields=["is_active", "updated_at"])
        return success(message="Department deactivated.")


class BranchDepartmentDetailView(APIView):
    """PATCH /api/v1/org/branch-departments/{id}/ — {floor}: put a department on a floor of its branch (null for no floor)"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def patch(self, request, pk):
        db = request.hospital_db
        place = BranchDepartment.objects.using(db).select_related("branch", "department", "floor").filter(pk=pk).first()
        if place is None:
            return not_found("Department at this branch not found.")
        if "floor" not in request.data:
            return error("Validation error.", errors={"floor": "Required (use null for no floor)."})
        floor = None
        if request.data["floor"] is not None:
            floor = Floor.objects.using(db).filter(pk=request.data["floor"], branch_id=place.branch_id, is_active=True).first()
            if floor is None:
                return error("Floor not found at this branch.", errors={"floor": "Invalid floor."})
        place.floor = floor
        place.save(using=db, update_fields=["floor", "updated_at"])
        return success(data=BranchDepartmentSerializer(place).data, message="Department updated.")


# ── Floors ───────────────────────────────────────────────────────────────

class FloorListCreateView(APIView):
    """GET  /api/v1/org/floors/?branch_id=1  — list floors (any staff, read-only)"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = Floor.objects.using(request.hospital_db).filter(is_active=True).select_related("branch")
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return success(data=FloorSerializer(qs, many=True).data)

    def post(self, request):
        s = FloorSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        branch_id = s.validated_data["branch"].id
        try:
            branch = Branch.objects.using(request.hospital_db).get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            return error("Branch not found.", errors={"branch": "Invalid branch."})

        if Floor.objects.using(request.hospital_db).filter(
            branch=branch, name__iexact=s.validated_data["name"], is_active=True
        ).exists():
            return error("A floor with this name already exists at this branch.",
                         errors={"name": "Already in use."})

        floor = Floor(branch=branch, name=s.validated_data["name"], level=s.validated_data.get("level", 0))
        floor.save(using=request.hospital_db)
        return created(data=FloorSerializer(floor).data, message="Floor created.")


class FloorDetailView(APIView):
    """PATCH  /api/v1/org/floors/{id}/ — rename / renumber"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return Floor.objects.using(request.hospital_db).get(pk=pk)
        except Floor.DoesNotExist:
            return None

    def patch(self, request, pk):
        floor = self._get(request, pk)
        if not floor:
            return not_found("Floor not found.")
        s = FloorSerializer(floor, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        for attr, val in s.validated_data.items():
            setattr(floor, attr, val)
        floor.save(using=request.hospital_db)
        return success(data=FloorSerializer(floor).data, message="Floor updated.")

    def delete(self, request, pk):
        floor = self._get(request, pk)
        if not floor:
            return not_found("Floor not found.")
        floor.is_active = False
        floor.save(using=request.hospital_db, update_fields=["is_active"])
        return success(message="Floor deactivated.")


# ── Rooms & Room Assignments ──────────────────────────────────────────────────

def _room_type_option(db, value):
    """Looks up the billing.OptionList(list_type="room_type") row a room_type"""
    from apps.billing.models import OptionList
    return OptionList.objects.using(db).filter(
        list_type=OptionList.LIST_ROOM_TYPE, value=value, is_active=True
    ).first()


def _place_of_department(db, branch_id, department):
    """The branch_department of a department at a branch, or an error message when that branch does not offer it."""
    if department is None:
        return None, None
    place = BranchDepartment.objects.using(db).filter(branch_id=branch_id, department_id=department.id, is_active=True).first()
    if place is None:
        return None, f"{department.name} is not offered at this branch."
    return place, None


class RoomListCreateView(APIView):
    """GET  /api/v1/org/rooms/?branch_id=1  — list rooms (any staff, read-only)."""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = (Room.objects.using(request.hospital_db).filter(is_active=True)
              .select_related("floor__branch", "branch_department__department"))
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(floor__branch_id=branch_id)
        return success(data=RoomSerializer(qs, many=True).data)

    def post(self, request):
        db = request.hospital_db
        s = RoomSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        floor = s.validated_data["floor"]
        try:
            floor = Floor.objects.using(db).select_related("branch").get(pk=floor.id, is_active=True, branch__is_active=True)
        except Floor.DoesNotExist:
            return error("Floor not found.", errors={"floor_obj": "Invalid floor."})
        if request.data.get("branch") not in (None, "", floor.branch_id) and str(request.data.get("branch")) != str(floor.branch_id):
            return error("That floor belongs to a different branch.", errors={"floor_obj": "Not a floor of this branch."})

        if Room.objects.using(db).filter(floor=floor, name__iexact=s.validated_data["name"], is_active=True).exists():
            return error("A room with this name already exists on this floor.", errors={"name": "Already in use."})

        room_type = s.validated_data.get("room_type", "consultation")
        type_option = _room_type_option(db, room_type)
        if not type_option:
            return error("Not a configured room type for this hospital.", errors={"room_type": "Invalid choice."})

        # Bed capacity is required at setup time for a bed-based room type
        capacity = s.validated_data.get("capacity")
        if type_option.is_bed_based:
            if capacity is None or capacity < 1:
                return error("Bed capacity is required for this room type.",
                             errors={"capacity": "Enter the number of beds this room can hold."})
        else:
            capacity = None

        place, problem = _place_of_department(db, floor.branch_id, s.validated_data.get("department"))
        if problem:
            return error(problem, errors={"department": "Not offered at this branch."})
        room = Room(floor=floor, branch_department=place,
                    name=s.validated_data["name"], room_type=room_type, capacity=capacity)
        room.save(using=db)
        room = Room.objects.using(db).select_related("floor__branch", "branch_department__department").get(pk=room.pk)
        return created(data=RoomSerializer(room).data, message="Room created.")


class RoomDetailView(APIView):
    """PATCH  /api/v1/org/rooms/{id}/ — rename / move floor / change type / capacity / department"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return (Room.objects.using(request.hospital_db).select_related("floor__branch", "branch_department__department").get(pk=pk))
        except Room.DoesNotExist:
            return None

    def patch(self, request, pk):
        db = request.hospital_db
        room = self._get(request, pk)
        if not room:
            return not_found("Room not found.")
        s = RoomSerializer(room, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        data = dict(s.validated_data)
        effective_room_type = data.get("room_type", room.room_type)
        if "room_type" in data:
            if not _room_type_option(db, data["room_type"]):
                return error("Not a configured room type for this hospital.", errors={"room_type": "Invalid choice."})
        if "capacity" in data:
            new_capacity = data["capacity"]
            type_option = _room_type_option(db, effective_room_type)
            if type_option and type_option.is_bed_based:
                if new_capacity is None or new_capacity < 1:
                    return error("Bed capacity is required for this room type.",
                                 errors={"capacity": "Enter the number of beds this room can hold."})
                current_beds = room.r_beds.filter(is_active=True).count()
                if new_capacity < current_beds:
                    return error(
                        f"Capacity can't be set below {current_beds} — this room already has {current_beds} bed{'s' if current_beds != 1 else ''}. Remove a bed first.",
                        errors={"capacity": "Below current bed count."},
                    )
            else:
                data["capacity"] = None
        floor = data.get("floor", room.floor)
        if "floor" in data and floor.branch_id != room.floor.branch_id and room.r_beds.filter(is_active=True).exists():
            return error("Move the beds out first: a room with beds cannot change branch.", errors={"floor_obj": "Has beds."})
        if "department" in data or "floor" in data:
            department = data["department"] if "department" in data else (room.branch_department.department if room.branch_department_id else None)
            place, problem = _place_of_department(db, floor.branch_id, department)
            if problem:
                return error(problem, errors={"department": "Not offered at this branch."})
            room.branch_department = place
        data.pop("department", None)
        for attr, val in data.items():
            setattr(room, attr, val)
        room.save(using=db)
        return success(data=RoomSerializer(room).data, message="Room updated.")

    def delete(self, request, pk):
        room = self._get(request, pk)
        if not room:
            return not_found("Room not found.")
        room.is_active = False
        room.save(using=request.hospital_db, update_fields=["is_active"])
        # Assignments for a deactivated room are pointless to keep active —
        room_utils.deactivate_room_blocks(request.hospital_db, room.id)
        return success(message="Room deactivated.")


# ── Beds ────────────────────────────────────────────────────────────────

class BedListCreateView(APIView):
    """GET  /api/v1/org/beds/?room_id=&branch_id=&status=  — list beds"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = Bed.objects.using(request.hospital_db).filter(is_active=True).select_related("room__floor")
        room_id = request.query_params.get("room_id")
        if room_id:
            qs = qs.filter(room_id=room_id)
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(room__floor__branch_id=branch_id)
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return success(data=BedSerializer(qs, many=True).data)

    def post(self, request):
        s = BedSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        room_id = s.validated_data["room"].id
        try:
            room = Room.objects.using(request.hospital_db).get(pk=room_id, is_active=True)
        except Room.DoesNotExist:
            return error("Room not found.", errors={"room": "Invalid room."})

        type_option = _room_type_option(request.hospital_db, room.room_type)
        if not type_option or not type_option.is_bed_based:
            return error(f"{room.name} isn't a bed-based room type — beds can't be added to it.",
                         errors={"room": "Not a bed-based room type."})

        if Bed.objects.using(request.hospital_db).filter(
            room=room, bed_number__iexact=s.validated_data["bed_number"], is_active=True
        ).exists():
            return error("A bed with this number already exists in this room.",
                         errors={"bed_number": "Already in use."})

        # Rooms created before `capacity` existed are still capacity=None
        if room.capacity is not None:
            current_beds = Bed.objects.using(request.hospital_db).filter(room=room, is_active=True).count()
            if current_beds >= room.capacity:
                return error(
                    f"{room.name} is at full capacity ({current_beds}/{room.capacity} beds) — "
                    f"increase its capacity or remove a bed first.",
                    errors={"room": "At capacity."},
                )

        bed = Bed(room=room, bed_number=s.validated_data["bed_number"],
                  status=s.validated_data.get("status", Bed.STATUS_AVAILABLE))
        bed.save(using=request.hospital_db)
        return created(data=BedSerializer(bed).data, message="Bed created.")


class BedDetailView(APIView):
    """PATCH  /api/v1/org/beds/{id}/ — rename the bed number (or move it to a"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return Bed.objects.using(request.hospital_db).select_related("room").get(pk=pk)
        except Bed.DoesNotExist:
            return None

    def patch(self, request, pk):
        bed = self._get(request, pk)
        if not bed:
            return not_found("Bed not found.")
        data = {k: v for k, v in request.data.items() if k != "status"}
        s = BedSerializer(bed, data=data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        # Moving a bed into a different room is subject to that room's
        new_room = s.validated_data.get("room")
        if new_room is not None and new_room.id != bed.room_id:
            type_option = _room_type_option(request.hospital_db, new_room.room_type)
            if not type_option or not type_option.is_bed_based:
                return error(f"{new_room.name} isn't a bed-based room type — a bed can't be moved into it.",
                             errors={"room": "Not a bed-based room type."})
            if new_room.capacity is not None:
                current_beds = Bed.objects.using(request.hospital_db).filter(room=new_room, is_active=True).count()
                if current_beds >= new_room.capacity:
                    return error(
                        f"{new_room.name} is at full capacity ({current_beds}/{new_room.capacity} beds) — "
                        f"increase its capacity or remove a bed first.",
                        errors={"room": "At capacity."},
                    )
        for attr, val in s.validated_data.items():
            setattr(bed, attr, val)
        bed.save(using=request.hospital_db)
        return success(data=BedSerializer(bed).data, message="Bed updated.")

    def delete(self, request, pk):
        bed = self._get(request, pk)
        if not bed:
            return not_found("Bed not found.")
        if bed.status == Bed.STATUS_OCCUPIED:
            return error("This bed is occupied — release it (or discharge the admission) before deactivating.")
        bed.is_active = False
        bed.save(using=request.hospital_db, update_fields=["is_active"])
        return success(message="Bed deactivated.")


class BedMarkCleanView(APIView):
    """POST /api/v1/org/beds/{id}/mark-clean/ — cleaning -> available."""
    permission_classes = [IsAuthenticated, IsFrontDesk]

    def post(self, request, pk):
        db = request.hospital_db
        with transaction.atomic(using=db):
            try:
                bed = Bed.objects.using(db).select_for_update().get(pk=pk, is_active=True)
            except Bed.DoesNotExist:
                return not_found("Bed not found.")
            if bed.status != Bed.STATUS_CLEANING:
                return error(f"This bed is {bed.get_status_display().lower()}, not awaiting cleaning.")
            bed.status = Bed.STATUS_AVAILABLE
            bed.save(using=db, update_fields=["status", "updated_at"])
        return success(data=BedSerializer(bed).data, message="Bed marked clean and available.")


class BedMaintenanceView(APIView):
    """POST /api/v1/org/beds/{id}/maintenance/  body: {"action": "block" | "out_of_service" | "unblock"}"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    ACTION_TO_STATUS = {
        "block": Bed.STATUS_BLOCKED,
        "out_of_service": Bed.STATUS_OUT_OF_SERVICE,
        "unblock": Bed.STATUS_AVAILABLE,
    }

    def post(self, request, pk):
        db = request.hospital_db
        action = request.data.get("action")
        if action not in self.ACTION_TO_STATUS:
            return error("Invalid action.", errors={"action": "Must be one of: block, out_of_service, unblock."})

        with transaction.atomic(using=db):
            try:
                bed = Bed.objects.using(db).select_for_update().get(pk=pk, is_active=True)
            except Bed.DoesNotExist:
                return not_found("Bed not found.")

            if action == "unblock":
                if bed.status not in (Bed.STATUS_BLOCKED, Bed.STATUS_OUT_OF_SERVICE):
                    return error(f"This bed is {bed.get_status_display().lower()}, not blocked or out of service.")
            else:
                if bed.status != Bed.STATUS_AVAILABLE:
                    return error(
                        f"This bed is {bed.get_status_display().lower()} — only an available bed can be "
                        "taken out of rotation."
                    )

            bed.status = self.ACTION_TO_STATUS[action]
            bed.save(using=db, update_fields=["status", "updated_at"])
        return success(data=BedSerializer(bed).data, message="Bed updated.")


class BedBoardView(APIView):
    """GET /api/v1/org/beds/board/?branch_id="""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        from apps.billing.models import OptionList

        db = request.hospital_db
        branch_id = request.query_params.get("branch_id") or request.user.branch_id
        if not branch_id:
            return error("branch_id is required.", errors={"branch_id": "Required."})

        bed_based_types = {
            opt.value for opt in OptionList.objects.using(db).filter(
                list_type=OptionList.LIST_ROOM_TYPE, is_bed_based=True, is_active=True,
            )
        }
        rooms = (
            Room.objects.using(db)
            .filter(floor__branch_id=branch_id, is_active=True, room_type__in=bed_based_types)
            .select_related("floor", "branch_department__department")
            .prefetch_related("r_beds")
            .order_by("floor__level", "name")
        )

        floors = {}
        for room in rooms:
            floor_bucket = floors.setdefault(room.floor_id, {
                "floor_id": room.floor_id,
                "floor_name": room.floor.name,
                "rooms": [],
            })
            beds = [b for b in room.r_beds.all() if b.is_active]
            floor_bucket["rooms"].append({
                "room_id": room.id,
                "room_name": room.name,
                "room_type": room.room_type,
                "department_name": room.department.name if room.branch_department_id else None,
                "capacity": room.capacity,
                "beds": BedSerializer(beds, many=True).data,
            })

        return success(data={"floors": list(floors.values())})


# ── Front-desk triage: department-level doctor availability ────────────────

class DepartmentAvailabilityView(APIView):
    """GET /api/v1/org/departments/availability/?branch_id=&date=YYYY-MM-DD"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        from datetime import date as _date, timedelta as _timedelta, datetime as _datetime

        db = request.hospital_db
        branch_id = request.query_params.get("branch_id") or request.user.branch_id
        date_param = request.query_params.get("date")
        try:
            target_date = _datetime.strptime(date_param, "%Y-%m-%d").date() if date_param else _date.today()
        except ValueError:
            return error("Invalid date — use YYYY-MM-DD.", errors={"date": "Invalid format."})

        now_time = timezone.localtime().time() if target_date == _date.today() else None

        places = (BranchDepartment.objects.using(db).filter(is_active=True, department__is_active=True)
                  .select_related("department"))
        if branch_id:
            places = places.filter(branch_id=branch_id)

        results = []
        for place in places:
            dept = place.department
            doctor_ids = StaffUser.objects.using(db).filter(
                acts_as_q("doctor"), is_active=True, u_branch_departments__branch_department=place,
            ).values_list("id", flat=True)
            schedules = DoctorSchedule.objects.using(db).filter(
                staff_branch_department__branch_department=place, staff_branch_department__staff_id__in=list(doctor_ids))
            doctors_free_today = 0
            best_slot = None

            for schedule in schedules:
                slots_by_day = {row["day_of_week"]: row for row in room_utils.hours_of(schedule)}

                found = None
                for offset in range(8):  # today + next 7 days
                    check_date = target_date + _timedelta(days=offset)
                    day_row = slots_by_day.get(check_date.weekday())
                    if not day_row or not day_row["is_available"]:
                        continue
                    start_time = day_row["start_time"]
                    if offset == 0 and now_time and now_time > day_row["end_time"]:
                        continue  # today's window already over
                    if offset == 0 and now_time and now_time > start_time:
                        start_time = now_time  # window already open — "free" starts now
                    found = (check_date, start_time)
                    break

                if not found:
                    continue
                if found[0] == target_date:
                    doctors_free_today += 1
                if best_slot is None or found < best_slot:
                    best_slot = found

            results.append({
                "department_id": dept.id,
                "branch_department_id": place.id,
                "department_name": dept.name,
                "doctors_free_today": doctors_free_today,
                "is_available_today": best_slot is not None and best_slot[0] == target_date,
                "next_available_date": best_slot[0].isoformat() if best_slot else None,
                "next_available_time": best_slot[1].strftime("%H:%M") if best_slot else None,
            })

        return success(data=results)
