"""
The calculations behind the growth chart and the roadmaps, with the numbers written out so they can be read and checked:
  - WHO percentiles: growth_reference.py
  - When a vaccine or milestone is "upcoming", "due now" or "past window": roadmap.py
  - Which records a roadmap shows, and the counts above it: vaccine_schedule.py
Run:  python manage.py test apps.hospital_patients.pediatrics.tests_calculations -v 2
"""
import datetime as dt
from datetime import timedelta

from django.test import SimpleTestCase, TestCase

from apps.hospital_patients.pediatrics import growth_reference as who
from apps.hospital_patients.pediatrics import roadmap
from apps.hospital_patients.pediatrics.vaccine_schedule import build_roadmap, summarize_roadmap
from apps.atomwalk.models import ImmunizationRecord, Patient, Schedule, ScheduleRule

V = ImmunizationRecord


def value_at_z(measurement, sex, age_months, z):
    """The measurement a child would have to show to sit exactly at z (the formula run backwards)."""
    L, M, S = who._lms(measurement, sex, age_months)
    return M * (1 + z * L * S) ** (1 / L)


class PercentileTests(SimpleTestCase):
    def test_the_published_median_is_the_50th_percentile(self):
        # WHO median weight for a girl at 12 months is 8.9481 kg (the M column of the table)
        result = who.get_percentile("weight", "F", 12, 8.9481)
        self.assertEqual((result["z_score"], result["percentile"]), (0.0, 50.0))

    def test_every_checkpoint_median_scores_50(self):
        for measurement, by_sex in who.REFERENCE_TABLES.items():
            for sex, rows in by_sex.items():
                for age, _L, M, _S in rows:
                    self.assertEqual(who.get_percentile(measurement, sex, age, M)["percentile"], 50.0, (measurement, sex, age))

    def test_the_3rd_and_97th_percentile_values_score_3_and_97(self):
        # z = -1.881 and +1.881 are the lines WHO draws as the 3rd and 97th percentile curves
        for measurement in who.MEASUREMENTS:
            for sex in ("M", "F"):
                for age in (0, 6, 18, 36, 60):
                    low = who.get_percentile(measurement, sex, age, value_at_z(measurement, sex, age, -1.881))["percentile"]
                    high = who.get_percentile(measurement, sex, age, value_at_z(measurement, sex, age, 1.881))["percentile"]
                    self.assertAlmostEqual(low, 3.0, delta=0.1, msg=(measurement, sex, age))
                    self.assertAlmostEqual(high, 97.0, delta=0.1, msg=(measurement, sex, age))

    def test_a_heavier_child_scores_higher(self):
        scores = [who.get_percentile("weight", "M", 24, kg)["percentile"] for kg in (9, 10, 11, 12.1515, 13, 14, 16)]
        self.assertEqual(scores, sorted(scores))
        self.assertEqual(scores[3], 50.0)                      # 12.1515 kg is the boys' median at 24 months

    def test_between_two_checkpoints_the_reference_is_interpolated(self):
        low, high = who._lms("weight", "F", 3), who._lms("weight", "F", 6)
        middle = who._lms("weight", "F", 4.5)
        for a, b, mid in zip(low, high, middle):
            self.assertAlmostEqual(mid, (a + b) / 2, places=9)

    def test_out_of_range_inputs_give_no_percentile(self):
        self.assertIsNone(who.get_percentile("weight", "F", -1, 5))        # not born yet
        self.assertIsNone(who.get_percentile("weight", "F", 61, 20))       # WHO tables stop at 60 months
        self.assertIsNone(who.get_percentile("weight", "O", 12, 9))        # no table for another sex
        self.assertIsNone(who.get_percentile("weight", "F", 12, None))     # nothing measured
        self.assertIsNone(who.get_percentile("bmi", "F", 12, 9))           # not a measurement WHO covers here

    def test_a_wildly_wrong_reading_is_capped_at_5_standard_deviations(self):
        self.assertEqual(who.get_percentile("weight", "F", 12, 500)["z_score"], 5)
        self.assertEqual(who.get_percentile("weight", "F", 12, 0.5)["z_score"], -5)

    def test_the_tables_are_complete_and_in_order(self):
        for measurement in who.MEASUREMENTS:
            for sex in ("M", "F"):
                rows = who.REFERENCE_TABLES[measurement][sex]
                ages = [r[0] for r in rows]
                self.assertEqual((ages[0], ages[-1]), (0, 60), (measurement, sex))
                self.assertEqual(ages, sorted(set(ages)), (measurement, sex))
                self.assertEqual([r[2] for r in rows], sorted(r[2] for r in rows), (measurement, sex))   # the median grows with age


