"""Tests of the pediatric health timeline: the rules (services.py), the database side (processing.py), its task and its views."""
import atexit
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from datetime import date, timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.dispatch import receiver
from django.test.signals import setting_changed
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.documents import tasks, views_timeline as views
from apps.documents.models import (
    Admission, BirthHistory, ClinicalEvent, DocumentExtraction, GrowthMeasurement, HealthEpisode, ImmunizationRecord, LabResult, MedicalDocument,
)
from apps.patients.models import RecurrenceFlag
from apps.patients.models import Patient, PatientRelationship
from core.api.authentication import MockUser
from apps.documents import integration as ig
from apps.documents import lib_processing
from apps.documents.services import clinical_rules, immunization
from apps.documents.services.config import load_config
from apps.documents.services import extraction as llm_rules
from apps.documents.services import episodes as episode_rules

CONFIG = {
    "age_bands": [
        {"code": "NEONATE", "min_days": 0, "max_days": 28}, {"code": "INFANT", "min_days": 29, "max_days": 364},
        {"code": "TODDLER", "min_days": 365, "max_days": 1095}, {"code": "CHILD", "min_days": 1096, "max_days": 4380},
        {"code": "ADOLESCENT", "min_days": 4381, "max_days": 6573}, {"code": "ADULT", "min_days": 6574, "max_days": 99999}],
    "default_acute_merge_days": 14,
    "condition_groups": {
        "ASTHMA": {"label": "Asthma", "category": "CHRONIC", "icd_prefixes": ["J45"], "aliases": ["asthma"]},
        "EAR_INFECTION": {"label": "Ear infection", "category": "ACUTE", "merge_days": 14, "icd_prefixes": ["H66"]},
        "URTI": {"label": "Cold", "category": "ACUTE", "merge_days": 10, "icd_prefixes": ["J06"], "aliases": ["upper respiratory", "cold"]},
        "GASTROENTERITIS": {"label": "Gastroenteritis", "category": "ACUTE", "merge_days": 7, "icd_prefixes": ["A09"], "aliases": ["gastroenteritis"]}},
    "recurrence_rules": {"EAR_INFECTION": {"windows": [{"min_count": 3, "window_months": 6}], "clinical_hint": "Consider an ENT review"}},
    "lab_thresholds": {"HEMOGLOBIN_G_DL": {"aliases": ["hemoglobin", "hb"],
                                           "NEONATE": {"critical_low": 9, "low": 13}, "DEFAULT": {"critical_low": 5, "low": 10}}},
    "critical_keywords": {"terms": ["ventilator", "intubated"]},
    "growth": {"plausible_ranges": {"weight_kg": [0.4, 150], "height_cm": [20, 220], "head_circ_cm": [20, 65]}, "who_max_months": 60,
               "flags": {"SEVERE_LOW": {"z_max": -3}, "LOW": {"z_max": -2}, "HIGH": {"z_min": 2}, "SEVERE_HIGH": {"z_min": 3}},
               "faltering_drop_z": 1, "faltering_window_months": 6},
    "immunization_schedule": {
        "source": "test schedule",
        "doses": [{"code": "BCG", "vaccine": "BCG", "dose": 1, "due_days": 0, "grace_days": 30},
                  {"code": "OPV1", "vaccine": "OPV", "dose": 1, "due_days": 42, "grace_days": 14}],
        "vaccine_aliases": {"BCG": ["bcg"], "OPV": ["opv", "polio"]}, "combination_vaccines": {}},
    "patient_labels": {"CRITICAL": "Hospital care needed", "RECURRENT": "Happens often", "ACUTE": "Short illness", "CHRONIC": "Ongoing",
                       "CRITICAL_LAB": "Needs urgent care"},
}
_config_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
json.dump(CONFIG, _config_file)
_config_file.close()
with_config = override_settings(PEDIATRIC_HEALTH_CONFIG=_config_file.name)


@receiver(setting_changed)
def _reload_config(setting, **kwargs):
    """The rules read the config once and remember it, so a test that swaps the file must clear that memory."""
    if setting == "PEDIATRIC_HEALTH_CONFIG":
        load_config.cache_clear()


atexit.register(lambda: Path(_config_file.name).unlink(missing_ok=True))      # not tearDownModule: the runner runs this module's classes in two groups


def llm_says(**facts):
    """A stand-in for the LLM: always answers with these facts."""
    return lambda system, user: json.dumps(facts)


