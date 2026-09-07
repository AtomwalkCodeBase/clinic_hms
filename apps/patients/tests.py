"""
apps/patients/tests.py
----------------------
Unit tests for the consultation-pad recognition pipeline's pure helpers —
parsing, blank/ink detection, dose sanity, and drug-name resolution.

All DB-free (SimpleTestCase). Run:
    python manage.py test apps.patients

(If the local settings register tenant DB aliases without a TEST config, the
default runner errors during test-DB setup before any test runs — a
pre-existing env quirk, see apps/opd/tests.py. These tests need no DB; run
them through a runner that skips DB setup, e.g. django.setup() + unittest.)
"""

import io
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.patients import consult_pad_recognition as R
from apps.patients import consult_pad_views as V
from apps.patients.consult_pad_drug_aliases import alias_pairs, seed_name_pairs
from apps.patients.consult_pad_lab_aliases import alias_pairs as lab_alias_pairs


def _png(kind="inked", size=(120, 160)):
    """kind: 'white' | 'inked' | 'heavy'."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, "white")
    if kind != "white":
        d = ImageDraw.Draw(im)
        w = 6 if kind == "inked" else 40
        d.line((5, 5, size[0] - 5, size[1] - 5), fill=(0, 0, 0), width=w)
        d.line((5, size[1] - 5, size[0] - 5, 5), fill=(0, 0, 0), width=w)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ── recognition: scalar helpers ─────────────────────────────────────────────

class AsFloatTests(SimpleTestCase):
    def test_parses_and_clamps(self):
        self.assertEqual(R._as_float(0.5), 0.5)
        self.assertEqual(R._as_float("0.8"), 0.8)
        self.assertEqual(R._as_float(5), 1.0)
        self.assertEqual(R._as_float(-2), 0.0)

    def test_bad_values_are_none(self):
        for v in (None, "", "abc", [], {}, float("nan")):
            self.assertIsNone(R._as_float(v))


class HasContentTests(SimpleTestCase):
    def test_empty_dict_has_no_content(self):
        self.assertFalse(R._has_content(dict(R._EMPTY)))

    def test_prescription_or_diagnosis_counts(self):
        self.assertTrue(R._has_content({"prescription": [{"drug_name": "X"}]}))
        self.assertTrue(R._has_content({"diagnoses": [{"description": "Fever"}]}))

    def test_trivial_raw_text_does_not_count(self):
        self.assertFalse(R._has_content({"raw_text": "  ..  "}))
        self.assertTrue(R._has_content({"raw_text": "Fever since 2 days"}))


class CheckDoseTests(SimpleTestCase):
    def test_blank_is_not_flagged_here(self):
        self.assertEqual(R._check_dose(""), [])

    def test_normal_doses_pass_clean(self):
        for d in ("500 mg", "1 tab", "10 ml", "2.5 mg", "1-0-1", "1 tablet", "5mg"):
            self.assertEqual(R._check_dose(d), [], d)

    def test_absurd_strength_flagged(self):
        self.assertTrue(any("unusually high" in f for f in R._check_dose("5000 mg")))
        self.assertTrue(any("unusually high" in f for f in R._check_dose("50 g")))

    def test_zero_dose_flagged(self):
        self.assertTrue(any("zero" in f for f in R._check_dose("0 mg")))

    def test_non_amount_text_flagged(self):
        self.assertTrue(R._check_dose("as advised"))


# ── recognition: JSON parsing ──────────────────────────────────────────────

class ParseJsonTests(SimpleTestCase):
    def test_rejects_non_json(self):
        with self.assertRaises(ValueError):
            R._parse_json("not json at all")

    def test_extracts_confidence_and_clinical_flag(self):
        out = R._parse_json('{"is_clinical_note": false, "confidence": 0.1, "subjective": "x"}')
        self.assertFalse(out["is_clinical_note"])
        self.assertEqual(out["confidence"], 0.1)

    def test_defaults_when_keys_absent(self):
        out = R._parse_json('{"subjective": "cough"}')
        self.assertTrue(out["is_clinical_note"])
        self.assertIsNone(out["confidence"])

    def test_prescription_flags_and_frequency_default(self):
        raw = '''{"prescription": [
            {"drug_name": "Amoxicillin", "dosage": "", "frequency": "", "duration_days": null},
            {"drug_name": "Dolo", "dosage": "650 mg", "frequency": "bd", "duration_days": 5}
        ]}'''
        out = R._parse_json(raw)
        a, b = out["prescription"]
        self.assertEqual(a["frequency"], "od")
        self.assertTrue(a["frequency_defaulted"])
        self.assertIn("dose missing", a["flags"])
        self.assertIn("duration missing", a["flags"])
        self.assertIn("frequency assumed OD", a["flags"])
        self.assertFalse(b["frequency_defaulted"])
        self.assertEqual(b["flags"], [])

    def test_prescription_dose_sanity_flag(self):
        out = R._parse_json('{"prescription": [{"drug_name": "PCM", "dosage": "9000 mg", "frequency": "od", "duration_days": 3}]}')
        self.assertTrue(any("unusually high" in f for f in out["prescription"][0]["flags"]))

    def test_drops_items_without_name(self):
        out = R._parse_json('{"prescription": [{"drug_name": "", "dosage": "5 mg"}]}')
        self.assertEqual(out["prescription"], [])

    def test_bad_frequency_and_route_coerced(self):
        out = R._parse_json('{"prescription": [{"drug_name": "X", "dosage": "1 tab", "frequency": "weekly", "route": "smoke", "duration_days": 2}]}')
        it = out["prescription"][0]
        self.assertEqual(it["frequency"], "od")
        self.assertEqual(it["route"], "oral")


# ── recognition: pixel pre-check ──────────────────────────────────────────

class InkChecksTests(SimpleTestCase):
    def test_white_page_has_no_ink(self):
        self.assertLess(R._ink_fraction(_png("white")), R._BLANK_INK_FRACTION)

    def test_inked_page_has_ink(self):
        self.assertGreater(R._ink_fraction(_png("heavy")), R._SPARSE_INK_FRACTION)

    def test_decode_error_fails_open(self):
        self.assertEqual(R._ink_fraction(b"not-a-png"), 1.0)

    def test_blankness_all_white(self):
        all_blank, sparse = R._blankness([_png("white"), _png("white")])
        self.assertTrue(all_blank)
        self.assertTrue(sparse)

    def test_blankness_heavy(self):
        all_blank, sparse = R._blankness([_png("heavy")])
        self.assertFalse(all_blank)
        self.assertFalse(sparse)


@override_settings(CONSULT_PAD_LLM_KEY="test-key", CONSULT_PAD_LLM_MODEL="m",
                   CONSULT_PAD_LLM_BASE="https://example.invalid/v1")
class RecogniseTests(SimpleTestCase):
    def test_no_key_skips(self):
        with override_settings(CONSULT_PAD_LLM_KEY=""):
            r = R.recognise([_png("inked")])
        self.assertEqual(r["status"], "skipped")

    def test_no_pages_fails(self):
        self.assertEqual(R.recognise([])["status"], "failed")

    def test_blank_pages_short_circuit_without_calling_model(self):
        with mock.patch.object(R, "_post_chat", side_effect=AssertionError("model must not be called")) as p:
            r = R.recognise([_png("white"), _png("white")])
        self.assertEqual(r["status"], "empty")
        p.assert_not_called()

    def test_single_page_done_with_flags_and_confidence(self):
        payload = '{"is_clinical_note": true, "confidence": 0.9, "subjective": "fever 2d", "raw_text": "fever 2d", "prescription": [{"drug_name": "Dolo", "dosage": "650 mg", "frequency": "bd", "duration_days": 3}]}'
        with mock.patch.object(R, "_post_chat", return_value=payload):
            r = R.recognise([_png("heavy")], focus="all")
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["recognized"]["confidence"], 0.9)
        self.assertEqual(r["recognized"]["prescription"][0]["frequency"], "bd")

    def test_model_says_blank_returns_empty(self):
        with mock.patch.object(R, "_post_chat", return_value='{"is_clinical_note": false, "confidence": 0.0}'):
            r = R.recognise([_png("heavy")])
        self.assertEqual(r["status"], "empty")

    def test_multipage_partial_failure_keeps_good_pages(self):
        calls = {"n": 0}

        def fake_transcribe(png):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("page 2 unreadable")
            return "line from a page"

        with mock.patch.object(R, "_transcribe_page", side_effect=fake_transcribe), \
             mock.patch.object(R, "_structure_text", return_value=dict(R._EMPTY, subjective="ok", raw_text="ok")):
            r = R.recognise([_png("heavy"), _png("heavy"), _png("heavy")])
        self.assertEqual(r["status"], "done")
        self.assertIn("could not be read", r["recognized"]["page_warnings"])

    def test_sparse_ink_caps_confidence(self):
        payload = '{"is_clinical_note": true, "confidence": 0.95, "subjective": "x", "raw_text": "x here now"}'
        with mock.patch.object(R, "_blankness", return_value=(False, True)), \
             mock.patch.object(R, "_post_chat", return_value=payload):
            r = R.recognise([_png("heavy")])
        self.assertEqual(r["status"], "done")
        self.assertLessEqual(r["recognized"]["confidence"], 0.3)
        self.assertTrue(r["recognized"]["low_ink"])


# ── views: drug-name resolution ───────────────────────────────────────────

CATALOG = [
    {"name": "Dolo 650", "generic_name": "Paracetamol"},
    {"name": "Augmentin 625", "generic_name": "Amoxicillin + Clavulanic acid"},
    {"name": "Pan 40", "generic_name": "Pantoprazole"},
]


class CandidateMapTests(SimpleTestCase):
    def test_names_and_generics_indexed(self):
        c = V._candidate_map(CATALOG)
        self.assertEqual(c["dolo 650"], "Dolo 650")
        self.assertEqual(c["paracetamol"], "Dolo 650")

    def test_alias_resolves_only_when_generic_in_catalog(self):
        c = V._candidate_map(CATALOG, list(alias_pairs()))
        # "pcm" -> generic Paracetamol -> catalog "Dolo 650"
        self.assertEqual(c.get("pcm"), "Dolo 650")
        # a seed alias whose generic the catalog does not stock is absent
        self.assertNotIn("cetirizine", c)

    def test_alias_tolerates_strength_suffix_on_generic(self):
        c = V._candidate_map([{"name": "Amox 500", "generic_name": "Amoxicillin 500 mg"}],
                             [("amox", "amoxicillin"), ("mox 500", "amoxicillin")])
        self.assertEqual(c.get("amox"), "Amox 500")


class ResolveItemNameTests(SimpleTestCase):
    def setUp(self):
        from rapidfuzz import process, fuzz
        self.process, self.fuzz = process, fuzz
        self.candidates = V._candidate_map(CATALOG, list(alias_pairs()))
        self.keys = list(self.candidates)

    def _resolve(self, name):
        it = {"drug_name": name, "flags": []}
        V._resolve_item_name(it, self.candidates, self.keys, self.process, self.fuzz)
        return it

    def test_exact_generic_snaps_to_catalog(self):
        it = self._resolve("Paracetamol")
        self.assertEqual(it["drug_name"], "Dolo 650")
        self.assertEqual(it["name_source"], "catalog")

    def test_alias_snaps_to_catalog(self):
        it = self._resolve("pantoprazole")
        self.assertEqual(it["drug_name"], "Pan 40")
        self.assertEqual(it["name_source"], "catalog")

    def test_strips_form_word(self):
        it = self._resolve("Tab Paracetamol")
        self.assertEqual(it["name_source"], "catalog")

    def test_short_unknown_token_flagged_not_matched(self):
        it = self._resolve("xyz")
        self.assertEqual(it["name_source"], "verbatim")
        self.assertTrue(any("not found in catalog" in f for f in it["flags"]))

    def test_unknown_long_token_left_verbatim_with_flag(self):
        it = self._resolve("Ztrakelvzn")
        self.assertEqual(it["name_source"], "verbatim")
        self.assertTrue(it["flags"])

    def test_close_misspelling_is_fuzzy_match_with_confirm_flag(self):
        it = self._resolve("Augmentn 625")
        self.assertEqual(it["name_source"], "catalog_fuzzy")
        self.assertTrue(any("confirm" in f for f in it["flags"]))
        self.assertEqual(it["drug_name_raw"], "Augmentn 625")

    def test_raw_name_always_recorded(self):
        it = self._resolve("Paracetamol")
        self.assertEqual(it["drug_name_raw"], "Paracetamol")


class NormaliseOrchestratorTests(SimpleTestCase):
    def test_no_items_is_noop(self):
        blob = {"prescription": []}
        V._normalise_rx_against_catalog(blob, tenant_id=1)
        self.assertEqual(blob["prescription"], [])

    def test_resolves_via_seed_table_when_no_catalog(self):
        # tenant lookup fails (no DB in SimpleTestCase) — the standalone seed
        # drug table must still canonicalise a known brand / misspelling.
        blob = {"prescription": [
            {"drug_name": "Dolo"},          # brand -> generic
            {"drug_name": "Panacetamol"},   # misread -> Paracetamol
            {"drug_name": "Zxqwerty"},      # unknown -> left verbatim, flagged
        ]}
        V._normalise_rx_against_catalog(blob, tenant_id=999999)
        dolo, pana, unk = blob["prescription"]
        self.assertEqual(dolo["drug_name"], "Paracetamol")
        self.assertEqual(dolo["name_source"], "catalog")
        self.assertEqual(dolo["drug_name_raw"], "Dolo")
        self.assertEqual(pana["drug_name"], "Paracetamol")
        self.assertEqual(pana["drug_name_raw"], "Panacetamol")
        self.assertEqual(unk["name_source"], "verbatim")
        self.assertTrue(unk["flags"])


class DrugCandidateMapTests(SimpleTestCase):
    def test_seed_gives_standalone_resolution(self):
        c = V._drug_candidate_map([], seed_name_pairs())
        self.assertEqual(c["dolo"], "Paracetamol")
        self.assertEqual(c["panacetamol"], "Paracetamol")
        self.assertEqual(c["paracetamol"], "Paracetamol")

    def test_catalog_name_overrides_seed(self):
        c = V._drug_candidate_map(
            [{"name": "Dolo 650", "generic_name": "Paracetamol"}],
            [("dolo", "Paracetamol"), ("paracetamol", "Paracetamol")],
        )
        self.assertEqual(c["dolo 650"], "Dolo 650")     # catalog name added
        self.assertEqual(c["paracetamol"], "Paracetamol")  # seed alias kept


class AliasTableTests(SimpleTestCase):
    def test_pairs_are_lowercase_surface_and_generic(self):
        pairs = list(alias_pairs())
        self.assertTrue(pairs)
        for surface, generic in pairs:
            self.assertEqual(surface, surface.lower())
            self.assertEqual(generic, generic.lower())
            self.assertTrue(surface and generic)

    def test_known_shorthand_present(self):
        d = dict(alias_pairs())
        self.assertEqual(d.get("pcm"), "paracetamol")
        self.assertEqual(d.get("azithro"), "azithromycin")

    def test_seed_name_pairs_are_cased_canonicals(self):
        d = dict(seed_name_pairs())
        self.assertEqual(d.get("panacetamol"), "Paracetamol")
        self.assertEqual(d.get("azithromicin"), "Azithromycin")
        self.assertEqual(d.get("dolo"), "Paracetamol")
        for surface, canon in seed_name_pairs():
            self.assertEqual(surface, surface.lower())
            self.assertTrue(surface and canon)


class DecodePagesTests(SimpleTestCase):
    def test_skips_malformed_and_decodes_valid(self):
        good = "data:image/png;base64,aGVsbG8="  # "hello"
        out = V._decode_pages([good, "garbage", None, ""])
        self.assertEqual(out, [b"hello"])


# ── recognition: frequency / sig shorthand ───────────────────────────────

class FreqFromTextTests(SimpleTestCase):
    def test_blank(self):
        self.assertEqual(R._freq_from_text(""), (None, None))
        self.assertEqual(R._freq_from_text("after food"), (None, None))

    def test_plain_enums(self):
        for s, e in [("bd", "bd"), ("BID", "bd"), ("tds", "td"), ("tid", "td"),
                     ("qid", "qid"), ("od", "od"), ("qd", "od"), ("hs", "nocte"),
                     ("nocte", "nocte"), ("sos", "sos"), ("prn", "sos"), ("stat", "stat")]:
            self.assertEqual(R._freq_from_text(s)[0], e, s)

    def test_grids_and_words(self):
        self.assertEqual(R._freq_from_text("1-0-1")[0], "bd")
        self.assertEqual(R._freq_from_text("1-1-1")[0], "td")
        self.assertEqual(R._freq_from_text("twice daily")[0], "bd")
        self.assertEqual(R._freq_from_text("thrice a day")[0], "td")
        self.assertEqual(R._freq_from_text("once a day")[0], "od")

    def test_n_daily_including_misreads(self):
        self.assertEqual(R._freq_from_text("2 daily")[0], "bd")
        self.assertEqual(R._freq_from_text("2donly")[0], "bd")   # "2 daily" misread
        self.assertEqual(R._freq_from_text("3daly")[0], "td")
        self.assertEqual(R._freq_from_text("2x")[0], "bd")

    def test_does_not_eat_duration(self):
        self.assertEqual(R._freq_from_text("3 days")[0], None)
        self.assertEqual(R._freq_from_text("x 5 days")[0], None)


class ParseJsonFreqRecoveryTests(SimpleTestCase):
    def test_recovers_frequency_from_instructions_and_strips_it(self):
        out = R._parse_json(
            '{"prescription": [{"drug_name": "Paracetamol", "dosage": "500 mg",'
            ' "frequency": "", "duration_days": 3, "instructions": "2donly after food"}]}')
        it = out["prescription"][0]
        self.assertEqual(it["frequency"], "bd")
        self.assertFalse(it["frequency_defaulted"])
        self.assertNotIn("2donly", it["instructions"])
        self.assertIn("after food", it["instructions"])
        self.assertTrue(any("frequency read from instructions" in f for f in it["flags"]))

    def test_normalises_grid_frequency(self):
        out = R._parse_json('{"prescription": [{"drug_name": "X", "dosage": "1 tab", "frequency": "1-0-1", "duration_days": 5}]}')
        self.assertEqual(out["prescription"][0]["frequency"], "bd")

    def test_still_defaults_when_nothing_found(self):
        out = R._parse_json('{"prescription": [{"drug_name": "X", "dosage": "1 tab", "frequency": "", "duration_days": 5, "instructions": "with milk"}]}')
        it = out["prescription"][0]
        self.assertEqual(it["frequency"], "od")
        self.assertTrue(it["frequency_defaulted"])
        self.assertIn("with milk", it["instructions"])


# ── views: investigation-name resolution ──────────────────────────────────

class SplitInvestigationsTests(SimpleTestCase):
    def test_blank_is_empty_list(self):
        self.assertEqual(V._split_investigations(""), [])
        self.assertEqual(V._split_investigations("   "), [])
        self.assertEqual(V._split_investigations(None), [])

    def test_splits_on_common_separators(self):
        self.assertEqual(
            V._split_investigations("CBC, LFT / RFT and USG abdomen & ECG"),
            ["CBC", "LFT", "RFT", "USG abdomen", "ECG"],
        )

    def test_strips_list_markers_and_trailing_punctuation(self):
        self.assertEqual(
            V._split_investigations("1. CBC\n2) LFT\n- Urine R/M."),
            ["CBC", "LFT", "Urine R/M"],
        )

    def test_dedupes_case_insensitively_keeping_order(self):
        self.assertEqual(V._split_investigations("CBC, cbc, LFT, CBC"), ["CBC", "LFT"])


LAB_CATALOG = ["CBC (Hemogram)", "Liver Function Panel"]


class LabCandidateMapTests(SimpleTestCase):
    def test_seed_alias_and_canonical_indexed(self):
        c = V._lab_candidate_map([], lab_alias_pairs())
        self.assertEqual(c["cbc"], "Complete Blood Count")
        self.assertEqual(c["lft"], "Liver Function Test")
        self.assertEqual(c["complete blood count"], "Complete Blood Count")

    def test_catalog_name_overrides_seed_spelling(self):
        c = V._lab_candidate_map(LAB_CATALOG, [("cbc", "Complete Blood Count")])
        self.assertEqual(c["cbc"], "Complete Blood Count")           # seed alias kept
        self.assertEqual(c["cbc (hemogram)"], "CBC (Hemogram)")      # catalog name added

    def test_works_with_no_catalog(self):
        c = V._lab_candidate_map(None, [("esr", "Erythrocyte Sedimentation Rate")])
        self.assertEqual(c["esr"], "Erythrocyte Sedimentation Rate")


class ResolveInvestigationTests(SimpleTestCase):
    def setUp(self):
        from rapidfuzz import process, fuzz
        self.process, self.fuzz = process, fuzz
        self.candidates = V._lab_candidate_map([], lab_alias_pairs())
        self.keys = list(self.candidates)

    def _resolve(self, raw):
        return V._resolve_investigation(raw, self.candidates, self.keys, self.process, self.fuzz)

    def test_exact_acronym_snaps_to_standard_name(self):
        r = self._resolve("CBC")
        self.assertEqual(r["name"], "Complete Blood Count")
        self.assertEqual(r["source"], "catalog")
        self.assertEqual(r["raw"], "CBC")

    def test_exact_canonical_gets_standard_casing(self):
        r = self._resolve("complete blood count")
        self.assertEqual(r["name"], "Complete Blood Count")
        self.assertEqual(r["source"], "catalog")

    def test_close_misspelling_is_fuzzy_with_confirm_flag(self):
        # small controlled map so the winner is unambiguously ahead
        cands = {"complete blood count": "Complete Blood Count", "lipid profile": "Lipid Profile"}
        r = V._resolve_investigation("complete blood cont", cands, list(cands), self.process, self.fuzz)
        self.assertEqual(r["source"], "catalog_fuzzy")
        self.assertEqual(r["name"], "Complete Blood Count")
        self.assertTrue(any("confirm" in f for f in r["flags"]))

    def test_short_unknown_token_flagged_not_matched(self):
        r = self._resolve("zzq")
        self.assertEqual(r["source"], "verbatim")
        self.assertEqual(r["name"], "zzq")
        self.assertTrue(any("not a recognised investigation" in f for f in r["flags"]))

    def test_long_unknown_token_left_verbatim_with_flag(self):
        r = self._resolve("Fzzznordexil panel")
        self.assertEqual(r["source"], "verbatim")
        self.assertTrue(r["flags"])


class NormaliseInvestigationsTests(SimpleTestCase):
    def test_no_investigations_is_noop(self):
        blob = {"investigations": ""}
        V._normalise_investigations_against_catalog(blob, tenant_id=1)
        self.assertEqual(blob["investigations_resolved"], [])
        self.assertEqual(blob["investigations"], "")

    def test_rewrites_string_and_populates_resolved_without_a_tenant_catalog(self):
        # tenant lookup will fail (no DB in SimpleTestCase) — the seed table
        # must still canonicalise the tokens it knows.
        blob = {"investigations": "cbc, lft, usg abdomen, made-up-test"}
        V._normalise_investigations_against_catalog(blob, tenant_id=999999)
        self.assertEqual(
            blob["investigations"],
            "Complete Blood Count, Liver Function Test, Ultrasound Abdomen & Pelvis, made-up-test",
        )
        by_raw = {r["raw"]: r for r in blob["investigations_resolved"]}
        self.assertEqual(by_raw["cbc"]["source"], "catalog")
        self.assertEqual(by_raw["made-up-test"]["source"], "verbatim")
        self.assertTrue(by_raw["made-up-test"]["flags"])

    def test_raw_text_is_never_touched(self):
        blob = {"investigations": "cbc", "raw_text": "Adv: cbc"}
        V._normalise_investigations_against_catalog(blob, tenant_id=None)
        self.assertEqual(blob["raw_text"], "Adv: cbc")


class LabAliasTableTests(SimpleTestCase):
    def test_pairs_are_lowercase_surface_and_nonempty_canonical(self):
        pairs = list(lab_alias_pairs())
        self.assertTrue(pairs)
        for surface, canon in pairs:
            self.assertEqual(surface, surface.lower())
            self.assertTrue(surface and canon)

    def test_known_acronyms_present(self):
        d = dict(lab_alias_pairs())
        self.assertEqual(d.get("hba1c"), "HbA1c (Glycated Haemoglobin)")
        self.assertEqual(d.get("rft"), "Renal Function Test")
        self.assertEqual(d.get("ns1"), "Dengue NS1 Antigen")
