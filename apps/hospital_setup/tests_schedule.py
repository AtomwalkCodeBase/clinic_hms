"""apps/hospital_setup/tests_schedule.py — a doctor's working-hours schedule is stored and read back, per place of work."""

from apps.hospital_setup.models import DoctorSchedule
from apps.hospital_setup.staff_views import DoctorScheduleView
from core.tests.testing import HospitalDBTestCase, make_branch, make_staff, requires_hospital_db

DAYS = [{"day_of_week": d, "is_available": d <= 5, "start_time": "09:00", "end_time": "20:00"} for d in range(7)]


@requires_hospital_db
class DoctorScheduleTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        db = self.hospital_alias
        self.branch, self.place = make_branch(db)
        self.admin = make_staff(db, "hospital_admin", email="a@example.test", phone="9000000001")
        self.doctor = make_staff(db, "doctor", email="d@example.test", phone="9000000002", place=self.place)

    def call(self, method, data=None):
        return self.call_view(DoctorScheduleView.as_view(), method, "/api/v1/org/staff/1/schedule/", user_id=self.admin.id,
                              role="hospital_admin", data=data, view_kwargs={"pk": self.doctor.id})

    def test_the_days_sent_are_stored_and_come_back(self):
        put = self.call("put", {"slot_duration_minutes": 15, "days": DAYS})
        self.assertEqual(put.status_code, 200, put.data)
        schedule = DoctorSchedule.objects.using(self.hospital_alias).get()
        self.assertEqual(len(schedule.weekly_hours), 7)
        self.assertEqual(schedule.staff_branch_department.branch_department, self.place)       # the schedule belongs to the doctor's place
        got = self.call("get").data["data"]
        self.assertEqual(len(got["days"]), 7)
        self.assertEqual([d["is_available"] for d in sorted(got["days"], key=lambda d: d["day_of_week"])], [True] * 6 + [False])

    def test_saving_again_replaces_the_days(self):
        self.call("put", {"slot_duration_minutes": 15, "days": DAYS})
        self.call("put", {"slot_duration_minutes": 20, "days": DAYS[:2]})
        schedule = DoctorSchedule.objects.using(self.hospital_alias).get()
        self.assertEqual((len(schedule.weekly_hours), schedule.slot_duration_minutes), (2, 20))

    def test_a_doctor_with_no_place_of_work_has_no_schedule_to_save(self):
        nowhere = make_staff(self.hospital_alias, "doctor", email="n@example.test", phone="9000000003")
        response = self.call_view(DoctorScheduleView.as_view(), "put", "/x/", user_id=self.admin.id, role="hospital_admin",
                                  data={"slot_duration_minutes": 15, "days": DAYS}, view_kwargs={"pk": nowhere.id})
        self.assertEqual(response.status_code, 400)

    def test_a_doctor_at_two_branches_has_a_schedule_at_each(self):
        other, other_place = make_branch(self.hospital_alias, "Other")
        from apps.hospital_setup.branch_utils import set_staff_branches
        set_staff_branches(self.doctor, [self.branch.id, other.id], self.branch.id, self.hospital_alias)
        self.call("put", {"slot_duration_minutes": 15, "days": DAYS[:1]})
        response = self.call_view(DoctorScheduleView.as_view(), "put", f"/x/?branch_id={other.id}", user_id=self.admin.id, role="hospital_admin",
                                  data={"slot_duration_minutes": 30, "days": DAYS[:3]}, view_kwargs={"pk": self.doctor.id})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(DoctorSchedule.objects.using(self.hospital_alias).count(), 2)


@requires_hospital_db
class RoomForASlotTests(HospitalDBTestCase):
    def test_the_room_found_for_a_slot_brings_its_floor_name_with_it(self):
        from datetime import time
        from apps.hospital_setup.models import Room
        from apps.hospital_setup.room_utils import resolve_room_for_slot, save_block
        db = self.hospital_alias
        branch, place = make_branch(db)
        room = Room.objects.using(db).create(floor=place.floor, name="Room 101")
        doctor = make_staff(db, "doctor", email="d@example.test", phone="9000000002", place=place)
        self.assertIsNotNone(save_block(db, room, doctor, 0, time(9), time(20)))
        match = resolve_room_for_slot(db, doctor.id, 0, time(10))
        with self.assertNumQueries(0):                 # nothing is fetched afterwards, so nothing can go to the wrong database
            self.assertEqual((match.name, match.floor.name), ("Room 101", "Ground"))
        self.assertIsNone(resolve_room_for_slot(db, doctor.id, 0, time(21)))
        self.assertIsNone(resolve_room_for_slot(db, doctor.id, 1, time(10)))