def child(awpid="AW-KID", years=2, **fields):
    return Patient.objects.create(awpid=awpid, full_name="Kid", gender="F", date_of_birth=date.today() - timedelta(days=int(365.25 * years)), **fields)


def document(patient, text="Rx: Syrup for the child's ear. Dx: otitis media.", document_type="prescription", **fields):
    doc = MedicalDocument(patient=patient, document_ref_name="rx.pdf", status="completed", doc_classification=document_type, **fields)
    doc.file_name = "patients/AW-KID/documents/rx.pdf"
    doc.save()
    DocumentExtraction.objects.create(document=doc, extracted_text=text, engine="ocr")
    return doc


@with_config
class RulesTests(SimpleTestCase):
    def test_an_icd_code_finds_its_group_by_the_longest_prefix_and_an_unknown_one_still_gets_a_group(self):
        self.assertEqual(clinical_rules.classify_condition("J45.9")["category"], "CHRONIC")
        self.assertEqual(clinical_rules.classify_condition("h66.0")["group"], "EAR_INFECTION")
        unknown = clinical_rules.classify_condition("Z99.9")
        self.assertEqual((unknown["group"], unknown["category"], unknown["known"]), ("ICD_Z99", "ACUTE", False))

    def test_a_lab_value_is_judged_against_the_limits_of_the_childs_age_band(self):
        self.assertEqual(clinical_rules.evaluate_lab("HEMOGLOBIN_G_DL", 8, 10)["severity"], "CRITICAL")      # a newborn: below 9
        self.assertEqual(clinical_rules.evaluate_lab("HEMOGLOBIN_G_DL", 8, 500)["severity"], "ABNORMAL")      # a toddler: below 10, not 5
        self.assertEqual(clinical_rules.evaluate_lab("HEMOGLOBIN_G_DL", 12, 500)["severity"], "NORMAL")

    def test_a_critical_word_counts_unless_it_is_negated(self):
        self.assertEqual(clinical_rules.find_critical_keywords("child was intubated and on ventilator"), ["intubated", "ventilator"])
        self.assertEqual(clinical_rules.find_critical_keywords("no ventilator needed, not intubated"), [])

    def test_a_chronic_condition_is_one_open_episode_and_acute_ones_merge_inside_their_window(self):
        day = lambda n: date(2026, 1, 1) + timedelta(days=n)                                           # noqa: E731
        events = [episode_rules.EventIn(1, day(0), "J45.9"), episode_rules.EventIn(2, day(90), "J45.9"),
                  episode_rules.EventIn(3, day(0), "H66.9"), episode_rules.EventIn(4, day(10), "H66.9"), episode_rules.EventIn(5, day(60), "H66.9")]
        episodes = episode_rules.build_episodes(events)
        asthma = [e for e in episodes if e.group == "ASTHMA"]
        ears = [e for e in episodes if e.group == "EAR_INFECTION"]
        self.assertEqual((len(asthma), asthma[0].end, asthma[0].event_count), (1, None, 2))
        self.assertEqual([e.event_count for e in ears], [2, 1])

    def test_three_ear_infections_in_six_months_are_recurrent_and_a_provisional_one_does_not_count(self):
        starts = [date(2026, 1, 1), date(2026, 3, 1), date(2026, 5, 1)]
        episodes = episode_rules.build_episodes([episode_rules.EventIn(i, d, "H66.9") for i, d in enumerate(starts)])
        flag = episode_rules.detect_recurrence(episodes, date(2024, 1, 1), date(2026, 6, 1))[0]
        self.assertEqual((flag["is_recurrent"], flag["clinical_hint"]), (True, "Consider an ENT review"))
        provisional = episode_rules.build_episodes([episode_rules.EventIn(i, d, "H66.9", is_provisional=i == 2) for i, d in enumerate(starts)])
        self.assertFalse(episode_rules.detect_recurrence(provisional, date(2024, 1, 1), date(2026, 6, 1))[0]["is_recurrent"])

    def test_units_dates_and_implausible_values_are_cleaned_before_anything_is_saved(self):
        self.assertEqual(llm_rules.normalise_weight(3250, "g"), 3.25)
        self.assertEqual(llm_rules.normalise_length(0.74, "m"), 74.0)
        self.assertEqual(llm_rules.parse_date("14/03/2026"), date(2026, 3, 14))
        clean = llm_rules.normalise(
            {"document_date": "01/02/2026", "measurements": [{"measured_on": "01/02/2026", "weight": 9500, "weight_unit": "g", "height": 900, "height_unit": "cm"}],
             "diagnoses": [{"condition": "Otitis media", "icd10_guess": "h66.9", "is_provisional": True, "evidence": "? OM"},
                           {"condition": "Asthma (mother)", "is_current_patient_condition": False}]},
            date(2024, 1, 1), date(2026, 2, 5))
        self.assertEqual(clean["document_date"], date(2026, 2, 1))
        self.assertEqual((clean["measurements"][0]["weight_kg"], clean["measurements"][0]["height_cm"]), (9.5, None))
        self.assertEqual([(d["condition_text"], d["icd10"], d["is_provisional"]) for d in clean["diagnoses"]], [("Otitis media", "H66.9", True)])
        self.assertTrue(any("implausible" in w for w in clean["warnings"]))

    def test_a_birth_history_is_kept_when_it_says_something(self):
        empty = {"nicu_admission": False, "gestation_weeks": None, "birth_weight_kg": None}
        kept = llm_rules.normalise({"birth_history": {**empty, "nicu_admission": True}}, date(2024, 1, 1), date(2026, 2, 5))["birth_history"]
        self.assertTrue(kept["nicu_admission"])

    def test_a_combined_vaccine_fills_several_rows_and_an_unreadable_entry_is_listed_not_guessed(self):
        self.assertEqual(immunization.resolve_vaccines("OPV dose 1 and BCG"), ["BCG", "OPV"])
        dob = date(2026, 1, 1)
        status = immunization.immunization_status(dob, [{"vaccine_text": "BCG", "given_on": dob}, {"vaccine_text": "??", "given_on": dob, "id": 9}], date(2026, 6, 1))
        self.assertEqual({r["code"]: r["status"] for r in status["rows"]}, {"BCG": "GIVEN", "OPV1": "OVERDUE"})
        self.assertEqual([u["id"] for u in status["unresolved"]], [9])


