"""apps/hospital_setup/tests_structure.py — departments offered by branch, rooms on floors, staff in a user group with a place of work."""
from apps.hospital_master.models import Hospital, Subscription
from apps.hospital_setup.branch_utils import default_place, get_staff_branch_ids, place_for, primary_place, set_staff_branches, staff_place_at
from apps.hospital_setup.facility_views import BranchListCreateView, DepartmentDetailView, DepartmentListCreateView, RoomListCreateView
from apps.hospital_setup.models import Branch, BranchDepartment, Department, Floor, Room, StaffBranchAssignment, StaffUser, UserGroup
from apps.hospital_setup.rbac import acts_as_q, api_role, resolve_acts_as, role_q, system_role
from apps.hospital_setup.staff_views import StaffDetailView, StaffInviteView, StaffListView
from apps.hospital_setup.models import OptionList
from core.tests.testing import HospitalDBTestCase, make_branch, make_staff, requires_hospital_db


@requires_hospital_db
class DepartmentsByBranchTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        self.db = self.hospital_alias
        self.north, _ = make_branch(self.db, "North")
        self.south, _ = make_branch(self.db, "South")
        self.admin = make_staff(self.db, "hospital_admin", phone="9000000001")
        self.hospital = Hospital.objects.using("default").create(name="T", hospital_code="t-departments", db_name=self.db)
        Subscription.objects.using("default").create(hospital=self.hospital, license_tier="enterprise", status="active", max_branches=10)

    def call(self, view, method, data=None, **kw):
        return self.call_view(view.as_view(), method, "/api/v1/org/departments/", user_id=self.admin.pk, role="hospital_admin", data=data,
                              hospital_id=self.hospital.pk, **kw)

    def test_a_new_branch_offers_one_department_from_the_start(self):
        response = self.call(BranchListCreateView, "post", {"name": "East"})
        self.assertEqual(response.status_code, 201, response.data)
        branch = Branch.objects.using(self.db).get(name="East")
        self.assertEqual(default_place(self.db, branch.pk).department.name, "General")

    def test_the_same_department_at_two_branches_is_one_department(self):
        for branch in (self.north, self.south):
            response = self.call(DepartmentListCreateView, "post", {"name": "Paediatrics", "branch": branch.pk})
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Department.objects.using(self.db).filter(name="Paediatrics").count(), 1)
        self.assertEqual(BranchDepartment.objects.using(self.db).filter(department__name="Paediatrics").count(), 2)

    def test_offering_it_twice_at_one_branch_is_refused(self):
        self.call(DepartmentListCreateView, "post", {"name": "Paediatrics", "branch": self.north.pk})
        again = self.call(DepartmentListCreateView, "post", {"name": "paediatrics", "branch": self.north.pk})
        self.assertEqual(again.status_code, 400)

    def test_the_list_by_branch_reads_like_the_department_list(self):
        self.call(DepartmentListCreateView, "post", {"name": "Paediatrics", "branch": self.north.pk})
        listed = self.call(DepartmentListCreateView, "get").data
        # the whole list carries the branches that offer each department; the branch list carries the department ids
        names = {d["name"]: d for d in listed["data"]}
        self.assertEqual({b["branch_name"] for b in names["Paediatrics"]["branches"]}, {"North"})
        for_branch = self.call_view(DepartmentListCreateView.as_view(), "get", "/x/", user_id=self.admin.pk, role="hospital_admin",
                                    data={"branch_id": self.north.pk}).data["data"]
        self.assertEqual({d["name"] for d in for_branch}, {"General", "Paediatrics"})
        self.assertEqual(next(d for d in for_branch if d["name"] == "Paediatrics")["department_id"], names["Paediatrics"]["department_id"])

    def test_a_branch_cannot_lose_its_last_department(self):
        general = Department.objects.using(self.db).get(name="General")
        response = self.call_view(DepartmentDetailView.as_view(), "delete", "/x/", user_id=self.admin.pk, role="hospital_admin",
                                  view_kwargs={"pk": general.pk})
        self.assertEqual(response.status_code, 400)       # the department list is shared: both branches would be left with none
        self.assertEqual(BranchDepartment.objects.using(self.db).filter(department=general, is_active=True).count(), 2)


