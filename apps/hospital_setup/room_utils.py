"""apps/org/room_utils.py"""

from apps.hospital_setup.models import RoomAssignment


def find_overlapping_assignment(db_name, room_id, day_of_week, start_time, end_time, exclude_pk=None):
    """Returns the first active RoomAssignment for this room+day whose time"""
    qs = RoomAssignment.objects.using(db_name).filter(
        room_id=room_id, day_of_week=day_of_week, is_active=True,
        start_time__lt=end_time, end_time__gt=start_time,
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.select_related("doctor").first()


def resolve_room_for_slot(db_name, doctor_user_id, day_of_week, slot_time):
    """Which room (if any) a doctor is assigned to for a given day-of-week +"""
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


def get_doctor_home_room(db_name, doctor_user_id):
    """A doctor's "home" room, ignoring day/time entirely — just any active"""
    return (
        RoomAssignment.objects.using(db_name)
        .filter(doctor_id=doctor_user_id, is_active=True)
        .select_related("room")
        .first()
    )