FACTS = dict(
    document_date="2026-02-01",
    diagnoses=[{"condition": "Acute otitis media", "icd10_guess": "H66.9", "is_provisional": False, "is_current_patient_condition": True, "evidence": "Dx: AOM"},
               {"condition": "Bronchial asthma", "icd10_guess": "J45.9", "is_provisional": True, "is_current_patient_condition": True, "evidence": "? asthma"}],
    measurements=[{"measured_on": "2026-02-01", "weight": 11.2, "weight_unit": "kg", "height": 82, "height_unit": "cm"}],
    vaccines=[{"vaccine_text": "OPV 1", "given_on": "2025-12-01"}],
    labs=[{"test_name": "Hemoglobin", "value": 4.5, "unit": "g/dL", "collected_on": "2026-02-01"}],
    birth_history={"gestation_weeks": 34, "birth_weight_kg": 2.1, "nicu_admission": True, "nicu_days": 6, "delivery": "LSCS"},
    admission=None)


class LlmCallTests(SimpleTestCase):
    def reply(self, body, status=200):
        response = mock.Mock(status_code=status)
        response.json.return_value = body
        response.raise_for_status.side_effect = None if status < 400 else ValueError("http error")
        return response

    def test_the_instructions_and_the_document_go_in_one_prompt_with_the_token(self):
        with override_settings(LLM_API_STYLE="company", LLM_API_URL="https://llm.test/ask/", LLM_API_TOKEN="secret"), \
                mock.patch("requests.post", return_value=self.reply({"response": '{"diagnoses": []}'})) as post:
            self.assertEqual(ig.ask_llm("Return JSON.", "Text of the report"), '{"diagnoses": []}')
        (url,), kwargs = post.call_args
        self.assertEqual(url, "https://llm.test/ask/")
        self.assertEqual(kwargs["headers"], {"Authorization": "Token secret"})
        self.assertEqual(kwargs["json"], {"user_prompt": "Return JSON.\n\nText of the report"})

    def test_a_local_ollama_gets_the_same_prompt_in_its_own_format_and_no_token(self):
        with override_settings(LLM_API_STYLE="ollama", LLM_API_URL="http://localhost:11434/api/chat", LLM_API_MODEL="qwen"),                 mock.patch("requests.post", return_value=self.reply({"message": {"content": '{"diagnoses": []}'}})) as post:
            self.assertEqual(ig.ask_llm("Return JSON.", "Text of the report"), '{"diagnoses": []}')
        (url,), kwargs = post.call_args
        self.assertEqual(url, "http://localhost:11434/api/chat")
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "Return JSON.\n\nText of the report"}])
        self.assertEqual((kwargs["json"]["model"], kwargs["json"]["stream"], "headers" in kwargs), ("qwen", False, False))

    def test_an_error_answer_is_raised_not_read_as_facts(self):
        with override_settings(LLM_API_STYLE="company"), \
                mock.patch("requests.post", return_value=self.reply({"error": "Cannot connect to LLM server."})):
            with self.assertRaises(ValueError):
                ig.ask_llm("s", "u")


