"""Phase 2 of 3: fill the new structure from the old one.

- the department a staff member was placed in becomes their primary place of work (a staff_branch_department row)
- the user profile columns are copied onto the staff row; the extra roles into the plain many-to-many
- every department gets a floor (the branch's own floor; a "Ground" floor when the branch has none)
- a doctor's availability slots and room assignments become the weekly hours of the schedule at their place of work; a schedule that
  cannot be tied to a place (the doctor has none) is dropped
"""
from django.db import migrations

DEFAULT_FLOOR = "Ground"
PROFILE_FIELDS = [
    "registration_no", "council_name", "registration_expiry", "qualification", "experience_years", "specialisation", "consultation_fee",
    "followup_fee", "digital_signature", "known_for", "gender", "bio", "languages", "extra",
]


def hhmm(value):
    return value.strftime("%H:%M")


def forward(apps, schema_editor):
    db = schema_editor.connection.alias
    StaffUser = apps.get_model("hospital_setup", "StaffUser")
    StaffBranchDepartment = apps.get_model("hospital_setup", "StaffBranchDepartment")
    UserProfile = apps.get_model("hospital_setup", "UserProfile")
    UserRole = apps.get_model("hospital_setup", "UserRole")
    BranchDepartment = apps.get_model("hospital_setup", "BranchDepartment")
    Floor = apps.get_model("hospital_setup", "Floor")
    Room = apps.get_model("hospital_setup", "Room")
    DoctorSchedule = apps.get_model("hospital_setup", "DoctorSchedule")
    DoctorAvailabilitySlot = apps.get_model("hospital_setup", "DoctorAvailabilitySlot")
    RoomAssignment = apps.get_model("hospital_setup", "RoomAssignment")

    # ── places of work: the staff member's own department is the primary one ──
    for staff in StaffUser.objects.using(db).exclude(branch_department__isnull=True):
        link, _ = StaffBranchDepartment.objects.using(db).get_or_create(staff_id=staff.id, branch_department_id=staff.branch_department_id)
        if not link.is_primary:
            link.is_primary = True
            link.save(using=db, update_fields=["is_primary"])

    # ── profiles onto the staff row, extra roles into the many-to-many ──
    for profile in UserProfile.objects.using(db).all():
        StaffUser.objects.using(db).filter(pk=profile.staff_id).update(**{f: getattr(profile, f) for f in PROFILE_FIELDS})
    for user_role in UserRole.objects.using(db).all():
        StaffUser.extra_roles.through.objects.using(db).get_or_create(staffuser_id=user_role.staff_id, role_id=user_role.role_id)

    # ── every department sits on a floor ──
    for place in BranchDepartment.objects.using(db).filter(floor__isnull=True):
        floor = Floor.objects.using(db).filter(branch_id=place.branch_id).order_by("level", "id").first()
        if floor is None:
            floor = Floor.objects.using(db).create(branch_id=place.branch_id, name=DEFAULT_FLOOR, level=0)
        place.floor_id = floor.id
        place.save(using=db, update_fields=["floor"])

    # ── schedules: one per place of work, holding the availability and the room blocks ──
    def link_at(doctor_id, branch_id=None):
        links = StaffBranchDepartment.objects.using(db).filter(staff_id=doctor_id)
        if branch_id is not None:
            links = links.filter(branch_department__branch_id=branch_id)
        return links.order_by("-is_primary", "id").first()

    def schedule_at(link, slot_minutes):
        schedule = DoctorSchedule.objects.using(db).filter(staff_branch_department_id=link.id).first()
        if schedule is None:
            schedule = DoctorSchedule.objects.using(db).create(staff_branch_department_id=link.id, slot_duration_minutes=slot_minutes, weekly_hours=[])
        return schedule

    old_schedules = list(DoctorSchedule.objects.using(db).filter(staff_branch_department__isnull=True))
    for old in old_schedules:
        link = link_at(old.doctor_id)
        if link is None:
            continue                                                    # no place of work: nothing to attach this schedule to
        windows = [{"day_of_week": slot.day_of_week, "start_time": hhmm(slot.start_time), "end_time": hhmm(slot.end_time), "is_active": slot.is_available}
                   for slot in DoctorAvailabilitySlot.objects.using(db).filter(schedule_id=old.id).order_by("day_of_week")]
        old.staff_branch_department_id = link.id
        old.weekly_hours = windows
        old.save(using=db, update_fields=["staff_branch_department", "weekly_hours"])

    import uuid
    for block in RoomAssignment.objects.using(db).select_related("room__floor_obj").all():
        link = link_at(block.doctor_id, block.room.floor_obj.branch_id) or link_at(block.doctor_id)
        if link is None:
            continue
        schedule = schedule_at(link, 15)
        schedule.weekly_hours = [*schedule.weekly_hours, {
            "id": str(uuid.uuid4()), "room_id": block.room_id, "day_of_week": block.day_of_week,
            "start_time": hhmm(block.start_time), "end_time": hhmm(block.end_time), "is_active": block.is_active}]
        schedule.save(using=db, update_fields=["weekly_hours"])

    DoctorSchedule.objects.using(db).filter(staff_branch_department__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0010_places_profiles_add"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
