"""Phase 2 of 3: fill the new structure from the old one.

- departments with the same name at different branches become one department, offered at each of those branches
- every branch ends up with at least one department ("General" when it had none)
- a room without a floor goes on a "Ground" floor of its branch
- a staff member's role / custom role becomes one user group; branch + department become one branch_department
- the extra branches of a staff member become extra branch_departments
- the doctor profile and the staff profile become one user profile
"""
from django.db import migrations

DEFAULT_DEPARTMENT = "General"
DEFAULT_FLOOR = "Ground"
ROLE_LABELS = {
    "hospital_admin": "Hospital Admin", "doctor": "Doctor", "nurse": "Nurse",
    "front_desk": "Front Desk", "lab_tech": "Lab Technician", "pharmacist": "Pharmacist",
}
PROFILE_FIELDS = ["registration_no", "qualification", "experience_years", "gender", "bio", "languages"]
DOCTOR_FIELDS = ["specialisation", "consultation_fee", "followup_fee", "digital_signature", "known_for"]
COUNCIL_FIELDS = ["council_name", "registration_expiry", "extra"]


def forward(apps, schema_editor):
    db = schema_editor.connection.alias
    Branch = apps.get_model("hospital_setup", "Branch")
    Department = apps.get_model("hospital_setup", "Department")
    BranchDepartment = apps.get_model("hospital_setup", "BranchDepartment")
    Floor = apps.get_model("hospital_setup", "Floor")
    Room = apps.get_model("hospital_setup", "Room")
    Role = apps.get_model("hospital_setup", "Role")
    StaffUser = apps.get_model("hospital_setup", "StaffUser")
    StaffBranchMapping = apps.get_model("hospital_setup", "StaffBranchMapping")
    StaffBranchDepartment = apps.get_model("hospital_setup", "StaffBranchDepartment")
    DoctorProfile = apps.get_model("hospital_setup", "DoctorProfile")
    StaffProfile = apps.get_model("hospital_setup", "StaffProfile")
    UserProfile = apps.get_model("hospital_setup", "UserProfile")
    Admission = apps.get_model("ipd", "Admission")
    AdmissionReferral = apps.get_model("ipd", "AdmissionReferral")

    # ── departments: one row per name, offered at each branch that had it ──
    keeper_of_name, dept_map = {}, {}
    for dept in Department.objects.using(db).order_by("id"):
        keeper = keeper_of_name.setdefault(dept.name, dept)
        dept_map[dept.id] = keeper.id
        BranchDepartment.objects.using(db).get_or_create(
            branch_id=dept.branch_id, department_id=keeper.id, defaults={"is_active": dept.is_active})
    for old_id, keeper_id in dept_map.items():
        if old_id != keeper_id:
            Admission.objects.using(db).filter(department_id=old_id).update(department_id=keeper_id)
            AdmissionReferral.objects.using(db).filter(department_id=old_id).update(department_id=keeper_id)
    # rooms and staff still point at the old row until they are moved below; remember which keeper they will use
    for old_id, keeper_id in dept_map.items():
        if old_id != keeper_id:
            Room.objects.using(db).filter(department_id=old_id).update(department_id=keeper_id)
            StaffUser.objects.using(db).filter(department_id=old_id).update(department_id=keeper_id)
    Department.objects.using(db).exclude(id__in=set(dept_map.values())).delete()

    general = Department.objects.using(db).filter(name=DEFAULT_DEPARTMENT).first()
    for branch in Branch.objects.using(db).all():
        if not BranchDepartment.objects.using(db).filter(branch_id=branch.id).exists():
            if general is None:
                general = Department.objects.using(db).create(name=DEFAULT_DEPARTMENT, branch_id=branch.id)
            BranchDepartment.objects.using(db).create(branch_id=branch.id, department_id=general.id)

    def default_place(branch_id):
        """The department a branch uses when none is named: "General" if it offers it, else its first."""
        places = BranchDepartment.objects.using(db).filter(branch_id=branch_id).order_by("id")
        return places.filter(department__name=DEFAULT_DEPARTMENT).first() or places.first()

    def place_for(branch_id, department_id):
        """The branch_department of a department at a branch, or the branch's default when the branch does not offer it."""
        if department_id:
            hit = BranchDepartment.objects.using(db).filter(branch_id=branch_id, department_id=department_id).first()
            if hit:
                return hit
        return default_place(branch_id)

    # ── rooms: a floor of their own, and the department as a branch_department ──
    for room in Room.objects.using(db).all():
        changed = []
        if room.floor_obj_id is None:
            floor, _ = Floor.objects.using(db).get_or_create(branch_id=room.branch_id, name=DEFAULT_FLOOR, defaults={"level": 0})
            room.floor_obj_id = floor.id
            changed.append("floor_obj")
        if room.department_id:
            room.branch_department_id = place_for(room.branch_id, room.department_id).id
            changed.append("branch_department")
        if changed:
            room.save(using=db, update_fields=changed)

    # ── staff: user group and place of work ──
    roles = {r.system_role_key: r for r in Role.objects.using(db).filter(is_system_role=True)}
    for staff in StaffUser.objects.using(db).all():
        if staff.role == "custom" and staff.custom_role_id:
            group_id = staff.custom_role_id
        else:
            role = roles.get(staff.role)
            if role is None:
                role = Role.objects.using(db).create(
                    name=ROLE_LABELS.get(staff.role, staff.role), is_system_role=True, system_role_key=staff.role)
                roles[staff.role] = role
            group_id = role.id
        branch_id = staff.branch_id
        if branch_id is None:
            primary = StaffBranchMapping.objects.using(db).filter(staff_id=staff.id, is_primary=True).first()
            branch_id = primary.branch_id if primary else None
        staff.group_id = group_id
        staff.branch_department_id = place_for(branch_id, staff.department_id).id if branch_id else None
        staff.save(using=db, update_fields=["group", "branch_department"])
        for mapping in StaffBranchMapping.objects.using(db).filter(staff_id=staff.id):
            if mapping.branch_id == branch_id:
                continue
            StaffBranchDepartment.objects.using(db).get_or_create(
                staff_id=staff.id, branch_department_id=place_for(mapping.branch_id, staff.department_id).id)

    # ── profiles: one row per staff member ──
    for doctor_profile in DoctorProfile.objects.using(db).all():
        values = {f: getattr(doctor_profile, f) for f in PROFILE_FIELDS + DOCTOR_FIELDS}
        other = StaffProfile.objects.using(db).filter(staff_id=doctor_profile.staff_id).first()
        if other is not None:
            for f in PROFILE_FIELDS:
                if not values[f] and getattr(other, f):
                    values[f] = getattr(other, f)
            values.update({f: getattr(other, f) for f in COUNCIL_FIELDS})
        UserProfile.objects.using(db).create(staff_id=doctor_profile.staff_id, **values)
    done = set(UserProfile.objects.using(db).values_list("staff_id", flat=True))
    for staff_profile in StaffProfile.objects.using(db).exclude(staff_id__in=done):
        values = {f: getattr(staff_profile, f) for f in PROFILE_FIELDS + COUNCIL_FIELDS}
        UserProfile.objects.using(db).create(staff_id=staff_profile.staff_id, **values)


class Migration(migrations.Migration):

    dependencies = [
        ("hospital_setup", "0007_structure_add"),
        ("ipd", "0004_prefixed_related_names"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