@with_config
class ProcessDocumentTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.kid = child()
        self.doc = document(self.kid)

    def process(self, **kw):
        return lib_processing.process_document(self.doc, llm=llm_says(**{**FACTS, **kw}))

    def test_a_hospital_issued_document_with_no_text_yet_is_read_from_its_file_before_the_llm_sees_it(self):
        issued = MedicalDocument(patient=self.kid, document_ref_name="RX-1", status="completed", doc_classification="prescription")
        issued.file_name = "patients/AW-KID/prescriptions/rx.pdf"
        issued.save()                                                    # no DocumentExtraction yet, as for an issued document
        seen = []
        llm = lambda system, user: (seen.append(user), json.dumps(FACTS))[1]                      # noqa: E731
        with mock.patch("apps.documents.lib_documents._read_file", return_value=b"%PDF"),                 mock.patch("apps.documents.lib_documents.extract_text", return_value=("Rx: Syrup for the child's ear. Dx: otitis media.", "pdf_text")):
            result = lib_processing.process_document(issued, llm=llm)
        self.assertEqual(result["status"], "DONE")
        self.assertIn("otitis media", seen[0])
        self.assertEqual(DocumentExtraction.objects.get(document=issued).extracted_text, "Rx: Syrup for the child's ear. Dx: otitis media.")

    def test_the_facts_become_rows_of_the_patient_and_the_extraction_is_done(self):
        result = self.process()
        self.assertEqual((result["status"], result["counts"]["events"], result["counts"]["labs"]), ("DONE", 2, 1))
        events = {e.icd10: e for e in ClinicalEvent.objects.filter(document=self.doc, event_type="DIAGNOSIS")}
        self.assertEqual((events["H66.9"].condition_group, events["H66.9"].category, events["H66.9"].event_date), ("EAR_INFECTION", "ACUTE", date(2026, 2, 1)))
        self.assertTrue(events["J45.9"].is_provisional)
        self.assertEqual(GrowthMeasurement.objects.get(document=self.doc).weight_kg, Decimal("11.2"))
        vaccine = ImmunizationRecord.objects.get(document=self.doc)
        self.assertEqual((vaccine.vaccines, vaccine.verification_status), (["OPV"], ImmunizationRecord.STATUS_PENDING))
        lab = LabResult.objects.get(document=self.doc)
        self.assertEqual((lab.analyte, lab.severity, lab.direction), ("HEMOGLOBIN_G_DL", "CRITICAL", "LOW"))
        birth = BirthHistory.objects.get(patient=self.kid)
        self.assertEqual((birth.gestational_age_weeks, birth.delivery_mode, birth.source), (34, "c_section", "EXTRACTED"))
        extraction = DocumentExtraction.objects.get(document=self.doc)
        self.assertEqual((extraction.status, extraction.normalised["extractor_version"]), ("done", llm_rules.EXTRACTOR_VERSION))

    def test_reading_it_again_replaces_what_was_extracted_and_never_touches_what_a_person_decided(self):
        self.process()
        mine = ClinicalEvent.objects.get(document=self.doc, icd10="H66.9")
        mine.verification_status = "verified"
        mine.save()
        ClinicalEvent.objects.filter(document=self.doc, icd10="J45.9").update(verification_status="rejected")
        lib_processing.process_document(self.doc, llm=llm_says(**FACTS), force=True)
        self.assertEqual(ClinicalEvent.objects.filter(document=self.doc, event_type="DIAGNOSIS").count(), 2)
        self.assertTrue(ClinicalEvent.objects.get(document=self.doc, icd10="H66.9").is_verified)
        self.assertTrue(ClinicalEvent.objects.get(document=self.doc, icd10="J45.9").is_rejected)
        self.assertEqual(GrowthMeasurement.objects.filter(document=self.doc).count(), 1)

    def test_a_document_already_read_is_skipped_unless_forced(self):
        self.process()
        self.assertEqual(self.process()["status"], "SKIPPED")

    def test_an_adult_a_patient_without_a_birth_date_and_a_document_without_text_are_skipped_and_the_llm_is_not_called(self):
        llm = mock.Mock()
        adult = child("AW-ADULT", years=30)
        no_dob = Patient.objects.create(awpid="AW-NODOB", full_name="X")
        for patient, text, reason in ((adult, "a long enough text for a report", "outside pediatric age scope"),
                                      (no_dob, "a long enough text for a report", "no date of birth"),
                                      (self.kid, "short", "no extracted text")):
            doc = document(patient, text=text)
            self.assertEqual(lib_processing.process_document(doc, llm=llm), {"status": "SKIPPED", "reason": reason})
            self.assertEqual(DocumentExtraction.objects.get(document=doc).status, "skipped")
        llm.assert_not_called()

    def test_a_discharge_summary_with_a_ventilator_is_a_critical_admission_and_a_bill_gives_no_diagnoses(self):
        summary = document(self.kid, text="Admitted to PICU, on ventilator for two days.", document_type="discharge_summary")
        lib_processing.process_document(summary, llm=llm_says(**{**FACTS, "admission": {"admitted_on": "2026-01-10", "discharged_on": "2026-01-14", "ward": "PICU"}}))
        stay = Admission.objects.get(document=summary)
        self.assertEqual((stay.is_critical, stay.ward, stay.critical_terms, stay.discharged_on), (True, "PICU", ["ventilator"], date(2026, 1, 14)))
        self.assertTrue(all(e.severity == "CRITICAL" for e in ClinicalEvent.objects.filter(document=summary, event_type="DIAGNOSIS")))
        bill = document(self.kid, text="Hospital bill: PICU charges for 4 days", document_type="medical_bill")
        lib_processing.process_document(bill, llm=llm_says(**{**FACTS, "admission": {"admitted_on": "2026-01-10", "ward": "PICU"}}))
        self.assertFalse(ClinicalEvent.objects.filter(document=bill, event_type="DIAGNOSIS").exists())

    def test_a_birth_history_a_person_entered_is_not_replaced(self):
        BirthHistory.objects.create(patient=self.kid, source="MANUAL", gestational_age_weeks=40)
        self.process()
        self.assertEqual(BirthHistory.objects.get(patient=self.kid).gestational_age_weeks, 40)


