"""The weekly hours of a doctor at a place and the rooms they sit in. All of it is StaffBranchAssignment.weekly_hours (see the model): a window without
a room_id is a working-hours window, a window with a room_id is a room block carrying its own id."""

import uuid
from datetime import time

from apps.hospital_setup.models import Room, StaffBranchAssignment


def as_time(text):
    """"09:00" or "09:00:00" as a time."""
    parts = [int(p) for p in str(text).split(":")]
    return time(*parts[:3])


def as_text(value):
    return value.strftime("%H:%M")


def schedule_of(staff_id, db_name, branch_id=None):
    """The schedule of a doctor at one of their places, which is the assignment itself: the one at `branch_id`, else the primary one. None
    when the doctor has no such place (a schedule belongs to a place)."""
    links = StaffBranchAssignment.objects.using(db_name).filter(staff_id=staff_id)
    if branch_id:
        links = links.filter(branch_id=branch_id)
    return links.order_by("-is_primary", "pk").first()


# ── working hours ──

def hours_of(schedule):
    """The working-hours windows, one per day: [{day_of_week, is_available, start_time, end_time}] in day order."""
    rows = [{"day_of_week": w["day_of_week"], "is_available": w.get("is_active", True), "start_time": as_time(w["start_time"]), "end_time": as_time(w["end_time"])}
            for w in schedule.weekly_hours if not w.get("room_id")]
    return sorted(rows, key=lambda row: row["day_of_week"])


def set_hours(schedule, slot_duration_minutes, days, db_name):
    """Replace the working hours (and slot length); the room blocks stay."""
    blocks = [w for w in schedule.weekly_hours if w.get("room_id")]
    hours = [{"day_of_week": d["day_of_week"], "start_time": as_text(d["start_time"]), "end_time": as_text(d["end_time"]), "is_active": d["is_available"]}
             for d in days]
    schedule.slot_duration_minutes = slot_duration_minutes
    schedule.weekly_hours = hours + blocks
    schedule.save(using=db_name)


def schedule_json(schedule):
    return {
        "staff_branch_assignment_id": schedule.pk, "slot_duration_minutes": schedule.slot_duration_minutes,
        "days": [{"schedule_block_id": f"{schedule.pk}-{row['day_of_week']}", "day_of_week": row["day_of_week"],
                  "day_label": dict(StaffBranchAssignment.DAY_CHOICES)[row["day_of_week"]], "is_available": row["is_available"],
                  "start_time": row["start_time"].strftime("%H:%M:%S"), "end_time": row["end_time"].strftime("%H:%M:%S")}
                 for row in hours_of(schedule)],
    }


# ── room blocks: which doctor sits in which room, on which day and times ──

def _block(schedule, window):
    link = schedule
    return {
        "schedule_block_id": window["schedule_block_id"], "schedule": schedule, "doctor": link.staff, "doctor_id": link.staff_id, "room_id": window["room_id"],
        "day_of_week": window["day_of_week"], "start_time": as_time(window["start_time"]), "end_time": as_time(window["end_time"]),
        "is_active": window.get("is_active", True),
    }


def room_blocks(db_name, room_id=None, doctor_id=None, branch_id=None, active_only=True):
    """Every room block in this hospital, filtered; each a dict with the block's own fields plus its `doctor` and `schedule`."""
    schedules = StaffBranchAssignment.objects.using(db_name).select_related("staff")
    room_ids = None
    if branch_id:
        room_ids = set(Room.objects.using(db_name).filter(floor__branch_id=branch_id).values_list("pk", flat=True))
    found = []
    for schedule in schedules:
        if doctor_id and schedule.staff_id != int(doctor_id):
            continue
        for window in schedule.weekly_hours:
            if not window.get("room_id"):
                continue
            if active_only and not window.get("is_active", True):
                continue
            if room_id and window["room_id"] != int(room_id):
                continue
            if room_ids is not None and window["room_id"] not in room_ids:
                continue
            found.append(_block(schedule, window))
    return found


