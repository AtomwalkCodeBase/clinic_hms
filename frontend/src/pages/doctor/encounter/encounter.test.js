// Pure helpers of the doctor's consultation workspace. Run with `npm test`.
import test from "node:test";
import assert from "node:assert/strict";

import { classifyBP, classifyVital } from "./vitals";
import { mapFreq, mapRoute } from "./drugs";
import { icdCodeForDescription, matchICD } from "./diagnosis";
import { parseDrugSpeech, wordsToNumber } from "./speech";
import { buildVisitSummary } from "./visitSummary";
import { ICD10_CODES, ICD10_CODE_SET } from "./constants";

test("classifyVital follows the documented reference ranges", () => {
  assert.equal(classifyVital("pulse", 72), "normal");
  assert.equal(classifyVital("pulse", 100), "watch");
  assert.equal(classifyVital("pulse", 121), "high");
  assert.equal(classifyVital("pulse", 55), "watch");
  assert.equal(classifyVital("spo2", 98), "normal");
  assert.equal(classifyVital("spo2", 92), "watch");
  assert.equal(classifyVital("spo2", 89), "high");
  assert.equal(classifyVital("temp", 98.4), "normal");
  assert.equal(classifyVital("temp", 100), "watch");
  assert.equal(classifyVital("temp", 102), "high");
  assert.equal(classifyVital("rr", 16), "normal");
  assert.equal(classifyVital("rr", 25), "watch");
});

test("classifyVital returns null for missing, non-numeric or unknown readings", () => {
  assert.equal(classifyVital("pulse", null), null);
  assert.equal(classifyVital("pulse", ""), null);
  assert.equal(classifyVital("pulse", "abc"), null);
  assert.equal(classifyVital("weight", 70), null);
});

test("classifyBP", () => {
  assert.equal(classifyBP(118, 76), "normal");
  assert.equal(classifyBP(125, 78), "watch");
  assert.equal(classifyBP(118, 82), "watch");
  assert.equal(classifyBP(142, 85), "high");
  assert.equal(classifyBP(130, 92), "high");
  assert.equal(classifyBP(null, 80), null);
});

test("mapFreq normalises free text to a frequency code", () => {
  assert.equal(mapFreq("bd"), "bd");
  assert.equal(mapFreq("Twice daily"), "bd");
  assert.equal(mapFreq("1-1-1"), "td");
  assert.equal(mapFreq("four times a day"), "qid");
  assert.equal(mapFreq("SOS"), "sos");
  assert.equal(mapFreq("at bedtime"), "nocte");
  assert.equal(mapFreq("once daily"), "od");
  assert.equal(mapFreq("daily"), "od");
  assert.equal(mapFreq("1-0-1 daily"), "bd");   // "daily" must not win over the dose pattern
  assert.equal(mapFreq("three times daily"), "td");
  assert.equal(mapFreq(""), "od");
  assert.equal(mapFreq("something odd"), "od");
});

test("mapRoute normalises free text to a route code", () => {
  assert.equal(mapRoute("oral"), "oral");
  assert.equal(mapRoute("IV"), "iv");
  assert.equal(mapRoute("intramuscular"), "im");
  assert.equal(mapRoute("under tongue"), "sublingual");
  assert.equal(mapRoute("puff"), "inhaled");
  assert.equal(mapRoute(undefined), "oral");
});

test("wordsToNumber", () => {
  assert.equal(wordsToNumber("500"), 500);
  assert.equal(wordsToNumber("2.5"), 2.5);
  assert.equal(wordsToNumber("five hundred"), 500);
  assert.equal(wordsToNumber("banana"), null);
});

test("parseDrugSpeech pulls dose, frequency, duration and instructions out of dictation", () => {
  const d = parseDrugSpeech("Tablet paracetamol 500 milligrams twice a day for 5 days after food");
  assert.equal(d.dosage, "500mg");
  assert.equal(d.frequency, "bd");
  assert.equal(d.duration_days, "5");
  assert.equal(d.instructions, "After food");
  assert.equal(d.drug_name, "Paracetamol");
});

test("parseDrugSpeech handles spelled-out numbers and week durations", () => {
  const d = parseDrugSpeech("amoxicillin two hundred mg three times a day for two weeks");
  assert.equal(d.dosage, "200mg");
  assert.equal(d.frequency, "td");
  assert.equal(d.duration_days, "14");
});

test("parseDrugSpeech defaults to once daily", () => {
  assert.equal(parseDrugSpeech("cetirizine 10 mg").frequency, "od");
});

test("the ICD-10 starter table is well-formed and indexed", () => {
  assert.ok(ICD10_CODES.length > 20);
  for (const c of ICD10_CODES) {
    assert.ok(c.code && c.desc, `entry needs code and desc: ${JSON.stringify(c)}`);
    assert.ok(ICD10_CODE_SET.has(c.code.toUpperCase()));
  }
});

test("icdCodeForDescription: exact match, partial match and no match", () => {
  const first = ICD10_CODES[0];
  assert.equal(icdCodeForDescription(first.desc), first.code);
  assert.equal(icdCodeForDescription(first.desc.toUpperCase()), first.code);
  assert.equal(icdCodeForDescription(""), "");
  assert.equal(icdCodeForDescription("zzzz not a diagnosis zzzz"), "");
});

test("matchICD ranks keyword hits and respects the limit", () => {
  assert.deepEqual(matchICD(""), []);
  const hits = matchICD("fever with cough and running nose", 3);
  assert.ok(hits.length > 0 && hits.length <= 3);
  assert.ok(hits.every(h => h.code));
});

test("buildVisitSummary assembles the doctor's own entries", () => {
  const text = buildVisitSummary(
    { subjective: "fever for 3 days", assessment: "", plan: "rest and fluids", follow_up_in_days: 5 },
    [{ description: "Viral fever", is_primary: true }, { description: "Dehydration" }],
  );
  assert.match(text, /Patient reports: fever for 3 days\./);
  assert.match(text, /Working diagnosis: Viral fever \(\+1 more\)\./);
  assert.match(text, /rest and fluids/);
});
