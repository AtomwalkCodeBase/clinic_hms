/**
 * pages/doctor/EncounterPage.jsx
 * --------------------------------
 * Comprehensive consultation workspace.
 *
 * Sections:
 *   1. Patient info + vitals banner
 *   2. SOAP notes (S/O/A/P)
 *   3. ICD-10 diagnoses (searchable add, list with remove)
 *   4. Prescriptions (add drug lines inline)
 *   5. Investigations / orders
 *   6. Referral
 *   7. Advice + Follow-up
 *   8. Sign & Close
 */
import { useParams, useNavigate } from "react-router-dom";
import { useToast } from "../../hooks/useToast";
import { useApi } from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import { useState, useRef, useEffect } from "react";
import { encounterApi } from "../../api";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { Printer, Download, QrCode, X as XIcon, Sparkles } from "lucide-react";
import { FREQ_LABELS, HW_LOW_CONFIDENCE, HW_PENDING_STALE_MS, ICD10_CODE_SET, ROUTE_LABELS } from "./encounter/constants";
import { icdCodeForDescription, matchICD } from "./encounter/diagnosis";
import { parseDrugSpeech } from "./encounter/speech";
import { mapFreq, mapRoute } from "./encounter/drugs";
import { downloadVisitSummary } from "./encounter/summary";
import { buildVisitSummary } from "./encounter/visitSummary";
import { ClinicalSummaryHeader } from "./encounter/ClinicalSummaryHeader";
import { SectionCard } from "./encounter/SectionCard";
import { VitalsDisplay } from "./encounter/VitalsDisplay";
import { miniBtn } from "./encounter/styles";
import { DictateButton } from "./encounter/DictateButton";
import { Field, Textarea } from "./encounter/FormParts";
import { DiagnosisSearch } from "./encounter/DiagnosisSearch";
import { FavouritesBar } from "./encounter/FavouritesBar";
import { DrugForm } from "./encounter/DrugForm";
import { LabOrderSection } from "./encounter/LabOrderSection";
import { PastConsultationTab } from "./encounter/PastConsultationTab";
import { HistorySidebar } from "./encounter/HistorySidebar";
import { AdmissionReferralModal } from "./encounter/AdmissionReferralModal";
import { FollowUpModal } from "./encounter/FollowUpModal";
import { DocumentViewerDrawer } from "./encounter/DocumentViewerDrawer";
import { ConsultPadQRModal } from "./encounter/ConsultPadQRModal";
import { RecognisedTextModal } from "./encounter/RecognisedTextModal";

