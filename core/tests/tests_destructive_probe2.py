"""core/tests/tests_destructive_probe2.py — second batch of probes for docs/Destructive_Test_Cases.xlsx: who may call what, public links, login, bad input.
Results go to the file named by PROBE_OUT2, as in tests_destructive_probe.py."""

import json
import os
from types import SimpleNamespace

from django.core.cache import cache
from django.db import transaction
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api.authentication import MockUser
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff, requires_hospital_db

RESULTS = {}


@requires_hospital_db
class DestructiveProbes2(HospitalDBTestCase):
    @classmethod
    def tearDownClass(cls):
        out = os.environ.get("PROBE_OUT2")
        if out:
            with open(out, "w", encoding="utf8") as f:
                json.dump(RESULTS, f, indent=1, sort_keys=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from apps.hospital_master.models import Hospital, HospitalParameters
        from apps.patients.models import Patient
        cache.clear()
        db = self.hospital_alias
        self.hospital = Hospital.objects.using("default").create(name="Probe H2", hospital_code="probe-h2", db_name=db)
        HospitalParameters.objects.using("default").create(hospital=self.hospital)
        from apps.hospital_master.models import Subscription
        Subscription.objects.using("default").create(hospital=self.hospital, license_tier="enterprise", status="active", feat_patient_app=True)
        self.branch, self.place = make_branch(db)
        self.doctor = make_staff(db, "doctor", email="dr.p2@example.test", phone="9000000041", place=self.place)
        self.acct = Patient.objects.using("default").create(awpid="AW-ME", full_name="Me Myself", mobile="9111111111", password="x", date_of_birth="1990-01-01")
        self.other = Patient.objects.using("default").create(awpid="AW-OTHER", full_name="Other Person", mobile="9222222222", password="x", date_of_birth="1991-01-01")
        make_patient(db, "AW-ME", uhid="UME", branch=self.branch, full_name="Me Myself")

    # helpers
    def req(self, view, method, data=None, *, role=None, uid=None, awpid=None, kwargs=None, query=None, fmt="json"):
        factory = APIRequestFactory()
        if method == "get":
            request = factory.get("/x/", query or data or {})
        else:
            request = getattr(factory, method)("/x/", data or {}, format=fmt)
        if role:
            user = MockUser({"user_id": uid or self.doctor.pk, "role": role, "hospital_id": self.hospital.pk, "awpid": awpid})
            user.subscription = SimpleNamespace(**{f: True for f in ("opd", "billing", "patients", "staff", "facility", "reports", "compliance")})
            force_authenticate(request, user=user)
        request.hospital_db = self.hospital_alias
        request.hospital_id = self.hospital.pk
        return view.as_view()(request, **(kwargs or {}))

    def probe(self, name, fn):
        try:
            with transaction.atomic(using=self.hospital_alias):
                r = fn()
            RESULTS[name] = {"status": r.status_code, "body": str(getattr(r, "data", ""))[:200]}
        except Exception as e:
            RESULTS[name] = {"status": "EXCEPTION", "body": f"{type(e).__name__}: {str(e)[:160]}"}

    # who may call what
    def test_roles(self):
        from apps.billing.views import BillingSummaryView, InvoiceListCreateView, RevenueReportView
        from apps.hospital_master.platform_views import HospitalListCreateView
        from apps.hospital_setup.compliance_views import AuditLogListView
        from apps.hospital_setup.facility_views import BranchListCreateView
        from apps.hospital_setup.staff_views import RoleListCreateView, StaffInviteView, StaffListView
        from apps.opd.views import EncounterCreateView, PrescriptionCreateView
        G = [
            ("Invoices list as a nurse", InvoiceListCreateView, "get", "nurse"),
            ("Invoices list as a patient", InvoiceListCreateView, "get", "patient"),
            ("Billing summary as a front-desk user", BillingSummaryView, "get", "front_desk"),
            ("Revenue report as a front-desk user", RevenueReportView, "get", "front_desk"),
            ("Revenue report as a doctor", RevenueReportView, "get", "doctor"),
            ("Staff list as a doctor", StaffListView, "get", "doctor"),
            ("Staff list as a patient", StaffListView, "get", "patient"),
            ("Staff invite as a doctor", StaffInviteView, "post", "doctor"),
            ("Roles list as a nurse", RoleListCreateView, "get", "nurse"),
            ("Role create as a front-desk user", RoleListCreateView, "post", "front_desk"),
            ("Branch create as a doctor", BranchListCreateView, "post", "doctor"),
            ("Audit log as a doctor", AuditLogListView, "get", "doctor"),
            ("Audit log as a patient", AuditLogListView, "get", "patient"),
            ("Platform hospital list as a hospital admin", HospitalListCreateView, "get", "hospital_admin"),
            ("Platform hospital create as a doctor", HospitalListCreateView, "post", "doctor"),
            ("Encounter create as a front-desk user", EncounterCreateView, "post", "front_desk"),
            ("Prescription create as a nurse", PrescriptionCreateView, "post", "nurse"),
        ]
        for name, view, method, role in G:
            self.probe(name, lambda v=view, m=method, r=role: self.req(v, m, {}, role=r))
        self.probe("Billing summary as a hospital admin (should work)", lambda: self.req(BillingSummaryView, "get", role="hospital_admin"))
        self.probe("Staff list as a hospital admin (should work)", lambda: self.req(StaffListView, "get", role="hospital_admin"))

    # a patient and other patients' records
    def test_patient_access(self):
        from apps.documents.views_timeline import (ClinicalEventView, PatientClinicalSummaryView, PatientGrowthView,
                                                   PatientHealthTimelineView, PatientImmunizationView, PatientRebuildView,
                                                   RecurrenceAckView)
        P = dict(role="patient", uid=self.acct.pk, awpid="AW-ME")
        for label, view in [("timeline", PatientHealthTimelineView), ("growth", PatientGrowthView),
                            ("immunization", PatientImmunizationView), ("clinical summary", PatientClinicalSummaryView)]:
            self.probe(f"Patient opens own {label}", lambda v=view: self.req(v, "get", kwargs={"awpid": "AW-ME"}, **P))
            self.probe(f"Patient opens another patient's {label}", lambda v=view: self.req(v, "get", kwargs={"awpid": "AW-OTHER"}, **P))
            self.probe(f"Patient opens a {label} that does not exist", lambda v=view: self.req(v, "get", kwargs={"awpid": "AW-NOPE"}, **P))
        self.probe("Patient rebuilds own timeline", lambda: self.req(PatientRebuildView, "post", kwargs={"awpid": "AW-ME"}, **P))
        self.probe("Patient edits an event", lambda: self.req(ClinicalEventView, "patch", {"action": "reject"}, kwargs={"event_id": 1}, **P))
        self.probe("Patient acknowledges a recurrence flag", lambda: self.req(RecurrenceAckView, "post", kwargs={"flag_id": 1}, **P))
        self.probe("Timeline with no token at all", lambda: self.req(PatientHealthTimelineView, "get", kwargs={"awpid": "AW-ME"}))
        self.probe("Timeline with bad period dates", lambda: self.req(PatientHealthTimelineView, "get", query={"from": "bad", "to": "worse"}, kwargs={"awpid": "AW-ME"}, **P))

    # patient booking input checks
    def test_portal_booking(self):
        from datetime import date, timedelta
        from apps.patients.views import (PortalBookView, PortalCancelBookingView, PortalDocumentDetailView, PortalDoctorListView,
                                         PortalHospitalListView, PortalMyBookingsView, PortalRescheduleBookingView, PortalSearchView)
        P = dict(role="patient", uid=self.acct.pk, awpid="AW-ME")
        t = date.today()

        def book(**d):
            base = {"hospital_id": self.hospital.pk, "doctor_id": self.doctor.pk}
            base.update(d)
            return lambda: self.req(PortalBookView, "post", base, **P)
        self.probe("Portal book with no hospital or doctor", lambda: self.req(PortalBookView, "post", {}, **P))
        self.probe("Portal book a past date", book(scheduled_date=str(t - timedelta(days=3))))
        self.probe("Portal book 200 days ahead", book(scheduled_date=str(t + timedelta(days=200))))
        self.probe("Portal book with a bad date", book(scheduled_date="31-02-2026"))
        self.probe("Portal book with a hospital that does not exist", book(hospital_id=99999))
        self.probe("Portal book with a doctor that does not exist", book(doctor_id=99999))
        self.probe("Portal book with text ids", book(hospital_id="abc", doctor_id="x"))
        self.probe("Portal book for a patient not in the family", book(patient_awpid="AW-OTHER"))
        self.probe("Portal book with someone else's mobile", book(contact_mobile="9999999999"))
        self.probe("Portal book with a bad payment preference", book(payment_preference="bitcoin"))
        self.probe("Portal cancel a booking that does not exist", lambda: self.req(PortalCancelBookingView, "post", kwargs={"pk": 99999}, **P))
        self.probe("Portal reschedule a booking that does not exist", lambda: self.req(PortalRescheduleBookingView, "post", {"scheduled_date": str(t)}, kwargs={"pk": 99999}, **P))
        self.probe("Portal open a document that does not exist", lambda: self.req(PortalDocumentDetailView, "get", kwargs={"doc_id": 99999}, **P))
        self.probe("Portal my bookings as a doctor", lambda: self.req(PortalMyBookingsView, "get", role="doctor"))
        self.probe("Portal book as a doctor", lambda: self.req(PortalBookView, "post", {"hospital_id": 1, "doctor_id": 1}, role="doctor"))
        self.probe("Portal search with 10,000 characters", lambda: self.req(PortalSearchView, "get", query={"q": "a" * 10000}, **P))
        self.probe("Portal search with symbols", lambda: self.req(PortalSearchView, "get", query={"q": "%'\";--<script>"}, **P))
        self.probe("Portal doctors of a hospital that does not exist", lambda: self.req(PortalDoctorListView, "get", kwargs={"hospital_id": 99999}, **P))

    # links that need no login
    def test_public_links(self):
        from apps.documents.views import DocumentViewView
        from apps.patients.views import ConsultPadView, EmergencySummaryView, RecordsShareClaimView, RecordsShareStatusView
        for label, view in [("Emergency link", EmergencySummaryView), ("Consult pad link", ConsultPadView),
                            ("Share status link", RecordsShareStatusView), ("View-report link", DocumentViewView)]:
            self.probe(f"{label} with a made-up token", lambda v=view: self.req(v, "get", kwargs={"token": "not-a-real-token"}))
            self.probe(f"{label} with a 5,000-character token", lambda v=view: self.req(v, "get", kwargs={"token": "x" * 5000}))
            self.probe(f"{label} with script text as the token", lambda v=view: self.req(v, "get", kwargs={"token": "<script>alert(1)</script>"}))
        self.probe("Share claim with no code", lambda: self.req(RecordsShareClaimView, "post", {}))
        self.probe("Share claim with a wrong code", lambda: self.req(RecordsShareClaimView, "post", {"code": "000000"}))
        self.probe("Share claim with a 10,000-character code", lambda: self.req(RecordsShareClaimView, "post", {"code": "9" * 10000}))

    # logging in
    def test_login(self):
        from core.auth.views import PatientLoginView, PlatformLoginView, StaffLoginView
        from core.auth.otp_views import OTPRequestView, OTPVerifyView
        pl = lambda **d: (lambda: self.req(PatientLoginView, "post", d))
        self.probe("Patient login with no fields", pl())
        self.probe("Patient login with an unknown id", pl(awpid="AW-NONE", password="whatever1"))
        self.probe("Patient login with a wrong password", pl(awpid="AW-ME", password="wrong-password"))
        self.probe("Patient login with SQL text", pl(awpid="' OR 1=1 --", password="' OR 1=1 --"))
        self.probe("Patient login with script text", pl(awpid="<script>alert(1)</script>", password="x"))
        self.probe("Patient login with 10,000 characters", pl(awpid="A" * 10000, password="B" * 10000))
        self.probe("Patient login with numbers instead of text", pl(awpid=12345, password=67890))
        self.probe("Patient login with lists instead of text", pl(awpid=["a"], password={"b": 1}))
        self.probe("Staff login with no fields", lambda: self.req(StaffLoginView, "post", {}))
        self.probe("Staff login with a wrong password", lambda: self.req(StaffLoginView, "post", {"hospital_code": "probe-h2", "email": "dr.p2@example.test", "password": "nope"}))
        self.probe("Staff login to a hospital that does not exist", lambda: self.req(StaffLoginView, "post", {"hospital_code": "nope", "email": "a@b.co", "password": "nope"}))
        self.probe("Platform login with a wrong password", lambda: self.req(PlatformLoginView, "post", {"email": "a@b.co", "password": "nope"}))
        self.probe("OTP request with no number", lambda: self.req(OTPRequestView, "post", {}))
        self.probe("OTP request for an unknown number", lambda: self.req(OTPRequestView, "post", {"purpose": "patient_login", "mobile": "9000099999"}))
        self.probe("OTP verify with no code", lambda: self.req(OTPVerifyView, "post", {}))
        self.probe("OTP verify with a wrong code", lambda: self.req(OTPVerifyView, "post", {"purpose": "patient_login", "mobile": "9111111111", "code": "000000"}))
        codes = []
        for _ in range(14):
            r = self.req(PatientLoginView, "post", {"awpid": "AW-ME", "password": "bad-guess"})
            codes.append(r.status_code)
        RESULTS["Patient login 14 wrong guesses in a row"] = {"status": codes[-1], "body": str(codes)}

    # bad input on lists and writes
    def test_bad_input(self):
        from apps.hospital_patients.views import PatientSearchView
        from apps.opd.views import AppointmentListCreateView, AppointmentStatusView, PrescriptionCreateView
        from apps.billing.views import InvoiceListCreateView, PaymentCreateView
        F = dict(role="front_desk")
        self.probe("Wrong method: DELETE on payments", lambda: self.req(PaymentCreateView, "delete", **F))
        self.probe("Wrong method: PUT on appointments", lambda: self.req(AppointmentListCreateView, "put", {}, **F))
        self.probe("Wrong method: GET on appointment status", lambda: self.req(AppointmentStatusView, "get", kwargs={"pk": "00000000-0000-0000-0000-000000000000"}, **F))
        self.probe("Appointments page 0", lambda: self.req(AppointmentListCreateView, "get", query={"page": 0}, **F))
        self.probe("Appointments page -1", lambda: self.req(AppointmentListCreateView, "get", query={"page": -1}, **F))
        self.probe("Appointments page 'abc'", lambda: self.req(AppointmentListCreateView, "get", query={"page": "abc"}, **F))
        self.probe("Appointments page size 100000", lambda: self.req(AppointmentListCreateView, "get", query={"page_size": 100000}, **F))
        self.probe("Appointments filtered by a bad date", lambda: self.req(AppointmentListCreateView, "get", query={"date": "not-a-date"}, **F))
        self.probe("Invoices page size 100000", lambda: self.req(InvoiceListCreateView, "get", query={"page_size": 100000}, **F))
        self.probe("Invoices with a bad date range", lambda: self.req(InvoiceListCreateView, "get", query={"date_from": "2026-12-31", "date_to": "2026-01-01"}, **F))
        self.probe("Patient search with 10,000 characters", lambda: self.req(PatientSearchView, "get", query={"q": "a" * 10000}, **F))
        self.probe("Patient search with symbols", lambda: self.req(PatientSearchView, "get", query={"q": "%'\";--<script>"}, **F))
        self.probe("Patient search with one character", lambda: self.req(PatientSearchView, "get", query={"q": "a"}, **F))
        self.probe("Appointment create with extra fields", lambda: self.req(AppointmentListCreateView, "post", {"patient_id": 1, "doctor_id": self.doctor.pk, "status": "done", "role": "admin"}, **F))
        self.probe("Appointment create with a list body", lambda: self.req(AppointmentListCreateView, "post", [1, 2, 3], **F))
        self.probe("Prescription create with an empty body", lambda: self.req(PrescriptionCreateView, "post", {}, role="doctor"))
