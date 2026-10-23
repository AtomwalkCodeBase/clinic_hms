"""Phase 2 of 3: the doctor's id was kept as a UUID built from the staff id; turn it into a real link, and give every visit its branch_department."""
import uuid

from django.db import migrations


def forward(apps, schema_editor):
    db = schema_editor.connection.alias
    Appointment = apps.get_model("opd", "Appointment")
    OPDEncounter = apps.get_model("opd", "OPDEncounter")
    Prescription = apps.get_model("opd", "Prescription")
    PrescriptionFavourite = apps.get_model("opd", "PrescriptionFavourite")
    Branch = apps.get_model("hospital_setup", "Branch")
    Department = apps.get_model("hospital_setup", "Department")
    BranchDepartment = apps.get_model("hospital_setup", "BranchDepartment")
    StaffUser = apps.get_model("hospital_setup", "StaffUser")
    StaffBranchDepartment = apps.get_model("hospital_setup", "StaffBranchDepartment")
    Role = apps.get_model("hospital_setup", "Role")

    known = set(StaffUser.objects.using(db).values_list("id", flat=True))
    used = set()
    for model in (Appointment, OPDEncounter, Prescription, PrescriptionFavourite):
        used.update(u.int for u in model.objects.using(db).values_list("doctor_user_id", flat=True))
    missing = sorted(used - known)
    if missing:
        # a doctor whose staff row is gone: keep the history readable under a closed account with the same id
        doctor_role = Role.objects.using(db).filter(is_system_role=True, system_role_key="doctor").first()
        if doctor_role is None:
            doctor_role = Role.objects.using(db).create(name="Doctor", is_system_role=True, system_role_key="doctor")
        for staff_id in missing:
            StaffUser.objects.using(db).create(
                id=staff_id, first_name="Former", last_name=f"staff #{staff_id}", phone=f"gone{staff_id}"[:15],
                group_id=doctor_role.id, is_active=False)
    staff_by_id = {s.id: s for s in StaffUser.objects.using(db).all()}

    for model in (OPDEncounter, Prescription, PrescriptionFavourite):
        for row in model.objects.using(db).all():
            row.doctor_id = row.doctor_user_id.int
            row.save(using=db, update_fields=["doctor"])

    def any_place():
        place = BranchDepartment.objects.using(db).order_by("id").first()
        if place is None:                                # a hospital with visits but no branch set up at all
            branch = Branch.objects.using(db).order_by("id").first() or Branch.objects.using(db).create(name="Main")
            department = Department.objects.using(db).filter(name="General").first() or Department.objects.using(db).create(name="General")
            place = BranchDepartment.objects.using(db).create(branch_id=branch.id, department_id=department.id)
        return place

    for appt in Appointment.objects.using(db).all():
        doctor = staff_by_id[appt.doctor_user_id.int]
        place = None
        if appt.branch_id:
            if doctor.branch_department_id and BranchDepartment.objects.using(db).filter(pk=doctor.branch_department_id, branch_id=appt.branch_id).exists():
                place = doctor.branch_department_id
            else:
                link = StaffBranchDepartment.objects.using(db).filter(
                    staff_id=doctor.id, branch_department__branch_id=appt.branch_id).first()
                if link:
                    place = link.branch_department_id
                else:
                    places = BranchDepartment.objects.using(db).filter(branch_id=appt.branch_id).order_by("id")
                    chosen = places.filter(department__name="General").first() or places.first()
                    place = chosen.id if chosen else None
        if place is None:
            place = doctor.branch_department_id or any_place().id
        appt.doctor_id = doctor.id
        appt.branch_department_id = place
        appt.save(using=db, update_fields=["doctor", "branch_department"])


class Migration(migrations.Migration):

    dependencies = [
        ("opd", "0006_doctor_add"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
