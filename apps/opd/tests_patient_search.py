"""apps/opd/tests_patient_search.py — the front-desk patient search."""

from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff, requires_hospital_db

from apps.opd.patient_views import PatientSearchView


@requires_hospital_db
class PatientSearchTests(HospitalDBTestCase):
    def setUp(self):
        super().setUp()
        db = self.hospital_alias
        self.branch, place = make_branch(db)
        self.staff = make_staff(db, "front_desk", email="fd@example.test", phone="9000000002", place=place)
        make_patient(db, "AWPID-20261021-AAAA1111", uhid="UHID-1", branch=self.branch, full_name="Asha Rao", mobile="9876501234")

    def search(self, q):
        return self.call_view(PatientSearchView.as_view(), "get", "/api/v1/patients/search/", user_id=self.staff.id, role="front_desk", data={"q": q})

    def test_an_awpid_that_is_not_a_patient_here_finds_nothing_and_does_not_crash(self):
        response = self.search("AWPID-20261021-09WEHMW3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["results"], [])

    def test_digits_that_are_not_a_valid_mobile_number_do_not_crash(self):
        self.assertEqual(self.search("1234567").status_code, 200)

    def test_an_awpid_of_a_patient_here_is_found(self):
        self.assertEqual(len(self.search("AWPID-20261021-AAAA1111").data["data"]["results"]), 1)
