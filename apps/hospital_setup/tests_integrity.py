from apps.hospital_setup.compliance_services import record_consent
from apps.hospital_setup.models import Branch, ConsentRecord, Floor, NextNumber, Permission, Role, RolePermission, Room
from apps.hospital_setup.rbac import PERMISSION_CATALOG, SYSTEM_ROLE_PERMISSIONS, sync_roles_and_permissions
from apps.hospital_setup.staff_services import next_employee_id
from apps.opd.models import HospitalPatient
from core.tests.testing import HospitalDBTestCase


class SystemRolesFollowTheCodeTests(HospitalDBTestCase):
    def test_a_missing_permission_and_a_stray_grant_are_put_right(self):
        Permission.objects.using(self.hospital_alias).filter(code="milestone.record").delete()
        doctor = Role.objects.using(self.hospital_alias).get(system_role_key="doctor")
        extra = Permission.objects.using(self.hospital_alias).get(code="staff.manage")
        RolePermission.objects.using(self.hospital_alias).create(role=doctor, permission=extra)
        sync_roles_and_permissions(self.hospital_alias)
        self.assertEqual(Permission.objects.using(self.hospital_alias).count(), len(PERMISSION_CATALOG))
        granted = set(RolePermission.objects.using(self.hospital_alias).filter(role=doctor).values_list("permission__code", flat=True))
        self.assertEqual(granted, set(SYSTEM_ROLE_PERMISSIONS["doctor"]))

    def test_every_system_role_exists_once(self):
        sync_roles_and_permissions(self.hospital_alias)
        sync_roles_and_permissions(self.hospital_alias)
        self.assertEqual(Role.objects.using(self.hospital_alias).filter(is_system_role=True).count(), 6)


class ConsentTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        branch = Branch.objects.using(self.hospital_alias).create(name="Main")
        self.patient = HospitalPatient.objects.using(self.hospital_alias).create(
            awpid="AWP-C1", uhid="U-1", branch=branch, full_name="C One", hie_consent_given=False)

    def row(self):
        return HospitalPatient.objects.using(self.hospital_alias).get(pk=self.patient.pk)

    def test_granting_and_withdrawing_move_the_flag_with_the_record(self):
        record_consent(self.hospital_alias, self.patient, ConsentRecord.CONSENT_HIE_SHARING, ConsentRecord.SOURCE_PORTAL)
        self.assertTrue(self.row().hie_consent_given)
        record_consent(self.hospital_alias, self.patient, ConsentRecord.CONSENT_HIE_SHARING, ConsentRecord.SOURCE_PORTAL, granted=False)
        self.assertFalse(self.row().hie_consent_given)
        self.assertEqual(ConsentRecord.objects.using(self.hospital_alias).filter(patient=self.patient).count(), 2)

    def test_a_consent_record_cannot_be_edited_or_deleted(self):
        record_consent(self.hospital_alias, self.patient, ConsentRecord.CONSENT_HIE_SHARING, ConsentRecord.SOURCE_PORTAL)
        record = ConsentRecord.objects.using(self.hospital_alias).get()
        record.notes = "changed"
        with self.assertRaises(ValueError):
            record.save(using=self.hospital_alias)
        with self.assertRaises(ValueError):
            record.delete(using=self.hospital_alias)


class CounterAndFloorTests(HospitalDBTestCase):
    def test_employee_ids_use_one_hospital_wide_counter(self):
        self.assertEqual(next_employee_id(self.hospital_alias), "EMP-000001")
        self.assertEqual(next_employee_id(self.hospital_alias), "EMP-000002")
        counter = NextNumber.objects.using(self.hospital_alias).get(entity="employee_id")
        self.assertIsNone(counter.branch_id)

    def test_a_room_reads_its_floor_name_from_the_floor_row(self):
        branch = Branch.objects.using(self.hospital_alias).create(name="Main")
        floor = Floor.objects.using(self.hospital_alias).create(branch=branch, name="2nd Floor")
        room = Room.objects.using(self.hospital_alias).create(branch=branch, floor_obj=floor, name="R1")
        self.assertEqual(room.floor, "2nd Floor")
        floor.name = "Second"
        floor.save(using=self.hospital_alias)
        self.assertEqual(Room.objects.using(self.hospital_alias).get(pk=room.pk).floor, "Second")
