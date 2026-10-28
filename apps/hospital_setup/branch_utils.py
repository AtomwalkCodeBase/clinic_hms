"""Where staff work: a staff member has one department and one or more branches (StaffBranchAssignment, one marked primary); a place is that department at one of those branches."""

from apps.hospital_setup.models import Branch, BranchDepartment, Department, Floor, StaffBranchAssignment, StaffUser

DEFAULT_DEPARTMENT = "General"
DEFAULT_FLOOR = "Ground"


def default_place(db_name, branch_id):
    """The department a branch uses when none is named: "General" if the branch offers it, else the first it offers. None if it offers none."""
    places = BranchDepartment.objects.using(db_name).filter(branch_id=branch_id, is_active=True).select_related("department", "branch").order_by("pk")
    return places.filter(department__name=DEFAULT_DEPARTMENT).first() or places.first()


def ensure_default_place(db_name, branch):
    """Make sure the branch offers at least one department, adding "General" when it has none; returns the default one."""
    place = default_place(db_name, branch.pk)
    if place is None:
        department = Department.objects.using(db_name).filter(name=DEFAULT_DEPARTMENT).order_by("pk").first() or Department.objects.using(db_name).create(name=DEFAULT_DEPARTMENT)
        floor = Floor.objects.using(db_name).filter(branch=branch).order_by("level", "pk").first()             or Floor.objects.using(db_name).create(branch=branch, name=DEFAULT_FLOOR)
        place, _ = BranchDepartment.objects.using(db_name).get_or_create(
            branch=branch, department=department, defaults={"is_active": True, "floor": floor})
        if not place.is_active:
            BranchDepartment.objects.using(db_name).filter(pk=place.pk).update(is_active=True)
    return place


def place_for(db_name, branch_id, department_id=None):
    """The branch_department of a department at a branch (None when the branch does not offer it); with no department, the branch's default."""
    if department_id:
        return (BranchDepartment.objects.using(db_name).select_related("department", "branch")
                .filter(branch_id=branch_id, department_id=department_id, is_active=True).first())
    return default_place(db_name, branch_id)


PLACE_PREFETCH = ("u_branch_assignments__branch",)


def _assignments(staff, db_name):
    prefetched = getattr(staff, "_prefetched_objects_cache", {}).get("u_branch_assignments")
    if prefetched is not None:
        return list(prefetched)
    return list(StaffBranchAssignment.objects.using(db_name).filter(staff_id=staff.pk).select_related("branch"))


def forget_places(staff):
    staff.__dict__.pop("_primary_place", None)
    getattr(staff, "_prefetched_objects_cache", {}).pop("u_branch_assignments", None)


def _place_at(db_name, staff, branch_id):
    return place_for(db_name, branch_id, staff.department_id) or default_place(db_name, branch_id)


def primary_branch_id(staff, db_name=None):
    db = db_name or staff._state.db or "default"
    return next((a.branch_id for a in _assignments(staff, db) if a.is_primary), None)


def primary_department_id(staff, db_name=None):
    return staff.department_id


def primary_place(staff, db_name=None):
    if "_primary_place" not in staff.__dict__:
        db = db_name or staff._state.db or "default"
        branch_id = primary_branch_id(staff, db)
        staff.__dict__["_primary_place"] = _place_at(db, staff, branch_id) if branch_id else None
    return staff.__dict__["_primary_place"]


def get_staff_places(staff, db_name):
    rows = sorted(_assignments(staff, db_name), key=lambda a: (not a.is_primary, a.branch.name))
    return [place for place in (_place_at(db_name, staff, a.branch_id) for a in rows) if place is not None]


def get_staff_branch_ids(staff_id, db_name):
    return set(StaffBranchAssignment.objects.using(db_name).filter(staff_id=staff_id).values_list("branch_id", flat=True))


def get_staff_ids_in_branch(branch_id, db_name):
    return set(StaffBranchAssignment.objects.using(db_name).filter(branch_id=int(branch_id)).values_list("staff_id", flat=True))


def is_staff_in_branch(staff, branch_id, db_name):
    if branch_id is None:
        return False
    return StaffBranchAssignment.objects.using(db_name).filter(staff_id=staff.pk, branch_id=int(branch_id)).exists()


def staff_place_at(staff, branch_id, db_name):
    return _place_at(db_name, staff, int(branch_id))


def set_primary_place(staff, place, db_name):
    mine = StaffBranchAssignment.objects.using(db_name).filter(staff_id=staff.pk)
    if place is None:
        mine.filter(is_primary=True).update(is_primary=False)
    else:
        mine.filter(is_primary=True).exclude(branch_id=place.branch_id).update(is_primary=False)
        row, _ = StaffBranchAssignment.objects.using(db_name).get_or_create(staff_id=staff.pk, branch_id=place.branch_id)
        if not row.is_primary:
            row.is_primary = True
            row.save(using=db_name, update_fields=["is_primary"])
        if staff.department_id != place.department_id:
            staff.department_id = place.department_id
            staff.save(using=db_name, update_fields=["department", "updated_at"])
    forget_places(staff)


def set_staff_branches(staff, branch_ids, primary_branch_id, db_name):
    branch_ids = list(dict.fromkeys(int(b) for b in branch_ids))
    if primary_branch_id is not None:
        primary_branch_id = int(primary_branch_id)
        if primary_branch_id not in branch_ids:
            branch_ids.insert(0, primary_branch_id)
    elif branch_ids:
        primary_branch_id = branch_ids[0]
    StaffBranchAssignment.objects.using(db_name).filter(staff_id=staff.pk).delete()
    StaffBranchAssignment.objects.using(db_name).bulk_create(
        [StaffBranchAssignment(staff_id=staff.pk, branch_id=b, is_primary=b == primary_branch_id) for b in branch_ids])
    forget_places(staff)
