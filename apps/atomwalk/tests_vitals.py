"""How a visit's vitals are split between vitals and growth_measurement and read back together (apps/atomwalk/vitals.py)."""
import datetime as dt
import uuid
from decimal import Decimal

from django.test import TestCase

from apps.atomwalk import vitals
from apps.atomwalk.models import GrowthMeasurement, Patient, Vitals
from core.testing import ensure_hospital

FORM = {"systolic_bp": 110, "diastolic_bp": 70, "pulse_rate": 90, "temperature": Decimal("98.6"),
        "height_cm": Decimal("85"), "weight_kg": Decimal("12"), "head_circumference_cm": Decimal("47"), "nurse_notes": "calm"}


class VisitVitalsTests(TestCase):
    databases = {"default"}

    def setUp(self):
        ensure_hospital(1)
        ensure_hospital(2)
        self.patient = Patient.objects.using("default").create(awpid="AW-V1", full_name="V One")
        self.visit = uuid.uuid4()

    def save(self, data=FORM, *, minor, visit=None):
        return vitals.save_visit(self.patient, visit or self.visit, 1, None, dict(data), is_minor=minor)

    def test_an_adult_visit_is_one_vitals_row_with_height_and_weight(self):
        merged = self.save(minor=False)
        row = Vitals.objects.get()
        self.assertEqual((row.systolic_bp, row.height_cm, row.weight_kg, row.bmi), (110, Decimal("85.0"), Decimal("12.0"), Decimal("16.6")))
        self.assertFalse(GrowthMeasurement.objects.exists())
        self.assertIsNone(merged.head_circumference_cm)             # an adult's head size is not kept

    def test_a_child_visit_writes_a_row_in_each_table_and_reads_back_as_one(self):
        merged = self.save(minor=True)
        self.assertEqual((Vitals.objects.get().systolic_bp, Vitals.objects.get().height_cm), (110, None))
        growth = GrowthMeasurement.objects.get()
        self.assertEqual((growth.height_cm, growth.weight_kg, growth.head_circumference_cm, growth.measured_on),
                         (Decimal("85.0"), Decimal("12.000"), Decimal("47.0"), dt.date.today()))
        self.assertEqual((merged.systolic_bp, merged.height_cm, merged.weight_kg, merged.head_circumference_cm, merged.nurse_notes),
                         (110, Decimal("85.0"), Decimal("12.000"), Decimal("47.0"), "calm"))

    def test_saving_a_visit_again_updates_it_and_clearing_growth_removes_the_row(self):
        self.save(minor=True)
        self.save({"pulse_rate": 100, "height_cm": None, "weight_kg": None, "head_circumference_cm": None}, minor=True)
        self.assertEqual((Vitals.objects.count(), Vitals.objects.get().pulse_rate, GrowthMeasurement.objects.count()), (1, 100, 0))

    def test_a_visit_with_no_growth_fields_creates_no_growth_row(self):
        self.save({"pulse_rate": 80}, minor=True)
        self.assertFalse(GrowthMeasurement.objects.exists())

    def test_visits_and_their_vitals_are_looked_up_together(self):
        other = uuid.uuid4()
        self.save(minor=True)
        self.save({"pulse_rate": 70}, minor=False, visit=other)
        found = vitals.visits_vitals([self.visit, other, uuid.uuid4()])
        self.assertEqual(set(found), {self.visit, other})
        self.assertEqual(vitals.recorded([self.visit, uuid.uuid4()]), {self.visit})
        self.assertIsNone(vitals.visit_vitals(uuid.uuid4()))

    def test_history_readings_use_the_names_the_history_screens_read(self):
        self.save(minor=True)
        (reading,) = vitals.history_readings("AW-V1")
        self.assertEqual((reading["bp_systolic"], reading["bp_diastolic"], reading["weight_kg"], reading["head_circumference_cm"], reading["source"]),
                         (110, 70, Decimal("12.000"), Decimal("47.0"), "clinic"))
        self.assertNotIn("source_hospital_id", reading)

    def test_growth_points_are_one_per_day_and_say_whose_they_are(self):
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 1, 1), weight_kg=Decimal("10"), source_hospital_id=1)
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 2, 1), weight_kg=Decimal("11"), source_hospital_id=2)
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 3, 1), weight_kg=Decimal("12"), source_hospital_id=1, is_rejected=True)
        GrowthMeasurement.objects.create(patient=self.patient, measured_on=dt.date(2026, 4, 1), source_hospital_id=1)       # nothing measured
        mine = vitals.growth_points("AW-V1", hospital_id=1, include_other=False)
        self.assertEqual([(p["date"], p["source"]) for p in mine], [("2026-01-01", "this_hospital")])
        both = vitals.growth_points("AW-V1", hospital_id=1)
        self.assertEqual([p["source"] for p in both], ["this_hospital", "other_hospital"])
        self.assertEqual([p["source"] for p in vitals.growth_points("AW-V1")], ["clinic", "clinic"])

    def test_an_adults_height_and_weight_also_reach_the_growth_chart(self):
        self.save({"height_cm": Decimal("170"), "weight_kg": Decimal("70")}, minor=False)
        (point,) = vitals.growth_points("AW-V1", hospital_id=1)
        self.assertEqual((point["height_cm"], point["weight_kg"], point["bmi"]), (170.0, 70.0, 24.2))