@requires_hospital_db
class RoomsOnFloorsTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        self.db = self.hospital_alias
        self.branch, self.place = make_branch(self.db, "North")
        self.other, self.other_place = make_branch(self.db, "South")
        self.floor = self.place.floor
        self.admin = make_staff(self.db, "hospital_admin", phone="9000000001")
        OptionList.objects.using(self.db).get_or_create(
            list_type=OptionList.LIST_ROOM_TYPE, value="consultation", defaults={"label": "Consultation"})

    def create(self, **data):
        return self.call_view(RoomListCreateView.as_view(), "post", "/x/", user_id=self.admin.pk, role="hospital_admin",
                              data={"name": "Room 1", "room_type": "consultation", **data})

    def test_a_room_takes_its_branch_from_its_floor(self):
        response = self.create(floor_obj=self.floor.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["branch"], self.branch.pk)
        self.assertEqual(Room.objects.using(self.db).get().floor.branch, self.branch)

    def test_a_room_needs_a_floor(self):
        self.assertEqual(self.create().status_code, 400)

    def test_a_branch_that_is_not_the_floors_is_refused(self):
        self.assertEqual(self.create(floor_obj=self.floor.pk, branch=self.other.pk).status_code, 400)

    def test_a_room_name_is_unique_on_its_floor_only(self):
        self.assertEqual(self.create(floor_obj=self.floor.pk).status_code, 201)
        self.assertEqual(self.create(floor_obj=self.floor.pk).status_code, 400)
        upstairs = Floor.objects.using(self.db).create(branch=self.branch, name="First")
        self.assertEqual(self.create(floor_obj=upstairs.pk).status_code, 201)

    def test_a_department_must_be_offered_at_the_floors_branch(self):
        elsewhere = Department.objects.using(self.db).create(name="Cardiology")
        BranchDepartment.objects.using(self.db).create(branch=self.other, department=elsewhere, floor=self.other_place.floor)
        self.assertEqual(self.create(floor_obj=self.floor.pk, department=elsewhere.pk).status_code, 400)
        general = Department.objects.using(self.db).get(name="General")
        response = self.create(floor_obj=self.floor.pk, department=general.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["department_name"], "General")


