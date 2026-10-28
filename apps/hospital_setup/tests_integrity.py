from apps.hospital_setup.models import INITIAL_PASSWORD, MODULE_HEADERS, ROLE_CHOICES, Floor, NextNumber, Room, UserGroup, UserPermission
from apps.hospital_setup.rbac import get_effective_modules, sync_roles_and_permissions
from apps.hospital_setup.staff_services import next_employee_id
from apps.hospital_patients.models import HospitalPatient
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff


class UserGroupTests(HospitalDBTestCase):
    def test_every_role_has_one_default_group_and_syncing_twice_adds_nothing(self):
        sync_roles_and_permissions(self.hospital_alias)
        sync_roles_and_permissions(self.hospital_alias)
        self.assertEqual(UserGroup.objects.using(self.hospital_alias).count(), len(ROLE_CHOICES))
        self.assertEqual(set(UserGroup.objects.using(self.hospital_alias).values_list("role", flat=True)), {r for r, _ in ROLE_CHOICES})

    def test_a_role_gets_its_modules_and_a_group_permission_adds_more(self):
        branch, place = make_branch(self.hospital_alias)
        nurse = make_staff(self.hospital_alias, "nurse", phone="9000000042", place=place)
        self.assertEqual(get_effective_modules(nurse, self.hospital_alias), {"patients", "opd"})
        UserPermission.objects.using(self.hospital_alias).create(user_group=nurse.user_group, branch_department=place, modules=UserPermission.pack(["billing"]))
        self.assertIn("billing", get_effective_modules(nurse, self.hospital_alias))
        admin = make_staff(self.hospital_alias, "hospital_admin", phone="9000000043")
        self.assertEqual(get_effective_modules(admin, self.hospital_alias), set(MODULE_HEADERS))

    def test_a_staff_member_gets_a_login_with_the_initial_password(self):
        from django.contrib.auth.models import User
        staff = make_staff(self.hospital_alias, "doctor", phone="9000000044", first_name="Ann", last_name="Lee")
        login = User.objects.using("default").get(username=str(staff.user_id))
        self.assertEqual((login.first_name, login.last_name), ("Ann", "Lee"))
        self.assertTrue(login.check_password(INITIAL_PASSWORD))
        self.assertTrue(staff.must_change_password)

    def test_the_catalog_and_the_login_follow_the_staff_row(self):
        from django.contrib.auth.models import User
        from apps.hospital_master.models import GlobalStaffUserIndexCatalog, Hospital
        from apps.hospital_setup.staff_services import sync_catalog
        hospital = Hospital.objects.using("default").create(name="Sync H", hospital_code="sync-h", db_name=self.hospital_alias)
        doctor = make_staff(self.hospital_alias, "doctor", phone="9000000046", first_name="Ann", last_name="Lee", specialisation="Paediatrics")
        sync_catalog(doctor, hospital.pk)
        doctor.first_name, doctor.specialisation = "Anna", "Cardiology"
        doctor.save(using=self.hospital_alias)
        sync_catalog(doctor, hospital.pk)
        row = GlobalStaffUserIndexCatalog.objects.using("default").get(user__username=str(doctor.user_id))
        self.assertEqual((row.mobile, row.is_doctor, row.doctor_details["specialisation"]), ("9000000046", True, "Cardiology"))
        self.assertEqual(User.objects.using("default").get(username=str(doctor.user_id)).first_name, "Anna")

    def test_no_login_is_left_behind_when_the_staff_row_cannot_be_saved(self):
        from django.contrib.auth.models import User
        make_staff(self.hospital_alias, "doctor", phone="9000000045")
        before = User.objects.using("default").count()
        with self.assertRaises(Exception):
            make_staff(self.hospital_alias, "nurse", phone="9000000045")
        self.assertEqual(User.objects.using("default").count(), before)


class CounterAndFloorTests(HospitalDBTestCase):
    def test_employee_ids_use_one_hospital_wide_counter(self):
        self.assertEqual(next_employee_id(self.hospital_alias), "EMP-000001")
        self.assertEqual(next_employee_id(self.hospital_alias), "EMP-000002")
        counter = NextNumber.objects.using(self.hospital_alias).get(entity="employee_id")
        self.assertIsNone(counter.branch_id)

    def test_a_room_reads_its_floor_name_from_the_floor_row(self):
        branch, _place = make_branch(self.hospital_alias)
        floor = Floor.objects.using(self.hospital_alias).create(branch=branch, name="2nd Floor")
        room = Room.objects.using(self.hospital_alias).create(floor=floor, name="R1")
        self.assertEqual((room.floor.name, room.floor.branch), ("2nd Floor", branch))      # a room's branch is its floor's branch
        floor.name = "Second"
        floor.save(using=self.hospital_alias)
        self.assertEqual(Room.objects.using(self.hospital_alias).get(pk=room.pk).floor.name, "Second")
