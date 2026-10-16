"""apps/org/nurse_doctor_utils.py"""

from apps.hospital_setup.models import NurseDoctorAssignment


def get_nurse_doctor_ids(nurse_id, db_name):
    """All doctor IDs a nurse is assigned to, in this hospital DB."""
    return set(
        NurseDoctorAssignment.objects.using(db_name)
        .filter(nurse_id=nurse_id)
        .values_list("doctor_id", flat=True)
    )


def set_nurse_doctors(nurse, doctor_ids, db_name):
    """Replace a nurse's full doctor assignment with `doctor_ids`. An empty"""
    doctor_ids = list(dict.fromkeys(int(d) for d in doctor_ids))  # dedupe, keep order
    NurseDoctorAssignment.objects.using(db_name).filter(nurse_id=nurse.id).delete()
    NurseDoctorAssignment.objects.using(db_name).bulk_create([
        NurseDoctorAssignment(nurse_id=nurse.id, doctor_id=d) for d in doctor_ids
    ])