class AddPercentilesTests(SimpleTestCase):
    dob = dt.date(2024, 1, 15)

    def point(self, taken, source="this_hospital", weight=12.0):
        return {"date": taken, "weight_kg": weight, "height_cm": None, "head_circumference_cm": None, "source": source}

    def test_age_in_months_is_counted_from_the_date_of_birth(self):
        series = [self.point("2025-01-15"), self.point("2026-01-14")]            # 12 and 24 months
        self.assertTrue(who.add_percentiles(series, "F", self.dob))
        self.assertEqual(series[0]["percentiles"]["weight"], who.get_percentile("weight", "F", 12, 12.0))
        self.assertEqual(series[1]["percentiles"]["weight"], who.get_percentile("weight", "F", 24, 12.0))

    def test_readings_after_the_age_of_5_get_none(self):
        series = [self.point("2029-03-01")]                                      # 61 months
        self.assertFalse(who.add_percentiles(series, "F", self.dob))
        self.assertNotIn("percentiles", series[0])

    def test_only_the_wanted_source_is_scored(self):
        series = [self.point("2025-01-15"), self.point("2025-01-15", source="other_hospital")]
        who.add_percentiles(series, "M", self.dob, only_source="this_hospital")
        self.assertIn("percentiles", series[0])
        self.assertNotIn("percentiles", series[1])

    def test_no_percentiles_without_a_known_sex_or_birth_date(self):
        self.assertFalse(who.add_percentiles([self.point("2025-01-15")], "O", self.dob))
        self.assertFalse(who.add_percentiles([self.point("2025-01-15")], "F", None))


class TimingTests(SimpleTestCase):
    """roadmap.timing_for(age_days, min_age_days, max_age_days): 14 days of lead, 90 days of grace when there is no maximum."""

    def test_the_window_opens_14_days_early(self):
        self.assertEqual(roadmap.timing_for(41, 60, None), "upcoming")           # 60 - 14 = 46 is the first due day
        self.assertEqual(roadmap.timing_for(45, 60, None), "upcoming")
        self.assertEqual(roadmap.timing_for(46, 60, None), "due_now")

    def test_with_no_maximum_it_is_due_for_90_days(self):
        self.assertEqual(roadmap.timing_for(149, 60, None), "due_now")
        self.assertEqual(roadmap.timing_for(150, 60, None), "past_window")       # 60 + 90

    def test_with_a_maximum_the_window_closes_there(self):
        self.assertEqual(roadmap.timing_for(119, 60, 120), "due_now")
        self.assertEqual(roadmap.timing_for(120, 60, 120), "past_window")

    def test_no_birth_date_or_no_minimum_gives_no_timing(self):
        self.assertIsNone(roadmap.timing_for(None, 60, None))
        self.assertIsNone(roadmap.timing_for(100, None, None))