@requires_hospital_db
class StaffGroupAndPlaceTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        self.db = self.hospital_alias
        self.north, self.north_general = make_branch(self.db, "North")
        self.south, self.south_general = make_branch(self.db, "South")
        self.paeds = Department.objects.using(self.db).create(name="Paediatrics")
        self.north_paeds = BranchDepartment.objects.using(self.db).create(branch=self.north, department=self.paeds, floor=self.north_general.floor)
        self.south_paeds = BranchDepartment.objects.using(self.db).create(branch=self.south, department=self.paeds, floor=self.south_general.floor)
        self.hospital = Hospital.objects.using("default").create(name="T", hospital_code="t-structure", db_name=self.db)
        Subscription.objects.using("default").create(hospital=self.hospital, license_tier="enterprise", status="active")
        self.admin = make_staff(self.db, "hospital_admin", phone="9000000001", place=self.north_general)

    def invite(self, **data):
        body = {"first_name": "Ann", "last_name": "Lee", "phone": "9000000100", "role": "doctor", **data}
        return self.call_view(StaffInviteView.as_view(), "post", "/x/", user_id=self.admin.pk, role="hospital_admin", data=body,
                              hospital_id=self.hospital.pk)

    # ── user group ─────────────────────────────────────────────────────────
    def test_a_staff_member_is_in_the_group_of_their_role(self):
        doctor = make_staff(self.db, "doctor", phone="9000000002")
        self.assertEqual((doctor.user_group.role, doctor.get_role(), api_role(doctor)), ("d", "d", "doctor"))
        self.assertEqual(resolve_acts_as(doctor), {"doctor"})


    def test_the_role_filter_of_the_staff_list_follows_the_group(self):
        make_staff(self.db, "doctor", phone="9000000002")
        response = self.call_view(StaffListView.as_view(), "get", "/x/", user_id=self.admin.pk, role="hospital_admin", data={"role": "doctor"})
        self.assertEqual([s["role"] for s in response.data["data"]["results"]], ["doctor"])

    # ── invite: group, place, profile ──────────────────────────────────────
    def test_an_invited_doctor_gets_the_doctor_group_a_place_and_one_profile(self):
        response = self.invite(branch_id=self.north.pk, department_id=self.paeds.pk, specialisation="Paediatrics",
                               registration_no="KMC-1", qualification="MD")
        self.assertEqual(response.status_code, 201, response.data)
        doctor = StaffUser.objects.using(self.db).get(phone="9000000100")
        self.assertEqual((api_role(doctor), primary_place(doctor, self.db)), ("doctor", self.north_paeds))
        self.assertEqual((doctor.specialisation, doctor.registration_no), ("Paediatrics", "KMC-1"))
        shown = response.data["data"]
        self.assertEqual((shown["role"], shown["branch"], shown["department"]), ("doctor", self.north.pk, self.paeds.pk))
        self.assertEqual(shown["doctor_profile"]["specialisation"], "Paediatrics")
        self.assertIsNone(shown["staff_profile"])

    def test_a_nurse_profile_holds_the_council_details_in_the_same_table(self):
        response = self.invite(role="nurse", phone="9000000101", branch_id=self.north.pk, registration_no="KNC-1", council_name="Karnataka")
        self.assertEqual(response.status_code, 201, response.data)
        nurse = StaffUser.objects.using(self.db).get(phone="9000000101")
        self.assertEqual((nurse.registration_no, nurse.council_name, nurse.specialisation), ("KNC-1", "Karnataka", ""))
        self.assertEqual(response.data["data"]["staff_profile"]["council_name"], "Karnataka")
        self.assertIsNone(response.data["data"]["doctor_profile"])

    def test_with_no_department_named_the_branchs_default_one_is_used(self):
        self.invite(branch_id=self.south.pk)
        self.assertEqual(primary_place(StaffUser.objects.using(self.db).get(phone="9000000100"), self.db), self.south_general)

    def test_a_department_the_branch_does_not_offer_is_refused(self):
        cardio = Department.objects.using(self.db).create(name="Cardiology")
        self.assertEqual(self.invite(branch_id=self.north.pk, department_id=cardio.pk).status_code, 400)

    def test_a_department_without_a_branch_is_refused(self):
        self.assertEqual(self.invite(department_id=self.paeds.pk).status_code, 400)

    def test_extra_branches_become_extra_places_in_the_same_department(self):
        response = self.invite(branch_id=self.north.pk, department_id=self.paeds.pk, branch_ids=[self.south.pk])
        self.assertEqual(response.status_code, 201, response.data)
        doctor = StaffUser.objects.using(self.db).get(phone="9000000100")
        self.assertEqual(set(StaffBranchAssignment.objects.using(self.db).filter(staff=doctor).values_list("branch", flat=True)),
                         {self.north.pk, self.south.pk})
        self.assertEqual(StaffBranchAssignment.objects.using(self.db).get(staff=doctor, is_primary=True).branch, self.north)
        self.assertEqual(get_staff_branch_ids(doctor.pk, self.db), {self.north.pk, self.south.pk})
        branches = response.data["data"]["branches"]
        self.assertEqual([(b["name"], b["is_primary"]) for b in branches], [("North", True), ("South", False)])
        self.assertEqual(staff_place_at(doctor, self.south.pk, self.db), self.south_paeds)
        self.assertEqual(staff_place_at(doctor, self.north.pk, self.db), self.north_paeds)

    # ── change a staff member ───────────────────────────────────────────────
    def patch(self, staff, **data):
        return self.call_view(StaffDetailView.as_view(), "patch", "/x/", user_id=self.admin.pk, role="hospital_admin", data=data,
                              hospital_id=self.hospital.pk, view_kwargs={"pk": staff.pk})

    def test_changing_the_role_moves_the_staff_member_to_that_group(self):
        nurse = make_staff(self.db, "nurse", phone="9000000004", place=self.north_general)
        response = self.patch(nurse, role="front_desk")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(api_role(StaffUser.objects.using(self.db).get(pk=nurse.pk)), "front_desk")

    def test_the_last_hospital_admin_cannot_be_moved_out_of_the_admin_group(self):
        self.assertEqual(self.patch(self.admin, role="doctor").status_code, 400)

    def test_a_staff_member_moves_to_another_branch_and_department(self):
        doctor = make_staff(self.db, "doctor", phone="9000000005", place=self.north_general)
        response = self.patch(doctor, branch_id=self.south.pk, department_id=self.paeds.pk)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(primary_place(StaffUser.objects.using(self.db).get(pk=doctor.pk), self.db), self.south_paeds)
        self.assertEqual(StaffBranchAssignment.objects.using(self.db).filter(staff=doctor, is_primary=True).count(), 1)

    def test_set_staff_branches_keeps_the_department_where_the_branch_offers_it(self):
        doctor = make_staff(self.db, "doctor", phone="9000000006", place=self.north_paeds)
        set_staff_branches(doctor, [self.north.pk, self.south.pk], self.south.pk, self.db)
        self.assertEqual(primary_place(doctor, self.db), self.south_paeds)
        self.assertEqual(place_for(self.db, self.north.pk, self.paeds.pk), self.north_paeds)
        self.assertEqual(set(StaffBranchAssignment.objects.using(self.db).filter(staff=doctor).values_list("branch", flat=True)),
                         {self.north.pk, self.south.pk})

    def test_a_user_group_is_created_edited_and_deleted_through_the_api(self):
        from apps.hospital_setup.staff_views import RoleDetailView, RoleListCreateView
        features = ("feat_custom_roles",)
        made = self.call_view(RoleListCreateView.as_view(), "post", "/x/", user_id=self.admin.pk, role="hospital_admin", features=features,
                              data={"name": "Ward Nurses", "role": "nurse", "modules": ["patients", "opd"]})
        self.assertEqual(made.status_code, 201, made.data)
        group_id = made.data["data"]["user_group_id"]
        self.assertEqual(sorted(made.data["data"]["modules"]), ["opd", "patients"])
        edited = self.call_view(RoleDetailView.as_view(), "patch", "/x/", user_id=self.admin.pk, role="hospital_admin", features=features,
                                data={"name": "Night Nurses", "modules": ["billing"]}, view_kwargs={"pk": group_id})
        self.assertEqual((edited.status_code, edited.data["data"]["name"], edited.data["data"]["modules"]), (200, "Night Nurses", ["billing"]))
        make_staff(self.db, "nurse", phone="9000000077", user_group=UserGroup.objects.using(self.db).get(pk=group_id))
        blocked = self.call_view(RoleDetailView.as_view(), "delete", "/x/", user_id=self.admin.pk, role="hospital_admin", features=features,
                                 view_kwargs={"pk": group_id})
        self.assertEqual(blocked.status_code, 400)
        StaffUser.objects.using(self.db).filter(user_group_id=group_id).delete()
        gone = self.call_view(RoleDetailView.as_view(), "delete", "/x/", user_id=self.admin.pk, role="hospital_admin", features=features,
                              view_kwargs={"pk": group_id})
        self.assertEqual(gone.status_code, 200)
        self.assertFalse(UserGroup.objects.using(self.db).filter(pk=group_id).exists())

