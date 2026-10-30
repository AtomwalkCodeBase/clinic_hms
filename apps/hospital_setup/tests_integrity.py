from apps.hospital_setup.models import MODULE_HEADERS, ROLE_CHOICES, Floor, NextNumber, Room, UserGroup, UserPermission
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

    def test_a_staff_member_gets_a_login_with_a_password_of_their_own(self):
        from django.contrib.auth.models import User
        staff = make_staff(self.hospital_alias, "doctor", phone="9000000044", first_name="Ann", last_name="Lee")
        login = User.objects.using("default").get(username=str(staff.user_id))
        self.assertEqual((login.first_name, login.last_name), ("Ann", "Lee"))
        other = User.objects.using("default").get(username=str(make_staff(self.hospital_alias, "doctor", phone="9000000045").user_id))
        self.assertTrue(login.has_usable_password())
        self.assertNotEqual(login.password, other.password)           # no password is shared between new logins
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


class AuditLogIsAppendOnlyTests(HospitalDBTestCase):
    def entry(self):
        from apps.hospital_setup.models import AuditLog
        return AuditLog.objects.using(self.hospital_alias).create(action="x.test", actor_email="a@b.c")

    def test_an_entry_cannot_be_updated_or_deleted_in_bulk(self):
        from apps.hospital_setup.models import AuditLog
        e = self.entry()
        with self.assertRaises(ValueError):
            AuditLog.objects.using(self.hospital_alias).filter(pk=e.pk).update(action="changed")
        with self.assertRaises(ValueError):
            AuditLog.objects.using(self.hospital_alias).filter(pk=e.pk).delete()

    def test_the_database_refuses_raw_changes_too(self):
        from django.db import DatabaseError, connections, transaction
        e = self.entry()
        for sql in ("UPDATE audit_log SET action = 'changed' WHERE id = %s", "DELETE FROM audit_log WHERE id = %s"):
            with self.assertRaises(DatabaseError), transaction.atomic(using=self.hospital_alias):
                connections[self.hospital_alias].cursor().execute(sql, [e.pk])

    def test_clearing_the_patient_link_is_still_allowed(self):
        from apps.hospital_setup.models import AuditLog
        branch, _place = make_branch(self.hospital_alias)
        patient = make_patient(self.hospital_alias, "AWP-AUD", uhid="U-AUD", branch=branch, full_name="A")
        e = AuditLog.objects.using(self.hospital_alias).create(action="x.test", patient=patient)
        from django.db import connections
        # what SET_NULL does when a patient row is removed: only the link changes
        connections[self.hospital_alias].cursor().execute("UPDATE audit_log SET patient_id = NULL WHERE id = %s", [e.pk])
        self.assertIsNone(AuditLog.objects.using(self.hospital_alias).get(pk=e.pk).patient_id)


class UserPermissionModulesTests(HospitalDBTestCase):
    def test_modules_are_stored_as_keys_in_the_order_of_the_module_list(self):
        self.assertEqual(UserPermission.pack(["billing", "opd", "nonsense"]), ["opd", "billing"])

    def test_an_unknown_module_key_is_refused(self):
        from django.core.exceptions import ValidationError
        _branch, place = make_branch(self.hospital_alias)
        group = UserGroup.objects.using(self.hospital_alias).create(name="g", role="n")
        row = UserPermission(user_group=group, branch_department=place, modules=["opd", "nonsense"])
        with self.assertRaises(ValidationError):
            row.full_clean(exclude=["user_group", "branch_department"])
