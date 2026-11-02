"""core/tests/tests_destructive_probe3.py — third batch of probes for docs/Destructive_Test_Cases.xlsx: the real HTTP stack (tokens, bad bodies, CORS),
the patient portal, billing, prescriptions, staff set-up, dates, and small volumes. Results go to the file named by PROBE_OUT3."""

import datetime as dt
import json
import os
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.db import transaction
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from core.api.authentication import MockUser
from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff, requires_hospital_db

RESULTS = {}
MODULES = ("opd", "billing", "patients", "staff", "facility", "reports", "compliance")


@requires_hospital_db
class DestructiveProbes3(HospitalDBTestCase):
    @classmethod
    def tearDownClass(cls):
        out = os.environ.get("PROBE_OUT3")
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
        self.hospital = Hospital.objects.using("default").create(name="Probe H3", hospital_code="probe-h3", db_name=db)
        HospitalParameters.objects.using("default").create(hospital=self.hospital, default_tax_rate=Decimal("0"))
        Subscription.objects.using("default").create(hospital=self.hospital, license_tier="enterprise", status="active", feat_patient_app=True,
                                                     max_branches=50, max_doctors=50, max_staff=50)
        self.branch, self.place = make_branch(db)
        self.doctor = make_staff(db, "doctor", email="dr.p3@example.test", phone="9000000061", place=self.place)
        self.doctor2 = make_staff(db, "doctor", email="dr.p3b@example.test", phone="9000000062", place=self.place)
        self.admin = make_staff(db, "hospital_admin", email="adm.p3@example.test", phone="9000000063", place=self.place)
        self.nurse = make_staff(db, "nurse", email="nu.p3@example.test", phone="9000000064", place=self.place)
        self.me = Patient.objects.using("default").create(awpid="AW-3ME", full_name="Me Three", mobile="9333333331", password="x", date_of_birth="2015-01-01", email="me3@example.test")
        self.other = Patient.objects.using("default").create(awpid="AW-3OT", full_name="Other Three", mobile="9333333332", password="x", date_of_birth="2016-01-01")
        self.hp = make_patient(db, "AW-3ME", uhid="U3ME", branch=self.branch, full_name="Me Three")
        self.hp_other = make_patient(db, "AW-3OT", uhid="U3OT", branch=self.branch, full_name="Other Three")
        NextNumber.objects.using(db).create(branch_id=self.branch.pk, entity="invoice", prefix="INV-")

    # helpers
    def req(self, view, method, data=None, *, role=None, uid=None, awpid=None, kwargs=None, query=None, fmt="json"):
        factory = APIRequestFactory()
        request = factory.get("/x/", query or data or {}) if method == "get" else getattr(factory, method)("/x/", data or {}, format=fmt)
        if role:
            user = MockUser({"user_id": uid or self.admin.pk, "role": role, "hospital_id": self.hospital.pk, "awpid": awpid})
            user.subscription = SimpleNamespace(**{f: True for f in MODULES})
            force_authenticate(request, user=user)
        request.hospital_db = self.hospital_alias
        request.hospital_id = self.hospital.pk
        return view.as_view()(request, **(kwargs or {}))

    def patient(self, view, method, data=None, **kw):
        return self.req(view, method, data, role="patient", uid=self.me.pk, awpid="AW-3ME", **kw)

    def probe(self, name, fn):
        try:
            with transaction.atomic(using="default"), transaction.atomic(using=self.hospital_alias):
                r = fn()
            body = r.data if hasattr(r, "data") and r.data is not None else ""
            RESULTS[name] = {"status": r.status_code, "body": str(body)[:240]}
        except Exception as e:
            RESULTS[name] = {"status": "EXCEPTION", "body": f"{type(e).__name__}: {str(e)[:160]}"}

    def note(self, name, status, body=""):
        RESULTS[name] = {"status": status, "body": str(body)[:240]}

    def appt(self, **kw):
        from apps.opd.models import Appointment
        kw.setdefault("scheduled_date", dt.date.today())
        kw.setdefault("patient", self.hp)
        kw.setdefault("doctor", self.doctor)
        return Appointment.objects.using(self.hospital_alias).create(branch_department=self.place, **kw)

    # ---- the real HTTP stack
    def test_http_stack(self):
        from core.auth.views import _make_tokens
        c = APIClient(raise_request_exception=False)
        r = c.get("/health/")
        self.note("HTTP health check", r.status_code, r.content)
        tokens = _make_tokens({"user_id": self.me.pk, "role": "patient", "awpid": "AW-3ME"})
        good = tokens["access"]
        for name, tok in [("no token", None), ("garbage token", "abc.def.ghi"), ("tampered token (last char changed)", good[:-1] + ("A" if good[-1] != "A" else "B")),
                          ("refresh token as access", tokens["refresh"]), ("token signed with another key", __import__("jwt").encode({"user_id": 1, "role": "hospital_admin", "token_type": "access", "exp": 9999999999, "jti": "x"}, "wrong-key", algorithm="HS256")),
                          ("token with alg none", __import__("jwt").encode({"user_id": 1, "role": "hospital_admin", "token_type": "access", "exp": 9999999999, "jti": "y"}, None, algorithm="none"))]:
            c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}" if tok else "")
            r = c.get("/api/v1/auth/me/")
            self.note(f"HTTP /me/ with {name}", r.status_code, r.content[:150])
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {good}")
        self.note("HTTP /me/ with a good token (control)", c.get("/api/v1/auth/me/").status_code)
        c.credentials()
        r = c.post("/api/v1/auth/login/patient/", "{bad json", content_type="application/json")
        self.note("HTTP malformed JSON", r.status_code, r.content[:150])
        r = c.post("/api/v1/auth/login/patient/", "", content_type="application/json")
        self.note("HTTP empty body", r.status_code, r.content[:150])
        r = c.post("/api/v1/auth/login/patient/", "awpid=a&password=b", content_type="text/plain")
        self.note("HTTP wrong content type", r.status_code, r.content[:150])
        r = c.post("/api/v1/auth/login/patient/", json.dumps({"awpid": "a" * (21 * 1024 * 1024), "password": "x"}), content_type="application/json")
        self.note("HTTP 21 MB body", r.status_code, r.content[:150])
        r = c.options("/api/v1/auth/login/patient/", HTTP_ORIGIN="https://evil.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.note("HTTP CORS preflight from an unlisted origin", r.status_code, f"allow-origin={r.headers.get('Access-Control-Allow-Origin')}")
        r = c.options("/api/v1/auth/login/patient/", HTTP_ORIGIN="http://localhost:5173", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.note("HTTP CORS preflight from a listed origin (control)", r.status_code, f"allow-origin={r.headers.get('Access-Control-Allow-Origin')}")
        for path in ("/django-admin/", "/api/docs/", "/api/schema/"):
            r = c.get(path)
            self.note(f"HTTP {path} without a login", r.status_code, r.headers.get("Location", ""))
        # a crash must not show a stack trace
        from apps.billing import views as bv
        c.credentials(HTTP_AUTHORIZATION="Bearer " + _make_tokens({"user_id": self.admin.pk, "role": "hospital_admin", "hospital_id": self.hospital.pk, "db_name": self.hospital_alias})["access"])
        with mock.patch.object(bv.InvoiceListCreateView, "get", side_effect=RuntimeError("secret-db-name hospital_test boom")):
            r = c.get("/api/v1/billing/invoices/")
        body = r.content.decode("utf8", "ignore")
        self.note("HTTP a crash shows no trace", r.status_code, f"traceback_shown={'Traceback' in body}; leaks_message={'secret-db-name' in body}; body={body[:120]}")

    def test_rate_limits(self):
        c = APIClient(raise_request_exception=False)
        codes = [c.post("/api/v1/auth/login/patient/", {"awpid": "AW-3ME", "password": "nope"}, format="json").status_code for _ in range(14)]
        self.note("HTTP 14 wrong patient logins", codes[-1], codes)
        cache.clear()
        codes = [c.post("/api/v1/auth/otp/request/", {"purpose": "patient_login", "mobile": "9333333331"}, format="json").status_code for _ in range(9)]
        self.note("HTTP 9 OTP requests", codes[-1], codes)
        cache.clear()
        codes = [c.get("/api/v1/emergency/not-a-token/").status_code for _ in range(25)]
        self.note("HTTP 25 emergency page hits", codes[-1], codes)
        cache.clear()
        codes = [c.get("/api/v1/consult-pad/not-a-token/").status_code for _ in range(25)]
        self.note("HTTP 25 consult-pad hits", codes[-1], codes)

    # ---- the patient portal
    def test_portal(self):
        from apps.patients.models import Patient
        from apps.patients.views import (PortalChangePasswordView, PortalDocumentCountsView, PortalDocumentDaysView, PortalDocumentListCreateView,
                                         PortalDocumentZipView, PortalEmergencyTokenView, PortalHealthSummaryView, PortalInvoiceListView,
                                         PortalInvoiceReceiptPDFView, PortalMobileChangeRequestOTPView, PortalMyBookingsView, PortalNotificationMarkReadView,
                                         PortalNotificationsView, PortalPrescriptionReceiptPDFView, PortalProfileView, EmergencySummaryView)
        from apps.documents.views_timeline import PatientHealthTimelineView
        P = self.patient
        self.probe("Portal change password with the wrong current one", lambda: P(PortalChangePasswordView, "post", {"current_password": "wrong", "new_password": "NewPass#12345"}))
        self.probe("Portal change password to a short one", lambda: P(PortalChangePasswordView, "post", {"current_password": "x", "new_password": "abc"}))
        self.probe("Portal change password with nothing sent", lambda: P(PortalChangePasswordView, "post", {}))
        self.probe("Portal profile patch tries role, active flag and awpid", lambda: P(PortalProfileView, "patch", {"is_active": False, "awpid": "HACKED", "role": "hospital_admin", "password": "pw", "full_name": "Me Three"}))
        self.note("Portal profile fields after that patch", 200, str(list(Patient.objects.using("default").filter(pk=self.me.pk).values("awpid", "is_active", "password"))))
        self.probe("Portal profile with a 10,000-character name", lambda: P(PortalProfileView, "patch", {"full_name": "N" * 10000}))
        self.probe("Portal profile with emoji and script text", lambda: P(PortalProfileView, "patch", {"full_name": "Me 😀 <script>alert(1)</script>"}))
        self.probe("Portal profile with a blank name", lambda: P(PortalProfileView, "patch", {"full_name": "  "}))
        self.probe("Portal profile with a future date of birth", lambda: P(PortalProfileView, "patch", {"date_of_birth": "2099-01-01"}))
        self.probe("Portal profile with a bad mobile number", lambda: P(PortalProfileView, "patch", {"mobile": "12345"}))
        self.probe("Portal profile with a number already in use", lambda: P(PortalProfileView, "patch", {"mobile": "9333333332"}))
        codes = [self.patient(PortalMobileChangeRequestOTPView, "post", {"mobile": "9444444441"}).status_code for _ in range(8)]
        self.note("Portal mobile-change OTP asked 8 times", codes[-1], codes)
        self.probe("Portal invoices with none", lambda: P(PortalInvoiceListView, "get"))
        self.probe("Portal my bookings with none", lambda: P(PortalMyBookingsView, "get"))
        self.probe("Portal health summary for a new patient", lambda: P(PortalHealthSummaryView, "get"))
        self.probe("Portal notifications with none", lambda: P(PortalNotificationsView, "get"))
        self.probe("Portal notification of an unknown hospital", lambda: P(PortalNotificationMarkReadView, "post", kwargs={"hospital_db": "nope", "pk": 1}))
        self.probe("Portal invoice receipt of an unknown hospital", lambda: P(PortalInvoiceReceiptPDFView, "get", kwargs={"hospital_db": "nope", "pk": 1}))
        self.probe("Portal prescription receipt of an unknown hospital", lambda: P(PortalPrescriptionReceiptPDFView, "get", kwargs={"hospital_db": "nope", "pk": "00000000-0000-0000-0000-000000000000"}))
        self.probe("Portal documents page 0", lambda: P(PortalDocumentListCreateView, "get", query={"page": 0}))
        self.probe("Portal documents page -1", lambda: P(PortalDocumentListCreateView, "get", query={"page": -1}))
        self.probe("Portal documents page size 100000", lambda: P(PortalDocumentListCreateView, "get", query={"page_size": 100000}))
        self.probe("Portal documents for a family member who is not linked", lambda: P(PortalDocumentListCreateView, "get", query={"patient_awpid": "AW-3OT"}))
        self.probe("Portal documents uploaded_on with a bad date", lambda: P(PortalDocumentListCreateView, "get", query={"uploaded_on": "tomorrow"}))
        self.probe("Portal document counts with none", lambda: P(PortalDocumentCountsView, "get"))
        self.probe("Portal document days with none", lambda: P(PortalDocumentDaysView, "get"))
        self.probe("Portal zip of nothing", lambda: P(PortalDocumentZipView, "post", {"ids": []}))
        self.probe("Portal zip with ids as text", lambda: P(PortalDocumentZipView, "post", {"ids": ["a", "b"]}))
        self.probe("Portal zip of documents that do not exist", lambda: P(PortalDocumentZipView, "post", {"ids": [99999]}))
        self.probe("Timeline filtered to a period with nothing", lambda: P(PatientHealthTimelineView, "get", kwargs={"awpid": "AW-3ME"}, query={"from": "2030-01-01", "to": "2030-02-01"}))
        self.probe("Timeline for a patient with no data", lambda: P(PatientHealthTimelineView, "get", kwargs={"awpid": "AW-3ME"}))
        # emergency QR
        first = self.patient(PortalEmergencyTokenView, "post")
        t1 = (first.data or {}).get("token") or (first.data or {}).get("data", {}).get("token") if hasattr(first, "data") else None
        self.note("Emergency token (first)", first.status_code, str(first.data)[:160])
        second = self.patient(PortalEmergencyTokenView, "post")
        t2 = (second.data or {}).get("token") or (second.data or {}).get("data", {}).get("token")
        self.note("Emergency token (second)", second.status_code, f"same_token={t1 == t2}")
        if t1:
            r_old = self.req(EmergencySummaryView, "get", kwargs={"token": t1})
            self.note("Emergency page with the OLD token after regenerating", r_old.status_code, str(r_old.data)[:200])
        if t2:
            r_new = self.req(EmergencySummaryView, "get", kwargs={"token": t2})
            self.note("Emergency page with the NEW token (control)", r_new.status_code, f"keys={sorted((r_new.data or {}).keys()) if isinstance(r_new.data, dict) else r_new.data}")
            Patient.objects.using("default").filter(pk=self.me.pk).update(is_active=False)
            r_off = self.req(EmergencySummaryView, "get", kwargs={"token": t2})
            self.note("Emergency page for a deactivated patient", r_off.status_code, str(r_off.data)[:200])

    # ---- billing
    def test_billing(self):
        from apps.billing.models import BillingItem, Invoice
        from apps.billing.views import (BillingServiceListView, BillingServiceUploadView, BillingSummaryView, InvoiceItemCreateView, InvoicePDFView,
                                        PaymentCreateView, PaymentModeListCreateView, PaymentModeDetailView, RevenueReportView,
                                        ServiceCategoryDetailView, ServiceCategoryListCreateView)
        from django.core.files.uploadedfile import SimpleUploadedFile
        db = self.hospital_alias
        A = lambda v, m, d=None, **k: self.req(v, m, d, role="hospital_admin", **k)
        self.probe("Service create (control)", lambda: A(BillingServiceListView, "post", {"name": "X-ray", "code": "XR1", "unit_price": "300"}))
        self.probe("Service create with a duplicate code", lambda: A(BillingServiceListView, "post", {"name": "X-ray 2", "code": "XR1", "unit_price": "300"}))
        self.probe("Service create with a negative price", lambda: A(BillingServiceListView, "post", {"name": "Neg", "code": "NG1", "unit_price": "-5"}))
        cat = A(ServiceCategoryListCreateView, "post", {"name": "Radiology", "label": "Radiology", "value": "radiology"})
        self.note("Category create (control)", cat.status_code, str(cat.data)[:160])
        self.probe("Category create with a duplicate name", lambda: A(ServiceCategoryListCreateView, "post", {"name": "Radiology", "label": "Radiology", "value": "radiology"}))
        self.probe("Category delete that does not exist", lambda: A(ServiceCategoryDetailView, "delete", kwargs={"pk": 99999}))
        self.probe("Payment mode delete that does not exist", lambda: A(PaymentModeDetailView, "delete", kwargs={"pk": 99999}))
        for label, fname, content in [("wrong type", "a.exe", b"MZ"), ("empty file", "a.csv", b""), ("wrong columns", "a.csv", b"foo,bar\n1,2\n"), ("one bad row", "a.csv", b"name,code,unit_price\nOk,OK1,10\nBad,BD1,abc\n")]:
            self.probe(f"Service upload: {label}", lambda f=fname, c=content: self.req(BillingServiceUploadView, "post", {"file": SimpleUploadedFile(f, c)}, role="hospital_admin", fmt="multipart"))
        # invoices
        inv = Invoice.objects.using(db).create(patient=self.hp, branch=self.branch, invoice_number="I-P3", status="issued")
        self.probe("Invoice PDF with 0 items", lambda: self.req(InvoicePDFView, "get", role="front_desk", kwargs={"pk": inv.pk}))
        self.probe("Invoice PDF that does not exist", lambda: self.req(InvoicePDFView, "get", role="front_desk", kwargs={"pk": 99999}))
        big = Invoice.objects.using(db).create(patient=self.hp, branch=self.branch, invoice_number="I-P3B", status="draft")
        big.lines = [{"description": f"Line {i}", "quantity": 1, "unit_price": "10.00"} for i in range(200)]
        from apps.billing.services import recompute_invoice_totals
        recompute_invoice_totals(big, db)
        t0 = time.time()
        self.probe("Invoice PDF with 200 items", lambda: self.req(InvoicePDFView, "get", role="front_desk", kwargs={"pk": big.pk}))
        RESULTS["Invoice PDF with 200 items"]["body"] += f" | seconds={time.time() - t0:.1f}"
        # who may take payments
        self.probe("Payment taken by a nurse", lambda: self.req(PaymentCreateView, "post", {"invoice": big.pk, "amount": "5", "payment_mode": "cash"}, role="nurse", uid=self.nurse.pk))
        self.probe("Payment taken by a patient", lambda: self.req(PaymentCreateView, "post", {"invoice": big.pk, "amount": "5", "payment_mode": "cash"}, role="patient"))
        # reports
        self.probe("Revenue report with end before start", lambda: A(RevenueReportView, "get", query={"date_from": "2026-12-31", "date_to": "2026-01-01"}))
        self.probe("Revenue report with a bad date", lambda: A(RevenueReportView, "get", query={"date_from": "nope"}))
        self.probe("Revenue report over 10 years", lambda: A(RevenueReportView, "get", query={"date_from": "2016-01-01", "date_to": "2026-12-31"}))
        self.probe("Revenue report with no data", lambda: A(RevenueReportView, "get", query={"date_from": "2001-01-01", "date_to": "2001-01-02"}))
        # totals match
        a = Invoice.objects.using(db).create(patient=self.hp, branch=self.branch, invoice_number="I-SUM", status="issued", total_amount=Decimal("100"), subtotal=Decimal("100"))
        for amt in ("30", "20"):
            self.req(PaymentCreateView, "post", {"invoice": a.pk, "amount": amt, "payment_mode": "cash"}, role="front_desk")
        a.refresh_from_db(using=db)
        r = A(BillingSummaryView, "get", query={"patient_id": self.hp.pk})
        self.note("Billing summary vs invoices and payments", r.status_code, f"invoice_paid={a.paid_amount}; summary={str(getattr(r, 'data', ''))[:200]}")

    # ---- encounters and prescriptions
    def test_encounter(self):
        from apps.opd.models import OPDEncounter
        from apps.opd.views import (EncounterCreateView, EncounterDetailView, EncounterInternalNoteView, EncounterSignView, EncounterSummaryPDFView,
                                    FavouriteDeleteView, FavouriteListCreateView, FollowUpActionView, PrescriptionCreateView, PrescriptionItemView)
        D = lambda v, m, d=None, **k: self.req(v, m, d, role="doctor", uid=self.doctor.pk, **k)
        a = self.appt(status="waiting")
        r = D(EncounterCreateView, "post", {"appointment_id": str(a.pk)})
        self.note("Encounter create with nothing filled in (control)", r.status_code)
        enc = OPDEncounter.objects.using(self.hospital_alias).get(appointment=a)
        self.probe("Sign an encounter with nothing filled in", lambda: D(EncounterSignView, "post", kwargs={"pk": enc.pk}))
        self.probe("PDF of an unsigned encounter", lambda: self.req(EncounterSummaryPDFView, "get", role="doctor", uid=self.doctor.pk, kwargs={"pk": enc.pk}))
        for label, val in [("10,000 characters", "D" * 10000), ("script text", "<script>alert(1)</script>"), ("emoji", "fever 😀")]:
            self.probe(f"Assessment with {label}", lambda v=val: D(EncounterDetailView, "patch", {"assessment": v}, kwargs={"pk": enc.pk}))
        self.probe("Diagnoses as the wrong shape", lambda: D(EncounterDetailView, "patch", {"diagnoses": "not a list"}, kwargs={"pk": enc.pk}))
        self.probe("Diagnoses with a list of numbers", lambda: D(EncounterDetailView, "patch", {"diagnoses": [1, 2, 3]}, kwargs={"pk": enc.pk}))
        for label, val in [("abc", "abc"), ("-1", -1), ("0", 0), ("1.5", 1.5), ("9999999", 9999999)]:
            self.probe(f"Follow-up in {label} days", lambda v=val: D(EncounterDetailView, "patch", {"follow_up_in_days": v}, kwargs={"pk": enc.pk}))
        self.probe("Internal note with 10,000 characters", lambda: D(EncounterInternalNoteView, "post", {"internal_note": "N" * 10000, "note": "N" * 10000}, kwargs={"pk": enc.pk}))
        # prescriptions
        self.probe("Prescription for an encounter that does not exist", lambda: D(PrescriptionCreateView, "post", {"encounter_id": "00000000-0000-0000-0000-000000000000"}))
        rx = D(PrescriptionCreateView, "post", {"encounter_id": str(enc.pk)})
        self.note("Prescription create (control)", rx.status_code, str(rx.data)[:160])
        rxid = (rx.data or {}).get("opd_prescription_id") or (rx.data or {}).get("prescription_id") or (rx.data or {}).get("id")
        if rxid:
            item = lambda **d: (lambda: D(PrescriptionItemView, "post", {"drug_name": "Paracetamol", "dosage": "500mg", "frequency": "bd", "route": "oral", "duration_days": 3, "quantity": 6, **d}, kwargs={"pk": rxid}))
            self.probe("Drug item (control)", item())
            self.probe("Same drug added twice", item())
            self.probe("Drug with an empty name", item(drug_name=""))
            self.probe("Drug with a 10,000-character name", item(drug_name="X" * 10000))
            self.probe("Drug with an unknown frequency", item(frequency="whenever"))
            self.probe("Drug with a negative duration", item(duration_days=-1))
            self.probe("Drug with zero quantity", item(quantity=0))
            self.probe("Drug with a huge duration", item(duration_days=99999999999))
            self.probe("Drug with script text in the instructions", item(instructions="<script>alert(1)</script>"))
            with mock.patch("apps.opd.views._store_prescription_pdf"):
                OPDEncounter.objects.using(self.hospital_alias).filter(pk=enc.pk).update(assessment="ok", diagnoses=[{"code": "B34.9", "description": "Viral"}])
                self.note("Sign (control)", D(EncounterSignView, "post", kwargs={"pk": enc.pk}).status_code)
            self.probe("Add a drug to a signed prescription", item(drug_name="Ibuprofen"))
            self.probe("Edit a signed encounter's follow-up", lambda: D(FollowUpActionView, "post", {"mode": "book", "days": 5}, kwargs={"pk": enc.pk}))
        # favourites
        fav = lambda name: (lambda: D(FavouriteListCreateView, "post", {"name": name, "items": [{"drug_name": "Paracetamol", "dosage": "500mg", "frequency": "bd"}]}))
        self.probe("Favourite (control)", fav("Fever"))
        self.probe("Favourite with the same name again", fav("Fever"))
        self.probe("Favourite with a blank name", fav(""))
        self.probe("Favourite deleted by another doctor", lambda: self.req(FavouriteDeleteView, "delete", role="doctor", uid=self.doctor2.pk, kwargs={"pk": "00000000-0000-0000-0000-000000000000"}))

    # ---- who can see what
    def test_staff_and_structure(self):
        from apps.hospital_patients.views import PatientDetailView, PatientFamilyTreeView, PatientRegisterView
        from apps.hospital_setup.facility_views import BranchListCreateView, DepartmentListCreateView, RoomListCreateView
        from apps.hospital_setup.staff_views import RoleDetailView, RoleListCreateView, StaffDetailView, StaffInviteView, StaffResendInviteView
        A = lambda v, m, d=None, **k: self.req(v, m, d, role="hospital_admin", uid=self.admin.pk, **k)
        inv = lambda **d: (lambda: A(StaffInviteView, "post", {"phone": "9000000071", "first_name": "New", "role": "nurse", **d}))
        self.probe("Staff invite (control)", inv())
        self.probe("Staff invite with the same phone again", inv())
        self.probe("Staff invite with an invalid email", inv(phone="9000000072", email="not-an-email"))
        self.probe("Staff invite with a short phone", inv(phone="123"))
        self.probe("Staff invite with a role that does not exist", inv(phone="9000000073", role="emperor"))
        self.probe("Staff invite with a 10,000-character name", inv(phone="9000000074", first_name="N" * 10000))
        self.probe("Staff invite with script text as the name", inv(phone="9000000075", first_name="<script>alert(1)</script>"))
        self.probe("Resend invite to an active user", lambda: A(StaffResendInviteView, "post", kwargs={"pk": self.nurse.pk}))
        self.probe("Deactivate the only admin", lambda: A(StaffDetailView, "patch", {"is_active": False}, kwargs={"pk": self.admin.pk}))
        self.probe("Staff detail that does not exist", lambda: A(StaffDetailView, "get", kwargs={"pk": 99999}))
        self.probe("Role with no permissions (control)", lambda: A(RoleListCreateView, "post", {"name": "Empty role", "permissions": []}))
        self.probe("Role with the same name again", lambda: A(RoleListCreateView, "post", {"name": "Empty role", "permissions": []}))
        self.probe("Role delete that does not exist", lambda: A(RoleDetailView, "delete", kwargs={"pk": 99999}))
        self.probe("Branch (control)", lambda: A(BranchListCreateView, "post", {"name": "North"}))
        self.probe("Branch with the same name again", lambda: A(BranchListCreateView, "post", {"name": "North"}))
        self.probe("Branch with a blank name", lambda: A(BranchListCreateView, "post", {"name": ""}))
        self.probe("Branch with a 10,000-character name", lambda: A(BranchListCreateView, "post", {"name": "B" * 10000}))
        self.probe("Department (control)", lambda: A(DepartmentListCreateView, "post", {"name": "Dermatology"}))
        self.probe("Department with the same name again", lambda: A(DepartmentListCreateView, "post", {"name": "Dermatology"}))
        self.probe("Room (control)", lambda: A(RoomListCreateView, "post", {"name": "R1", "room_number": "R1", "branch": self.branch.pk}))
        self.probe("Room with the same number again", lambda: A(RoomListCreateView, "post", {"name": "R1", "room_number": "R1", "branch": self.branch.pk}))
        # patients
        self.probe("Patient detail that does not exist", lambda: self.req(PatientDetailView, "get", role="front_desk", kwargs={"pk": 99999}))
        self.probe("Patient registered by a nurse", lambda: self.req(PatientRegisterView, "post", {"full_name": "Nurse Reg", "mobile": "9555555551", "branch_id": self.branch.pk}, role="nurse", uid=self.nurse.pk))
        self.probe("Patient registered by a patient account", lambda: self.req(PatientRegisterView, "post", {"full_name": "Pat Reg", "mobile": "9555555552", "branch_id": self.branch.pk}, role="patient"))
        self.probe("Family tree with nothing sent", lambda: self.req(PatientFamilyTreeView, "get", role="front_desk"))
        # staff cross-hospital
        self.probe("Staff list of this hospital (control)", lambda: A(StaffInviteView, "get"))

    # ---- dates, volumes
    def test_dates_and_volume(self):
        from core.utils import age_years_months
        from apps.documents.services.clinical_rules import age_in_months
        from apps.documents.services.immunization import immunization_status
        from apps.opd.views import AppointmentListCreateView
        today = dt.date.today()
        self.note("Age of a newborn of 0 days", 200, str(age_years_months(today)))
        self.note("Age in months of a newborn of 0 days", 200, age_in_months(today, today))
        try:
            st = immunization_status(today, [], today)
            self.note("Immunization status for a newborn of 0 days", 200, f"rows={len(st['rows'])}")
        except Exception as e:
            self.note("Immunization status for a newborn of 0 days", "EXCEPTION", repr(e))
        leap = dt.date(2020, 2, 29)
        self.note("Age in months on 28 Feb and 1 Mar of a leap-day baby", 200, f"{age_in_months(leap, dt.date(2025, 2, 28)):.2f} / {age_in_months(leap, dt.date(2025, 3, 1)):.2f}")
        try:
            imm = immunization_status(leap, [], dt.date(2025, 3, 1))
            self.note("Immunization status for a leap-day baby", 200, f"rows={len(imm['rows'])}")
        except Exception as e:
            self.note("Immunization status for a leap-day baby", "EXCEPTION", repr(e))
        for t in ("23:59", "00:00"):
            self.probe(f"Appointment at {t}", lambda t=t: self.req(AppointmentListCreateView, "post", {"patient_id": self.hp.pk, "doctor_id": self.doctor.pk, "scheduled_date": str(today + dt.timedelta(days=3)), "scheduled_time": t}, role="front_desk"))
        # volume: 3,000 appointments, then the day's list and a search
        from apps.opd.models import Appointment
        rows = [Appointment(patient=self.hp, doctor=self.doctor, branch_department=self.place, scheduled_date=today, token_number=1000 + i) for i in range(3000)]
        Appointment.objects.using(self.hospital_alias).bulk_create(rows, batch_size=500)
        for label, fn in [("day list of 3,000 appointments", lambda: self.req(AppointmentListCreateView, "get", role="front_desk", query={"page_size": 100}))]:
            t0 = time.time()
            r = fn()
            self.note(f"Volume: {label}", r.status_code, f"seconds={time.time() - t0:.2f}")
