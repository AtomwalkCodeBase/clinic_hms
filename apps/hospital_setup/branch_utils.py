"""Where staff work: every place is a StaffBranchDepartment row (a department at a branch); the one marked is_primary is where they normally sit."""

from apps.hospital_setup.models import BranchDepartment, Department, Floor, StaffBranchDepartment, StaffUser

DEFAULT_DEPARTMENT = "General"
DEFAULT_FLOOR = "Ground"


def default_place(db_name, branch_id):
    """The department a branch uses when none is named: "General" if the branch offers it, else the first it offers. None if it offers none."""
    places = BranchDepartment.objects.using(db_name).filter(branch_id=branch_id, is_active=True).select_related("department", "branch").order_by("id")
    return places.filter(department__name=DEFAULT_DEPARTMENT).first() or places.first()


def ensure_default_place(db_name, branch):
    """Make sure the branch offers at least one department, adding "General" when it has none; returns the default one."""
    place = default_place(db_name, branch.id)
    if place is None:
        department, _ = Department.objects.using(db_name).get_or_create(name=DEFAULT_DEPARTMENT)
        floor = Floor.objects.using(db_name).filter(branch=branch).order_by("level", "id").first()             or Floor.objects.using(db_name).create(branch=branch, name=DEFAULT_FLOOR)
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


PLACE_PREFETCH = ("u_branch_departments__branch_department__branch", "u_branch_departments__branch_department__department")


def _links(staff, db_name):
    """The staff member's StaffBranchDepartment rows with their places loaded (from a prefetch when the caller made one)."""
    prefetched = getattr(staff, "_prefetched_objects_cache", {}).get("u_branch_departments")
    if prefetched is not None:
        return list(prefetched)
    return list(StaffBranchDepartment.objects.using(db_name).filter(staff_id=staff.id)
                .select_related("branch_department__branch", "branch_department__department"))


def forget_places(staff):
    """Drop what was loaded about a staff member's places, after they changed."""
    staff.__dict__.pop("_primary_place", None)
    getattr(staff, "_prefetched_objects_cache", {}).pop("u_branch_departments", None)


def primary_place(staff, db_name=None):
    """The branch_department a staff member normally works at (their primary StaffBranchDepartment), or None for a hospital-wide user."""
    if "_primary_place" not in staff.__dict__:
        db = db_name or staff._state.db or "default"
        staff.__dict__["_primary_place"] = next((link.branch_department for link in _links(staff, db) if link.is_primary), None)
    return staff.__dict__["_primary_place"]


def primary_branch_id(staff, db_name=None):
    place = primary_place(staff, db_name)
    return place.branch_id if place else None


def primary_department_id(staff, db_name=None):
    place = primary_place(staff, db_name)
    return place.department_id if place else None


def get_staff_places(staff, db_name):
    """Every branch_department a staff member works at: the primary first, then the others by branch name."""
    links = sorted(_links(staff, db_name), key=lambda link: (not link.is_primary, link.branch_department.branch.name))
    return [link.branch_department for link in links]


def get_staff_branch_ids(staff_id, db_name):
    """All branch IDs a staff member works at, in this hospital DB."""
    return set(StaffBranchDepartment.objects.using(db_name).filter(staff_id=staff_id).values_list("branch_department__branch_id", flat=True))


def get_staff_ids_in_branch(branch_id, db_name):
    """Reverse of get_staff_branch_ids() — every staff id with a place at the branch."""
    return set(StaffBranchDepartment.objects.using(db_name).filter(branch_department__branch_id=int(branch_id)).values_list("staff_id", flat=True))


def is_staff_in_branch(staff, branch_id, db_name):
    """True if `staff` (a StaffUser instance) works at `branch_id`."""
    if branch_id is None:
        return False
    return StaffBranchDepartment.objects.using(db_name).filter(staff_id=staff.id, branch_department__branch_id=int(branch_id)).exists()


def staff_place_at(staff, branch_id, db_name):
    """The branch_department a staff member sits in at a branch: their primary if it is at that branch, else another of theirs there, else the
    branch's default. None when the branch offers no department."""
    branch_id = int(branch_id)
    links = [link for link in _links(staff, db_name) if link.branch_department.branch_id == branch_id]
    links.sort(key=lambda link: not link.is_primary)
    return links[0].branch_department if links else default_place(db_name, branch_id)


def set_primary_place(staff, place, db_name):
    """Make `place` the staff member's primary place (None: no primary place); their other places stay."""
    mine = StaffBranchDepartment.objects.using(db_name).filter(staff_id=staff.id, is_primary=True)
    mine.exclude(branch_department_id=place.id if place else None).update(is_primary=False)
    if place is not None:
        link, _ = StaffBranchDepartment.objects.using(db_name).get_or_create(staff_id=staff.id, branch_department_id=place.id)
        if not link.is_primary:
            link.is_primary = True
            link.save(using=db_name, update_fields=["is_primary"])
    forget_places(staff)


def set_staff_branches(staff, branch_ids, primary_branch_id, db_name):
    """Replace a staff member's places: `primary_branch_id` (or the first of `branch_ids`) becomes their primary place, keeping their
    department there when the branch offers it; every other branch becomes another place, in the same department when offered."""
    branch_ids = list(dict.fromkeys(int(b) for b in branch_ids))  # dedupe, keep order
    if primary_branch_id is not None:
        primary_branch_id = int(primary_branch_id)
        if primary_branch_id not in branch_ids:
            branch_ids.insert(0, primary_branch_id)
    elif branch_ids:
        primary_branch_id = branch_ids[0]

    department_id = primary_department_id(staff, db_name)
    links = []
    for branch_id in branch_ids:
        place = place_for(db_name, branch_id, department_id) or default_place(db_name, branch_id)
        if place is not None:
            links.append(StaffBranchDepartment(staff_id=staff.id, branch_department_id=place.id, is_primary=branch_id == primary_branch_id))
    StaffBranchDepartment.objects.using(db_name).filter(staff_id=staff.id).delete()
    StaffBranchDepartment.objects.using(db_name).bulk_create(links)
    forget_places(staff)
