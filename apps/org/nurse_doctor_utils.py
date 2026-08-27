"""
apps/org/nurse_doctor_utils.py
-------------------------------
Shared helpers for NurseDoctorAssignment — which doctor(s) a nurse is
rostered to. Mirrors apps/org/branch_utils.py's shape exactly (same
replace-the-whole-set pattern), just without a "primary" concept since a
nurse covering three doctors doesn't have one that's more "primary" than
the others.
"""

from .models import NurseDoctorAssignment


def get_nurse_doctor_ids(nurse_id, db_name):
    """All doctor IDs a nurse is assigned to, in this tenant DB."""
    return set(
        NurseDoctorAssignment.objects.using(db_name)
        .filter(nurse_id=nurse_id)
        .values_list("doctor_id", flat=True)
    )


def set_nurse_doctors(nurse, doctor_ids, db_name):
    """
    Replace a nurse's full doctor assignment with `doctor_ids`. An empty
    list clears all assignments — a valid state for a newly-invited nurse,
    or one being unassigned pending reassignment (their queue/vitals/
    upcoming-schedule views show nothing until re-assigned, same as a
    doctor with no appointments booked).
    """
    doctor_ids = list(dict.fromkeys(int(d) for d in doctor_ids))  # dedupe, keep order
    NurseDoctorAssignment.objects.using(db_name).filter(nurse_id=nurse.id).delete()
    NurseDoctorAssignment.objects.using(db_name).bulk_create([
        NurseDoctorAssignment(nurse_id=nurse.id, doctor_id=d) for d in doctor_ids
    ])
