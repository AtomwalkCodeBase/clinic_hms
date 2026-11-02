"""core/tests/tests_destructive_probe.py — tries the risky cases from docs/Destructive_Test_Cases.xlsx against the real views and records what happens.

Each probe stores the status code it got (or the exception it raised) under the case's name. Nothing here asserts a pass or fail; the
results are written to the file named by the PROBE_OUT environment variable and compared with the spreadsheet afterwards."""

import datetime as dt
import json
import os
from decimal import Decimal
from unittest import mock

from core.tests.testing import HospitalDBTestCase, make_branch, make_patient, make_staff, requires_hospital_db

RESULTS = {}


def code(resp):
    return resp.status_code


@requires_hospital_db
class DestructiveProbes(HospitalDBTestCase):
    @classmethod
    def tearDownClass(cls):
        out = os.environ.get("PROBE_OUT")
        if out:
            with open(out, "w", encoding="utf8") as f:
                json.dump(RESULTS, f, indent=1, sort_keys=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        from apps.hospital_master.models import Hospital, HospitalParameters
        from apps.hospital_setup.models import NextNumber

        db = self.hospital_alias
        self.hospital = Hospital.objects.using("default").create(name="Probe H", hospital_code="probe-h", db_name=db)
        HospitalParameters.objects.using("default").create(hospital=self.hospital, default_tax_rate=Decimal("0"))
        self.branch, self.place = make_branch(db)
        self.doctor = make_staff(db, "doctor", email="dr.probe@example.test", phone="9000000031", place=self.place)
        self.other_doctor = make_staff(db, "doctor", email="dr.two@example.test", phone="9000000032", place=self.place)
        self.patient = make_patient(db, "AW-PRB-1", uhid="UP1", branch=self.branch, full_name="Probe One")
        NextNumber.objects.using(db).create(branch_id=self.branch.pk, entity="invoice", prefix="INV-")

    # helpers
    def call(self, view, method, data=None, *, role, user_id=None, kwargs=None):
        return self.call_view(view.as_view(), method, "/x/", user_id=user_id or self.doctor.pk, role=role, data=data,
                              hospital_id=self.hospital.pk, view_kwargs=kwargs)

    def probe(self, name, fn):
        from django.db import transaction
        try:
            with transaction.atomic(using=self.hospital_alias):
                r = fn()
            RESULTS[name] = {"status": r.status_code, "body": str(getattr(r, "data", ""))[:200]}
        except Exception as e:                     # an uncaught error is what a patient would see as a 500
            RESULTS[name] = {"status": "EXCEPTION", "body": f"{type(e).__name__}: {str(e)[:160]}"}

    def appt(self, **kw):
        from apps.opd.models import Appointment
        kw.setdefault("scheduled_date", dt.date.today())
        return Appointment.objects.using(self.hospital_alias).create(
            patient=self.patient, doctor=self.doctor, branch_department=self.place, **kw)

    def booking(self, **extra):
        from apps.opd.views import AppointmentListCreateView
        data = {"patient_id": self.patient.pk, "doctor_id": self.doctor.pk, **extra}
        return self.call(AppointmentListCreateView, "post", data, role="front_desk")

    # appointments
    def test_appointments(self):
        from apps.opd.views import AppointmentListCreateView, AppointmentRescheduleView, AppointmentStatusView
        t = dt.date.today()
        self.probe("Book in the past", lambda: self.booking(scheduled_date=str(t - dt.timedelta(days=30))))
        self.probe("Book the same doctor twice on one day (first)", lambda: self.booking(scheduled_date=str(t + dt.timedelta(days=1))))
        self.probe("Book the same doctor twice on one day", lambda: self.booking(scheduled_date=str(t + dt.timedelta(days=1))))
        self.probe("Double-book the same doctor and slot (first)", lambda: self.booking(scheduled_date=str(t + dt.timedelta(days=2)), scheduled_time="10:00"))
        self.probe("Double-book the same doctor and slot", lambda: self.booking(scheduled_date=str(t + dt.timedelta(days=2)), scheduled_time="10:00"))
        self.probe("Book with a doctor ID that does not exist", lambda: self.call(AppointmentListCreateView, "post", {"patient_id": self.patient.pk, "doctor_id": 99999}, role="front_desk"))
        self.probe("Book with a patient ID that does not exist", lambda: self.call(AppointmentListCreateView, "post", {"patient_id": 99999, "doctor_id": self.doctor.pk}, role="front_desk"))
        self.probe("Book with missing fields", lambda: self.call(AppointmentListCreateView, "post", {}, role="front_desk"))
        self.probe("Book with text in a number field", lambda: self.call(AppointmentListCreateView, "post", {"patient_id": "abc", "doctor_id": "x"}, role="front_desk"))
        self.probe("Book with an unconfigured appointment type", lambda: self.booking(appointment_type="nonsense"))

        from django.utils import timezone as _tz; done = self.appt(status="done", started_at=_tz.now(), completed_at=_tz.now())
        self.probe("Status moved backwards (completed to booked)", lambda: self.call(AppointmentStatusView, "post", {"status": "scheduled"}, role="front_desk", kwargs={"pk": done.pk}))
        sched = self.appt(status="scheduled")
        self.probe("Status skipping steps (booked straight to completed)", lambda: self.call(AppointmentStatusView, "post", {"status": "done"}, role="front_desk", kwargs={"pk": sched.pk}))
        self.probe("Status with an invalid value", lambda: self.call(AppointmentStatusView, "post", {"status": "banana"}, role="front_desk", kwargs={"pk": sched.pk}))
        waiting = self.appt(status="waiting")
        self.probe("Check the same patient in twice", lambda: self.call(AppointmentStatusView, "post", {"status": "waiting"}, role="front_desk", kwargs={"pk": waiting.pk}))
        self.probe("Reschedule a completed appointment", lambda: self.call(AppointmentRescheduleView, "post", {"scheduled_date": str(t + dt.timedelta(days=3))}, role="front_desk", kwargs={"pk": done.pk}))
        self.probe("Reschedule into the past", lambda: self.call(AppointmentRescheduleView, "post", {"scheduled_date": str(t - dt.timedelta(days=5))}, role="front_desk", kwargs={"pk": sched.pk}))
        self.probe("Reschedule with a bad date", lambda: self.call(AppointmentRescheduleView, "post", {"scheduled_date": "not-a-date"}, role="front_desk", kwargs={"pk": sched.pk}))
        self.probe("Reschedule with no date", lambda: self.call(AppointmentRescheduleView, "post", {}, role="front_desk", kwargs={"pk": sched.pk}))
        self.probe("Appointment detail by an ID that does not exist", lambda: self.call(
            __import__("apps.opd.views", fromlist=["AppointmentDetailView"]).AppointmentDetailView, "get", role="front_desk",
            kwargs={"pk": "00000000-0000-0000-0000-000000000000"}))

    # vitals
    def test_vitals(self):
        from apps.opd.views import VitalsView
        a = self.appt(status="waiting")

        def v(**d):
            return lambda: self.call(VitalsView, "post", d, role="nurse", kwargs={"pk": a.pk})
        self.probe("Temperature 200", v(temperature="200"))
        self.probe("Temperature -5", v(temperature="-5"))
        self.probe("Pulse 0", v(pulse_rate=0))
        self.probe("Pulse 999", v(pulse_rate=999))
        self.probe("Systolic lower than diastolic", v(systolic_bp=60, diastolic_bp=120))
        self.probe("Negative weight", v(weight_kg="-10"))
        self.probe("Zero height", v(height_cm="0"))
        self.probe("Letters in numeric fields", v(pulse_rate="abc"))
        b = self.appt(status="scheduled")
        self.probe("All vitals blank", lambda: self.call(VitalsView, "post", {}, role="nurse", kwargs={"pk": b.pk}))
        c = self.appt(status="cancelled")
        self.probe("Vitals for a cancelled appointment", lambda: self.call(VitalsView, "post", {"pulse_rate": 80}, role="nurse", kwargs={"pk": c.pk}))
        self.probe("Vitals for an appointment that does not exist", lambda: self.call(VitalsView, "post", {"pulse_rate": 80}, role="nurse", kwargs={"pk": "00000000-0000-0000-0000-000000000000"}))
        self.probe("Vitals by a front-desk user", lambda: self.call(VitalsView, "post", {"pulse_rate": 80}, role="front_desk", kwargs={"pk": a.pk}))
        self.probe("Vitals by a patient", lambda: self.call(VitalsView, "post", {"pulse_rate": 80}, role="patient", kwargs={"pk": a.pk}))
        self.probe("Save vitals twice (first)", v(pulse_rate=70))
        self.probe("Save vitals twice", v(pulse_rate=71))

    # encounters
    def test_encounters(self):
        from apps.opd.models import OPDEncounter
        from apps.opd.views import EncounterCreateView, EncounterDetailView, EncounterSignView
        a = self.appt(status="waiting")

        def create(appt, role="doctor", uid=None):
            return lambda: self.call(EncounterCreateView, "post", {"appointment_id": str(appt.pk), "assessment": "x"}, role=role, user_id=uid or self.doctor.pk)
        self.probe("Start an encounter (first)", create(a))
        self.probe("Start a second encounter for the same appointment", create(a))
        canc = self.appt(status="cancelled")
        self.probe("Start an encounter for a cancelled appointment", create(canc))
        other = self.appt(status="waiting")
        self.probe("Start an encounter for another doctor's appointment", create(other, uid=self.other_doctor.pk))
        self.probe("Start an encounter as a nurse", create(self.appt(status="waiting"), role="nurse"))
        self.probe("Start an encounter with no appointment", lambda: self.call(EncounterCreateView, "post", {}, role="doctor", user_id=self.doctor.pk))

        e = OPDEncounter.objects.using(self.hospital_alias).filter(appointment=a).first()
        if e:
            self.probe("Edit then sign an empty encounter", lambda: self.call(EncounterSignView, "post", role="doctor", user_id=self.doctor.pk, kwargs={"pk": e.pk}))
            e.assessment = "ok"
            e.diagnoses = [{"code": "B34.9", "description": "Viral"}]
            e.save(using=self.hospital_alias)
            with mock.patch("apps.opd.views._store_prescription_pdf"):
                self.probe("Sign (first)", lambda: self.call(EncounterSignView, "post", role="doctor", user_id=self.doctor.pk, kwargs={"pk": e.pk}))
                self.probe("Sign twice", lambda: self.call(EncounterSignView, "post", role="doctor", user_id=self.doctor.pk, kwargs={"pk": e.pk}))
            self.probe("Edit an encounter after signing", lambda: self.call(EncounterDetailView, "patch", {"assessment": "changed"}, role="doctor", user_id=self.doctor.pk, kwargs={"pk": e.pk}))
            self.probe("Read an encounter as a front-desk user", lambda: self.call(EncounterDetailView, "get", role="front_desk", kwargs={"pk": e.pk}))

    # billing
    def test_billing(self):
        from apps.billing.models import Invoice
        from apps.billing.views import InvoiceDetailView, InvoiceItemCreateView, InvoiceListCreateView, PaymentCreateView
        db = self.hospital_alias

        def inv(total="100", status="issued"):
            return Invoice.objects.using(db).create(patient=self.patient, branch=self.branch, invoice_number=f"I-{Invoice.objects.using(db).count()}",
                                                    total_amount=Decimal(total), status=status)

        def pay(i, amount, ref=""):
            return lambda: self.call(PaymentCreateView, "post", {"invoice": i.pk, "amount": amount, "payment_mode": "cash", "transaction_ref": ref}, role="front_desk")
        a = inv()
        self.probe("Payment larger than the balance", pay(a, "500"))
        self.probe("Payment of zero", pay(a, "0"))
        self.probe("Payment negative", pay(a, "-5"))
        self.probe("Payment with text amount", pay(a, "abc"))
        self.probe("Payment with 4 decimals", pay(a, "10.1234"))
        self.probe("Payment huge", pay(a, "99999999999999"))
        self.probe("Payment on an invoice that does not exist", lambda: self.call(PaymentCreateView, "post", {"invoice": 99999, "amount": "5", "payment_mode": "cash"}, role="front_desk"))
        self.probe("Payment (first, with reference)", pay(a, "10", "R1"))
        self.probe("Payment same reference again", pay(a, "10", "R1"))
        self.probe("Payment same amount no reference (second)", pay(a, "10"))
        self.probe("Payment same amount no reference (third)", pay(a, "10"))
        full = inv("50")
        pay(full, "50")()
        self.probe("Payment on a fully paid invoice", pay(full, "1"))
        cancelled = inv("100", status="cancelled")
        self.probe("Payment on a cancelled invoice", pay(cancelled, "10"))

        d = inv()
        self.probe("Negative discount", lambda: self.call(InvoiceDetailView, "patch", {"discount_amount": "-50"}, role="front_desk", kwargs={"pk": d.pk}))
        self.probe("Discount bigger than the total", lambda: self.call(InvoiceDetailView, "patch", {"discount_amount": "5000"}, role="front_desk", kwargs={"pk": d.pk}))
        self.probe("Discount as text", lambda: self.call(InvoiceDetailView, "patch", {"discount_amount": "abc"}, role="front_desk", kwargs={"pk": d.pk}))
        self.probe("Discount on a paid invoice", lambda: self.call(InvoiceDetailView, "patch", {"discount_amount": "10"}, role="front_desk", kwargs={"pk": full.pk}))
        self.probe("Cancel a paid invoice", lambda: self.call(InvoiceDetailView, "patch", {"status": "cancelled"}, role="front_desk", kwargs={"pk": full.pk}))
        self.probe("Invoice that does not exist", lambda: self.call(InvoiceDetailView, "get", role="front_desk", kwargs={"pk": 99999}))

        def item(i, **d):
            return lambda: self.call(InvoiceItemCreateView, "post", d, role="front_desk", kwargs={"pk": i.pk})
        draft = inv("0", status="draft")
        self.probe("Invoice item zero quantity", item(draft, description="x", quantity=0, unit_price="10"))
        self.probe("Invoice item negative quantity", item(draft, description="x", quantity=-1, unit_price="10"))
        self.probe("Invoice item negative price", item(draft, description="x", quantity=1, unit_price="-10"))
        self.probe("Invoice item huge price", item(draft, description="x", quantity=1, unit_price="99999999999"))
        self.probe("Invoice item 500-character description", item(draft, description="x" * 500, quantity=1, unit_price="10"))
        self.probe("Invoice item to a cancelled invoice", item(cancelled, description="x", quantity=1, unit_price="10"))
        self.probe("Invoice item to a paid invoice", item(full, description="x", quantity=1, unit_price="10"))
        self.probe("Create invoice with no patient", lambda: self.call(InvoiceListCreateView, "post", {}, role="front_desk"))

    # patient registration (front desk)
    def test_registration(self):
        from apps.hospital_patients.views import PatientRegisterView

        def reg(**d):
            base = {"full_name": "Reg Test", "mobile": "9876543210", "branch_id": self.branch.pk}
            base.update(d)
            return lambda: self.call(PatientRegisterView, "post", base, role="front_desk")
        self.probe("Register with a future date of birth", reg(date_of_birth="2099-01-01", mobile="9876500001"))
        self.probe("Register with date of birth 150 years ago", reg(date_of_birth="1850-01-01", mobile="9876500002"))
        self.probe("Register with no mobile", reg(mobile=""))
        self.probe("Register with a 5-digit mobile", reg(mobile="12345"))
        self.probe("Register with letters in mobile", reg(mobile="abcdefghij"))
        self.probe("Register with a 10,000-character name", reg(full_name="A" * 10000, mobile="9876500003"))
        self.probe("Register with script text as name", reg(full_name="<script>alert(1)</script>", mobile="9876500004"))
        self.probe("Register with no name", reg(full_name="", mobile="9876500005"))
        self.probe("Register a dependent with no guardian", reg(is_dependent=True, mobile="", date_of_birth="2020-01-01"))
        self.probe("Register a dependent with no date of birth", reg(is_dependent=True, mobile="", guardian_awpid="AW-PRB-1"))
        self.probe("Register with an invalid gender", reg(gender="banana", mobile="9876500006"))
        self.probe("Register (first, for duplicate test)", reg(mobile="9876500007"))
        self.probe("Register same mobile and name again", reg(mobile="9876500007"))
