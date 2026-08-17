"""
apps/org/room_utils.py
------------------------
Shared helpers for Room / RoomAssignment — overlap detection (same room,
same day, clashing time window) and resolving which room a doctor is
sitting in for a given appointment slot.
"""

from .models import RoomAssignment


def find_overlapping_assignment(db_name, room_id, day_of_week, start_time, end_time, exclude_pk=None):
    """
    Returns the first active RoomAssignment for this room+day whose time
    window overlaps [start_time, end_time), or None if the slot is free.

    Overlap test: two ranges [a_start, a_end) and [b_start, b_end) overlap
    iff a_start < b_end AND a_end > b_start — this catches partial overlaps
    (e.g. an existing 9:00-13:00 slot blocks a new 12:30-14:00 request),
    not just exact duplicates.
    """
    qs = RoomAssignment.objects.using(db_name).filter(
        room_id=room_id, day_of_week=day_of_week, is_active=True,
        start_time__lt=end_time, end_time__gt=start_time,
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.select_related("doctor").first()


def resolve_room_for_slot(db_name, doctor_user_id, day_of_week, slot_time):
    """
    Which room (if any) a doctor is assigned to for a given day-of-week +
    time — used to auto-fill an appointment's room/floor at booking time.
    Returns the matching RoomAssignment (with .room preloaded) or None if
    the doctor has no room assignment covering that slot (rooms are opt-in;
    a hospital that hasn't set up room assignments yet just gets no room on
    the appointment, not an error).
    """
    if slot_time is None:
        return None
    return (
        RoomAssignment.objects.using(db_name)
        .filter(
            doctor_id=doctor_user_id, day_of_week=day_of_week, is_active=True,
            start_time__lte=slot_time, end_time__gt=slot_time,
        )
        .select_related("room")
        .first()
    )