@with_config
class RebuildAndPayloadTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.kid = child()
        for n, on in enumerate([date(2026, 1, 1), date(2026, 3, 1), date(2026, 5, 1)]):
            ClinicalEvent.objects.create(patient=self.kid, event_type="DIAGNOSIS", event_date=on, icd10="H66.9", condition_text="ear infection", source="MANUAL")
        ClinicalEvent.objects.create(patient=self.kid, event_type="DIAGNOSIS", event_date=date(2026, 2, 1), icd10="J45.9", condition_text="asthma",
                                     source="MANUAL", is_provisional=True)

    def test_the_rebuild_makes_episodes_links_the_events_and_flags_the_recurrence(self):
        result = lib_processing.rebuild_patient(self.kid.pk)
        self.assertEqual((result["episodes"], result["recurrent"]), (4, ["EAR_INFECTION"]))
        self.assertEqual(HealthEpisode.objects.filter(patient=self.kid, category="ACUTE").count(), 3)
        self.assertTrue(all(e.episode_id for e in ClinicalEvent.objects.filter(patient=self.kid)))
        self.assertEqual(RecurrenceFlag.objects.get(patient=self.kid).clinical_hint, "Consider an ENT review")
        lib_processing.rebuild_patient(self.kid.pk)                                                      # again: the same, not doubled
        self.assertEqual((HealthEpisode.objects.filter(patient=self.kid).count(), RecurrenceFlag.objects.filter(patient=self.kid).count()), (4, 1))

    def test_a_rejected_event_leaves_the_episodes(self):
        ClinicalEvent.objects.filter(patient=self.kid, icd10="H66.9", event_date=date(2026, 5, 1)).update(verification_status="rejected")
        lib_processing.rebuild_patient(self.kid.pk)
        self.assertFalse(RecurrenceFlag.objects.filter(patient=self.kid).exists())

    def test_the_parent_sees_plain_words_and_no_unconfirmed_condition_and_the_doctor_sees_it(self):
        lib_processing.rebuild_patient(self.kid.pk)
        parent = lib_processing.build_timeline_payload(self.kid, self.kid.date_of_birth, date.today(), "guardian")
        doctor = lib_processing.build_timeline_payload(self.kid, self.kid.date_of_birth, date.today(), "doctor")
        lanes = lambda payload: {lane["id"] for lane in payload["lanes"]}                              # noqa: E731
        self.assertNotIn("chronic:ASTHMA", lanes(parent))
        self.assertIn("chronic:ASTHMA", lanes(doctor))
        ears = next(lane for lane in parent["lanes"] if lane["id"] == "acute:EAR_INFECTION")
        self.assertEqual((ears["is_recurrent"], ears["category_label"], len(ears["episodes"])), (True, "Happens often", 3))
        self.assertEqual(ears["recurrence"]["id"], RecurrenceFlag.objects.get(patient=self.kid).pk)
        ears_doctor = next(lane for lane in doctor["lanes"] if lane["id"] == "acute:EAR_INFECTION")      # the event ids are for doctors only
        shown = [event["id"] for episode in ears_doctor["episodes"] for event in episode["events"]]
        self.assertEqual(sorted(shown), sorted(ClinicalEvent.objects.filter(patient=self.kid, icd10="H66.9").values_list("pk", flat=True)))
        self.assertEqual(parent["summary"]["recurrent_conditions"], 1)

    def test_a_hospital_that_may_not_see_the_rest_gets_only_its_own_rows(self):
        from core.tests.testing import ensure_hospital
        mine = ensure_hospital(1)
        ClinicalEvent.objects.filter(patient=self.kid, icd10="H66.9", event_date=date(2026, 1, 1)).update(source_hospital=mine)
        payload = lib_processing.build_timeline_payload(self.kid, self.kid.date_of_birth, date.today(), "doctor", hospital_id=mine.id)
        ears = next(lane for lane in payload["lanes"] if lane["id"] == "acute:EAR_INFECTION")
        self.assertEqual(len(ears["episodes"]), 1)

    def test_a_preterm_baby_is_plotted_on_corrected_age_until_two(self):
        bh = BirthHistory(gestational_age_weeks=32)
        self.assertEqual(lib_processing.growth_dob(date(2026, 1, 1), bh), date(2026, 1, 1) + timedelta(weeks=8))
        self.assertEqual(lib_processing.growth_dob(date(2026, 1, 1), BirthHistory(gestational_age_weeks=38)), date(2026, 1, 1))


