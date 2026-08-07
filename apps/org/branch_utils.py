"""
apps/org/branch_utils.py
--------------------------
Shared helpers for StaffBranchMapping — keeps StaffUser.branch (the legacy
single FK, still what JWT payloads carry as branch_id and what most reads
fall back to) in sync with the mapping table's primary row, so nothing
that only knows about the old single-branch field ever goes stale.
"""

from .models import StaffBranchMapping


def get_staff_branch_ids(staff_id, db_name):
    """All branch IDs a staff member is mapped to, in this tenant DB."""
    return set(
        StaffBranchMapping.objects.using(db_name)
        .filter(staff_id=staff_id)
        .values_list("branch_id", flat=True)
    )


def is_staff_in_branch(staff, branch_id, db_name):
    """
    True if `staff` (a StaffUser instance) is assigned to `branch_id` —
    either via the mapping table, or (for staff who predate/haven't been
    given extra mappings) via the legacy single `branch` FK. A staff
    member with zero mapping rows and no legacy branch is assigned to
    nothing and this returns False for every branch_id, including None.
    """
    if branch_id is None:
        return False
    branch_id = int(branch_id)
    if staff.branch_id == branch_id:
        return True
    return StaffBranchMapping.objects.using(db_name).filter(
        staff_id=staff.id, branch_id=branch_id
    ).exists()


def set_staff_branches(staff, branch_ids, primary_branch_id, db_name):
    """
    Replace a staff member's full branch assignment with `branch_ids`,
    marking `primary_branch_id` (must be one of them, or the first one if
    not given) as primary. Also updates `staff.branch` (legacy FK) to the
    primary, saved by the caller — this function only touches the mapping
    table and sets `staff.branch_id` in memory.

    An empty `branch_ids` list clears all assignments (staff.branch
    becomes None) — a valid state for a newly-invited staff member with
    no branch yet, or someone being unassigned pending reassignment.
    """
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
    """
    Call after `staff.branch` (the legacy single FK) is set/changed
    directly (e.g. StaffDetailView.patch's plain branch_id field) without
    going through set_staff_branches — keeps the mapping table's primary
    row matching, demoting any previous primary and adding/promoting a
    mapping row for the new one. No-op if staff.branch_id is None (mapping
    rows for OTHER branches, if any, are left alone — clearing the
    primary via this path doesn't imply un-assigning the extra branches).
    """
    StaffBranchMapping.objects.using(db_name).filter(staff_id=staff.id).update(is_primary=False)
    if staff.branch_id is not None:
        StaffBranchMapping.objects.using(db_name).update_or_create(
            staff_id=staff.id, branch_id=staff.branch_id,
            defaults={"is_primary": True},
        )
