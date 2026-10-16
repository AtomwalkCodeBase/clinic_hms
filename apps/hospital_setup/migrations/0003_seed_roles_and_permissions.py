"""Every hospital database starts with the permission catalog and the six system roles (and what each role grants)."""
from django.db import migrations

PERMISSIONS = [
    ('patient.view', 'View patient records'),
    ('patient.register', 'Register new patients'),
    ('encounter.create', 'Create consultation notes'),
    ('encounter.sign', 'Sign/finalise consultation notes'),
    ('prescription.create', 'Prescribe medicines'),
    ('prescription.dispense', 'Dispense prescriptions'),
    ('lab.order', 'Order lab tests'),
    ('lab.catalog.manage', 'Manage the lab test catalog'),
    ('lab.process', 'Process lab requests'),
    ('lab.report.upload', 'Upload/deliver lab reports'),
    ('vitals.record', 'Record patient vitals'),
    ('appointment.manage', 'Create/manage appointments'),
    ('queue.manage', 'Manage the check-in / consultation queue'),
    ('billing.manage', 'Handle billing intake and transactions'),
    ('staff.manage', 'Invite, edit, deactivate staff'),
    ('branch.manage', 'Create/edit branches and departments'),
    ('role.manage', 'Create/edit custom roles (enterprise)'),
    ('subscription.view', 'View hospital subscription/usage'),
    ('profile.edit.own', 'Edit own profile'),
]
ROLES = [   # name, description, system_role_key, acts_as
    ('Hospital Admin', '', 'hospital_admin', []),
    ('Doctor', '', 'doctor', []),
    ('Nurse', '', 'nurse', []),
    ('Front Desk', '', 'front_desk', []),
    ('Lab Technician', '', 'lab_tech', []),
    ('Pharmacist', '', 'pharmacist', []),
]
GRANTS = [   # role name, permission code
    ('Hospital Admin', 'lab.catalog.manage'),
    ('Hospital Admin', 'patient.register'),
    ('Hospital Admin', 'lab.process'),
    ('Hospital Admin', 'appointment.manage'),
    ('Hospital Admin', 'patient.view'),
    ('Hospital Admin', 'branch.manage'),
    ('Hospital Admin', 'billing.manage'),
    ('Hospital Admin', 'encounter.create'),
    ('Hospital Admin', 'lab.report.upload'),
    ('Hospital Admin', 'subscription.view'),
    ('Hospital Admin', 'encounter.sign'),
    ('Hospital Admin', 'vitals.record'),
    ('Hospital Admin', 'profile.edit.own'),
    ('Hospital Admin', 'prescription.create'),
    ('Hospital Admin', 'prescription.dispense'),
    ('Hospital Admin', 'lab.order'),
    ('Hospital Admin', 'staff.manage'),
    ('Hospital Admin', 'queue.manage'),
    ('Hospital Admin', 'role.manage'),
    ('Doctor', 'encounter.create'),
    ('Doctor', 'queue.manage'),
    ('Doctor', 'encounter.sign'),
    ('Doctor', 'lab.order'),
    ('Doctor', 'prescription.create'),
    ('Doctor', 'profile.edit.own'),
    ('Doctor', 'patient.view'),
    ('Nurse', 'vitals.record'),
    ('Nurse', 'queue.manage'),
    ('Nurse', 'lab.order'),
    ('Nurse', 'profile.edit.own'),
    ('Nurse', 'patient.view'),
    ('Front Desk', 'patient.register'),
    ('Front Desk', 'billing.manage'),
    ('Front Desk', 'queue.manage'),
    ('Front Desk', 'appointment.manage'),
    ('Front Desk', 'profile.edit.own'),
    ('Lab Technician', 'lab.process'),
    ('Lab Technician', 'lab.report.upload'),
    ('Lab Technician', 'lab.catalog.manage'),
    ('Lab Technician', 'profile.edit.own'),
    ('Pharmacist', 'prescription.dispense'),
    ('Pharmacist', 'billing.manage'),
    ('Pharmacist', 'profile.edit.own'),
]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias
    Permission, Role, RolePermission = (apps.get_model("hospital_setup", n) for n in ("Permission", "Role", "RolePermission"))
    permissions = {code: Permission.objects.using(db).get_or_create(code=code, defaults={"description": text})[0]
                   for code, text in PERMISSIONS}
    roles = {name: Role.objects.using(db).get_or_create(
        name=name, defaults={"description": text, "is_system_role": True, "system_role_key": key, "acts_as": acts})[0]
             for name, text, key, acts in ROLES}
    for role, code in GRANTS:
        RolePermission.objects.using(db).get_or_create(role=roles[role], permission=permissions[code])


class Migration(migrations.Migration):
    dependencies = [("hospital_setup", "0002_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