@with_config
class TaskTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.kid = child()
        self.doc = document(self.kid)

    def test_a_task_that_cannot_reach_the_llm_marks_the_extraction_failed_without_failing_the_document(self):
        with mock.patch.object(lib_processing, "process_document", side_effect=ValueError("no parseable extraction output")):
            tasks.process_document_task.apply(args=[self.doc.pk]).get()
        extraction = DocumentExtraction.objects.get(document=self.doc)
        self.assertEqual((extraction.status, extraction.normalised["error"]), ("failed", "no parseable extraction output"))
        self.assertEqual(MedicalDocument.objects.get(pk=self.doc.pk).status, "completed")

    def test_a_finished_document_rebuilds_its_patients_timeline(self):
        with mock.patch.object(lib_processing, "process_document", return_value={"status": "DONE", "patient_id": self.kid.pk}), \
                mock.patch.object(lib_processing, "rebuild_patient") as rebuild:
            tasks.process_document_task.apply(args=[self.doc.pk]).get()
        rebuild.assert_called_once_with(self.kid.pk)

    def test_the_backfill_queues_only_documents_not_read_yet_oldest_first(self):
        done = document(self.kid)
        DocumentExtraction.objects.filter(document=done).update(status="done")
        with mock.patch.object(tasks.process_document_task, "apply_async") as queue:
            tasks.backfill_task.apply().get()
        self.assertEqual([call.kwargs["args"][0] for call in queue.call_args_list], [self.doc.pk])