class RoadmapContentTests(TestCase):
    """build_roadmap / summarize_roadmap against the atomwalk database."""
    databases = {"default"}
    rules = [
        {"vaccine_name": "BCG", "scheduled_label": "Birth", "min_age_days": 0, "max_age_days": 30},
        {"vaccine_name": "OPV 1", "scheduled_label": "6 weeks", "min_age_days": 42, "max_age_days": None},
        {"vaccine_name": "MMR", "scheduled_label": "9 months", "min_age_days": 270, "max_age_days": None},
    ]

    def setUp(self):
        self.dob = dt.date.today() - timedelta(days=60)           # a 2-month-old

    def record(self, name="BCG", label="Birth", **fields):
        kid = Patient.objects.using("default").get_or_create(awpid="AW-K", defaults={"full_name": "Kid"})[0]
        base = dict(patient=kid, vaccine_name=name, scheduled_label=label, source=V.SOURCE_CLINIC,
                    verification_status=V.STATUS_VERIFIED, source_hospital_id=1, administered_date=dt.date.today())
        return V.objects.using("default").create(**{**base, **fields})

    def roadmap(self, **kw):
        return build_roadmap("AW-K", self.dob, self.rules, viewer_hospital_id=1, **kw)

    def test_each_slot_is_matched_to_its_own_record_once(self):
        first = self.record()
        self.record()                                             # a second BCG fits no free slot
        rows = self.roadmap()
        self.assertEqual([r["status"] for r in rows[:3]], ["completed", "unknown", "unknown"])
        self.assertEqual(rows[0]["record_id"], first.id)
        self.assertEqual([r["extra"] for r in rows], [False, False, False, True])

    def test_matching_ignores_case_and_spaces_in_the_name(self):
        self.record(name="  bcg ")
        self.assertEqual(self.roadmap()[0]["status"], "completed")

    def test_without_consent_other_hospitals_records_are_hidden_except_pending_reviews(self):
        self.record(source_hospital_id=2)                                                    # verified elsewhere: hidden
        self.record(name="OPV 1", label="6 weeks", source_hospital_id=2,
                    verification_status=V.STATUS_PENDING, source=V.SOURCE_SELF_REPORTED)   # awaiting review: shown
        self.record(name="MMR", label="9 months", source_hospital_id=None)                   # never tied to a hospital: shown
        by_name = {r["vaccine_name"]: r["status"] for r in self.roadmap(hie_consent=False)}
        self.assertEqual(by_name, {"BCG": "unknown", "OPV 1": "pending_review", "MMR": "completed"})

    def test_with_consent_everything_is_shown(self):
        self.record(source_hospital_id=2)
        self.assertEqual(self.roadmap(hie_consent=True)[0]["status"], "completed")

    def test_removing_a_schedule_rule_never_removes_a_childs_record(self):
        schedule = Schedule.objects.using("default").create(kind="vaccination", name="s")
        rule = ScheduleRule.objects.using("default").create(schedule=schedule, item="BCG", scheduled_label="Birth", min_age_days=0)
        self.record()
        rule.delete()
        self.assertEqual(V.objects.using("default").count(), 1)
        rows = build_roadmap("AW-K", self.dob, ScheduleRule.objects.using("default").filter(schedule=schedule))
        self.assertEqual([(r["vaccine_name"], r["extra"]) for r in rows], [("BCG", True)])    # still shown, as an extra record

    def test_the_counts_above_the_roadmap(self):
        self.record()                                                                         # BCG completed
        self.record(name="OPV 1", label="6 weeks", verification_status=V.STATUS_PENDING,
                    source=V.SOURCE_SELF_REPORTED)                                            # pending review (not at a clinic)
        summary = summarize_roadmap(self.roadmap())
        # 2-month-old: MMR (270 days) is not due yet; OPV 1 has a record
        self.assertEqual((summary["completed_count"], summary["total_count"]), (1, 3))
        self.assertEqual(summary["stats"], {"completed": 1, "upcoming": 1, "needs_review": 1, "outside": 1})
        self.assertIsNone(summary["next_recommended"])

    def test_the_next_recommended_dose_is_the_first_unknown_one_that_is_due(self):
        summary = summarize_roadmap(self.roadmap())
        # a 60-day-old with no records: BCG window closed at day 30, OPV 1 (day 42) is due, MMR is upcoming
        self.assertEqual(summary["next_recommended"]["vaccine_name"], "OPV 1")
        self.assertEqual(summary["stats"], {"completed": 0, "upcoming": 1, "needs_review": 2, "outside": 0})