def get_block(db_name, block_id):
    for block in room_blocks(db_name, active_only=False):
        if block["schedule_block_id"] == str(block_id):
            return block
    return None


def block_json(db_name, block):
    room = Room.objects.using(db_name).select_related("floor").get(pk=block["room_id"])
    return {
        "schedule_block_id": block["schedule_block_id"], "room": room.pk, "room_name": room.name, "floor": room.floor, "doctor": block["doctor_id"],
        "doctor_name": block["doctor"].get_full_name(), "day_of_week": block["day_of_week"],
        "day_label": dict(StaffBranchAssignment.DAY_CHOICES)[block["day_of_week"]],
        "start_time": block["start_time"].strftime("%H:%M:%S"), "end_time": block["end_time"].strftime("%H:%M:%S"), "is_active": block["is_active"],
    }


def find_overlapping_assignment(db_name, room_id, day_of_week, start_time, end_time, exclude_id=None):
    """The first active block for this room and day whose time overlaps [start_time, end_time), or None."""
    for block in room_blocks(db_name, room_id=room_id):
        if exclude_id is not None and block["schedule_block_id"] == str(exclude_id):
            continue
        if block["day_of_week"] == day_of_week and block["start_time"] < end_time and block["end_time"] > start_time:
            return block
    return None


def save_block(db_name, room, doctor, day_of_week, start_time, end_time, is_active=True, block_id=None):
    """Create a block, or (with `block_id`) move an existing one to this room, doctor and time. Returns the block, or None when the doctor has
    no place at the room's branch (a block lives in the schedule of a place)."""
    schedule = schedule_of(doctor.pk, db_name, branch_id=room.floor.branch_id)
    if schedule is None:
        return None
    if block_id is not None:
        remove_block(db_name, block_id)
        schedule.refresh_from_db(using=db_name)
    window = {"schedule_block_id": str(block_id or uuid.uuid4()), "room_id": room.pk, "day_of_week": day_of_week,
              "start_time": as_text(start_time), "end_time": as_text(end_time), "is_active": is_active}
    schedule.weekly_hours = [*schedule.weekly_hours, window]
    schedule.save(using=db_name)
    return get_block(db_name, window["schedule_block_id"])


def remove_block(db_name, block_id):
    block = get_block(db_name, block_id)
    if block is None:
        return
    schedule = block["schedule"]
    schedule.weekly_hours = [w for w in schedule.weekly_hours if w.get("schedule_block_id") != str(block_id)]
    schedule.save(using=db_name)


def deactivate_room_blocks(db_name, room_id):
    """Switch off every block of a room (used when the room is deactivated)."""
    for schedule in StaffBranchAssignment.objects.using(db_name):
        if any(w.get("room_id") == room_id for w in schedule.weekly_hours):
            schedule.weekly_hours = [{**w, "is_active": False} if w.get("room_id") == room_id else w for w in schedule.weekly_hours]
            schedule.save(using=db_name)


def resolve_room_for_slot(db_name, doctor_user_id, day_of_week, slot_time):
    """The Room (if any) a doctor sits in on a day of the week at a time, or None. `slot_time` may be a time or "HH:MM"/"HH:MM:SS" text."""
    if slot_time is None:
        return None
    if not isinstance(slot_time, time):
        slot_time = as_time(slot_time)
    for block in room_blocks(db_name, doctor_id=doctor_user_id):
        if block["day_of_week"] == day_of_week and block["start_time"] <= slot_time < block["end_time"]:
            return Room.objects.using(db_name).select_related("floor").get(pk=block["room_id"])
    return None


def get_doctor_home_room(db_name, doctor_user_id):
    """A doctor's "home" room, ignoring day and time: any active block's room."""
    blocks = room_blocks(db_name, doctor_id=doctor_user_id)
    return Room.objects.using(db_name).select_related("floor").get(pk=blocks[0]["room_id"]) if blocks else None
