// Shared frontend helpers. Run with `npm test`.
import test from "node:test";
import assert from "node:assert/strict";

import { addDays, formatDateTime, timeAgo } from "./dates";
import { calcAge, formatAge } from "./age";
import { vaxBucket } from "./vaccination";
import { chunkBySize } from "./files";
import {
  NEEDS_ATTENTION, chipsFor, confidenceTone, fileKind, formatSize, matchesSearch, sortReports, stateOf, statusLine, typeLabel,
} from "./reports";

test("addDays moves a YYYY-MM-DD date forwards and backwards across month ends", () => {
  assert.equal(addDays("2026-01-30", 3), "2026-02-02");
  assert.equal(addDays("2026-03-01", -1), "2026-02-28");
});

test("formatDateTime and timeAgo tolerate empty values", () => {
  assert.equal(formatDateTime(null), "—");
  assert.equal(timeAgo(""), "");
});

test("timeAgo reports minutes, hours and falls back to a date after a day", () => {
  const ago = mins => new Date(Date.now() - mins * 60000).toISOString();
  assert.equal(timeAgo(ago(5)), "5 min ago");
  assert.equal(timeAgo(ago(180)), "3 hr ago");
  assert.equal(timeAgo(ago(60 * 48)), new Date(ago(60 * 48)).toLocaleDateString());
  assert.equal(timeAgo(new Date(Date.now() + 60000).toISOString()), "0 min ago");   // clock skew never goes negative
});

test("calcAge counts whole years and handles missing/invalid input", () => {
  const dob = new Date(); dob.setFullYear(dob.getFullYear() - 30); dob.setDate(dob.getDate() + 1);   // birthday tomorrow
  assert.equal(calcAge(dob.toISOString().slice(0, 10)), 29);
  assert.equal(calcAge(null), null);
  assert.equal(calcAge("not a date"), null);
  assert.equal(formatAge(null), "");
});

test("vaxBucket groups vaccination statuses", () => {
  assert.equal(vaxBucket({ status: "completed" }), "Completed");
  assert.equal(vaxBucket({ status: "declined" }), "Completed");
  assert.equal(vaxBucket({ status: "pending_review" }), "Needs Review");
  assert.equal(vaxBucket({ status: "rejected" }), "Needs Review");
  assert.equal(vaxBucket({ status: "ordered" }), "Needs Review");
  assert.equal(vaxBucket({ status: "unknown", timing: "due_now" }), "Needs Review");
  assert.equal(vaxBucket({ status: "unknown", timing: "past_window" }), "Needs Review");
  assert.equal(vaxBucket({ status: "unknown", timing: "later" }), "Upcoming");
  assert.equal(vaxBucket({ status: "scheduled" }), "Upcoming");
});

