"""Episodes and recurrence, built from a patient's clinical events (timeline_insights/episodes.py), and the events a document gives."""
import datetime as dt
from unittest import mock

from django.test import TestCase, override_settings

from apps.atomwalk.models import ClinicalEvent, HealthEpisode, RecurrenceFlag
from apps.records.timeline_insights import episodes, extract

from .helpers import identity, make_doc

TODAY = dt.date(2026, 6, 30)


def event(patient, group, on, *, category="ACUTE", severity="NORMAL", **fields):
    return ClinicalEvent.objects.create(patient=patient, condition_group=group, condition_text=group.lower(), event_date=on,
                                        category=category, severity=severity, **fields)


class EpisodeTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.patient = identity("AWP-EP")

    def rebuild(self):
        episodes.rebuild(self.patient, today=TODAY)
        return list(HealthEpisode.objects.filter(patient=self.patient).order_by("start_date"))

    def test_a_chronic_condition_is_one_ongoing_episode(self):
        event(self.patient, "ASTHMA", dt.date(2024, 1, 5), category="CHRONIC")
        event(self.patient, "ASTHMA", dt.date(2026, 3, 1), category="CHRONIC", severity="MILD")
        (episode,) = self.rebuild()
        self.assertEqual((episode.key, episode.start_date, episode.last_seen, episode.end_date, episode.event_count, episode.peak_severity),
                         ("ASTHMA", dt.date(2024, 1, 5), dt.date(2026, 3, 1), None, 2, "MILD"))

    def test_an_acute_condition_starts_a_new_episode_after_a_gap(self):
        event(self.patient, "URTI", dt.date(2026, 1, 1))
        event(self.patient, "URTI", dt.date(2026, 1, 10))          # the same illness
        event(self.patient, "URTI", dt.date(2026, 3, 1))           # a new one
        first, second = self.rebuild()
        self.assertEqual((first.key, first.event_count, first.end_date), ("URTI:2026-01-01", 2, dt.date(2026, 1, 10)))
        self.assertEqual((second.key, second.event_count), ("URTI:2026-03-01", 1))
        self.assertEqual(ClinicalEvent.objects.get(event_date=dt.date(2026, 3, 1)).episode_id, second.id)

    def test_three_episodes_in_a_year_raise_a_recurrence_flag_fewer_do_not(self):
        for month in (1, 3):
            event(self.patient, "URTI", dt.date(2026, month, 1))
        self.rebuild()
        self.assertFalse(RecurrenceFlag.objects.exists())
        event(self.patient, "URTI", dt.date(2026, 5, 1))
        self.rebuild()
        flag = RecurrenceFlag.objects.get()
        self.assertEqual((flag.condition_group, flag.episodes_last_12m), ("URTI", 3))

    def test_old_episodes_do_not_count_towards_recurrence(self):
        for day in (dt.date(2024, 1, 1), dt.date(2024, 3, 1), dt.date(2024, 5, 1)):
            event(self.patient, "URTI", day)
        self.rebuild()
        self.assertFalse(RecurrenceFlag.objects.exists())

    def test_a_rejected_event_is_left_out_and_rebuilding_twice_changes_nothing(self):
        event(self.patient, "URTI", dt.date(2026, 1, 1))
        event(self.patient, "URTI", dt.date(2026, 1, 5), is_rejected=True)
        self.assertEqual([e.event_count for e in self.rebuild()], [1])
        self.assertEqual([e.event_count for e in self.rebuild()], [1])
        self.assertEqual(HealthEpisode.objects.count(), 1)

    def test_an_episode_whose_events_are_gone_is_removed(self):
        gone = event(self.patient, "URTI", dt.date(2026, 1, 1))
        self.rebuild()
        gone.delete()
        self.assertEqual(self.rebuild(), [])

    def test_the_group_is_the_icd_category_or_else_the_name(self):
        self.assertEqual(episodes.condition_group("J06.9", "Acute URI"), "J06")
        self.assertEqual(episodes.condition_group("", "Asthma"), "ASTHMA")


@override_settings(RECORDS_REVIEW_FROM="2000-01-01T00:00:00+00:00")
class ExtractedEventTests(TestCase):
    databases = {"default"}

    def read(self, text, **fields):
        doc = make_doc("AWP-EX", status="completed", document_type="lab_report", by="human", text=text, **fields)
        extract.run_insights(doc.id)
        return doc

    def test_a_condition_in_a_document_becomes_a_clinical_event_of_the_patient(self):
        doc = self.read("Date: 10/01/2026" + chr(10) + "Diabetes. Fever.")
        events = ClinicalEvent.objects.filter(document=doc)
        found = events.get(condition_text="diabetes mellitus")
        self.assertEqual((found.patient.awpid, found.event_date, found.source, found.category), ("AWP-EX", dt.date(2026, 1, 10), "EXTRACTED", "CHRONIC"))
        self.assertTrue(HealthEpisode.objects.filter(patient=found.patient, condition_group="DIABETES MELLITUS").exists())

    def test_symptoms_and_denied_conditions_are_not_events(self):
        doc = self.read("Date: 10/01/2026" + chr(10) + "Fever. No diabetes.")
        self.assertFalse(ClinicalEvent.objects.filter(document=doc).exists())

    def test_reading_again_keeps_one_event_and_a_persons_verdict(self):
        doc = self.read("Date: 10/01/2026" + chr(10) + "Diabetes.")
        ClinicalEvent.objects.filter(document=doc).update(is_rejected=True)
        extract.run_insights(doc.id)
        events = ClinicalEvent.objects.filter(document=doc)
        self.assertEqual([e.is_rejected for e in events], [True])        # not brought back, not duplicated

    def test_a_finished_reading_marks_the_extraction_done(self):
        doc = self.read("Date: 10/01/2026" + chr(10) + "Diabetes.")
        self.assertEqual(doc.extraction.status, "done")
        self.assertEqual(doc.extraction.extractor_version, extract.EXTRACTOR_VERSION)
        with mock.patch.object(extract, "_vocabulary", return_value={}):
            self.assertEqual(extract.build_timeline("AWP-EX"), {"days": [], "undated": []})
