"""apps/org/views.py"""

import logging

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from django.db import transaction

from core.api.permissions import IsHospitalAdmin, IsHospitalStaff, IsFrontDesk
from core.api.response import success, created, error, not_found

from apps.hospital_setup.models import Branch, Department, Floor, Room, Bed
from apps.hospital_setup.models import StaffUser, RoomAssignment, DoctorSchedule

logger = logging.getLogger(__name__)


from apps.hospital_setup.staff_services import seed_next_numbers

from apps.hospital_setup.facility_serializers import BranchSerializer, DepartmentSerializer, FloorSerializer, RoomSerializer, BedSerializer

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
    """GET  /api/v1/org/departments/?branch_id=1  — list departments"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = Department.objects.using(request.hospital_db).filter(is_active=True)
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return success(data=DepartmentSerializer(qs, many=True).data)

    def post(self, request):
        s = DepartmentSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        # Verify branch belongs to this hospital
        branch_id = s.validated_data["branch"].id
        try:
            branch = Branch.objects.using(request.hospital_db).get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            return error("Branch not found.", errors={"branch": "Invalid branch."})

        dept = Department(branch=branch, name=s.validated_data["name"])
        dept.save(using=request.hospital_db)
        return created(data=DepartmentSerializer(dept).data, message="Department created.")


class DepartmentDetailView(APIView):
    """PATCH /api/v1/org/departments/{id}/ — rename or deactivate."""
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
        dept = self._get(request, pk)
        if not dept:
            return not_found("Department not found.")
        dept.is_active = False
        dept.save(using=request.hospital_db, update_fields=["is_active"])
        return success(message="Department deactivated.")


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


class RoomListCreateView(APIView):
    """GET  /api/v1/org/rooms/?branch_id=1  — list rooms (any staff, read-only)."""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = Room.objects.using(request.hospital_db).filter(is_active=True).select_related("branch", "department", "floor_obj")
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return success(data=RoomSerializer(qs, many=True).data)

    def post(self, request):
        s = RoomSerializer(data=request.data)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        branch_id = s.validated_data["branch"].id
        try:
            branch = Branch.objects.using(request.hospital_db).get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            return error("Branch not found.", errors={"branch": "Invalid branch."})

        if Room.objects.using(request.hospital_db).filter(
            branch=branch, name__iexact=s.validated_data["name"], is_active=True
        ).exists():
            return error("A room with this name already exists at this branch.",
                         errors={"name": "Already in use."})

        room_type = s.validated_data.get("room_type", "consultation")
        type_option = _room_type_option(request.hospital_db, room_type)
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

        floor_obj = s.validated_data.get("floor_obj")
        room = Room(branch=branch, floor_obj=floor_obj,
                    department=s.validated_data.get("department"),
                    name=s.validated_data["name"], room_type=room_type, capacity=capacity)
        room.save(using=request.hospital_db)
        return created(data=RoomSerializer(room).data, message="Room created.")


class RoomDetailView(APIView):
    """PATCH  /api/v1/org/rooms/{id}/ — rename / move floor / change type / capacity / department"""
    permission_classes = [IsAuthenticated, IsHospitalAdmin]

    def _get(self, request, pk):
        try:
            return Room.objects.using(request.hospital_db).get(pk=pk)
        except Room.DoesNotExist:
            return None

    def patch(self, request, pk):
        room = self._get(request, pk)
        if not room:
            return not_found("Room not found.")
        s = RoomSerializer(room, data=request.data, partial=True)
        if not s.is_valid():
            return error("Validation error.", errors=s.errors)
        effective_room_type = s.validated_data.get("room_type", room.room_type)
        if "room_type" in s.validated_data:
            if not _room_type_option(request.hospital_db, s.validated_data["room_type"]):
                return error("Not a configured room type for this hospital.", errors={"room_type": "Invalid choice."})
        if "capacity" in s.validated_data:
            new_capacity = s.validated_data["capacity"]
            type_option = _room_type_option(request.hospital_db, effective_room_type)
            if type_option and type_option.is_bed_based:
                if new_capacity is None or new_capacity < 1:
                    return error("Bed capacity is required for this room type.",
                                 errors={"capacity": "Enter the number of beds this room can hold."})
                current_beds = room.beds.filter(is_active=True).count()
                if new_capacity < current_beds:
                    return error(
                        f"Capacity can't be set below {current_beds} — this room already has {current_beds} bed{'s' if current_beds != 1 else ''}. Remove a bed first.",
                        errors={"capacity": "Below current bed count."},
                    )
            else:
                s.validated_data["capacity"] = None
        for attr, val in s.validated_data.items():
            setattr(room, attr, val)
        room.save(using=request.hospital_db)
        return success(data=RoomSerializer(room).data, message="Room updated.")

    def delete(self, request, pk):
        room = self._get(request, pk)
        if not room:
            return not_found("Room not found.")
        room.is_active = False
        room.save(using=request.hospital_db, update_fields=["is_active"])
        # Assignments for a deactivated room are pointless to keep active —
        RoomAssignment.objects.using(request.hospital_db).filter(room=room, is_active=True).update(is_active=False)
        return success(message="Room deactivated.")


# ── Beds ────────────────────────────────────────────────────────────────

class BedListCreateView(APIView):
    """GET  /api/v1/org/beds/?room_id=&branch_id=&status=  — list beds"""
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsHospitalStaff()]
        return [IsAuthenticated(), IsHospitalAdmin()]

    def get(self, request):
        qs = Bed.objects.using(request.hospital_db).filter(is_active=True).select_related("room", "room__branch")
        room_id = request.query_params.get("room_id")
        if room_id:
            qs = qs.filter(room_id=room_id)
        branch_id = request.query_params.get("branch_id")
        if branch_id:
            qs = qs.filter(room__branch_id=branch_id)
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
            .filter(branch_id=branch_id, is_active=True, room_type__in=bed_based_types)
            .select_related("floor_obj", "department")
            .prefetch_related("beds")
            .order_by("floor_obj__level", "name")
        )

        floors = {}
        for room in rooms:
            floor_key = room.floor_obj_id or 0
            floor_bucket = floors.setdefault(floor_key, {
                "floor_id": room.floor_obj_id,
                "floor_name": room.floor_obj.name if room.floor_obj else "Unassigned",
                "rooms": [],
            })
            beds = [b for b in room.beds.all() if b.is_active]
            floor_bucket["rooms"].append({
                "room_id": room.id,
                "room_name": room.name,
                "room_type": room.room_type,
                "department_name": room.department.name if room.department else None,
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

        departments = Department.objects.using(db).filter(is_active=True)
        if branch_id:
            departments = departments.filter(branch_id=branch_id)

        results = []
        for dept in departments:
            doctors = StaffUser.objects.using(db).filter(
                department=dept, role="doctor", is_active=True,
            )
            doctors_free_today = 0
            best_slot = None

            for doc in doctors:
                schedule = (
                    DoctorSchedule.objects.using(db)
                    .filter(doctor=doc)
                    .prefetch_related("days")
                    .first()
                )
                if not schedule:
                    continue
                slots_by_day = {d.day_of_week: d for d in schedule.days.all()}

                found = None
                for offset in range(8):  # today + next 7 days
                    check_date = target_date + _timedelta(days=offset)
                    day_row = slots_by_day.get(check_date.weekday())
                    if not day_row or not day_row.is_available:
                        continue
                    start_time = day_row.start_time
                    if offset == 0 and now_time and now_time > day_row.end_time:
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
                "department_name": dept.name,
                "doctors_free_today": doctors_free_today,
                "is_available_today": best_slot is not None and best_slot[0] == target_date,
                "next_available_date": best_slot[0].isoformat() if best_slot else None,
                "next_available_time": best_slot[1].strftime("%H:%M") if best_slot else None,
            })

        return success(data=results)