test("toLocalISODate / todayLocal use the local calendar day, not the UTC day", async () => {
  const { toLocalISODate, todayLocal } = await import("./dates");
  // 00:30 local on 15 March, whatever the machine's timezone is: the UTC date can differ, the local one must not.
  assert.equal(toLocalISODate(new Date(2026, 2, 15, 0, 30)), "2026-03-15");
  assert.equal(toLocalISODate(new Date(2026, 11, 31, 23, 59)), "2026-12-31");
  assert.match(todayLocal(), /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(todayLocal(), toLocalISODate(new Date()));
});

test("chunkBySize keeps order and splits by file count and by total size", () => {
  const files = (n, size = 1) => Array.from({ length: n }, (_, i) => ({ id: i, size }));
  assert.deepEqual(chunkBySize(files(120), 50, 1000).map(c => c.length), [50, 50, 20]);
  assert.deepEqual(chunkBySize(files(5, 100), 50, 250).map(c => c.length), [2, 2, 1]);
  assert.deepEqual(chunkBySize([{ size: 300 }], 50, 250).map(c => c.length), [1]);      // one big file still goes alone
  assert.deepEqual(chunkBySize([], 50, 250), []);
  assert.deepEqual(chunkBySize(files(120), 50, 1000).flat().map(f => f.id), files(120).map(f => f.id));
});

test("a report is in exactly one state and only the three problem states need attention", () => {
  const doc = (processing_status, doc_type = "") => ({ processing_status, doc_type });
  assert.equal(stateOf(doc("queued")), "processing");
  assert.equal(stateOf(doc("extracting")), "processing");
  assert.equal(stateOf(doc("classifying")), "processing");
  assert.equal(stateOf(doc("failed")), "failed");
  assert.equal(stateOf(doc("rejected")), "duplicate");
  assert.equal(stateOf(doc("completed", "lab_report")), "ready");
  assert.equal(stateOf(doc("completed", "")), "unclassified");
  assert.deepEqual([...NEEDS_ATTENTION].sort(), ["duplicate", "failed", "unclassified"]);
});

test("the line under a report says what happened, in plain words", () => {
  assert.equal(typeLabel("x_ray_report"), "X ray report");
  assert.equal(typeLabel(""), "Unable to classify");
  assert.match(statusLine({ processing_status: "extracting" }).text, /Reading the pages/);
  const unclear = statusLine({ processing_status: "completed", doc_type: "", best_guess: "lab_report", score: 20 });
  assert.equal(unclear.tone, "warn");
  assert.equal(unclear.text, "Unable to classify (closest: Lab report, 20% confident)");
  assert.equal(statusLine({ processing_status: "completed", doc_type: "" }).text, "Unable to classify");
  const dup = statusLine({ processing_status: "rejected", error: "Same as a.pdf, uploaded 01 Oct 2026." });
  assert.equal(dup.text, "Already in your reports — Same as a.pdf, uploaded 01 Oct 2026.");
  assert.equal(statusLine({ processing_status: "failed", error: "The file is empty." }).tone, "error");
  assert.match(statusLine({ processing_status: "completed", doc_type: "prescription", score: 46.15 }).text, /Prescription · 46% confident/);
  assert.equal(statusLine({ processing_status: "completed", doc_type: "scan", method: "staff" }).text, "Scan");
});

test("file kind, size and confidence tone", () => {
  assert.equal(fileKind({ mime_type: "application/pdf" }), "pdf");
  assert.equal(fileKind({ file_name: "scan.JPG" }), "image");
  assert.equal(fileKind({ file_name: "notes.txt" }), "other");
  assert.equal(formatSize(850 * 1024), "850 KB");
  assert.equal(formatSize(1.2 * 1048576), "1.2 MB");
  assert.equal(formatSize(null), "");
  assert.deepEqual([90, 70, 69, 40, 39, 0, null].map(confidenceTone), ["good", "good", "mid", "mid", "low", "low", "low"]);
});

test("the chips on a row say what it is and how sure we are", () => {
  const done = (extra) => ({ processing_status: "completed", doc_type: "lab_report", score: 83.4, method: "rule", ...extra });
  assert.deepEqual(chipsFor(done()), { type: { text: "Lab report", tone: "type" }, extra: { text: "83% confident", tone: "good" } });
  assert.equal(chipsFor(done({ method: "staff" })).extra.text, "Set by you");
  assert.equal(chipsFor(done({ source_tenant_id: 3 })).extra.text, "Issued by hospital");
  assert.equal(chipsFor({ processing_status: "completed", doc_type: "", score: 20 }).type.text, "Unable to classify");
  assert.equal(chipsFor({ processing_status: "completed", doc_type: "", score: 20 }).extra.text, "20% confident");
  assert.equal(chipsFor({ processing_status: "rejected" }).type.text, "Duplicate");
  assert.equal(chipsFor({ processing_status: "failed" }).type.tone, "bad");
  assert.equal(chipsFor({ processing_status: "extracting" }).type.text, "Reading…");
});

test("sorting and searching reports", () => {
  const docs = [
    { id: 1, title: "b report", created_at: "2026-10-01T10:00:00Z", size: 5, doc_type: "lab_report", processing_status: "completed" },
    { id: 2, title: "A scan", created_at: "2026-10-03T10:00:00Z", size: 50, doc_type: "", processing_status: "completed", best_guess: "scan" },
    { id: 3, title: "c copy", created_at: "2026-10-02T10:00:00Z", size: 1, doc_type: "", processing_status: "rejected" },
  ];
  const ids = (key) => sortReports(docs, key).map(d => d.id);
  assert.deepEqual(ids("newest"), [2, 3, 1]);
  assert.deepEqual(ids("oldest"), [1, 3, 2]);
  assert.deepEqual(ids("name"), [2, 1, 3]);
  assert.deepEqual(ids("size"), [2, 1, 3]);
  assert.deepEqual(docs.filter(d => matchesSearch(d, "lab")).map(d => d.id), [1]);          // by type
  assert.deepEqual(docs.filter(d => matchesSearch(d, "duplicate")).map(d => d.id), [3]);    // by state
  assert.deepEqual(docs.filter(d => matchesSearch(d, "scan")).map(d => d.id), [2]);         // by name / closest guess
  assert.equal(docs.filter(d => matchesSearch(d, "  ")).length, 3);
});
