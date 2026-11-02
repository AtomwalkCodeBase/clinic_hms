"""core/tests/tests_destructive_probe4.py — fourth batch of probes for docs/Destructive_Test_Results.xlsx: the cases no earlier probe tried.
Every result is stored under the case number ("No." column) and goes to the file named by PROBE_OUT4."""

import datetime as dt
import importlib
import json
import os
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.db import transaction
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from core.api.authentication import MockUser
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff, requires_hospital_db

RESULTS = {}
MODULES = ("opd", "billing", "patients", "staff", "facility", "reports", "compliance")
VIEW_MODULES = ("apps.opd.views", "apps.billing.views", "apps.patients.views", "apps.hospital_patients.views", "apps.hospital_setup.staff_views",
                "apps.hospital_setup.facility_views", "apps.hospital_setup.compliance_views", "apps.documents.views", "apps.documents.views_timeline",
                "apps.hospital_master.platform_views", "apps.hospital_master.classification_rule_views", "core.auth.views", "core.auth.otp_views")


def V(name):
    for m in VIEW_MODULES:
        mod = importlib.import_module(m)
        if hasattr(mod, name):
            return getattr(mod, name)
    raise ImportError(name)


@requires_hospital_db
class DestructiveProbes4(HospitalDBTestCase):
    @classmethod
    def tearDownClass(cls):
        out = os.environ.get("PROBE_OUT4")
        if out:
            with open(out, "w", encoding="utf8") as f:
                json.dump(RESULTS, f, indent=1, sort_keys=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from apps.hospital_master.models import Hospital, HospitalParameters, Subscription
        from apps.hospital_setup.models import NextNumber
        from apps.patients.models import Patient
        cache.clear()
        db = self.hospital_alias
        self.hospital = Hospital.objects.using("default").create(name="Probe H4", hospital_code="probe-h4", db_name=db)
        HospitalParameters.objects.using("default").create(hospital=self.hospital, default_tax_rate=Decimal("0"))
        Subscription.objects.using("default").create(hospital=self.hospital, license_tier="enterprise", status="active", feat_patient_app=True,
                                                     max_branches=50, max_doctors=50, max_staff=50)
        self.branch, self.place = make_branch(db)
        self.doctor = make_staff(db, "doctor", email="dr.p4@example.test", phone="9000000081", place=self.place)
        self.doctor2 = make_staff(db, "doctor", email="dr.p4b@example.test", phone="9000000082", place=self.place)
        self.admin = make_staff(db, "hospital_admin", email="adm.p4@example.test", phone="9000000083", place=self.place)
        self.nurse = make_staff(db, "nurse", email="nu.p4@example.test", phone="9000000084", place=self.place)
        self.front = make_staff(db, "front_desk", email="fd.p4@example.test", phone="9000000085", place=self.place)
        self.me = Patient.objects.using("default").create(awpid="AW-4ME", full_name="Me Four", mobile="9444444431", password="x",
                                                          date_of_birth="2015-01-01", email="me4@example.test")
        self.other = Patient.objects.using("default").create(awpid="AW-4OT", full_name="Other Four", mobile="9444444432", password="x",
                                                             date_of_birth="2016-01-01")
        from apps.patients.services import set_password
        for acct in (self.me, self.other):
            set_password(acct, "Pass#1234")
            acct.save(using="default", update_fields=["password"])
        self.hp = make_patient(db, "AW-4ME", uhid="U4ME", branch=self.branch, full_name="Me Four")
        self.hp_other = make_patient(db, "AW-4OT", uhid="U4OT", branch=self.branch, full_name="Other Four")
        NextNumber.objects.using(db).create(branch_id=self.branch.pk, entity="invoice", prefix="INV-")

    # ---- helpers
    def req(self, view, method, data=None, *, role=None, uid=None, awpid=None, kwargs=None, query=None, fmt="json", platform=False):
        factory = APIRequestFactory()
        request = factory.get("/x/", query or data or {}) if method == "get" else getattr(factory, method)("/x/", data or {}, format=fmt)
        if role:
            user = MockUser({"user_id": uid or self.admin.pk, "role": role, "hospital_id": self.hospital.pk, "awpid": awpid, "is_platform": platform})
            user.subscription = SimpleNamespace(**{f: True for f in MODULES})
            force_authenticate(request, user=user)
        request.hospital_db = self.hospital_alias
        request.hospital_id = self.hospital.pk
        return view.as_view()(request, **(kwargs or {}))

    def P(self, view, method, data=None, **kw):
        return self.req(view, method, data, role="patient", uid=self.me.pk, awpid="AW-4ME", **kw)

    def A(self, view, method, data=None, **kw):
        return self.req(view, method, data, role="hospital_admin", uid=self.admin.pk, **kw)

    def D(self, view, method, data=None, **kw):
        return self.req(view, method, data, role="doctor", uid=self.doctor.pk, **kw)

    def F(self, view, method, data=None, **kw):
        return self.req(view, method, data, role="front_desk", uid=self.front.pk, **kw)

    def N(self, view, method, data=None, **kw):
        return self.req(view, method, data, role="nurse", uid=self.nurse.pk, **kw)

    def PL(self, view, method, data=None, **kw):
        return self.req(view, method, data, role="platform_admin", uid=1, platform=True, **kw)

    def probe(self, no, fn, sub=""):
        key = f"{no}{sub}"
        try:
            with transaction.atomic(using="default"), transaction.atomic(using=self.hospital_alias):
                r = fn()
            body = r.data if hasattr(r, "data") and r.data is not None else ""
            RESULTS[key] = {"status": r.status_code, "body": str(body)[:300]}
        except Exception as e:
            RESULTS[key] = {"status": "EXCEPTION", "body": f"{type(e).__name__}: {str(e)[:200]}"}

    def note(self, no, status, body="", sub=""):
        RESULTS[f"{no}{sub}"] = {"status": status, "body": str(body)[:300]}

    def appt(self, **kw):
        from apps.opd.models import Appointment
        kw.setdefault("scheduled_date", dt.date.today())
        kw.setdefault("patient", self.hp)
        kw.setdefault("doctor", self.doctor)
        place = kw.pop("place", self.place)
        return Appointment.objects.using(self.hospital_alias).create(branch_department=place, **kw)

    def tokens_for(self, **payload):
        from core.auth.views import _make_tokens
        return _make_tokens(payload)

    def http(self, access=None):
        c = APIClient(raise_request_exception=False)
        if access:
            c.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return c

    # ===================================================== login, passwords, tokens
    def test_auth(self):
        from apps.hospital_setup.staff_services import set_login_password
        from core.auth.otp import Purpose, make_action_token
        import jwt
        from django.conf import settings
        set_login_password(self.nurse, "Staff#12345")
        c = self.http()
        r = c.post("/api/v1/auth/login/patient/", {"awpid": "9000000084", "password": "Staff#12345"}, format="json")
        self.note(7, r.status_code, r.content[:200], "a")
        r = c.post("/api/v1/auth/login/patient/", {"awpid": "nu.p4@example.test", "password": "Staff#12345"}, format="json")
        self.note(7, r.status_code, r.content[:200], "b")
        cache.clear()
        r = c.post("/api/v1/auth/login/staff/", {"mobile": "9444444431", "password": "Pass#1234"}, format="json")
        self.note(8, r.status_code, r.content[:200], "a")
        r = c.post("/api/v1/auth/login/platform/", {"username": "AW-4ME", "password": "Pass#1234"}, format="json")
        self.note(8, r.status_code, r.content[:200], "b")
        r = c.post("/api/v1/auth/login/platform/", {"username": "9444444431", "password": "Pass#1234"}, format="json")
        self.note(291, r.status_code, r.content[:200], "a")
        r = c.post("/api/v1/auth/login/platform/", {"username": "dr.p4@example.test", "password": "x"}, format="json")
        self.note(291, r.status_code, r.content[:200], "b")
        # two devices: the password changes on one, the other still holds a token
        cache.clear()
        r1 = c.post("/api/v1/auth/login/patient/", {"mobile": "9444444431", "password": "Pass#1234"}, format="json")
        r2 = c.post("/api/v1/auth/login/patient/", {"mobile": "9444444431", "password": "Pass#1234"}, format="json")
        try:
            d1 = r1.json().get("data") or r1.json()
            d2 = r2.json().get("data") or r2.json()
            a1, a2, ref1 = d1["access"], d2["access"], d1["refresh"]
            ch = self.http(a2).post("/api/v1/portal/profile/change-password/", {"current_password": "Pass#1234", "new_password": "Newer#5678"}, format="json")
            self.note(15, ch.status_code, ch.content[:150], "a")
            me = self.http(a1).get("/api/v1/auth/me/")
            self.note(15, me.status_code, f"old device's access token after the password change: {me.status_code}", "b")
            rf = self.http().post("/api/v1/auth/token/refresh/", {"refresh": ref1}, format="json")
            self.note(15, rf.status_code, f"old device's refresh token after the password change: {rf.status_code}", "c")
        except Exception as e:
            self.note(15, "EXCEPTION", f"{type(e).__name__}: {e}; login bodies {r1.content[:120]}")
        # registration: mobile formats and weak passwords
        cache.clear()
        counter = iter(range(100))
        def tok():
            return make_action_token(Purpose.REGISTRATION_PATIENT, f"newreg{next(counter)}@example.test")
        base = {"full_name": "New Reg", "mobile": "9876500011", "password": "Str0ng!pass", "date_of_birth": "1990-01-01"}
        PR = V("PortalRegisterView")
        for label, extra in [("letters", {"mobile": "abcdefghij"}), ("5 digits", {"mobile": "12345"}), ("20 digits", {"mobile": "1" * 20})]:
            self.probe(22, lambda e=extra: self._register({**base, **e}, tok()), "-" + label)
        for label, pw in [("3 characters", "abc"), ("all digits", "12345678"), ("a common password", "password"), ("same as the mobile", "9876500011")]:
            self.probe(24, lambda p=pw: self._register({**base, "password": p, "mobile": f"98765{abs(hash(p)) % 100000:05d}"}, tok()), "-" + label)
        # forgot password: the same password again, then the same token again
        t = make_action_token(Purpose.PASSWORD_RESET_PATIENT, "9444444431", target_type="patient", target_id=self.me.pk)
        FP = V("PatientForgotPasswordResetView")
        body = lambda pw: {"action_token": t, "new_password": pw, "confirm_password": pw}
        self.probe(27, lambda: self.req(FP, "post", body("Pass#1234")), "-same as the old password")
        self.probe(27, lambda: self.req(FP, "post", body("Second#9999")), "-token used again")
        # setup-password invite link used twice
        invite = jwt.encode({"token_type": "invite", "staff_id": self.nurse.pk, "hospital_db": self.hospital_alias, "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)},
                            settings.JWT_SIGNING_KEY, algorithm="HS256")
        SP = V("SetupPasswordView")
        b = lambda pw: {"invite_token": invite, "new_password": pw, "confirm_password": pw}
        self.probe(30, lambda: self.req(SP, "post", b("FirstPass#1")), "-first use")
        self.probe(30, lambda: self.req(SP, "post", b("SecondPass#2")), "-second use")
        expired = jwt.encode({"token_type": "invite", "staff_id": self.nurse.pk, "hospital_db": self.hospital_alias, "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)},
                             settings.JWT_SIGNING_KEY, algorithm="HS256")
        self.probe(266, lambda: self.req(SP, "post", {"invite_token": expired, "new_password": "ThirdPass#3", "confirm_password": "ThirdPass#3"}), "-expired link")
        self.note(266, RESULTS["30-second use"]["status"], RESULTS["30-second use"]["body"], "-used twice")

    def _register(self, data, token):
        with mock.patch("core.validation.validate_mobile_real", return_value=(True, "")):
            return self.req(V("PortalRegisterView"), "post", {**data, "action_token": token})

    # ===================================================== patient documents
    def test_documents(self):
        from apps.documents.tests.tests import make_doc
        from apps.documents.models import MedicalDocument
        Del, Prev, Zip = V("PortalDocumentDetailView"), V("PortalDocumentPreviewView"), V("PortalDocumentZipView")
        gone = make_doc("AW-4ME", status="failed", error_message="x")
        with mock.patch("core.storage.delete"):
            self.probe(45, lambda: self.P(Del, "delete", kwargs={"doc_id": gone.pk}), "-first delete")
            self.probe(45, lambda: self.P(Del, "delete", kwargs={"doc_id": gone.pk}), "-second delete")
        self.probe(44, lambda: self.P(Prev, "get", kwargs={"doc_id": gone.pk}))
        self.note(73, RESULTS["44"]["status"], "same route the timeline uses: " + RESULTS["44"]["body"])
        self.probe(244, lambda: self.D(V("PatientDocumentDetailView"), "get", kwargs={"doc_id": gone.pk}))
        self.probe(262, lambda: self.req(V("DocumentViewView"), "get", kwargs={"token": "made-up.token.value"}), "-bad code")
        # the view-report code of a document that was removed
        from core import utils as cu
        doc2 = make_doc("AW-4ME", status="completed", document_type="prescription", by="human", name="LAB-4ME-1")
        token = cu.issue_qr_token(doc_type="prescription", public_document_id="LAB-4ME-1", awpid="AW-4ME")
        with mock.patch("core.storage.signed_url", return_value="http://file"):
            self.probe(348, lambda: self.req(V("DocumentViewView"), "get", kwargs={"token": token}), "-code of a real document")
            MedicalDocument.objects.filter(pk=doc2.pk).delete()
            self.probe(262, lambda: self.req(V("DocumentViewView"), "get", kwargs={"token": token}), "-document removed")
        # the qr of a replaced document points to the newest one with that reference
        d3 = make_doc("AW-4ME", status="completed", document_type="prescription", by="human", name="LAB-4ME-2")
        d4 = make_doc("AW-4ME", status="completed", document_type="prescription", by="human", name="LAB-4ME-2")
        t2 = cu.issue_qr_token(doc_type="prescription", public_document_id="LAB-4ME-2", awpid="AW-4ME")
        with mock.patch("core.storage.signed_url", side_effect=lambda name, **k: f"http://file/{name}"):
            r = self.req(V("DocumentViewView"), "get", kwargs={"token": t2})
        self.note(349, r.status_code, f"two documents share the reference; newest is {d4.pk}; answer={str(r.data)[:150]}")
        # a code made for another patient's reference
        t3 = cu.issue_qr_token(doc_type="prescription", public_document_id="LAB-4ME-2", awpid="AW-4OT")
        r = self.req(V("DocumentViewView"), "get", kwargs={"token": t3})
        self.note(347, r.status_code, "code carrying a different patient's id for the same reference: " + str(r.data)[:150])
        # zip with two documents of the same name
        z1 = make_doc("AW-4ME", status="completed", document_type="lab_report", by="human", name="same.pdf")
        z2 = make_doc("AW-4ME", status="completed", document_type="lab_report", by="human", name="same.pdf")
        with mock.patch("core.storage.get_bytes", return_value=b"%PDF-1.4 x"):
            r = self.P(Zip, "post", {"ids": [z1.pk, z2.pk]})
        names = []
        try:
            import io
            import zipfile
            names = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content) if hasattr(r, "streaming_content") else r.content)).namelist()
        except Exception as e:
            names = [f"could not read zip: {type(e).__name__}"]
        self.note(49, r.status_code, f"files inside: {names}")
        # file with a nasty name: stored name is built by the system or taken from the user?
        from apps.documents.lib_documents import display_name
        nasty = make_doc("AW-4ME", status="completed", document_type="lab_report", by="human", name="../../etc/passwd 😀.pdf")
        self.note(37, 200, f"display name = {display_name(nasty)!r}; stored key = {nasty.file_name.name!r}")
        # upload route with odd files (storage and the reader are mocked: only the route is under test)
        from django.core.files.uploadedfile import SimpleUploadedFile
        UV = V("UploadView")
        for no, label, name, content in [(37, "emoji and ../../ in the name", "../../x 😀.pdf", b"%PDF-1.4 hello"),
                                         (38, "password-protected PDF", "locked.pdf", b"%PDF-1.6\n1 0 obj<</Encrypt 2 0 R>>endobj\n%%EOF"),
                                         (39, "truncated JPG", "cut.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF"), (39, "corrupted PDF", "bad.pdf", b"%PDF-1.4 \x00\x01\x02 not a pdf")]:
            with mock.patch("apps.documents.views.save_upload") as su, mock.patch("apps.documents.views.start_processing"):
                su.return_value = (SimpleNamespace(pk=1, b_documents=SimpleNamespace(order_by=lambda *a: [])), [])
                self.probe(no, lambda n=name, c=content: self.P(UV, "post", {"files": SimpleUploadedFile(n, c), "mode": "instant"}, fmt="multipart"), "-" + label)

    # ===================================================== growth, vaccination, timeline
    def test_timeline(self):
        GV, IV = V("PatientGrowthView"), V("PatientImmunizationView")
        today = dt.date.today()
        k = {"awpid": "AW-4ME"}
        self.probe(61, lambda: self.D(GV, "post", {"measured_on": str(today), "height_cm": "900"}, kwargs=k), "-height 900")
        self.probe(61, lambda: self.D(GV, "post", {"measured_on": str(today), "weight_kg": "-3"}, kwargs=k), "-weight -3")
        self.probe(62, lambda: self.D(GV, "post", {"measured_on": str(today + dt.timedelta(days=5)), "weight_kg": "10"}, kwargs=k))
        self.probe(63, lambda: self.D(GV, "post", {"measured_on": str(today), "weight_kg": "17"}, kwargs=k), "-add one point")
        self.probe(63, lambda: self.P(GV, "get", query={"indicator": "weight_kg"}, kwargs=k), "-chart with one point")
        self.probe(66, lambda: self.D(IV, "post", {"vaccine_text": "BCG", "given_on": str(today + dt.timedelta(days=3))}, kwargs=k))
        self.probe(67, lambda: self.D(IV, "post", {"vaccine_text": "BCG", "given_on": str(today)}, kwargs=k), "-first")
        self.probe(67, lambda: self.D(IV, "post", {"vaccine_text": "BCG", "given_on": str(today)}, kwargs=k), "-again")
        self.probe(67, lambda: self.P(IV, "get", kwargs=k), "-schedule after")
        from apps.documents.models import ImmunizationRecord
        n = ImmunizationRecord.objects.using("default").filter(patient__awpid="AW-4ME", vaccine_name="BCG").count()
        self.note(67, 200, f"BCG rows stored for that date after recording twice: {n}", "-count")
        # vaccination upload from the portal
        VU = V("PortalVaccinationUploadView")
        good = "data:application/pdf;base64,JVBERi0xLjQ="
        with mock.patch("core.storage.upload_data_uri", return_value="vaccination-certs/x.pdf"):
            self.probe(68, lambda: self.P(VU, "post", {"vaccine_name": "BCG", "administered_date": str(today), "file_data": "data:text/plain;base64,aGk="}), "-wrong type")
            self.probe(68, lambda: self.P(VU, "post", {"vaccine_name": "BCG", "administered_date": str(today), "file_data": "data:application/pdf;base64," + "A" * 16_000_000}), "-over size")
            self.probe(68, lambda: self.P(VU, "post", {"vaccine_name": "BCG", "administered_date": str(today), "file_data": "data:application/pdf;base64,"}), "-empty file")
            self.probe(66, lambda: self.P(VU, "post", {"vaccine_name": "BCG", "administered_date": str(today + dt.timedelta(days=9))}), "-portal upload future date")
        # a certificate of another patient fetched by record id
        rec = ImmunizationRecord.objects.using("default").create(patient=self.other, vaccine_name="MMR", administered_date=today, source="self_reported",
                                                                verification_status="pending_review")
        self.probe(69, lambda: self.P(V("PortalVaccinationFileView"), "get", kwargs={"record_id": rec.pk}))
        # a removed family member
        PF, PD = V("PortalFamilyListCreateView"), V("PortalFamilyDetailView")
        add = self.P(PF, "post", {"full_name": "Kid One", "date_of_birth": "2020-05-05", "gender": "male", "relationship": "child"})
        self.note(105, add.status_code, str(add.data)[:200], "-first add")
        self.probe(105, lambda: self.P(PF, "post", {"full_name": "Kid One", "date_of_birth": "2020-05-05", "gender": "male", "relationship": "child"}), "-again")
        fam_awpid = ((add.data or {}).get("data") or {}).get("awpid") if isinstance(add.data, dict) else None
        self.note(105, 200, f"new member awpid={fam_awpid}", "-awpid")
        self.probe(107, lambda: self.P(PF, "post", {"full_name": "Older Kid", "date_of_birth": "1980-01-01", "relationship": "child"}), "-dependent older than parent")
        self.probe(107, lambda: self.P(PF, "post", {"full_name": "Same Day", "date_of_birth": "2015-01-01", "relationship": "child"}), "-same birth date as parent")
        if fam_awpid:
            ape = self.appt(patient=self.hp)  # a booking exists for the parent (the child has no hospital row yet)
            self.probe(108, lambda: self.P(PD, "delete", kwargs={"awpid": fam_awpid}))
            self.probe(70, lambda: self.P(V("PatientHealthTimelineView"), "get", kwargs={"awpid": fam_awpid}), "-removed member's timeline")
            self.probe(109, lambda: self.P(V("PortalDocumentListCreateView"), "get", query={"patient_awpid": fam_awpid}), "-removed member's records")

    # ===================================================== booking and notifications
    def test_booking(self):
        from apps.patients.models import PatientBooking
        from apps.opd.models import Appointment
        db = self.hospital_alias
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        a1 = self.appt(scheduled_date=tomorrow, scheduled_time="10:00", status="scheduled")
        a2 = self.appt(scheduled_date=tomorrow, scheduled_time="10:30", status="scheduled", patient=self.hp_other)
        mk = lambda a, who: PatientBooking.objects.using("default").create(hospital=self.hospital, appointment_id=a.pk, booked_by=who, scheduled_date=tomorrow, status="scheduled") if _has(PatientBooking) else None
        def _has(m):
            return True
        try:
            b1 = mk(a1, self.me)
            b2 = mk(a2, self.other)
        except Exception as e:
            self.note(83, "EXCEPTION", f"could not create bookings: {type(e).__name__}: {e}")
            return
        Can, Res = V("PortalCancelBookingView"), V("PortalRescheduleBookingView")
        self.probe(83, lambda: self.P(Can, "post", kwargs={"pk": b2.pk}))
        self.probe(84, lambda: self.P(Res, "post", {"scheduled_date": str(tomorrow), "scheduled_time": "10:30"}, kwargs={"pk": b1.pk}))
        Appointment.objects.using(db).filter(pk=a1.pk).update(status="in_progress")
        self.probe(86, lambda: self.P(Res, "post", {"scheduled_date": str(tomorrow), "scheduled_time": "11:00"}, kwargs={"pk": b1.pk}))
        Appointment.objects.using(db).filter(pk=a1.pk).update(status="scheduled")
        nt = V("PortalNextTokenView")
        d_lone = make_staff(db, "doctor", email="lone.p4@example.test", phone="9000000086")
        self.probe(88, lambda: self.P(nt, "get", kwargs={"hospital_id": self.hospital.pk, "doctor_id": d_lone.pk}, query={"date": str(tomorrow)}), "-doctor without a schedule")
        self.probe(88, lambda: self.P(nt, "get", kwargs={"hospital_id": self.hospital.pk, "doctor_id": 99999}, query={"date": str(tomorrow)}), "-doctor that does not exist")
        self.probe(90, lambda: self.P(V("PortalSlotListView"), "get", kwargs={"hospital_id": self.hospital.pk, "doctor_id": d_lone.pk}, query={"date": str(tomorrow)}), "-doctor with no slots")
        self.probe(90, lambda: self.P(V("PortalDoctorListView"), "get", kwargs={"hospital_id": self.hospital.pk}, query={"specialty": "nothing-matches-this"}), "-no doctors match")
        # notifications
        from apps.hospital_setup.models import NotificationLog
        try:
            log = NotificationLog.objects.using(db).create(patient=self.hp, channel="in_app", body="Reminder", reference="appt_reminder:1")
            NM = V("PortalNotificationMarkReadView")
            k = {"hospital_db": db, "pk": log.pk}
            self.probe(93, lambda: self.P(NM, "post", kwargs=k), "-first")
            self.probe(93, lambda: self.P(NM, "post", kwargs=k), "-second")
            log2 = NotificationLog.objects.using(db).create(patient=self.hp_other, channel="in_app", body="Not mine", reference="appt_reminder:2")
            self.probe(94, lambda: self.P(NM, "post", kwargs={"hospital_db": db, "pk": log2.pk}))
            log3 = NotificationLog.objects.using(db).create(patient=self.hp, channel="in_app", body="Reminder for a gone booking", reference="appt_reminder:99999")
            self.probe(95, lambda: self.P(V("PortalNotificationsView"), "get"), "-list")
            self.probe(95, lambda: self.P(NM, "post", kwargs={"hospital_db": db, "pk": log3.pk}), "-mark")
        except Exception as e:
            self.note(93, "EXCEPTION", f"{type(e).__name__}: {e}")

    # ===================================================== profile, corrections, privacy, photo
    def test_profile(self):
        PP = V("PortalProfileView")
        for label, data in [("wrong type", "data:text/plain;base64,aGk="), ("not an image", "data:image/png;base64,bm90IGFuIGltYWdl"), ("over size", "data:image/png;base64," + "A" * 20_000_000), ("empty", "")]:
            with mock.patch("core.storage.upload_data_uri", return_value="photos/x.png"):
                self.probe(100, lambda d=data: self.P(PP, "patch", {"photo": d}), "-" + label)
        AM = V("PortalRecordAmendmentView")
        mk = lambda **d: {"hospital_id": self.hospital.pk, **d}
        self.probe(110, lambda: self.P(AM, "post", mk()), "-nothing sent")
        self.probe(110, lambda: self.P(AM, "post", mk(field_name="", details="", reason="")), "-blank")
        r = self.P(AM, "post", mk(field_name="full_name", requested_value="Me Fourth", reason="spelling"))
        self.note(111, r.status_code, str(r.data)[:240], "-control with guessed fields")
        self.probe(113, lambda: self.P(AM, "post", mk(patient_awpid="AW-4OT", field_name="full_name", requested_value="X", reason="x")), "-someone else's record")
        # the amendment model fields, to build a real one for the resolve probes
        from apps.hospital_setup.models import RecordAmendment
        fields = [f.name for f in RecordAmendment._meta.get_fields() if getattr(f, "concrete", False)]
        self.note(111, 200, f"RecordAmendment fields: {fields}", "-fields")
        try:
            row = RecordAmendment.objects.using(self.hospital_alias).create(patient=self.hp, **{k: v for k, v in {"field_name": "full_name", "requested_value": "X", "current_value": "Y", "reason": "r", "details": "d", "status": "pending"}.items() if k in fields})
        except Exception as e:
            self.note(286, "EXCEPTION", f"could not build an amendment: {type(e).__name__}: {e}")
            return
        RS = V("RecordAmendmentResolveView")
        self.probe(112, lambda: self.P(AM, "post", mk(field_name="full_name", requested_value="Z", reason="again")), "-new one after")
        self.probe(286, lambda: self.A(RS, "post", {"status": "approved", "review_notes": "ok"}, kwargs={"pk": row.pk}), "-first resolve")
        self.probe(286, lambda: self.A(RS, "post", {"status": "rejected", "review_notes": "again"}, kwargs={"pk": row.pk}), "-second resolve")
        row2 = RecordAmendment.objects.using(self.hospital_alias).create(patient=self.hp, **{k: v for k, v in {"field_name": "full_name", "requested_value": "X", "current_value": "Y", "reason": "r", "details": "d", "status": "pending"}.items() if k in fields})
        self.probe(287, lambda: self.N(RS, "post", {"status": "approved"}, kwargs={"pk": row2.pk}), "-nurse")
        self.probe(287, lambda: self.F(RS, "post", {"status": "approved"}, kwargs={"pk": row2.pk}), "-front desk")
        self.probe(287, lambda: self.D(RS, "post", {"status": "approved"}, kwargs={"pk": row2.pk}), "-doctor")
        self.probe(287, lambda: self.A(RS, "post", {"status": "nonsense"}, kwargs={"pk": row2.pk}), "-bad status")
        self.probe(371, lambda: self.A(V("AuditLogListView"), "get", query={"page_size": 200}), "-audit log")
        # privacy toggle
        from apps.documents.tests.tests import make_doc
        doc = make_doc("AW-4ME", status="completed", document_type="lab_report", by="human")
        PT = V("RecordsPrivacyToggleView")
        self.probe(119, lambda: self.P(PT, "post", {"doc_id": doc.pk, "private": True}), "-hide")
        self.probe(119, lambda: self.P(PT, "post", {"doc_id": doc.pk, "private": True}), "-hide again")
        self.probe(119, lambda: self.P(PT, "post", {"doc_id": 99999, "private": True}), "-not in my records")
        self.probe(119, lambda: self.P(PT, "post", {"doc_id": "abc"}), "-doc id as text")

    # ===================================================== consult pad, shares
    def test_consult_pad(self):
        from apps.opd.models import ConsultSession
        CP = V("ConsultPadView")
        fields = [f.name for f in ConsultSession._meta.get_fields() if getattr(f, "concrete", False)]
        self.note(132, 200, f"ConsultSession fields: {fields}", "-fields")
        for tok in ("not-a-token", "A" * 64, "x" * 5000):
            self.probe(132, lambda t=tok: self.req(CP, "get", kwargs={"token": t}), f"-token {len(tok)} chars")
        self.probe(135, lambda: self.req(CP, "post", {"text": "T" * 5_000_000}, kwargs={"token": "A" * 64}), "-5 MB of text to a bad token")
        r = self.http().post("/api/v1/consult-pad/" + "A" * 64 + "/", {"text": "T" * 5_000_000}, format="json")
        self.note(135, r.status_code, "HTTP, 5 MB of text to the pad: " + str(r.content[:120]), "-http")

    # ===================================================== front desk, patients
    def test_front_desk(self):
        PL, PA = V("PatientLookupView"), V("PatientAttachNetworkView")
        self.probe(142, lambda: self.F(PL, "get", query={"mobile": "9000099999"}), "-number nobody has")
        self.probe(142, lambda: self.F(PL, "get", query={"mobile": "9444444432"}), "-number of a network patient not in this hospital yet")
        from apps.hospital_patients.models import HospitalPatient
        from apps.patients.models import Patient as _P
        _P.objects.using("default").create(awpid="AW-4NW", full_name="Network Only", mobile="9444444433", date_of_birth="1990-01-01")
        self.probe(142, lambda: self.F(PL, "get", query={"mobile": "9444444433"}), "-network patient with no row here")
        body = {"mobile": "9444444433", "branch_id": self.branch.pk}
        self.probe(143, lambda: self.F(PA, "post", body), "-first")
        self.probe(143, lambda: self.F(PA, "post", body), "-second")
        n = HospitalPatient.objects.using(self.hospital_alias).filter(awpid="AW-4NW").count()
        self.note(143, 200, f"hospital rows for that patient after attaching twice: {n}", "-count")
        BH = V("BirthHistoryView")
        pk = self.hp.pk
        self.probe(146, lambda: self.D(BH, "post", {"gestational_age_weeks": 80, "birth_weight_kg": "50", "delivery_mode": "normal"}, kwargs={"pk": pk}), "-80 weeks, 50 kg")
        self.probe(146, lambda: self.D(BH, "post", {"gestational_age_weeks": -2, "birth_weight_kg": "-1", "delivery_mode": "normal"}, kwargs={"pk": pk}), "-negative values")
        self.probe(146, lambda: self.D(BH, "post", {"gestational_age_weeks": 38, "birth_weight_kg": "3.1", "delivery_mode": "normal", "nicu_admission": False, "nicu_days": 9}, kwargs={"pk": pk}), "-NICU days without NICU")
        FT = V("PatientFamilyTreeView")
        self.probe(149, lambda: self.F(FT, "get", query={"patient_id": pk}), "-tree of one patient")
        # a loop: A guardian of B and B guardian of A
        from apps.patients.models import PatientRelationship
        try:
            PatientRelationship.objects.using("default").create(guardian=self.me, dependent=self.other, relationship="child")
            PatientRelationship.objects.using("default").create(guardian=self.other, dependent=self.me, relationship="child")
            self.probe(149, lambda: self.F(FT, "get", query={"patient_id": pk}), "-tree with a loop")
        except Exception as e:
            self.note(149, "EXCEPTION", f"{type(e).__name__}: {e}", "-loop")
        # appointment types
        AT, ATD = V("AppointmentTypeListCreateView"), V("AppointmentTypeDetailView")
        self.probe(165, lambda: self.A(AT, "post", {"name": "Telehealth"}), "-control")
        self.probe(165, lambda: self.A(AT, "post", {"name": "Telehealth"}), "-duplicate name")
        # a type in use
        c = self.A(AT, "post", {"name": "InUse"})
        opt = (c.data or {}).get("data") or c.data or {}
        oid = opt.get("option_list_id") or opt.get("id")
        if oid:
            self.appt(appointment_type="inuse", status="scheduled")
            self.probe(165, lambda: self.A(ATD, "delete", kwargs={"pk": oid}), "-delete one in use")
        else:
            self.note(165, "n/a", f"could not create a type: {str(c.data)[:150]}", "-delete one in use")
        # reschedule into a full slot and detail of an id that is not here
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        a1 = self.appt(scheduled_date=tomorrow, scheduled_time="09:00", status="scheduled")
        a2 = self.appt(scheduled_date=tomorrow, scheduled_time="09:30", status="scheduled", patient=self.hp_other)
        self.probe(161, lambda: self.F(V("AppointmentRescheduleView"), "post", {"scheduled_date": str(tomorrow), "scheduled_time": "09:30"}, kwargs={"pk": a1.pk}))
        self.probe(164, lambda: self.F(V("AppointmentDetailView"), "get", kwargs={"pk": "11111111-1111-1111-1111-111111111111"}))
        # follow-up marked booked twice
        from apps.opd.models import OPDEncounter
        a3 = self.appt(status="waiting")
        e = self.D(V("EncounterCreateView"), "post", {"appointment_id": str(a3.pk)})
        enc = OPDEncounter.objects.using(self.hospital_alias).get(appointment=a3)
        FU = V("FollowUpActionView")
        self.probe(170, lambda: self.D(FU, "post", {"mode": "book", "days": 5}, kwargs={"pk": enc.pk}), "-ask for a follow-up")
        MB = V("FollowupMarkBookedView")
        self.probe(170, lambda: self.F(MB, "post", kwargs={"pk": enc.pk}), "-mark booked")
        self.probe(170, lambda: self.F(MB, "post", kwargs={"pk": enc.pk}), "-mark booked again")
        self.probe(210, lambda: self.N(V("FollowupNurseWorklistView"), "get"), "-worklist")
        self.probe(210, lambda: self.N(MB, "post", kwargs={"pk": enc.pk}), "-nurse marks booked again")

    # ===================================================== billing
    def test_billing(self):
        from apps.billing.models import Invoice
        db = self.hospital_alias
        inv = Invoice.objects.using(db).create(patient=self.hp, branch=self.branch, invoice_number="I-P4", status="issued")
        BS, BSD = V("BillingServiceListView"), V("BillingServiceDetailView")
        c = self.A(BS, "post", {"name": "Dressing", "code": "DR1", "unit_price": "50"})
        sid = ((c.data or {}).get("data") or c.data or {}).get("id") or ((c.data or {}).get("data") or {}).get("billing_item_id") if isinstance(c.data, dict) else None
        self.note(182, c.status_code, str(c.data)[:200], "-service create")
        sk = {"pk": sid} if sid else None
        if sk:
            self.A(BSD, "patch", {"is_active": False}, kwargs=sk)
            self.probe(182, lambda: self.A(V("InvoiceItemCreateView"), "post", {"billing_item": sid, "quantity": 1}, kwargs={"pk": inv.pk}), "-add an inactive service")
        SC, SCD = V("ServiceCategoryListCreateView"), V("ServiceCategoryDetailView")
        cat = self.A(SC, "post", {"name": "Procedures", "label": "Procedures", "value": "procedures"})
        cd = (cat.data or {}).get("data") or cat.data or {}
        cid = cd.get("id") or cd.get("option_list_id")
        self.note(190, cat.status_code, str(cat.data)[:200], "-category create")
        if cid:
            self.A(BS, "post", {"name": "Suture", "code": "SU1", "unit_price": "80", "category": "procedures"})
            self.probe(190, lambda: self.A(SCD, "delete", kwargs={"pk": cid}), "-delete category with a service")
        PM, PMD = V("PaymentModeListCreateView"), V("PaymentModeDetailView")
        pm = self.A(PM, "post", {"name": "Card", "label": "Card", "value": "card"})
        pd_ = (pm.data or {}).get("data") or pm.data or {}
        pid = pd_.get("id") or pd_.get("option_list_id")
        self.note(191, pm.status_code, str(pm.data)[:200], "-mode create")
        if pid:
            self.A(V("PaymentCreateView"), "post", {"invoice": inv.pk, "amount": "10", "payment_mode": "card"})
            self.probe(191, lambda: self.A(PMD, "delete", kwargs={"pk": pid}), "-delete a mode already used")
            self.A(PMD, "patch", {"is_active": False}, kwargs={"pk": pid})
            self.probe(182, lambda: self.A(V("PaymentCreateView"), "post", {"invoice": inv.pk, "amount": "5", "payment_mode": "card"}), "-pay with an inactive mode")
        self.probe(182, lambda: self.A(V("PaymentCreateView"), "post", {"invoice": inv.pk, "amount": "5", "payment_mode": "does-not-exist"}), "-pay with a mode that does not exist")
        # another hospital's patient and invoice
        self.probe(183, lambda: self.A(V("InvoiceListCreateView"), "post", {"patient_id": 99999, "branch_id": self.branch.pk}), "-patient not at this hospital")
        self.probe(184, lambda: self.A(V("InvoiceDetailView"), "get", kwargs={"pk": 99999}), "-detail")
        self.probe(184, lambda: self.A(V("InvoicePDFView"), "get", kwargs={"pk": 99999}), "-pdf")
        # reports permission: billing but not reports
        req = APIRequestFactory().get("/x/")
        user = MockUser({"user_id": self.admin.pk, "role": "hospital_admin", "hospital_id": self.hospital.pk})
        user.subscription = SimpleNamespace(billing=True, reports=False, opd=True, patients=True, staff=True, facility=True, compliance=True)
        force_authenticate(req, user=user)
        req.hospital_db, req.hospital_id = db, self.hospital.pk
        try:
            r = V("RevenueReportView").as_view()(req)
            self.note(196, r.status_code, str(getattr(r, "data", ""))[:200])
        except Exception as e:
            self.note(196, "EXCEPTION", f"{type(e).__name__}: {e}")
        r = self.http().get("/api/v1/billing/reports/revenue/")
        self.note(196, r.status_code, "HTTP without a token: " + str(r.content[:100]), "-http")

    # ===================================================== nurse and doctor
    def test_clinical(self):
        from apps.opd.models import OPDEncounter
        V_ = V("VitalsView")
        self.probe(205, lambda: self.N(V_, "post", {"temperature_c": "37"}, kwargs={"pk": "11111111-1111-1111-1111-111111111111"}))
        self.probe(209, lambda: self.N(V("MonitoringListView"), "get"), "-monitoring")
        self.probe(209, lambda: self.N(V("FollowupNurseWorklistView"), "get"), "-worklist")
        self.probe(212, lambda: self.D(V("OPDStatsView"), "get"), "-stats")
        self.probe(212, lambda: self.D(V("AppointmentListCreateView"), "get"), "-list")
        self.probe(214, lambda: self.D(V("PatientDetailView"), "get", kwargs={"pk": 99999}), "-patient that does not exist")
        # branch A / branch B
        branch_b, place_b = make_branch(self.hospital_alias, name="Branch B")
        other_doc = make_staff(self.hospital_alias, "doctor", email="drb.p4@example.test", phone="9000000087", place=place_b)
        ab = self.appt(doctor=other_doc, status="waiting", place=place_b)
        self.probe(217, lambda: self.D(V("AppointmentDetailView"), "get", kwargs={"pk": ab.pk}), "-another doctor's appointment")
        self.probe(217, lambda: self.D(V("EncounterCreateView"), "post", {"appointment_id": str(ab.pk)}), "-start an encounter on it")
        self.probe(217, lambda: self.D(V("AppointmentListCreateView"), "get", query={"branch_id": branch_b.pk}), "-queue of branch B")
        # doctor profile
        DP = V("MyDoctorProfileView")
        for label, data in [("registration number with symbols", {"registration_number": "!!@@##"}), ("10,000-character bio", {"bio": "B" * 10000}),
                            ("negative experience", {"experience_years": -5}), ("photo of the wrong type", {"photo": "data:text/plain;base64,aGk="})]:
            self.probe(218, lambda d=data: self.req(DP, "patch", d, role="doctor", uid=self.doctor.pk), "-" + label)
        # schedule
        DS = V("DoctorScheduleView")
        k = {"pk": self.doctor.pk}
        win = lambda *d: {"slot_duration_minutes": 15, "days": [{"day_of_week": x, "is_available": True, "start_time": s, "end_time": e} for x, s, e in d]}
        self.probe(219, lambda: self.A(DS, "put", win((0, "09:00", "13:00"), (0, "11:00", "15:00")), kwargs=k), "-two windows on one day")
        self.probe(220, lambda: self.A(DS, "put", win((1, "17:00", "09:00")), kwargs=k), "-end before start")
        self.probe(220, lambda: self.A(DS, "put", win((1, "09:00", "25:00")), kwargs=k), "-25:00")
        self.probe(220, lambda: self.A(DS, "put", {"slot_duration_minutes": 0, "days": []}, kwargs=k), "-slot length 0")
        self.probe(220, lambda: self.A(DS, "put", {"slot_duration_minutes": 100000, "days": []}, kwargs=k), "-slot length 100000")
        self.probe(220, lambda: self.A(DS, "put", win((9, "09:00", "10:00")), kwargs=k), "-day 9")
        self.probe(77, lambda: self.A(DS, "put", win((1, "09:00", "10:00")), kwargs=k), "-valid control")
        # encounter
        a = self.appt(status="waiting")
        self.D(V("EncounterCreateView"), "post", {"appointment_id": str(a.pk)})
        enc = OPDEncounter.objects.using(self.hospital_alias).get(appointment=a)
        self.probe(243, lambda: self.D(V("PreviousEncounterView"), "get", kwargs={"pk": "11111111-1111-1111-1111-111111111111"}), "-id that does not exist")
        self.probe(243, lambda: self.req(V("PreviousEncounterView"), "get", role="doctor", uid=self.doctor2.pk, kwargs={"pk": enc.pk}), "-another doctor's encounter")
        self.probe(246, lambda: self.D(V("PatientClinicalSummaryView"), "get", kwargs={"awpid": "AW-4ME"}), "-patient with no history")
        self.probe(246, lambda: self.D(V("PatientClinicalSummaryView"), "get", kwargs={"awpid": "AW-NOPE"}), "-patient that does not exist")

    # ===================================================== documents admin, platform
    def test_platform(self):
        from apps.documents.tests.tests import make_doc
        doc = make_doc("AW-4ME", status="completed", document_type="lab_report", by="rules")
        DC, RC, DR = V("DocumentCorrectView"), V("ReclassifyView"), V("DocumentReportView")
        self.probe(248, lambda: self.PL(DC, "patch", {"doc_type": "not_a_type"}, kwargs={"pk": doc.pk}), "-unknown type")
        self.probe(249, lambda: self.A(RC, "post"), "-hospital admin")
        self.probe(249, lambda: self.D(DC, "patch", {"doc_type": "prescription"}, kwargs={"pk": doc.pk}), "-doctor corrects")
        self.probe(250, lambda: self.P(V("PortalDocumentDetailView"), "get", kwargs={"doc_id": doc.pk}), "-patient view of own doc")
        self.probe(251, lambda: self.PL(DC, "patch", {"doc_type": "prescription"}, kwargs={"pk": doc.pk}), "-first correction")
        self.probe(251, lambda: self.PL(DC, "patch", {"doc_type": "prescription"}, kwargs={"pk": doc.pk}), "-same correction again")
        self.probe(251, lambda: self.PL(DC, "patch", {"doc_type": "lab_report"}, kwargs={"pk": doc.pk}), "-corrected back")
        self.probe(251, lambda: self.PL(DC, "patch", {"doc_type": "lab_report"}, kwargs={"pk": 99999}), "-document that does not exist")
        self.probe(248, lambda: self.PL(RC, "post"), "-platform reclassify")
        self.probe(305, lambda: self.PL(V("PlatformStatsView"), "get"), "-stats")
        self.probe(301, lambda: self.PL(V("PlatformUserListView"), "get", query={"search": "%'\";--<script>"}), "-search with symbols")
        self.probe(301, lambda: self.PL(V("PlatformUserListView"), "get", query={"search": "x" * 10000}), "-search with 10,000 characters")
        self.probe(299, lambda: self.PL(V("HospitalStaffResetPasswordView"), "post", kwargs={"pk": self.hospital.pk, "staff_id": self.nurse.pk}), "-reset")
        self.probe(299, lambda: self.PL(V("HospitalStaffResetPasswordView"), "post", kwargs={"pk": self.hospital.pk, "staff_id": 99999}), "-staff that does not exist")
        self.probe(299, lambda: self.A(V("HospitalStaffResetPasswordView"), "post", kwargs={"pk": self.hospital.pk, "staff_id": self.nurse.pk}), "-hospital admin")
        self.probe(290, lambda: self.PL(V("HospitalOverviewView"), "get", kwargs={"pk": self.hospital.pk}), "-overview of a new hospital")
        # suspend, expire and downgrade through the real stack
        from apps.hospital_master.models import Hospital, Subscription
        tk = self.tokens_for(user_id=self.doctor.pk, role="doctor", hospital_id=self.hospital.pk, db_name=self.hospital_alias)["access"]
        c = self.http(tk)
        self.note(295, c.get("/api/v1/opd/appointments/").status_code, "before suspending", "-before")
        Hospital.objects.using("default").filter(pk=self.hospital.pk).update(is_active=False)
        r = c.get("/api/v1/opd/appointments/")
        self.note(295, r.status_code, "staff token after the hospital is suspended: " + str(r.content[:150]), "-after")
        Hospital.objects.using("default").filter(pk=self.hospital.pk).update(is_active=True)
        Subscription.objects.using("default").filter(hospital=self.hospital).update(status="expired")
        r = c.get("/api/v1/opd/appointments/")
        self.note(296, r.status_code, "staff token after the subscription expired: " + str(r.content[:150]))
        Subscription.objects.using("default").filter(hospital=self.hospital).update(status="active", feat_patient_app=False)
        r = self.http(self.tokens_for(user_id=self.me.pk, role="patient", awpid="AW-4ME")["access"]).post("/api/v1/portal/book/", {"hospital_id": self.hospital.pk, "doctor_id": self.doctor.pk, "scheduled_date": str(dt.date.today() + dt.timedelta(days=1))}, format="json")
        self.note(297, r.status_code, "patient booking after the patient app was switched off: " + str(r.content[:150]))
        Subscription.objects.using("default").filter(hospital=self.hospital).update(license_tier="basic", feat_patient_app=True, feat_multi_branch=False)
        r = c.get("/api/v1/org/branches/")
        self.note(313, r.status_code, "branches list after multi-branch was switched off: " + str(r.content[:150]))

    # ===================================================== hospital admin
    def test_admin(self):
        from apps.documents.models import ImmunizationRecord
        SI, SD = V("StaffInviteView"), V("StaffDetailView")
        self.probe(268, lambda: self.A(SD, "patch", {"is_active": False}, kwargs={"pk": self.doctor.pk}), "-deactivate a doctor with appointments")
        self.appt(status="scheduled", scheduled_date=dt.date.today() + dt.timedelta(days=2))
        from apps.hospital_setup.models import StaffUser
        d3 = make_staff(self.hospital_alias, "doctor", email="d3.p4@example.test", phone="9000000088", place=self.place)
        self.appt(status="scheduled", scheduled_date=dt.date.today() + dt.timedelta(days=2), doctor=d3)
        self.probe(268, lambda: self.A(SD, "patch", {"is_active": False}, kwargs={"pk": d3.pk}), "-deactivate a doctor with upcoming appointments")
        self.probe(269, lambda: self.A(SI, "post", {"phone": "9000000099", "first_name": "NoRole"}), "-no role")
        self.probe(269, lambda: self.A(SI, "post", {"phone": "9000000098", "first_name": "NullRole", "role": None}), "-role null")
        # a removed permission for a logged-in user
        RL, RLD = V("RoleListCreateView"), V("RoleDetailView")
        c = self.A(RL, "post", {"name": "Billing only", "permissions": ["billing"]})
        self.note(271, c.status_code, str(c.data)[:200], "-role create")
        # own permissions through the profile API
        MP = V("MyStaffProfileView")
        self.probe(316, lambda: self.req(MP, "patch", {"role": "hospital_admin", "user_group": 1, "is_superuser": True, "permissions": ["billing"]}, role="nurse", uid=self.nurse.pk), "-nurse changes own role")
        self.note(316, 200, f"nurse role afterwards: {StaffUser.objects.using(self.hospital_alias).get(pk=self.nurse.pk).get_role()}", "-role after")
        MPD = V("MyStaffProfileDetailsView")
        self.probe(316, lambda: self.req(MPD, "patch", {"role": "hospital_admin", "user_group": 1}, role="nurse", uid=self.nurse.pk), "-details view")
        # branch switch
        MB = V("MyBranchesView")
        self.probe(317, lambda: self.req(MB, "get", role="nurse", uid=self.nurse.pk), "-my branches")
        branch_b, place_b = make_branch(self.hospital_alias, name="Branch B")
        tk = self.tokens_for(user_id=self.nurse.pk, role="nurse", hospital_id=self.hospital.pk, db_name=self.hospital_alias, branch_id=branch_b.pk)["access"]
        r = self.http(tk).get("/api/v1/org/me/branches/")
        self.note(317, r.status_code, "token carrying a branch the nurse is not assigned to: " + str(r.content[:200]), "-token branch")
        r = self.http(tk).get("/api/v1/opd/appointments/")
        self.note(317, r.status_code, "same token on the day list: " + str(r.content[:150]), "-day list")
        # old tokens
        old = self.tokens_for(user_id=self.nurse.pk, role="nurse", hospital_id=self.hospital.pk, db_name=self.hospital_alias)["access"]
        StaffUser.objects.using(self.hospital_alias).filter(pk=self.nurse.pk).update(is_active=False)
        r = self.http(old).get("/api/v1/opd/appointments/")
        self.note(311, r.status_code, "token of a staff member who was deactivated: " + str(r.content[:150]))
        StaffUser.objects.using(self.hospital_alias).filter(pk=self.nurse.pk).update(is_active=True)
        old_admin = self.tokens_for(user_id=self.front.pk, role="hospital_admin", hospital_id=self.hospital.pk, db_name=self.hospital_alias)["access"]
        r = self.http(old_admin).get("/api/v1/org/staff/")
        self.note(312, r.status_code, "token still claiming admin role while the account is front desk: " + str(r.content[:150]))
        # rooms
        from apps.hospital_setup.models import Room
        RM = V("RoomListCreateView")
        rr = self.A(RM, "post", {"name": "R9", "room_number": "R9", "branch": self.branch.pk})
        rd = (rr.data or {}).get("data") or rr.data or {}
        rid = rd.get("id") or rd.get("room_id")
        self.note(276, rr.status_code, str(rr.data)[:200], "-room create")
        RA = V("RoomAssignmentListCreateView")
        if rid:
            mk = lambda doc, s, e: {"room": rid, "doctor": doc.pk, "day_of_week": 2, "start_time": s, "end_time": e}
            self.probe(277, lambda: self.A(RA, "post", mk(self.doctor, "09:00", "12:00")), "-first")
            self.probe(277, lambda: self.A(RA, "post", mk(self.doctor2, "11:00", "13:00")), "-same room, overlapping time")
            self.probe(276, lambda: self.A(RA, "post", mk(self.doctor, "10:00", "11:00")), "-same doctor, overlapping time")
            r2 = self.A(RM, "post", {"name": "R10", "room_number": "R10", "branch": self.branch.pk})
            rid2 = (((r2.data or {}).get("data") or r2.data or {}).get("id")) if isinstance(r2.data, dict) else None
            if rid2:
                self.probe(276, lambda: self.A(RA, "post", {"room": rid2, "doctor": self.doctor.pk, "day_of_week": 2, "start_time": "10:00", "end_time": "11:00"}), "-same doctor in a second room at the same time")
        # settings
        HS = V("HospitalSettingsView")
        for label, d in [("blank name", {"name": ""}), ("invalid time zone", {"timezone": "Mars/Phobos"}), ("end before start", {"opening_time": "20:00", "closing_time": "06:00"}),
                         ("negative tax", {"default_tax_rate": "-5"}), ("tax over 100", {"default_tax_rate": "500"}), ("slot of 0 minutes", {"default_slot_minutes": 0}),
                         ("logo of the wrong type", {"logo": "data:text/plain;base64,aGk="}), ("logo not an image", {"logo": "data:image/png;base64,bm90IGFuIGltYWdl"})]:
            with mock.patch("core.storage.upload_data_uri", return_value="logos/x.png"):
                self.probe(278 if "logo" not in label else 279, lambda d=d: self.A(HS, "patch", d), "-" + label)
        # option lists
        for label, d in [("duplicate", {"name": "Dup"}), ("1,000-character label", {"name": "L" * 1000})]:
            self.probe(280, lambda d=d: self.A(V("AppointmentTypeListCreateView"), "post", d), "-" + label)
        self.probe(280, lambda: self.A(V("AppointmentTypeListCreateView"), "post", {"name": "Dup"}), "-duplicate again")
        # vaccination schedules
        VS, VSD, VSA = V("VaccinationScheduleListCreateView"), V("VaccinationScheduleDetailView"), V("VaccinationScheduleActivateView")
        s1 = self.A(VS, "post", {"name": "Sched A"})
        s2 = self.A(VS, "post", {"name": "Sched B"})
        self.note(281, s1.status_code, str(s1.data)[:200], "-create A")
        id1 = (((s1.data or {}).get("data") or s1.data or {}).get("id") or ((s1.data or {}).get("data") or {}).get("schedule_id")) if isinstance(s1.data, dict) else None
        id2 = (((s2.data or {}).get("data") or s2.data or {}).get("id") or ((s2.data or {}).get("data") or {}).get("schedule_id")) if isinstance(s2.data, dict) else None
        if id1 and id2:
            self.probe(281, lambda: self.A(VSA, "post", kwargs={"pk": id1}), "-activate A")
            self.probe(281, lambda: self.A(VSA, "post", kwargs={"pk": id2}), "-activate B")
            from apps.hospital_master.models import Schedule
            n = Schedule.objects.using("default").filter(is_active=True).count() if hasattr(Schedule, "is_active") else "n/a"
            self.note(281, 200, f"active schedules after activating A then B: {n}", "-count")
            self.probe(282, lambda: self.A(VSD, "delete", kwargs={"pk": id2}), "-delete the active one")
        # amendments listing (also 371)
        # hospital admin B reading hospital A
        self.probe(289, lambda: self.A(V("StaffDetailView"), "get", kwargs={"pk": 99999}), "-staff id from another hospital")
        self.probe(310, lambda: self.A(V("RoomDetailView"), "get", kwargs={"pk": 99999}), "-room id from another hospital")
        self.probe(310, lambda: self.A(V("InvoiceDetailView"), "get", kwargs={"pk": 99999}), "-invoice id from another hospital")
        self.probe(310, lambda: self.A(V("BranchDetailView"), "get", kwargs={"pk": 99999}), "-branch id from another hospital")
        # vaccination dose rules
        self.probe(283, lambda: self.A(VS, "post", {"name": "Bad doses", "rules": [{"vaccine_name": "X", "due_age_days": -5}]}), "-negative age")

    # ===================================================== cross-hospital and files
    def test_cross(self):
        # a patient with records in two hospitals: the portal shows every hospital's invoices and bookings
        from apps.hospital_master.models import Hospital
        self.probe(332, lambda: self.P(V("PortalMyRecordsView"), "get"), "-my records")
        self.probe(332, lambda: self.P(V("PortalInvoiceListView"), "get"), "-my invoices")
        self.probe(337, lambda: self.F(V("PatientSearchView"), "get", query={"q": "U4ME"}), "-search by hospital number")
        # staff in two branches booking into the wrong one
        branch_b, place_b = make_branch(self.hospital_alias, name="Branch B")
        self.probe(334, lambda: self.F(V("AppointmentListCreateView"), "post", {"patient_id": self.hp.pk, "doctor_id": self.doctor.pk, "scheduled_date": str(dt.date.today() + dt.timedelta(days=3)), "branch_id": branch_b.pk}), "-doctor is not in that branch")
        # generated files
        from apps.billing.models import Invoice
        inv = Invoice.objects.using(self.hospital_alias).create(patient=self.hp, branch=self.branch, invoice_number="I-P4B", status="issued")
        self.probe(346, lambda: self.A(V("InvoicePDFView"), "get", kwargs={"pk": inv.pk}), "-no logo, no registration number")
        long_name = "Z" * 100
        from apps.patients.models import Patient
        Patient.objects.using("default").filter(pk=self.me.pk).update(full_name=long_name[:100])
        self.probe(346, lambda: self.A(V("InvoicePDFView"), "get", kwargs={"pk": inv.pk}), "-100-character patient name")
        self.probe(347, lambda: self.req(V("InvoicePDFView"), "get", kwargs={"pk": inv.pk}), "-no login")
        self.probe(347, lambda: self.P(V("InvoicePDFView"), "get", kwargs={"pk": inv.pk}), "-a patient on the staff route")
        r = self.http().get(f"/api/v1/billing/invoices/{inv.pk}/pdf/")
        self.note(347, r.status_code, "HTTP, no token: " + str(r.content[:100]), "-http")
        # deleted patient: search, shares and PDFs
        Patient.objects.using("default").filter(pk=self.other.pk).update(is_active=False)
        self.probe(370, lambda: self.F(V("PatientSearchView"), "get", query={"q": "Other Four"}), "-search after deactivating")
        # audit log records
        self.probe(371, lambda: self.A(V("AuditLogListView"), "get"), "-audit log listing")
        # appointment history for same-number patients
        self.probe(337, lambda: self.F(V("PatientDetailView"), "get", kwargs={"pk": self.hp_other.pk}), "-detail of a patient with the same number elsewhere")

    # ===================================================== second round: the probes whose first payload was wrong
    def test_round2(self):
        from apps.hospital_setup.models import Floor, Room, NotificationLog
        from apps.opd.models import Appointment, OPDEncounter
        from apps.patients.models import PatientBooking, PatientRelationship
        from apps.hospital_master.models import Schedule, ScheduleRule, Subscription
        db = self.hospital_alias
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        # --- bookings and notifications
        a1 = self.appt(scheduled_date=tomorrow, scheduled_time="10:00", status="scheduled")
        a2 = self.appt(scheduled_date=tomorrow, scheduled_time="10:30", status="scheduled", patient=self.hp_other)
        mk = lambda a, who: PatientBooking.objects.using("default").create(hospital=self.hospital, appointment_id=a.pk, booked_by=who, patient=who, scheduled_date=tomorrow, status="scheduled")
        b1, b2 = mk(a1, self.me), mk(a2, self.other)
        Can, Res = V("PortalCancelBookingView"), V("PortalRescheduleBookingView")
        self.probe(83, lambda: self.P(Can, "post", kwargs={"pk": b2.pk}), "-r2")
        self.probe(84, lambda: self.P(Res, "post", {"scheduled_date": str(tomorrow), "scheduled_time": "10:30"}, kwargs={"pk": b1.pk}), "-r2")
        Appointment.objects.using(db).filter(pk=a1.pk).update(status="in_progress")
        self.probe(86, lambda: self.P(Res, "post", {"scheduled_date": str(tomorrow), "scheduled_time": "11:00"}, kwargs={"pk": b1.pk}), "-r2")
        Appointment.objects.using(db).filter(pk=a1.pk).update(status="scheduled")
        nt = V("PortalNextTokenView")
        d_lone = make_staff(db, "doctor", email="lone.p4@example.test", phone="9000000086")
        self.probe(88, lambda: self.P(nt, "get", kwargs={"hospital_id": self.hospital.pk, "doctor_id": d_lone.pk}, query={"date": str(tomorrow)}), "-r2 doctor without a schedule")
        self.probe(90, lambda: self.P(V("PortalSlotListView"), "get", kwargs={"hospital_id": self.hospital.pk, "doctor_id": d_lone.pk}, query={"date": str(tomorrow)}), "-r2 doctor with no slots")
        self.probe(90, lambda: self.P(V("PortalDoctorListView"), "get", kwargs={"hospital_id": self.hospital.pk}), "-r2 doctor list")
        log = NotificationLog.objects.using(db).create(patient=self.hp, channel="in_app", body="Reminder", reference="appt_reminder:1")
        NM = V("PortalNotificationMarkReadView")
        self.probe(93, lambda: self.P(NM, "post", kwargs={"hospital_db": db, "pk": log.pk}), "-r2 first")
        self.probe(93, lambda: self.P(NM, "post", kwargs={"hospital_db": db, "pk": log.pk}), "-r2 second")
        log2 = NotificationLog.objects.using(db).create(patient=self.hp_other, channel="in_app", body="Not mine", reference="appt_reminder:2")
        self.probe(94, lambda: self.P(NM, "post", kwargs={"hospital_db": db, "pk": log2.pk}), "-r2")
        log3 = NotificationLog.objects.using(db).create(patient=self.hp, channel="in_app", body="Gone booking", reference="appt_reminder:99999")
        self.probe(95, lambda: self.P(V("PortalNotificationsView"), "get"), "-r2 list")
        self.probe(95, lambda: self.P(NM, "post", kwargs={"hospital_db": db, "pk": log3.pk}), "-r2 mark")
        # --- a family member with an upcoming booking, then removed
        kid = self.P(V("PortalFamilyListCreateView"), "post", {"full_name": "Kid Two", "date_of_birth": "2019-03-03", "gender": "male", "relationship": "child"})
        kid_awpid = (((kid.data or {}).get("data")) or {}).get("awpid")
        if kid_awpid:
            hk = make_patient(db, kid_awpid, uhid="U4KID", branch=self.branch, full_name="Kid Two")
            ak = self.appt(patient=hk, scheduled_date=tomorrow, scheduled_time="12:00", status="scheduled")
            self.probe(108, lambda: self.P(V("PortalFamilyDetailView"), "delete", kwargs={"awpid": kid_awpid}), "-r2")
            still = Appointment.objects.using(db).filter(pk=ak.pk).exclude(status="cancelled").exists()
            self.note(108, 200, f"the child's upcoming appointment still stands after the member was unlinked: {still}", "-r2 appointment")
        # --- corrections (amendments)
        AM = V("PortalRecordAmendmentView")
        mkam = lambda **d: {"hospital_id": self.hospital.pk, "resource_type": "patient", "field_name": "full_name", "requested_value": "Me Fourth", **d}
        self.probe(110, lambda: self.P(AM, "post", mkam(requested_value="")), "-r2 blank requested value")
        self.probe(110, lambda: self.P(AM, "post", mkam(field_name="")), "-r2 blank field")
        r = self.P(AM, "post", mkam(reason="spelling"))
        self.note(111, r.status_code, str(r.data)[:200], "-r2 first")
        r = self.P(AM, "post", mkam(reason="spelling"))
        self.note(111, r.status_code, "second identical request: " + str(r.data)[:200], "-r2 second")
        from apps.hospital_setup.models import RecordAmendment
        n = RecordAmendment.objects.using(db).filter(patient=self.hp).count()
        self.note(111, 200, f"requests stored for two identical submissions: {n}", "-r2 count")
        self.probe(110, lambda: self.P(AM, "post", mkam(requested_value="Q" * 5000)), "-r2 5000 characters")
        self.probe(113, lambda: self.P(AM, "post", mkam(patient_awpid="AW-4OT")), "-r2 someone else's")
        row = RecordAmendment.objects.using(db).filter(patient=self.hp).first()
        if row:
            self.A(V("RecordAmendmentResolveView"), "post", {"status": "approved"}, kwargs={"pk": row.pk})
            ev = self.A(V("AuditLogListView"), "get", query={"page_size": 100})
            acts = [x.get("action") for x in ((ev.data or {}).get("data") or {}).get("results", [])] if isinstance(ev.data, dict) else []
            self.note(371, ev.status_code, f"audit actions listed after submitting and resolving a correction: {acts}", "-r2")
        # --- birth history
        BH = V("BirthHistoryView")
        pk = self.hp_other.pk
        self.probe(146, lambda: self.D(BH, "post", {"gestational_age_weeks": -2, "birth_weight_kg": "-1", "delivery_mode": "normal"}, kwargs={"pk": pk}), "-r2 negative")
        self.probe(146, lambda: self.D(BH, "post", {"gestational_age_weeks": 38, "birth_weight_kg": "3.1", "delivery_mode": "normal", "nicu_admission": False, "nicu_days": 9}, kwargs={"pk": pk}), "-r2 NICU days without NICU")
        # --- family tree
        FT = V("PatientFamilyTreeView")
        self.probe(149, lambda: self.F(FT, "get", query={"awpid": "AW-4ME"}), "-r2 normal")
        try:
            PatientRelationship.objects.using("default").create(guardian=self.me, dependent=self.other, relationship="child")
            PatientRelationship.objects.using("default").create(guardian=self.other, dependent=self.me, relationship="child")
        except Exception as e:
            self.note(149, "EXCEPTION", f"the loop could not even be stored: {type(e).__name__}", "-r2 loop stored")
        self.probe(149, lambda: self.F(FT, "get", query={"awpid": "AW-4ME"}), "-r2 with a loop")
        # --- appointment type in use
        AT, ATD = V("AppointmentTypeListCreateView"), V("AppointmentTypeDetailView")
        c = self.A(AT, "post", {"name": "Review"})
        opt = (c.data or {}).get("data") or {}
        if opt.get("option_list_id"):
            self.appt(appointment_type=opt["value"], status="scheduled", scheduled_date=tomorrow, scheduled_time="14:00")
            self.probe(165, lambda: self.A(ATD, "delete", kwargs={"pk": opt["option_list_id"]}), "-r2 delete one in use")
        # --- follow-up
        a3 = self.appt(status="waiting")
        self.D(V("EncounterCreateView"), "post", {"appointment_id": str(a3.pk)})
        enc = OPDEncounter.objects.using(db).get(appointment=a3)
        MB = V("FollowupMarkBookedView")
        self.probe(170, lambda: self.F(MB, "post", kwargs={"pk": enc.pk}), "-r2 marked booked when nobody asked")
        self.probe(170, lambda: self.D(V("FollowUpActionView"), "post", {"mode": "nurse", "note": "call in a week"}, kwargs={"pk": enc.pk}), "-r2 doctor asks the nurse")
        self.probe(170, lambda: self.F(MB, "post", kwargs={"pk": enc.pk}), "-r2 marked booked once")
        self.probe(170, lambda: self.F(MB, "post", kwargs={"pk": enc.pk}), "-r2 marked booked twice")
        self.probe(210, lambda: self.N(MB, "post", kwargs={"pk": enc.pk}), "-r2 nurse marks it a third time")
        self.probe(210, lambda: self.D(V("FollowUpActionView"), "post", {"mode": "reminder", "follow_up_in_days": 9999999}, kwargs={"pk": enc.pk}), "-r2 reminder 9,999,999 days")
        # --- billing
        from apps.billing.models import Invoice
        inv = Invoice.objects.using(db).create(patient=self.hp, branch=self.branch, invoice_number="I-P4R2", status="issued")
        BS, BSD = V("BillingServiceListView"), V("BillingServiceDetailView")
        c = self.A(BS, "post", {"name": "Dressing2", "code": "DR2", "unit_price": "50"})
        sid = ((c.data or {}).get("data") or {}).get("billing_item_id")
        if sid:
            pr = self.A(BSD, "patch", {"is_active": False}, kwargs={"pk": sid})
            self.note(182, pr.status_code, "switch the service off: " + str(pr.data)[:150], "-r2 switch off")
            self.probe(182, lambda: self.A(V("InvoiceItemCreateView"), "post", {"billing_item": sid, "quantity": 1}, kwargs={"pk": inv.pk}), "-r2 bill a switched-off service")
        self.A(V("InvoiceItemCreateView"), "post", {"description": "Consult", "quantity": 1, "unit_price": "100"}, kwargs={"pk": inv.pk})
        PMs = V("PaymentModeListCreateView")
        pm = self.A(PMs, "post", {"name": "Wallet"})
        pmd = (pm.data or {}).get("data") or {}
        self.note(191, pm.status_code, str(pm.data)[:160], "-r2 create mode")
        self.probe(182, lambda: self.A(V("PaymentCreateView"), "post", {"invoice": inv.pk, "amount": "5", "payment_mode": "does-not-exist"}), "-r2 mode that does not exist")
        if pmd.get("option_list_id"):
            self.A(V("PaymentCreateView"), "post", {"invoice": inv.pk, "amount": "5", "payment_mode": (pmd.get("value") or pmd.get("name"))})
            self.probe(191, lambda: self.A(V("PaymentModeDetailView"), "delete", kwargs={"pk": pmd["option_list_id"]}), "-r2 delete a mode already used")
            self.A(V("PaymentModeDetailView"), "patch", {"is_active": False}, kwargs={"pk": pmd["option_list_id"]})
            self.probe(182, lambda: self.A(V("PaymentCreateView"), "post", {"invoice": inv.pk, "amount": "5", "payment_mode": (pmd.get("value") or pmd.get("name"))}), "-r2 pay with a switched-off mode")
        self.probe(183, lambda: self.A(V("InvoiceListCreateView"), "post", {"patient": 99999, "branch": self.branch.pk}), "-r2 patient not at this hospital")
        cat = self.A(V("ServiceCategoryListCreateView"), "post", {"name": "Procs"})
        cd = (cat.data or {}).get("data") or {}
        if cd.get("option_list_id"):
            self.A(BS, "post", {"name": "Suture2", "code": "SU2", "unit_price": "80", "category": (cd.get("value") or cd.get("name"))})
            self.probe(190, lambda: self.A(V("ServiceCategoryDetailView"), "delete", kwargs={"pk": cd["option_list_id"]}), "-r2 delete a category with a service")
            from apps.billing.models import BillingItem
            self.note(190, 200, f"category left on the service afterwards: {list(BillingItem.objects.using(db).filter(code='SU2').values_list('category', flat=True))}", "-r2 service after")
        # --- doctor profile
        DP = V("MyDoctorProfileView")
        for label, d in [("10,000-character bio", {"bio": "B" * 10000}), ("languages as a number", {"languages": 5}), ("known_for as a list of 1,000 items", {"known_for": ["x"] * 1000}),
                         ("registration number (read-only?)", {"registration_no": "!!@@##"}), ("gender nonsense", {"gender": "zzz"}), ("photo of the wrong type", {"photo": "data:text/plain;base64,aGk="})]:
            self.probe(218, lambda d=d: self.req(DP, "patch", d, role="doctor", uid=self.doctor.pk), "-r2 " + label)
        # --- rooms
        fl = Floor.objects.using(db).create(branch=self.branch, name="F1")
        RM, RA = V("RoomListCreateView"), V("RoomAssignmentListCreateView")
        r1 = self.A(RM, "post", {"name": "R9", "floor_obj": fl.pk})
        r2 = self.A(RM, "post", {"name": "R10", "floor_obj": fl.pk})
        self.probe(276, lambda: self.A(RM, "post", {"name": "R9", "floor_obj": fl.pk}), "-r2 same room name on a floor")
        rid, rid2 = ((r1.data or {}).get("data") or {}).get("room_id"), ((r2.data or {}).get("data") or {}).get("room_id")
        self.note(276, r1.status_code, str(r1.data)[:160], "-r2 room create")
        if rid and rid2:
            mkb = lambda room, doc, s, e: {"room": room, "doctor": doc.pk, "day_of_week": 2, "start_time": s, "end_time": e}
            self.probe(277, lambda: self.A(RA, "post", mkb(rid, self.doctor, "09:00", "12:00")), "-r2 first")
            self.probe(277, lambda: self.A(RA, "post", mkb(rid, self.doctor2, "11:00", "13:00")), "-r2 same room overlapping")
            self.probe(276, lambda: self.A(RA, "post", mkb(rid2, self.doctor, "10:00", "11:00")), "-r2 same doctor in a second room at the same time")
        # --- settings
        HS = V("HospitalSettingsView")
        for label, d in [("registration fee as text", {"registration_fee_amount": "abc"}), ("negative registration fee", {"registration_fee_amount": "-50"}),
                         ("registration fee huge", {"registration_fee_amount": "99999999999999"}), ("fee_ownership nonsense", {"fee_ownership": "nobody"}),
                         ("blank tax", {"default_tax_rate": ""}), ("tax as text", {"default_tax_rate": "abc"})]:
            self.probe(278, lambda d=d: self.A(HS, "patch", d), "-r2 " + label)
        # --- vaccination schedules: a template, cloned twice, then deleted while active
        tmpl = Schedule.objects.using("default").create(kind="vaccination", name="India UIP P4", is_template=True)
        ScheduleRule.objects.using("default").create(schedule=tmpl, item="BCG", dose_number=1, scheduled_label="Birth", min_age_days=0)
        VS, VSD, VSA = V("VaccinationScheduleListCreateView"), V("VaccinationScheduleDetailView"), V("VaccinationScheduleActivateView")
        s1 = self.A(VS, "post", {"template_id": tmpl.pk, "name": "A"})
        s2 = self.A(VS, "post", {"template_id": tmpl.pk, "name": "B"})
        self.note(281, s1.status_code, str(s1.data)[:160], "-r2 clone A")
        id1, id2 = [((x.data or {}).get("data") or {}).get("immunization_schedule_id") or ((x.data or {}).get("data") or {}).get("id") for x in (s1, s2)]
        g = self.A(VS, "get")
        self.note(281, g.status_code, "active after cloning A then B: " + str(((g.data or {}).get("data") or {}).get("active_schedule_id")) + f" (A={id1}, B={id2})", "-r2 active")
        if id1 and id2:
            self.probe(281, lambda: self.A(VSA, "post", kwargs={"pk": id1}), "-r2 activate A")
            self.probe(282, lambda: self.A(VSD, "delete", kwargs={"pk": id1}), "-r2 delete the active one")
            g = self.A(VS, "get")
            self.note(282, g.status_code, "active schedule afterwards: " + str(((g.data or {}).get("data") or {}).get("active_schedule_id")), "-r2 after")
            rules_ids = list(ScheduleRule.objects.using("default").filter(schedule_id=id2).values_list("pk", flat=True))
            if rules_ids:
                self.probe(283, lambda: self.A(VSD, "patch", {"rules": [{"immunization_schedule_rule_id": rules_ids[0], "min_age_days": -5}]}, kwargs={"pk": id2}), "-r2 negative age")
                self.probe(283, lambda: self.A(VSD, "patch", {"rules": [{"immunization_schedule_rule_id": rules_ids[0], "min_age_days": 100000}]}, kwargs={"pk": id2}), "-r2 age 100000 days")
                self.probe(284, lambda: self.A(VSD, "patch", {"rules": [{"immunization_schedule_rule_id": rules_ids[0], "min_age_days": 100, "max_age_days": 50}]}, kwargs={"pk": id2}), "-r2 window ends before it starts")
                self.probe(284, lambda: self.A(VSD, "patch", {"rules": [{"vaccine_name": "BCG", "dose_number": 1, "scheduled_label": "Dup", "min_age_days": 5}]}, kwargs={"pk": id2}), "-r2 same vaccine and dose again")
        # --- consult pad
        cs = self.D(V("EncounterConsultSessionView"), "post", kwargs={"pk": enc.pk})
        self.note(132, cs.status_code, str(cs.data)[:200], "-r2 start session")
        token = (((cs.data or {}).get("data") or {}).get("pad_url") or "").rstrip("/").rsplit("/", 1)[-1] if isinstance(cs.data, dict) else None
        if token:
            CP = V("ConsultPadView")
            self.probe(132, lambda: self.req(CP, "get", kwargs={"token": token}), "-r2 first device")
            self.probe(132, lambda: self.req(CP, "get", kwargs={"token": token}), "-r2 second device")
            png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
            self.probe(135, lambda: self.req(CP, "put", {"tab": "rx", "pages": [png] * 21}, kwargs={"token": token}), "-r2 21 pages")
            self.probe(135, lambda: self.req(CP, "put", {"tab": "rx", "pages": ["data:image/png;base64," + "A" * 30_000_000]}, kwargs={"token": token}), "-r2 30 MB page")
            self.probe(135, lambda: self.req(CP, "put", {"tab": "other", "pages": []}, kwargs={"token": token}), "-r2 unknown tab")
            self.probe(135, lambda: self.req(CP, "put", {"tab": "rx", "pages": "not a list"}, kwargs={"token": token}), "-r2 pages not a list")
            self.probe(135, lambda: self.req(CP, "put", {"tab": "rx", "pages": ["data:text/html;base64,PGI+"]}, kwargs={"token": token}), "-r2 html page")
        # --- vaccination upload control: a good file
        with mock.patch("core.storage.upload_data_uri", return_value="vaccination-certs/x.pdf"):
            self.probe(68, lambda: self.P(V("PortalVaccinationUploadView"), "post", {"vaccine_name": "BCG", "administered_date": str(dt.date.today()), "file_data": "data:application/pdf;base64,JVBERi0xLjQKJSVFT0YK"}), "-r2 a good file")
            self.probe(68, lambda: self.P(V("PortalVaccinationUploadView"), "post", {"vaccine_name": "BCG", "administered_date": str(dt.date.today())}), "-r2 no file at all")
        # --- duplicate hospital number
        from apps.hospital_patients.models import HospitalPatient
        try:
            with transaction.atomic(using=db):
                HospitalPatient.objects.using(db).create(awpid="AW-4OT2", uhid="U4ME")
            self.note(337, 200, "a second patient with the same hospital number U4ME was stored", "-r2")
        except Exception as e:
            self.note(337, 400, f"refused: {type(e).__name__}", "-r2")
        # --- gates by plan, over the real HTTP stack
        sub = Subscription.objects.using("default").filter(hospital=self.hospital)
        adm = self.http(self.tokens_for(user_id=self.admin.pk, role="hospital_admin", hospital_id=self.hospital.pk, db_name=self.hospital_alias)["access"])
        sub.update(feat_analytics=False)
        r = adm.get("/api/v1/billing/reports/revenue/")
        self.note(196, r.status_code, "revenue report with analytics switched off in the plan: " + str(r.content[:140]), "-r2 analytics off")
        r = adm.get("/api/v1/billing/summary/")
        self.note(313, r.status_code, "billing summary with analytics switched off: " + str(r.content[:140]), "-r2 summary")
        sub.update(feat_analytics=True)
        nurse_tok = self.http(self.tokens_for(user_id=self.nurse.pk, role="nurse", hospital_id=self.hospital.pk, db_name=self.hospital_alias)["access"])
        branch_b, place_b = make_branch(db, name="Branch Z")
        r = nurse_tok.get(f"/api/v1/opd/appointments/?branch_id={branch_b.pk}")
        self.note(317, r.status_code, "nurse asks for the queue of a branch not assigned to them: " + str(r.content[:140]), "-r2")