@with_config
class ApiTests(TestCase):
    databases = {"default"}

    def setUp(self):
        self.kid = child()

    def call(self, view, method, role="patient", data=None, allowed=None, **kwargs):
        request = getattr(APIRequestFactory(), method)("/x/", data or {}, **({"format": "json"} if method != "get" else {}))
        force_authenticate(request, user=MockUser({"user_id": 1, "role": role, "awpid": "AW-KID" if role == "patient" else None,
                                                   "hospital_id": None if role == "patient" else 1}))
        if allowed is None:
            return view.as_view()(request, **kwargs)
        with mock.patch.object(ig, "can_view_patient", return_value=allowed):
            return view.as_view()(request, **kwargs)

    def test_a_patient_gets_their_own_timeline_for_a_period(self):
        body = self.call(views.PatientHealthTimelineView, "get", awpid=self.kid.awpid).data
        self.assertEqual((body["audience"], body["period"]["from"]), ("guardian", self.kid.date_of_birth.isoformat()))
        self.assertEqual(set(body), {"patient", "period", "audience", "summary", "notes", "lanes", "pending_documents"})

    def test_the_parent_sees_the_childs_timeline_and_a_stranger_does_not(self):
        parent = Patient.objects.create(awpid="AW-PARENT", full_name="Parent")
        PatientRelationship.objects.create(guardian=parent, dependent=self.kid)
        Patient.objects.create(awpid="AW-OTHER", full_name="Other")
        for awpid, expected in (("AW-PARENT", 200), ("AW-OTHER", 403)):
            request = APIRequestFactory().get("/x/")
            force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": awpid}))
            self.assertEqual(views.PatientHealthTimelineView.as_view()(request, awpid=self.kid.awpid).status_code, expected, awpid)

    def test_a_bad_period_is_refused(self):
        for params in ({"from": "yesterday"}, {"from": "2026-05-01", "to": "2026-01-01"}):
            request = APIRequestFactory().get("/x/", params)
            force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": "AW-KID"}))
            self.assertEqual(views.PatientHealthTimelineView.as_view()(request, awpid=self.kid.awpid).status_code, 400)

    def test_a_doctor_of_another_hospital_is_refused(self):
        self.assertEqual(self.call(views.PatientHealthTimelineView, "get", role="doctor", awpid=self.kid.awpid).status_code, 403)

    def test_only_a_clinician_can_add_a_measurement_and_it_is_scored_straight_away(self):
        body = {"measured_on": "2026-01-10", "weight_kg": "11.5", "head_circ_cm": "47"}
        self.assertEqual(self.call(views.PatientGrowthView, "post", data=body, allowed=True, awpid=self.kid.awpid).status_code, 403)
        self.assertEqual(self.call(views.PatientGrowthView, "post", role="doctor", data=body, allowed=True, awpid=self.kid.awpid).status_code, 201)
        saved = GrowthMeasurement.objects.get(patient=self.kid)
        self.assertEqual((saved.weight_kg, saved.head_circumference_cm, saved.source), (Decimal("11.5"), Decimal("47.0"), "manual"))
        wrong = {"measured_on": "2026-01-10", "weight_kg": "900"}
        self.assertEqual(self.call(views.PatientGrowthView, "post", role="doctor", data=wrong, allowed=True, awpid=self.kid.awpid).status_code, 400)

    def test_the_growth_points_come_back_for_one_indicator(self):
        GrowthMeasurement.objects.create(patient=self.kid, measured_on=date.today() - timedelta(days=30), weight_kg="11.5", head_circumference_cm="47")
        body = self.call(views.PatientGrowthView, "get", data={"indicator": "head_circ_cm"}, awpid=self.kid.awpid).data
        self.assertEqual((body["indicator"], [p["value"] for p in body["points"]]), ("head_circ_cm", [47.0]))
        self.assertEqual(self.call(views.PatientGrowthView, "get", data={"indicator": "bmi"}, awpid=self.kid.awpid).status_code, 400)

    def test_a_vaccine_is_added_only_if_it_is_recognised_and_a_parents_entry_waits_for_review(self):
        def post(role, text):
            return self.call(views.PatientImmunizationView, "post", role=role, allowed=True,
                             data={"vaccine_text": text, "given_on": "2026-01-10"}, awpid=self.kid.awpid)
        self.assertEqual(post("patient", "mystery shot").status_code, 400)
        self.assertEqual(post("patient", "BCG").status_code, 201)
        self.assertEqual(post("doctor", "OPV 1").status_code, 201)
        statuses = dict(ImmunizationRecord.objects.filter(patient=self.kid).values_list("vaccine_name", "verification_status"))
        self.assertEqual(statuses, {"BCG": ImmunizationRecord.STATUS_PENDING, "OPV 1": ImmunizationRecord.STATUS_VERIFIED})
        listed = self.call(views.PatientImmunizationView, "get", awpid=self.kid.awpid).data
        self.assertEqual({r["code"] for r in listed["rows"] if r["status"] == "GIVEN"}, {"BCG", "OPV1"})

    def test_a_doctor_verifies_rejects_and_recodes_an_event_and_the_timeline_is_rebuilt(self):
        event = ClinicalEvent.objects.create(patient=self.kid, event_type="DIAGNOSIS", event_date=date(2026, 1, 1), icd10="J06.9", condition_text="cold")

        def patch(**body):
            return self.call(views.ClinicalEventView, "patch", role="doctor", data=body, allowed=True, event_id=event.pk)
        with mock.patch.object(views.rebuild_patient_task, "delay") as rebuild:
            self.assertEqual(self.call(views.ClinicalEventView, "patch", data={"action": "verify"}, allowed=True, event_id=event.pk).status_code, 403)
            self.assertEqual(patch(action="recode", icd10="h66.9", condition_text="ear infection").status_code, 200)
            event.refresh_from_db()
            self.assertEqual((event.icd10, event.condition_group, event.is_verified, event.verified_at is not None), ("H66.9", "EAR_INFECTION", True, True))
            self.assertEqual(patch(action="reject").status_code, 200)
            event.refresh_from_db()
            self.assertEqual((event.is_rejected, event.is_verified), (True, False))
            self.assertEqual(patch(action="shred").status_code, 400)
        self.assertEqual(rebuild.call_count, 2)

    def test_a_doctor_acknowledges_a_recurrence_flag_and_asks_for_a_rebuild(self):
        flag = RecurrenceFlag.objects.create(patient=self.kid, condition_group="H66", label="Ear", triggered_on=date(2026, 1, 1))
        self.assertEqual(self.call(views.RecurrenceAckView, "post", role="doctor", allowed=True, flag_id=flag.pk).status_code, 200)
        self.assertIsNotNone(RecurrenceFlag.objects.get(pk=flag.pk).acknowledged_at)
        with mock.patch.object(views.rebuild_patient_task, "delay") as rebuild:
            self.assertEqual(self.call(views.PatientRebuildView, "post", role="doctor", allowed=True, awpid=self.kid.awpid).status_code, 202)
        rebuild.assert_called_once_with(self.kid.pk)



