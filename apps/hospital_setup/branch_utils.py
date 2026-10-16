"""apps/org/branch_utils.py"""

from apps.hospital_setup.models import StaffBranchMapping


def get_staff_branch_ids(staff_id, db_name):
    """All branch IDs a staff member is mapped to, in this hospital DB."""
    return set(
        StaffBranchMapping.objects.using(db_name)
        .filter(staff_id=staff_id)
        .values_list("branch_id", flat=True)
    )


def get_staff_ids_in_branch(branch_id, db_name):
    """Reverse of get_staff_branch_ids() — every staff id assigned to"""
    from apps.hospital_setup.models import StaffUser
    branch_id = int(branch_id)
    mapped = set(
        StaffBranchMapping.objects.using(db_name)
        .filter(branch_id=branch_id)
        .values_list("staff_id", flat=True)
    )
    legacy = set(
        StaffUser.objects.using(db_name)
        .filter(branch_id=branch_id)
        .values_list("id", flat=True)
    )
    return mapped | legacy


def is_staff_in_branch(staff, branch_id, db_name):
    """True if `staff` (a StaffUser instance) is assigned to `branch_id` —"""
    if branch_id is None:
        return False
    branch_id = int(branch_id)
    if staff.branch_id == branch_id:
        return True
    return StaffBranchMapping.objects.using(db_name).filter(
        staff_id=staff.id, branch_id=branch_id
    ).exists()


def set_staff_branches(staff, branch_ids, primary_branch_id, db_name):
    """Replace a staff member's full branch assignment with `branch_ids`,"""
    branch_ids = list(dict.fromkeys(int(b) for b in branch_ids))  # dedupe, keep order
    if primary_branch_id is not None:
        primary_branch_id = int(primary_branch_id)
        if primary_branch_id not in branch_ids:
            branch_ids.insert(0, primary_branch_id)
    elif branch_ids:
        primary_branch_id = branch_ids[0]

    StaffBranchMapping.objects.using(db_name).filter(staff_id=staff.id).delete()
    StaffBranchMapping.objects.using(db_name).bulk_create([
        StaffBranchMapping(staff_id=staff.id, branch_id=b, is_primary=(b == primary_branch_id))
        for b in branch_ids
    ])
    staff.branch_id = primary_branch_id


def sync_primary_branch(staff, db_name):
    """Call after `staff.branch` (the legacy single FK) is set/changed"""
    StaffBranchMapping.objects.using(db_name).filter(staff_id=staff.id).update(is_primary=False)
    if staff.branch_id is not None:
        StaffBranchMapping.objects.using(db_name).update_or_create(
            staff_id=staff.id, branch_id=staff.branch_id,
            defaults={"is_primary": True},
        )
