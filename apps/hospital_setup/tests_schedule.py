"""apps/hospital_setup/tests_schedule.py — a doctor's working-hours schedule is stored and read back, per place of work."""

from apps.hospital_setup.staff_views import DoctorScheduleView
from core.tests.testing import HospitalDBTestCase, make_branch, make_staff, requires_hospital_db

DAYS = [{"day_of_week": d, "is_available": d <= 5, "start_time": "09:00", "end_time": "20:00"} for d in range(7)]


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
        match = resolve_room_for_slot(db, doctor.pk, 0, time(10))
        with self.assertNumQueries(0):                 # nothing is fetched afterwards, so nothing can go to the wrong database
            self.assertEqual((match.name, match.floor.name), ("Room 101", "Ground"))
        self.assertIsNone(resolve_room_for_slot(db, doctor.pk, 0, time(21)))
        self.assertIsNone(resolve_room_for_slot(db, doctor.pk, 1, time(10)))