export default function EncounterPage() {
  const { id }   = useParams();
  const navigate = useNavigate();
  const { toastSuccess, toastError, toastApiError } = useToast();

  const { data: enc, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.ENCOUNTER(id));

  // Cross-hospital history — lifted up from the sidebar so the compact
  // clinical summary header can also read from it (allergies, active
  // problems) without a second, duplicate fetch.
  const { data: history, isLoading: historyLoading } = useApi(
    enc?.patient_pk ? API_ENDPOINTS.PATIENTS.HISTORY(enc.patient_pk) : null,
    { skip: !enc?.patient_pk }
  );

  // Form state
  const [form, setForm] = useState({
    subjective: "", objective: "", assessment: "", plan: "",
    investigations: "", advice_to_patient: "", follow_up_in_days: "",
    referred_to: "", referral_notes: "",
  });
  const [diagnoses, setDiagnoses] = useState([]);    // from enc.diagnoses
  const [saving,    setSaving]    = useState(false);
  const [signing,   setSigning]   = useState(false);
  const [dirty,     setDirty]     = useState(false);

  // Prescription state
  const [rxId,      setRxId]      = useState(null);
  const [rxItems,   setRxItems]   = useState([]);
  const [addingRx,  setAddingRx]  = useState(false);
  const [removingItem, setRemovingItem] = useState(null);

  // Voice dictation review state (human-in-the-loop)
  // { section, text, target?, drug?, codes?, selected? }
  const [dictation, setDictation] = useState(null);

  // Patient history sidebar — collapsed by default so it never crowds the
  // consultation workspace on first load; doctor opens it when needed.
  const [historyOpen, setHistoryOpen] = useState(false);
  const [viewerDoc, setViewerDoc] = useState(null); // document currently open in the resizable viewer
  const [activeTab, setActiveTab] = useState("consultation"); // "past" | "consultation"
  const [admissionModalOpen, setAdmissionModalOpen] = useState(false); // Recommend Admission is a button + modal, not a tab — see AdmissionReferralModal
  const [followUpModalOpen, setFollowUpModalOpen] = useState(false); // Book Follow-up is a button + modal too — see FollowUpModal

  // Handwriting session — the doctor starts it from this encounter
  // (POST .../consult-session/), shows the patient's QR, and writes on a
  // phone across two tabs. "Load handwritten note" pulls the current session
  // into the form; it's re-runnable and says "nothing new" when the session
  // hasn't changed since the last pull. See pages/public/ConsultPadPage.jsx.
  const [qrData, setQrData] = useState(null); // { qr_image, pad_url, session_id }
  const [qrOpen, setQrOpen] = useState(false);
  const [qrLoading, setQrLoading] = useState(false);
  const [recognisedNote, setRecognisedNote] = useState(null); // { note, rx } from the session
  const [textViewOpen, setTextViewOpen] = useState(false);
  const [loadingNote, setLoadingNote] = useState(false);
  const lastLoadedRef = useRef(null);       // session.updated_at at the last pull
  const loadedSnapshotRef = useRef({});     // field -> value as last loaded (to spot hand-edits)

  // Per-encounter sessionStorage so a page refresh doesn't lose the doctor's
  // "added" / "skipped" decisions or the still-to-review queue.
  const _ssKey = (k) => `hwpad:${id}:${k}`;
  const _ssGet = (k, fb) => { try { const v = sessionStorage.getItem(_ssKey(k)); return v ? JSON.parse(v) : fb; } catch { return fb; } };
  const _ssSet = (k, v) => { try { sessionStorage.setItem(_ssKey(k), JSON.stringify(v)); } catch { /* private mode / quota */ } };

  const loadedRxRef = useRef(new Set(_ssGet("dismissRx", []))); // norm drug names already added or skipped
  const loadedDxRef = useRef(new Set(_ssGet("dismissDx", []))); // norm diagnosis descs already added or skipped
  const [pendingRx, setPendingRx] = useState(() => _ssGet("pendingRx", [])); // Rx lines staged for review
  const [pendingDx, setPendingDx] = useState(() => _ssGet("pendingDx", [])); // diagnoses staged for review

  useEffect(() => { _ssSet("pendingRx", pendingRx); }, [pendingRx]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { _ssSet("pendingDx", pendingDx); }, [pendingDx]); // eslint-disable-line react-hooks/exhaustive-deps

  const _normName = (s) => (s || "").trim().toLowerCase().replace(/\s+/g, " ");
  const rememberDismissedRx = (n) => { loadedRxRef.current.add(n); _ssSet("dismissRx", [...loadedRxRef.current]); };
  const rememberDismissedDx = (n) => { loadedDxRef.current.add(n); _ssSet("dismissDx", [...loadedDxRef.current]); };
  const editPendingRx = (idx, patch) => setPendingRx(prev => prev.map((r, i) => i === idx ? { ...r, ...patch } : r));
  const editPendingDx = (idx, patch) => setPendingDx(prev => prev.map((r, i) => i === idx ? { ...r, ...patch } : r));

  // Drop staged items that are already on the record (e.g. after a refresh, or
  // if the doctor added one manually in the meantime).
  useEffect(() => {
    if (!pendingRx.length || !rxItems.length) return;
    const have = new Set(rxItems.map(i => _normName(i.drug_name)));
    setPendingRx(prev => prev.filter(it => !have.has(_normName(it.drug_name))));
  }, [rxItems]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!pendingDx.length || !diagnoses.length) return;
    const have = new Set(diagnoses.map(d => _normName(d.description)));
    setPendingDx(prev => prev.filter(d => !have.has(_normName(d.description))));
  }, [diagnoses]); // eslint-disable-line react-hooks/exhaustive-deps

  // Merge a session's recognised content into the encounter draft. SOAP-ish
  // text fields are replaced only where the doctor hasn't hand-edited since
  // the last load. Prescription lines AND diagnoses are NOT written to the
  // record here — they are staged into `pendingRx` / `pendingDx` for the
  // doctor to add one by one. Returns { set, changed, rxStaged, dxStaged, noteLowConf }.
  async function applyRecognised({ note, rx }) {
    setRecognisedNote({ note: note || null, rx: rx || null });
    const snap = loadedSnapshotRef.current;
    let set = 0, changed = 0, dxStaged = 0;

    // The model reports how confident it is that this was a legible clinical
    // note. Below the threshold we do NOT auto-fill the SOAP fields — the
    // doctor is pointed at "View text" to read it and copy anything useful by
    // hand, rather than have low-trust text land silently in the record.
    const lowConf = (t) => !!t && t.status === "done" &&
      typeof t.confidence === "number" && t.confidence < HW_LOW_CONFIDENCE;
    const noteLowConf = lowConf(note);
    const rxLowConf = lowConf(rx);
    const noteOk = !!note && note.status === "done" && !noteLowConf;
    const rxOk   = !!rx   && rx.status === "done"   && !rxLowConf;
    const anyLowConf = noteLowConf || rxLowConf;

    // ONE combined context. The doctor writes wherever they like — the
    // Prescription pad, the Internal Note pad, or both — and every field is
    // merged from both. No "this tab loads that field" rule to remember.
    const merge = (a, b) => {
      a = String(a || "").trim(); b = String(b || "").trim();
      if (!a) return b;
      if (!b || a === b) return a;
      const la = a.toLowerCase(), lb = b.toLowerCase();
      if (la.includes(lb)) return a;
      if (lb.includes(la)) return b;
      return `${a}\n${b}`;
    };
    const val = (src) => merge(noteOk ? note[src] : "", rxOk ? rx[src] : "");

    if (noteOk || rxOk) {
      const map = [
        ["subjective", "subjective"], ["objective", "objective"],
        ["assessment", "assessment"], ["plan", "plan"],
        ["investigations", "investigations"], ["advice", "advice_to_patient"],
      ];
      setForm(prev => {
        const m = { ...prev };
        const before = { set, changed };
        for (const [src, field] of map) {
          const inc = val(src);
          if (!inc) continue;
          const cur = (prev[field] || "").trim();
          if (!cur || cur === (snap[field] || "")) { m[field] = inc; set++; }
          else if (cur !== inc) { changed++; }
          snap[field] = inc;
        }
        // The model transcribed the note but didn't split it into SOAP
        // sections (common for a short free-form note) — don't silently drop
        // it. Drop the verbatim transcription into Subjective so it's on
        // screen for the doctor to re-file, instead of only living behind
        // "View text".
        if (set === before.set && changed === before.changed) {
          const raw = merge(noteOk ? note.raw_text : "", rxOk ? rx.raw_text : "");
          const cur = (prev.subjective || "").trim();
          if (raw && (!cur || cur === (snap.subjective || ""))) {
            m.subjective = raw;
            snap.subjective = raw;
            set++;
          }
        }
        const fu = (noteOk && note.follow_up_days != null && note.follow_up_days !== "")
          ? note.follow_up_days
          : (rxOk ? rx.follow_up_days : null);
        if (fu != null && fu !== "") {
          const cur = String(prev.follow_up_in_days || "").trim();
          if (!cur || cur === (snap.follow_up_in_days || "")) { m.follow_up_in_days = String(fu); set++; }
          snap.follow_up_in_days = String(fu);
        }
        return m;
      });

      // Diagnoses are staged for review (same as Rx) — a hallucinated
      // diagnosis or a wrong ICD code must not land on the record unseen.
      // Merged from whichever pad(s) they were written on.
      const dxIn = [
        ...(noteOk && Array.isArray(note.diagnoses) ? note.diagnoses : []),
        ...(rxOk && Array.isArray(rx.diagnoses) ? rx.diagnoses : []),
      ];
      if (dxIn.length) {
        const haveDx = new Set([
          ...diagnoses.map(d => _normName(d.description)),
          ...loadedDxRef.current,
        ]);
        const stagedDx = [];
        for (const d of dxIn) {
          const desc = (d?.description || "").trim();
          if (!desc || haveDx.has(_normName(desc))) continue;
          haveDx.add(_normName(desc));   // both pads may carry the same Dx
          const rawCode = (d?.code || "").trim().toUpperCase();
          const codeOk = !!rawCode && ICD10_CODE_SET.has(rawCode);
          const code = codeOk ? rawCode : icdCodeForDescription(desc);
          const flags = [];
          if (rawCode && !codeOk) flags.push(`read code ${rawCode} is not a known ICD-10 — replaced with a suggestion`);
          if (!code) flags.push("no ICD-10 code — add one before signing");
          stagedDx.push({ description: desc, code, raw_code: rawCode, code_verified: codeOk, flags });
        }
        setPendingDx(stagedDx);
        dxStaged = stagedDx.length;
      }
    }

    // Prescription lines are never written straight to the record — a mis-read
    // or hallucinated drug would land as a real order. Stage them into
    // `pendingRx`; the doctor adds each one explicitly from the review panel
    // under the Prescription card. De-dupe against what's already prescribed
    // and against lines the doctor already added or dismissed (`loadedRxRef`),
    // so re-loading the same pad is idempotent.
    let rxStaged = 0;
    const drugsOf = (t) => Array.isArray(t?.items) ? t.items
      : Array.isArray(t?.prescription) ? t.prescription : [];
    const rxIn = [
      ...(rxOk ? drugsOf(rx) : []),
      ...(noteOk ? drugsOf(note) : []),
    ].filter(x => (x?.drug_name || "").trim());
    if ((rxOk || noteOk) && rxIn.length) {
      const normDrug = (s) => (s || "").trim().toLowerCase().replace(/\s+/g, " ");
      const have = new Set([
        ...rxItems.map(i => normDrug(i.drug_name)),
        ...loadedRxRef.current,
      ]);
      const staged = rxIn.filter(it => {
        const n = normDrug(it.drug_name);
        if (!n || have.has(n)) return false;
        have.add(n);        // both pads may carry the same drug line
        return true;
      });
      setPendingRx(staged);
      rxStaged = staged.length;
    }

    if (set || changed) setDirty(true);
    return { set, changed, rxStaged, dxStaged, noteLowConf: anyLowConf };
  }

  async function openConsultPadQR() {
    if (!enc?.id) return;
    setQrLoading(true);
    try {
      const { data } = await encounterApi.createConsultSession(enc.id);
      setQrData(data?.data || data);
      setQrOpen(true);
    } catch (err) {
      toastApiError(err, "Could not start the handwriting session.");
    } finally {
      setQrLoading(false);
    }
  }

  // ── Handwriting: one pull + an auto-watch ─────────────────────────────────
  // The doctor can't know when transcription finishes (it runs on the phone's
  // autosave and can take 30-120s), so a single "Load" click that comes back
  // "still transcribing" is useless. Instead: pull once, and if it's not ready
  // yet, poll every few seconds and fill the fields the moment it lands — with
  // a small progress bar in place of the button meanwhile.
  const HW_WATCH_MAX_MS = 150_000;
  const HW_POLL_EVERY_TICKS = 3;   // 1s ticks → poll every 3s
  const [hwWatch, setHwWatch] = useState(false);
  const [hwElapsed, setHwElapsed] = useState(0);   // seconds since the watch began
  const hwTimerRef = useRef(null);
  const hwStartRef = useRef(0);
  const hwPct = Math.min(95, Math.round((hwElapsed / (HW_WATCH_MAX_MS / 1000)) * 100));

  const stopHwWatch = () => {
    if (hwTimerRef.current) { clearInterval(hwTimerRef.current); hwTimerRef.current = null; }
    setHwWatch(false);
    setHwElapsed(0);
  };
  useEffect(() => () => { if (hwTimerRef.current) clearInterval(hwTimerRef.current); }, []);

  // Fetch the session and either apply it or report why not.
  //   "settled"  — applied, or there's nothing more coming (stop)
  //   "waiting"  — recognition still running (keep polling)
  //   "inactive" — no session started yet (stop)
  // `quiet` suppresses the informational toasts ("no session", "nothing new")
  // used by the poll loop; terminal errors and a real apply always toast.
  async function pullHandwrittenNote({ quiet = false } = {}) {
    if (!enc?.id) return "inactive";
    try {
      const { data: res } = await encounterApi.getConsultSession(enc.id);
      const s = res?.data || res;
      if (!s?.active) {
        if (!quiet) toastError('No handwriting session yet — tap "Handwrite (QR)" and write on the phone first.');
        return "inactive";
      }
      const rxDone = s.rx && s.rx.status === "done";
      const noteDone = s.note && s.note.status === "done";
      if (s.updated_at && s.updated_at === lastLoadedRef.current && !quiet) {
        // Nothing new written since the last load. Re-apply the compiled
        // result anyway (the doctor may have cleared a field and wants it
        // back) — but don't re-run the model.
        if (rxDone || noteDone) {
          await applyRecognised({ note: s.note, rx: s.rx });
          toastSuccess("Re-applied the handwritten note.");
        } else {
          toastSuccess("Already loaded — nothing new on the phone since the last pull.");
        }
        return "settled";
      }
      const isStale = (t) => t && t.status === "pending" && t.at &&
        (Date.now() - new Date(t.at).getTime() > HW_PENDING_STALE_MS);
      const anyStale = isStale(s.rx) || isStale(s.note);
      const anyPending = !anyStale && ((s.rx && s.rx.status === "pending") || (s.note && s.note.status === "pending"));
      const anyEmpty = (s.rx && s.rx.status === "empty") || (s.note && s.note.status === "empty");
      const noteFailed = s.note && s.note.status === "failed";
      const rxFailed = s.rx && s.rx.status === "failed";

      if (!rxDone && !noteDone) {
        if (anyPending) return "waiting";   // still transcribing — poll again, no toast
        if (anyStale) toastError("Recognition timed out — write a little more on the phone to retry it, or type the note in.");
        else if (anyEmpty) toastError("The phone pages look blank or unreadable — write the note, then load again.");
        else if (noteFailed || rxFailed) toastError("Couldn't read the handwriting this time. Write a little clearer on the phone and load again, or type it in.");
        else if (!quiet) toastError("Nothing recognised yet — write on the phone, then load.");
        return anyEmpty || anyStale || noteFailed || rxFailed ? "settled" : "waiting";
      }

      const { set, changed, rxStaged, dxStaged, noteLowConf } = await applyRecognised({ note: s.note, rx: s.rx });
      setRecognisedNote({ note: s.note || null, rx: s.rx || null, rxPages: s.rx_pages || [], notePages: s.note_pages || [] });
      lastLoadedRef.current = s.updated_at || null;
      const bits = [];
      if (set) bits.push(`${set} field${set > 1 ? "s" : ""} filled`);
      if (rxStaged) bits.push(`${rxStaged} medication${rxStaged > 1 ? "s" : ""} to review`);
      if (dxStaged) bits.push(`${dxStaged} diagnos${dxStaged > 1 ? "es" : "is"} to review`);
      let msg = bits.length ? `Loaded — ${bits.join(", ")}.` : "Loaded — no new content.";
      if (noteLowConf) msg += ' The note came back low-confidence — open "View text" and check it before relying on it.';
      const lowInk = (s.note && s.note.low_ink) || (s.rx && s.rx.low_ink);
      if (lowInk) msg += " Very little was written on the page — check what was read.";
      const pageWarn = (s.note && s.note.page_warnings) || (s.rx && s.rx.page_warnings);
      if (pageWarn) msg += " " + pageWarn;
      if (changed) msg += ` ${changed} field${changed > 1 ? "s" : ""} changed on the phone — you'd edited them, so they were left as-is (see "View text").`;
      if (anyPending) msg += " (The other tab is still transcribing — it'll fill in automatically.)";
      if (noteDone && !rxDone && rxFailed) msg += " Couldn't read the Prescription tab — load again or add drugs manually.";
      if (rxDone && !noteDone && noteFailed) msg += " Couldn't read the Internal Note tab — load again or type it in.";
      toastSuccess(msg);
      return anyPending ? "waiting" : "settled";
    } catch (err) {
      if (!quiet) toastApiError(err, "Could not load the handwriting session.");
      return "waiting";   // transient — let the poll retry
    }
  }

  async function loadHandwrittenNote() {
    if (!enc?.id || loadingNote || hwWatch) return;
    setLoadingNote(true);
    let verdict = "waiting";
    try {
      // Lazy compile: nothing is transcribed until this click. The server
      // only runs the model over pages it hasn't seen before (a re-load after
      // the patient adds more just picks up the new pages), then re-reads.
      try {
        await encounterApi.recogniseConsultSession(enc.id);
      } catch { /* the pull below reports if there's no session yet */ }
      verdict = await pullHandwrittenNote({ quiet: false });
    } finally {
      setLoadingNote(false);
    }
    if (verdict !== "waiting") return;
    // Not ready — start watching. Fill the fields the moment it lands.
    hwStartRef.current = Date.now();
    setHwElapsed(0);
    setHwWatch(true);
    hwTimerRef.current = setInterval(async () => {
      const secs = Math.round((Date.now() - hwStartRef.current) / 1000);
      setHwElapsed(secs);
      if (Date.now() - hwStartRef.current > HW_WATCH_MAX_MS) {
        stopHwWatch();
        toastError("Recognition is taking longer than usual — keep writing on the phone, or type the note in and load again later.");
        return;
      }
      if (secs % HW_POLL_EVERY_TICKS !== 0) return;
      const r = await pullHandwrittenNote({ quiet: true });
      if (r !== "waiting") stopHwWatch();
    }, 1000);
  }

  function openDictation(section, text) {
    const base = { section, text };
    if (section === "soap")         base.target = "subjective";
    if (section === "diagnoses")  { base.codes = matchICD(text); base.selected = {}; }
    if (section === "prescription") base.drug = parseDrugSpeech(text);
    setDictation(base);
  }

  function applyDictation() {
    const d = dictation;
    if (!d) return;
    const text = d.text.trim();
    if (d.section === "soap") {
      upd(d.target, form[d.target] ? `${form[d.target]}\n${text}` : text);
    } else if (d.section === "investigations") {
      upd("investigations", form.investigations ? `${form.investigations}\n${text}` : text);
    } else if (d.section === "referral") {
      upd("referral_notes", form.referral_notes ? `${form.referral_notes}\n${text}` : text);
    } else if (d.section === "advice") {
      upd("advice_to_patient", form.advice_to_patient ? `${form.advice_to_patient}\n${text}` : text);
    } else if (d.section === "diagnoses") {
      const chosen = (d.codes || []).filter(c => d.selected[c.code]);
      chosen.forEach(c => addDiagnosis({ code: c.code, description: c.desc, clinical_status: "active", is_primary: false }));
      if (chosen.length === 0 && text) {
        // nothing matched — drop the transcript into Assessment so it isn't lost
        upd("assessment", form.assessment ? `${form.assessment}\n${text}` : text);
      }
    } else if (d.section === "prescription") {
      addDrug({ ...d.drug, duration_days: d.drug.duration_days ? parseInt(d.drug.duration_days) : null });
    }
    setDictation(null);
  }

  // Seed form from server data
  useEffect(() => {
    if (!enc) return;
    setForm({
      subjective:        enc.subjective        || "",
      objective:         enc.objective         || "",
      assessment:        enc.assessment        || "",
      plan:              enc.plan              || "",
      investigations:    enc.investigations    || "",
      advice_to_patient: enc.advice_to_patient || "",
      follow_up_in_days: enc.follow_up_in_days != null ? String(enc.follow_up_in_days) : "",
      referred_to:       enc.referred_to       || "",
      referral_notes:    enc.referral_notes    || "",
    });
    setDiagnoses(enc.diagnoses || []);
    if (enc.prescription) {
      setRxId(enc.prescription.id);
      setRxItems(enc.prescription.items || []);
    }
    setDirty(false);
  }, [enc]);

  const isClosed = enc?.status === "signed";
  // appointment_type is unreliable in real data — the live booking flow
  // (PortalBookView.post) hardcodes "opd" even for "Book follow-up" links,
  // so it's only ever "followup" for demo-seeded encounters. Fall back to
  // the chief complaint text, which is what's actually set in practice.
  const isFollowUp = enc?.appointment_type === "followup" || /^\s*follow[\s-]?up/i.test(enc?.chief_complaint || "");

  function upd(k, v) { setForm(p => ({ ...p, [k]: v })); setDirty(true); }

  // ── Save draft ──────────────────────────────────────────────────────────────
  async function saveDraft() {
    setSaving(true);
    try {
      const payload = {
        ...form,
        follow_up_in_days: form.follow_up_in_days ? parseInt(form.follow_up_in_days) : null,
        diagnoses,
      };
      await encounterApi.save(id, payload);
      toastSuccess("Notes saved.");
      setDirty(false);
      refetch();
    } catch (err) {
      toastApiError(err, "Failed to save notes.");
    } finally {
      setSaving(false);
    }
  }

  // ── Diagnoses ───────────────────────────────────────────────────────────────
  function addDiagnosis(diag) {
    // avoid duplicates
    if (diagnoses.some(d => d.code === diag.code)) {
      toastError("Diagnosis already added.");
      return;
    }
    const updated = [...diagnoses, { ...diag, is_primary: diagnoses.length === 0 }];
    setDiagnoses(updated);
    setDirty(true);
  }

  function removeDiagnosis(idx) {
    const updated = diagnoses.filter((_, i) => i !== idx);
    setDiagnoses(updated);
    setDirty(true);
  }

  function togglePrimary(idx) {
    setDiagnoses(prev => prev.map((d, i) => ({ ...d, is_primary: i === idx })));
    setDirty(true);
  }

  // ── Prescription ────────────────────────────────────────────────────────────
  async function ensureRx() {
    if (rxId) return rxId;
    const res = await encounterApi.createPrescription(id);
    const newId = res.data?.id || res.data?.data?.id;
    setRxId(newId);
    return newId;
  }

  async function addDrug(drugData) {
    setAddingRx(true);
    try {
      const pid = await ensureRx();
      const res = await encounterApi.addPrescriptionItem(pid, drugData);
      const item = res.data?.data || res.data;
      setRxItems(prev => [...prev, item]);
      toastSuccess("Drug added.");
    } catch (err) {
      toastApiError(err, "Failed to add drug.");
    } finally {
      setAddingRx(false);
    }
  }

  async function removeDrug(itemId) {
    if (!rxId) return;
    setRemovingItem(itemId);
    try {
      await encounterApi.removePrescriptionItem(rxId, itemId);
      setRxItems(prev => prev.filter(i => i.id !== itemId));
    } catch (err) {
      toastApiError(err, "Failed to remove drug.");
    } finally {
      setRemovingItem(null);
    }
  }

  // ── Handwriting: staged Rx / Dx review ───────────────────────────────────
  // Recognised prescription lines and diagnoses wait in `pendingRx` /
  // `pendingDx` until the doctor adds them here — nothing from handwriting is
  // written to the record on its own. Doctors can edit a staged row first;
  // that edit is what gets saved.
  function _rxPayload(it) {
    return {
      drug_name: (it.drug_name || "").trim(),
      dosage: (it.dosage || "").trim() || "as directed",
      frequency: mapFreq(it.frequency),
      route: mapRoute(it.route),
      duration_days: Number.isFinite(+it.duration_days) && +it.duration_days > 0 ? parseInt(it.duration_days, 10) : null,
      instructions: (it.instructions || "").trim(),
    };
  }
  async function addPendingRx(idx) {
    const it = pendingRx[idx];
    if (!it || addingRx || !(it.drug_name || "").trim()) return;
    setAddingRx(true);
    try {
      const pid = await ensureRx();
      const res = await encounterApi.addPrescriptionItem(pid, _rxPayload(it));
      setRxItems(prev => [...prev, res.data?.data || res.data]);
      rememberDismissedRx(_normName(it.drug_name));
      setPendingRx(prev => prev.filter((_, i) => i !== idx));
      setDirty(true);
      toastSuccess("Added to prescription.");
    } catch (err) {
      toastApiError(err, "Could not add this drug.");
    } finally {
      setAddingRx(false);
    }
  }
  function skipPendingRx(idx) {
    const it = pendingRx[idx];
    if (it) rememberDismissedRx(_normName(it.drug_name));
    setPendingRx(prev => prev.filter((_, i) => i !== idx));
  }
  async function addAllPendingRx() {
    if (!pendingRx.length || addingRx) return;
    setAddingRx(true);
    try {
      const pid = await ensureRx();
      const added = [], names = [];
      for (const it of pendingRx) {
        if (!(it.drug_name || "").trim()) continue;
        try {
          const res = await encounterApi.addPrescriptionItem(pid, _rxPayload(it));
          added.push(res.data?.data || res.data);
          names.push(_normName(it.drug_name));
        } catch { /* skip the ones that fail, keep going */ }
      }
      if (added.length) {
        setRxItems(prev => [...prev, ...added]);
        names.forEach(rememberDismissedRx);
        setDirty(true);
      }
      setPendingRx([]);
      toastSuccess(`${added.length} medication${added.length === 1 ? "" : "s"} added.`);
    } catch (err) {
      toastApiError(err, "Could not add the medications.");
    } finally {
      setAddingRx(false);
    }
  }
  function dismissAllPendingRx() {
    pendingRx.forEach(it => rememberDismissedRx(_normName(it.drug_name)));
    setPendingRx([]);
  }

  // ── Favourites: re-add every item in a saved bundle ─────────────────────
  async function applyFavourite(items) {
    if (!items.length || addingRx) return;
    setAddingRx(true);
    try {
      const pid = await ensureRx();
      const added = [];
      for (const it of items) {
        try {
          const res = await encounterApi.addPrescriptionItem(pid, _rxPayload(it));
          added.push(res.data?.data || res.data);
        } catch { /* skip the ones that fail, keep going */ }
      }
      if (added.length) {
        setRxItems(prev => [...prev, ...added]);
        setDirty(true);
      }
      toastSuccess(`${added.length} medication${added.length === 1 ? "" : "s"} added from favourite.`);
    } catch (err) {
      toastApiError(err, "Could not add this favourite.");
    } finally {
      setAddingRx(false);
    }
  }

  function addPendingDx(idx) {
    const d = pendingDx[idx];
    if (!d || !(d.description || "").trim()) return;
    setDiagnoses(prev => {
      if (prev.some(x => _normName(x.description) === _normName(d.description))) return prev;
      return [...prev, {
        code: (d.code || "").trim(),
        description: d.description.trim(),
        clinical_status: "active",
        is_primary: prev.length === 0,
      }];
    });
    rememberDismissedDx(_normName(d.description));
    setPendingDx(prev => prev.filter((_, i) => i !== idx));
    setDirty(true);
  }
  function skipPendingDx(idx) {
    const d = pendingDx[idx];
    if (d) rememberDismissedDx(_normName(d.description));
    setPendingDx(prev => prev.filter((_, i) => i !== idx));
  }
  function addAllPendingDx() {
    if (!pendingDx.length) return;
    setDiagnoses(prev => {
      const out = [...prev];
      for (const d of pendingDx) {
        const desc = (d.description || "").trim();
        if (!desc || out.some(x => _normName(x.description) === _normName(desc))) continue;
        out.push({ code: (d.code || "").trim(), description: desc, clinical_status: "active", is_primary: out.length === 0 });
      }
      return out;
    });
    pendingDx.forEach(d => rememberDismissedDx(_normName(d.description)));
    setPendingDx([]);
    setDirty(true);
  }
  function dismissAllPendingDx() {
    pendingDx.forEach(d => rememberDismissedDx(_normName(d.description)));
    setPendingDx([]);
  }

  // ── Sign & close ────────────────────────────────────────────────────────────
  async function signAndClose() {
    if (!form.assessment.trim() && diagnoses.length === 0) {
      toastError("Add at least one diagnosis or fill in the Assessment field before signing.");
      return;
    }
    if (!window.confirm("Sign and close this encounter? This cannot be undone.")) return;
    setSigning(true);
    try {
      // Save draft first
      const payload = {
        ...form,
        follow_up_in_days: form.follow_up_in_days ? parseInt(form.follow_up_in_days) : null,
        diagnoses,
      };
      await encounterApi.save(id, payload);
      await encounterApi.sign(id);
      toastSuccess("Encounter signed and closed.");
      refetch();
    } catch (err) {
      toastApiError(err, "Could not sign encounter.");
    } finally {
      setSigning(false);
    }
  }

  // ─── Render ─────────────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <AppShell>
        <div style={{ padding: 60, textAlign: "center", color: "var(--color-text-muted)" }}>
          Loading encounter…
        </div>
      </AppShell>
    );
  }

  if (!enc) {
    return (
      <AppShell>
        <div style={{ padding: 60, textAlign: "center" }}>
          <div style={{ fontWeight: 600 }}>Encounter not found.</div>
          <button className="btn-outline" style={{ marginTop: 16 }} onClick={() => navigate("/doctor/queue")}>← Back to Queue</button>
        </div>
      </AppShell>
    );
  }

  const vitals = enc.vitals || null;

  return (
    <AppShell>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
      <PageShell
        title={enc.patient_name || "Consultation"}
        action={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button className="btn-outline" onClick={() => setAdmissionModalOpen(true)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
              Recommend Admission
            </button>
            <button className="btn-outline" onClick={() => setFollowUpModalOpen(true)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
              Book Follow-up
            </button>
            {isClosed ? (
              <>
                <button className="btn-outline" onClick={() => window.print()} title="Print this consultation" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                  <Printer size={14} /> Print
                </button>
                <button className="btn-outline" onClick={() => downloadVisitSummary(id)} title="Download a PDF summary of this visit" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                  <Download size={14} /> Download Summary
                </button>
                <span style={{ fontSize: 12, fontWeight: 700, padding: "6px 14px", background: "#D1FAE5", color: "#065F46", borderRadius: 8 }}>
                  ✓ Signed & Closed
                </span>
              </>
            ) : (
              <>
                {dirty && (
                  <button className="btn-outline" disabled={saving} onClick={saveDraft} style={{ minWidth: 100 }}>
                    {saving ? "Saving…" : "Save Draft"}
                  </button>
                )}
                <button className="btn-primary" disabled={signing} onClick={signAndClose} style={{ minWidth: 130 }}>
                  {signing ? "Signing…" : "Sign & Close"}
                </button>
              </>
            )}
          </div>
        }
      >
        <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--color-border)", marginBottom: 4 }}>
          {isFollowUp && (
            <button
              type="button"
              onClick={() => setActiveTab("past")}
              style={{
                padding: "10px 16px", fontSize: 13, fontWeight: 600, border: "none", background: "none", cursor: "pointer",
                color: activeTab === "past" ? "var(--color-primary)" : "var(--color-text-muted)",
                borderBottom: activeTab === "past" ? "2px solid var(--color-primary)" : "2px solid transparent",
                marginBottom: -1,
              }}
            >
              Past Consultation
            </button>
          )}
          <button
            type="button"
            onClick={() => setActiveTab("consultation")}
            style={{
              padding: "10px 16px", fontSize: 13, fontWeight: 600, border: "none", background: "none", cursor: "pointer",
              color: activeTab === "consultation" ? "var(--color-primary)" : "var(--color-text-muted)",
              borderBottom: activeTab === "consultation" ? "2px solid var(--color-primary)" : "2px solid transparent",
              marginBottom: -1,
            }}
          >
            {isFollowUp ? "Follow-up" : "Consultation"}
          </button>
        </div>

        {activeTab === "consultation" && (
        <>
        <div style={{ display: "grid", gap: 16 }}>

          {/* ── Compact clinical summary — understand the patient in 5 seconds ── */}
          <ClinicalSummaryHeader
            enc={enc}
            history={history}
            allergies={history?.allergies || []}
            activeProblems={
              diagnoses.length > 0
                ? diagnoses.map(d => d.description)
                : (history?.diagnoses || [])
                    .filter(d => ["active", "chronic"].includes(d.clinical_status))
                    .slice(0, 3)
                    .map(d => d.description)
            }
            vitals={vitals}
            isClosed={isClosed}
          />

          {/* ── Vitals (read-only) ──────────────────────────────────────────── */}
          <SectionCard title="Vitals (recorded by nurse)">
            <VitalsDisplay vitals={vitals} />
          </SectionCard>

          {/* ── SOAP Notes + Diagnoses side by side ────────────────────────── */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
          <SectionCard title="SOAP Notes"
            extra={
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <button
                  type="button"
                  onClick={() => openConsultPadQR()}
                  disabled={isClosed || qrLoading || !enc.patient_pk}
                  title="Show a QR to hand-write this note on a phone"
                  style={miniBtn("var(--color-border)", "var(--color-text)", "var(--color-surface)", isClosed)}
                >
                  <QrCode size={13} /> {qrLoading ? "…" : "Handwrite (QR)"}
                </button>
                {hwWatch ? (
                  <span
                    title="Reading your handwritten note — the fields fill in automatically when it's ready"
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 8, padding: "4px 10px",
                      border: "1px solid var(--color-primary)", borderRadius: 6,
                      background: "var(--color-primary-light)", fontSize: 12, fontWeight: 600,
                      color: "var(--color-primary)",
                    }}
                  >
                    <span style={{ width: 64, height: 4, borderRadius: 2, background: "var(--color-border)", overflow: "hidden", flexShrink: 0 }}>
                      <span style={{ display: "block", height: "100%", width: `${hwPct}%`, background: "var(--color-primary)", transition: "width .6s linear" }} />
                    </span>
                    Reading your note…
                    <button
                      type="button"
                      onClick={stopHwWatch}
                      title="Stop waiting"
                      style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-primary)", padding: 0, display: "inline-flex" }}
                    >
                      <XIcon size={13} />
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={loadHandwrittenNote}
                    disabled={isClosed || loadingNote || !enc.patient_pk}
                    title="Pull the handwritten note you wrote on the phone into these fields"
                    style={miniBtn("var(--color-primary)", "var(--color-primary)", "var(--color-primary-light)", isClosed)}
                  >
                    <Sparkles size={13} /> {loadingNote ? "Loading…" : "Load handwritten note"}
                  </button>
                )}
                {recognisedNote && (
                  <button
                    type="button"
                    onClick={() => setTextViewOpen(true)}
                    title="View the transcribed handwritten note"
                    style={miniBtn("var(--color-primary)", "var(--color-primary)", "var(--color-primary-light)", false)}
                  >
                    View text
                  </button>
                )}
                <DictateButton disabled={isClosed} onTranscript={t => openDictation("soap", t)} />
              </div>
            }>
            <Field label="S — Subjective (history & chief complaint in patient's words)">
              <Textarea
                value={form.subjective}
                onChange={v => upd("subjective", v)}
                disabled={isClosed}
                placeholder="e.g. Patient presents with fever for 3 days, chills, headache. No vomiting. No rash."
                rows={3}
              />
            </Field>
            <Field label="O — Objective (examination findings)">
              <Textarea
                value={form.objective}
                onChange={v => upd("objective", v)}
                disabled={isClosed}
                placeholder="e.g. Temp 38.5°C. Throat mildly hyperaemic. Chest clear. Abdomen soft, non-tender."
                rows={3}
              />
            </Field>
            <Field label="A — Assessment (working diagnosis / clinical impression)">
              <Textarea
                value={form.assessment}
                onChange={v => upd("assessment", v)}
                disabled={isClosed}
                placeholder="e.g. Viral fever — r/o dengue, r/o malaria. ? URTI."
                rows={2}
              />
            </Field>
            <Field label="P — Plan (treatment, investigations, follow-up)">
              <Textarea
                value={form.plan}
                onChange={v => upd("plan", v)}
                disabled={isClosed}
                placeholder="e.g. Tab Paracetamol 500mg TID × 5 days. CBC + NS1 antigen. Review in 48h or if rash appears."
                rows={3}
              />
            </Field>

            {/* Visit summary — plain-text digest of what's already been typed
                above, not a model-generated interpretation (no LLM is wired
                into this backend). Saves a re-read before signing. */}
            {(() => {
              const summary = buildVisitSummary(form, diagnoses);
              return summary ? (
                <div style={{
                  marginTop: 4, background: "#F5F3FF", border: "1px solid #DDD6FE", borderRadius: 8,
                  padding: "10px 12px",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10, fontWeight: 800, color: "#6D28D9", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 4 }}>
                    <Sparkles size={12} /> Visit Summary — auto-assembled from your notes
                  </div>
                  <div style={{ fontSize: 12, color: "#4C1D95", lineHeight: 1.5 }}>{summary}</div>
                </div>
              ) : null;
            })()}
          </SectionCard>

          {/* ── Right column: Diagnoses + Prescription ─────────────────────── */}
          <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
          <SectionCard title="Diagnoses (ICD-10)" badge={diagnoses.length}
            extra={<DictateButton disabled={isClosed} onTranscript={t => openDictation("diagnoses", t)} />}>
            {!isClosed && (
              <div style={{ marginBottom: 14 }}>
                <DiagnosisSearch onAdd={addDiagnosis} disabled={isClosed}
                  chiefComplaint={enc.chief_complaint} existingCodes={diagnoses.map(d => d.code)} />
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                  Type ICD-10 code or description to search. First diagnosis is automatically marked Primary.
                </div>
              </div>
            )}
            {!isClosed && pendingDx.length > 0 && (
              <div style={{ border: "1px solid var(--color-border)", borderRadius: 8, padding: 10, margin: "0 0 12px", background: "var(--color-bg-subtle, #f8fafc)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--color-text-muted)" }}>
                    From handwriting — review before adding
                  </span>
                  <span style={{ display: "flex", gap: 6 }}>
                    <button onClick={addAllPendingDx} style={miniBtn("var(--color-primary)", "#fff", "var(--color-primary)", false)}>Add all</button>
                    <button onClick={dismissAllPendingDx} style={miniBtn("var(--color-border)", "var(--color-text-muted)", "transparent", false)}>Dismiss all</button>
                  </span>
                </div>
                {pendingDx.map((d, idx) => {
                  const inp = { fontSize: 12, padding: "3px 5px", border: "1px solid var(--color-border)", borderRadius: 4, background: "var(--color-surface, #fff)", color: "var(--color-text)" };
                  const codeKnown = (d.code || "").trim() && ICD10_CODE_SET.has((d.code || "").trim().toUpperCase());
                  return (
                    <div key={idx} style={{ padding: "7px 0", borderTop: idx ? "1px solid var(--color-border)" : "none" }}>
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 6, flexWrap: "wrap" }}>
                        <input aria-label="Diagnosis" value={d.description || ""} onChange={e => editPendingDx(idx, { description: e.target.value })}
                          placeholder="diagnosis" style={{ ...inp, flex: "3 1 150px", fontWeight: 600 }} />
                        <input aria-label="ICD-10 code" value={d.code || ""} onChange={e => editPendingDx(idx, { code: e.target.value.toUpperCase() })}
                          placeholder="ICD-10" style={{ ...inp, flex: "0 1 84px", borderColor: codeKnown ? "var(--color-border)" : "#F59E0B" }} />
                        <span style={{ display: "flex", gap: 4, flexShrink: 0, marginLeft: "auto" }}>
                          <button onClick={() => addPendingDx(idx)} disabled={!(d.description || "").trim()} style={miniBtn("var(--color-primary)", "var(--color-primary)", "transparent", !(d.description || "").trim())}>Add</button>
                          <button onClick={() => skipPendingDx(idx)} style={miniBtn("var(--color-border)", "var(--color-text-muted)", "transparent", false)}>Skip</button>
                        </span>
                      </div>
                      {!codeKnown && (
                        <div style={{ marginTop: 3 }}>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 5px", borderRadius: 4, background: "#FEF3C7", color: "#92400E" }}>unverified code</span>
                        </div>
                      )}
                      {Array.isArray(d.flags) && d.flags.length > 0 && (
                        <div style={{ marginTop: 3, fontSize: 10.5, color: "var(--color-text-muted)" }}>{d.flags.join(" · ")}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {diagnoses.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>No diagnoses added yet.</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "1.5px solid var(--color-border)" }}>
                    <th style={{ padding: "6px 10px", fontSize: 11, color: "var(--color-text-muted)", fontWeight: 700 }}>ICD-10</th>
                    <th style={{ padding: "6px 10px", fontSize: 11, color: "var(--color-text-muted)", fontWeight: 700 }}>DESCRIPTION</th>
                    <th style={{ padding: "6px 10px", fontSize: 11, color: "var(--color-text-muted)", fontWeight: 700 }}>STATUS</th>
                    <th style={{ padding: "6px 10px", fontSize: 11, color: "var(--color-text-muted)", fontWeight: 700 }}>PRIMARY</th>
                    {!isClosed && <th style={{ width: 40 }}></th>}
                  </tr>
                </thead>
                <tbody>
                  {diagnoses.map((d, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ padding: "8px 10px", fontFamily: "monospace", color: "var(--color-primary)", fontWeight: 700 }}>{d.code}</td>
                      <td style={{ padding: "8px 10px" }}>{d.description}</td>
                      <td style={{ padding: "8px 10px" }}>
                        {isClosed ? (
                          <span style={{ textTransform: "capitalize" }}>{d.clinical_status}</span>
                        ) : (
                          <select
                            className="form-input"
                            style={{ padding: "3px 8px", fontSize: 12, width: "auto" }}
                            value={d.clinical_status}
                            onChange={e => {
                              const upd = diagnoses.map((x, xi) => xi === i ? { ...x, clinical_status: e.target.value } : x);
                              setDiagnoses(upd);
                              setDirty(true);
                            }}
                          >
                            <option value="active">Active</option>
                            <option value="resolved">Resolved</option>
                            <option value="chronic">Chronic</option>
                            <option value="suspected">Suspected</option>
                          </select>
                        )}
                      </td>
                      <td style={{ padding: "8px 10px" }}>
                        {d.is_primary ? (
                          <span style={{ color: "var(--color-primary)", fontWeight: 700, fontSize: 12 }}>● Primary</span>
                        ) : !isClosed ? (
                          <button
                            onClick={() => togglePrimary(i)}
                            style={{ fontSize: 11, color: "var(--color-text-muted)", background: "none", border: "1px solid var(--color-border)", borderRadius: 6, padding: "2px 8px", cursor: "pointer" }}
                          >
                            Set Primary
                          </button>
                        ) : (
                          <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>Secondary</span>
                        )}
                      </td>
                      {!isClosed && (
                        <td style={{ padding: "8px 6px", textAlign: "center" }}>
                          <button onClick={() => removeDiagnosis(i)} style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444", fontSize: 16, lineHeight: 1 }}>✕</button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </SectionCard>

          {/* ── Prescription (under Diagnoses, right column) ───────────────── */}
          <SectionCard title="Prescription" badge={rxItems.length}
            extra={<DictateButton disabled={isClosed} onTranscript={t => openDictation("prescription", t)} />}>
            <FavouritesBar currentItems={rxItems} onApply={applyFavourite} disabled={isClosed || addingRx} />
            {!isClosed && <DrugForm onSave={addDrug} disabled={addingRx} />}
            {!isClosed && pendingRx.length > 0 && (
              <div style={{ border: "1px solid var(--color-border)", borderRadius: 8, padding: 10, margin: "6px 0 12px", background: "var(--color-bg-subtle, #f8fafc)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--color-text-muted)" }}>
                    From handwriting — review before adding
                  </span>
                  <span style={{ display: "flex", gap: 6 }}>
                    <button onClick={addAllPendingRx} disabled={addingRx} style={miniBtn("var(--color-primary)", "#fff", "var(--color-primary)", addingRx)}>Add all</button>
                    <button onClick={dismissAllPendingRx} disabled={addingRx} style={miniBtn("var(--color-border)", "var(--color-text-muted)", "transparent", addingRx)}>Dismiss all</button>
                  </span>
                </div>
                {pendingRx.map((it, idx) => {
                  const raw = (it.drug_name_raw || "").trim();
                  const nm = (it.drug_name || "").trim();
                  const renamed = raw && raw.toLowerCase() !== nm.toLowerCase();
                  const lowConf = typeof it.confidence === "number" && it.confidence < HW_LOW_CONFIDENCE;
                  const chips = [];
                  if (!(it.dosage || "").trim()) chips.push("no dose");
                  if (!it.duration_days) chips.push("no duration");
                  if (it.frequency_defaulted) chips.push("assumed OD");
                  if (it.name_source === "catalog_fuzzy") chips.push("confirm match");
                  if (lowConf) chips.push("low confidence");
                  const inp = { fontSize: 12, padding: "3px 5px", border: "1px solid var(--color-border)", borderRadius: 4, background: "var(--color-surface, #fff)", color: "var(--color-text)" };
                  return (
                    <div key={idx} style={{ padding: "7px 0", borderTop: idx ? "1px solid var(--color-border)" : "none" }}>
                      {renamed && (
                        <div style={{ fontSize: 10.5, color: "var(--color-text-muted)", marginBottom: 3 }}>
                          read “{raw}” → matched “{nm}”
                        </div>
                      )}
                      <div style={{ display: "flex", alignItems: "flex-start", gap: 6, flexWrap: "wrap" }}>
                        <input aria-label="Drug name" value={it.drug_name || ""} onChange={e => editPendingRx(idx, { drug_name: e.target.value })}
                          placeholder="drug" style={{ ...inp, flex: "2 1 130px", fontWeight: 600 }} />
                        <input aria-label="Dose" value={it.dosage || ""} onChange={e => editPendingRx(idx, { dosage: e.target.value })}
                          placeholder="dose" style={{ ...inp, flex: "1 1 70px" }} />
                        <select aria-label="Frequency" value={mapFreq(it.frequency)} onChange={e => editPendingRx(idx, { frequency: e.target.value, frequency_defaulted: false })}
                          style={{ ...inp, flex: "0 1 68px" }}>
                          {Object.entries(FREQ_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                        <input aria-label="Duration in days" type="number" min="0" value={it.duration_days ?? ""} onChange={e => editPendingRx(idx, { duration_days: e.target.value === "" ? null : Math.max(0, parseInt(e.target.value, 10) || 0) })}
                          placeholder="days" style={{ ...inp, flex: "0 1 56px" }} />
                        <span style={{ display: "flex", gap: 4, flexShrink: 0, marginLeft: "auto" }}>
                          <button onClick={() => addPendingRx(idx)} disabled={addingRx || !(it.drug_name || "").trim()} style={miniBtn("var(--color-primary)", "var(--color-primary)", "transparent", addingRx || !(it.drug_name || "").trim())}>Add</button>
                          <button onClick={() => skipPendingRx(idx)} disabled={addingRx} style={miniBtn("var(--color-border)", "var(--color-text-muted)", "transparent", addingRx)}>Skip</button>
                        </span>
                      </div>
                      {chips.length > 0 && (
                        <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
                          {chips.map(c => (
                            <span key={c} style={{ fontSize: 10, fontWeight: 700, padding: "1px 5px", borderRadius: 4, background: c === "low confidence" ? "#FEE2E2" : "#FEF3C7", color: c === "low confidence" ? "#B91C1C" : "#92400E" }}>{c}</span>
                          ))}
                        </div>
                      )}
                      {Array.isArray(it.flags) && it.flags.length > 0 && (
                        <div style={{ marginTop: 3, fontSize: 10.5, color: "var(--color-text-muted)" }}>{it.flags.join(" · ")}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {rxItems.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>No drugs added yet.</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "1.5px solid var(--color-border)" }}>
                    {["Drug", "Dose", "Freq", "Route", "Duration", "Instructions", ""].map(h => (
                      <th key={h} style={{ padding: "6px 8px", fontSize: 11, color: "var(--color-text-muted)", fontWeight: 700 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rxItems.map(item => (
                    <tr key={item.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ padding: "8px 8px", fontWeight: 600 }}>{item.drug_name}</td>
                      <td style={{ padding: "8px 8px" }}>{item.dosage}</td>
                      <td style={{ padding: "8px 8px", fontWeight: 600, color: "var(--color-primary)" }}>
                        {FREQ_LABELS[item.frequency] || item.frequency}
                      </td>
                      <td style={{ padding: "8px 8px" }}>{ROUTE_LABELS[item.route] || item.route}</td>
                      <td style={{ padding: "8px 8px" }}>{item.duration_days ? `${item.duration_days}d` : "—"}</td>
                      <td style={{ padding: "8px 8px", color: "var(--color-text-muted)", fontStyle: "italic" }}>{item.instructions || "—"}</td>
                      {!isClosed && (
                        <td style={{ padding: "8px 6px", textAlign: "center" }}>
                          <button
                            onClick={() => removeDrug(item.id)}
                            disabled={removingItem === item.id}
                            style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444", fontSize: 15 }}
                          >
                            {removingItem === item.id ? "…" : "✕"}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </SectionCard>
          </div>{/* end right column */}
          </div>{/* end 2-col grid */}

          {/* ── Investigations + Referral + Advice, three across ───────────── */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, alignItems: "start" }}>
          <SectionCard title="Investigations / Orders"
            extra={<DictateButton disabled={isClosed} onTranscript={t => openDictation("investigations", t)} />}>
            <LabOrderSection encounterId={id} isClosed={isClosed} onViewReport={setViewerDoc} />
            <Field label="Other orders (radiology, imaging — not in the lab catalog)">
              <Textarea
                value={form.investigations}
                onChange={v => upd("investigations", v)}
                disabled={isClosed}
                placeholder="e.g. Chest X-ray PA view, ECG, USG Abdomen"
                rows={2}
              />
            </Field>
          </SectionCard>

          {/* ── Referral ───────────────────────────────────────────────────── */}
          <SectionCard title="Referral"
            extra={<DictateButton disabled={isClosed} onTranscript={t => openDictation("referral", t)} />}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 4 }}>
              <Field label="Refer to (specialty / doctor)">
                <input
                  className="form-input"
                  value={form.referred_to}
                  onChange={e => upd("referred_to", e.target.value)}
                  disabled={isClosed}
                  placeholder="e.g. Cardiologist, Dr. Sharma"
                />
              </Field>
              <Field label="Referral reason / notes">
                <input
                  className="form-input"
                  value={form.referral_notes}
                  onChange={e => upd("referral_notes", e.target.value)}
                  disabled={isClosed}
                  placeholder="e.g. Suspected CAD, needs stress test and cardiology opinion"
                />
              </Field>
            </div>
          </SectionCard>

          {/* ── Advice + Follow-up ─────────────────────────────────────────── */}
          <SectionCard title="Advice & Follow-up"
            extra={<DictateButton disabled={isClosed} onTranscript={t => openDictation("advice", t)} />}>
            <Field label="Advice to patient">
              <Textarea
                value={form.advice_to_patient}
                onChange={v => upd("advice_to_patient", v)}
                disabled={isClosed}
                placeholder="e.g. Rest, increase fluid intake. Avoid cold food. Return if fever persists beyond 5 days."
                rows={2}
              />
            </Field>
            <Field label="Follow-up in (days)">
              <input
                className="form-input"
                type="number"
                min="1"
                style={{ maxWidth: 160 }}
                value={form.follow_up_in_days}
                onChange={e => {
                  const v = e.target.value;
                  // "0" (or negative) isn't a real follow-up — it's just
                  // today, the same visit — so it's rejected here rather
                  // than silently accepted and only caught on save. Empty
                  // stays allowed (no follow-up needed).
                  if (v !== "" && parseInt(v, 10) < 1) return;
                  upd("follow_up_in_days", v);
                }}
                disabled={isClosed}
                placeholder="e.g. 7"
              />
              {form.follow_up_in_days && (
                <span style={{ fontSize: 12, color: "var(--color-text-muted)", marginLeft: 10 }}>
                  → Follow up on {new Date(Date.now() + parseInt(form.follow_up_in_days) * 864e5).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                </span>
              )}
            </Field>
          </SectionCard>
          </div>

          {/* ── Footer actions ─────────────────────────────────────────────── */}
          {!isClosed ? (
            <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", paddingTop: 4 }}>
              <button className="btn-outline" onClick={() => navigate("/doctor/queue")}>← Back to Queue</button>
              {dirty && (
                <button className="btn-outline" disabled={saving} onClick={saveDraft}>
                  {saving ? "Saving…" : "Save Draft"}
                </button>
              )}
              <button className="btn-primary" disabled={signing} onClick={signAndClose} style={{ minWidth: 160 }}>
                {signing ? "Signing…" : "Sign & Close Encounter"}
              </button>
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <div style={{ color: "var(--color-success)", fontWeight: 700, marginBottom: 10 }}>
                ✓ Encounter signed and submitted to Health Exchange.
              </div>
              <button className="btn-outline" onClick={() => navigate("/doctor/queue")}>← Back to Queue</button>
            </div>
          )}

        </div>

        {/* ── Dictation review modal (human-in-the-loop) ─────────────────── */}
        {dictation && (
          <div style={{
            position: "fixed", inset: 0, background: "color-mix(in srgb, var(--color-hero) 50%, transparent)",
            zIndex: 300, display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <div className="card" style={{ width: 620, maxWidth: "94vw", maxHeight: "86vh", overflowY: "auto", padding: 24 }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 4 }}>
                Review dictation
              </div>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 16 }}>
                Whisper transcript — edit anything before inserting. Nothing is saved until you confirm.
              </div>

              {/* Transcript (editable) */}
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Transcript</label>
              <textarea
                className="form-input"
                rows={3}
                style={{ width: "100%", boxSizing: "border-box", fontSize: 14, marginBottom: 16 }}
                value={dictation.text}
                onChange={e => {
                  const text = e.target.value;
                  setDictation(d => ({
                    ...d, text,
                    ...(d.section === "diagnoses" ? { codes: matchICD(text) } : {}),
                    ...(d.section === "prescription" ? { drug: parseDrugSpeech(text) } : {}),
                  }));
                }}
              />

              {/* SOAP: choose target field */}
              {dictation.section === "soap" && (
                <div style={{ marginBottom: 16 }}>
                  <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Insert into</label>
                  <select className="form-input" style={{ maxWidth: 320 }}
                    value={dictation.target}
                    onChange={e => setDictation(d => ({ ...d, target: e.target.value }))}>
                    <option value="subjective">S — Subjective</option>
                    <option value="objective">O — Objective</option>
                    <option value="assessment">A — Assessment</option>
                    <option value="plan">P — Plan</option>
                  </select>
                </div>
              )}

              {/* Diagnoses: matched ICD codes */}
              {dictation.section === "diagnoses" && (
                <div style={{ marginBottom: 16 }}>
                  <label className="stat-label" style={{ display: "block", marginBottom: 8 }}>Matched ICD-10 codes — tick to add</label>
                  {(dictation.codes || []).length === 0 ? (
                    <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                      No ICD match found — on confirm, the transcript goes into the Assessment field instead.
                    </div>
                  ) : (
                    dictation.codes.map(c => (
                      <label key={c.code} style={{
                        display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
                        border: "1px solid var(--color-border)", borderRadius: 8, marginBottom: 6,
                        cursor: "pointer", background: dictation.selected[c.code] ? "var(--color-primary-light)" : "transparent",
                      }}>
                        <input type="checkbox"
                          checked={!!dictation.selected[c.code]}
                          onChange={e => setDictation(d => ({
                            ...d, selected: { ...d.selected, [c.code]: e.target.checked },
                          }))} />
                        <span style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--color-primary)" }}>{c.code}</span>
                        <span style={{ fontSize: 13 }}>{c.desc}</span>
                      </label>
                    ))
                  )}
                </div>
              )}

              {/* Prescription: parsed drug, fully editable */}
              {dictation.section === "prescription" && (
                <div style={{ marginBottom: 16 }}>
                  <label className="stat-label" style={{ display: "block", marginBottom: 8 }}>Parsed drug — correct anything</label>
                  <div style={{ display: "grid", gridTemplateColumns: "1.4fr 0.8fr 0.8fr 0.8fr", gap: 10, marginBottom: 10 }}>
                    <div>
                      <label className="stat-label">Drug</label>
                      <input className="form-input" value={dictation.drug.drug_name}
                        onChange={e => setDictation(d => ({ ...d, drug: { ...d.drug, drug_name: e.target.value } }))} />
                    </div>
                    <div>
                      <label className="stat-label">Dose</label>
                      <input className="form-input" value={dictation.drug.dosage}
                        onChange={e => setDictation(d => ({ ...d, drug: { ...d.drug, dosage: e.target.value } }))} />
                    </div>
                    <div>
                      <label className="stat-label">Frequency</label>
                      <select className="form-input" value={dictation.drug.frequency}
                        onChange={e => setDictation(d => ({ ...d, drug: { ...d.drug, frequency: e.target.value } }))}>
                        {Object.entries(FREQ_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="stat-label">Days</label>
                      <input className="form-input" type="number" min="1" value={dictation.drug.duration_days || ""}
                        onChange={e => setDictation(d => ({ ...d, drug: { ...d.drug, duration_days: e.target.value } }))} />
                    </div>
                  </div>
                  <div>
                    <label className="stat-label">Instructions</label>
                    <input className="form-input" value={dictation.drug.instructions}
                      onChange={e => setDictation(d => ({ ...d, drug: { ...d.drug, instructions: e.target.value } }))} />
                  </div>
                </div>
              )}

              {/* Actions */}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button className="btn-outline" onClick={() => setDictation(null)}>Discard</button>
                <button className="btn-primary"
                  disabled={dictation.section === "prescription" && (!dictation.drug.drug_name.trim() || !dictation.drug.dosage.trim())}
                  onClick={applyDictation}>
                  {dictation.section === "diagnoses" ? "Add selected" : dictation.section === "prescription" ? "Add drug" : "Insert"}
                </button>
              </div>
            </div>
          </div>
        )}
        </>
        )}
        {activeTab === "past" && <PastConsultationTab encounterId={id} />}
      </PageShell>
        </div>
        <HistorySidebar
          patientPk={enc.patient_pk}
          patientUhid={enc.patient_uhid}
          history={history}
          isLoading={historyLoading}
          open={historyOpen}
          onToggle={() => setHistoryOpen(o => !o)}
          onOpenDocument={setViewerDoc}
        />
      </div>
      {admissionModalOpen && (
        <AdmissionReferralModal
          patientId={enc.patient_pk}
          patientName={enc.patient_name}
          patientUhid={enc.patient_uhid}
          encounterId={id}
          onClose={() => setAdmissionModalOpen(false)}
        />
      )}
      {followUpModalOpen && (
        <FollowUpModal
          enc={enc}
          encounterId={id}
          refetch={refetch}
          onClose={() => setFollowUpModalOpen(false)}
        />
      )}
      <DocumentViewerDrawer doc={viewerDoc} onClose={() => setViewerDoc(null)} />
      {qrOpen && qrData && (
        <ConsultPadQRModal
          data={qrData}
          patientName={enc.patient_name}
          onClose={() => setQrOpen(false)}
        />
      )}
      {textViewOpen && recognisedNote && (
        <RecognisedTextModal data={recognisedNote} onClose={() => setTextViewOpen(false)} />
      )}
    </AppShell>
  );
}