class CleanWardTests(SimpleTestCase):
    def test_a_phrase_from_the_model_becomes_one_short_code(self):
        for raw, code in (("Paediatric ward, Bed 22", "WARD"), ("PICU (22/01 - 24/01), then ward", "PICU"), ("neonatal ICU", "ICU"), ("NICU Cot 6", "NICU"), (None, "WARD"), ("", "WARD")):
            self.assertEqual(lib_processing.clean_ward(raw), code, raw)
            self.assertLessEqual(len(lib_processing.clean_ward(raw)), 10)


@with_config
class ReadOnlyAfterConfirmationTests(TestCase):
    """A patient's upload is read for the timeline only once the patient has confirmed it."""
    databases = {"default"}

    def setUp(self):
        self.doc = document(child())

    def test_a_report_that_waits_for_the_patients_confirmation_is_not_read(self):
        from apps.documents import lib_documents
        with mock.patch.object(lib_documents, "is_awaiting_review", return_value=True), mock.patch.object(lib_processing, "process_document") as read:
            tasks.process_document_task.apply(args=[self.doc.pk])
        read.assert_not_called()

    def test_a_confirmed_report_is_read(self):
        from apps.documents import lib_documents
        with mock.patch.object(lib_documents, "is_awaiting_review", return_value=False), mock.patch.object(lib_processing, "process_document", return_value={"status": "SKIPPED"}) as read:
            tasks.process_document_task.apply(args=[self.doc.pk])
        read.assert_called_once()

    def test_confirming_the_type_queues_the_reading(self):
        from apps.documents import lib_documents
        with mock.patch.object(tasks.process_document_task, "apply_async") as queue, self.captureOnCommitCallbacks(execute=True):
            lib_documents.correct_document(self.doc, "prescription")
        queue.assert_called_once()
        self.assertEqual(queue.call_args.kwargs["args"], [self.doc.pk])
