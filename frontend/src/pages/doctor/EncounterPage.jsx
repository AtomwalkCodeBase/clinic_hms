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
import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate }  from "react-router-dom";
import { AppShell }    from "../../components/layout/AppShell";
import { PageShell }   from "../../components/common/PageShell";
import DependentBadge  from "../../components/common/DependentBadge";
import { useApi }      from "../../hooks/useApi";
import { useToast }    from "../../hooks/useToast";
import apiClient       from "../../services/api.client";
import API_ENDPOINTS   from "../../config/api.config";
import {
  AlertTriangle, Stethoscope, Pill, FlaskConical, Activity, Clock, Paperclip,
  Sparkles, Printer, Download, CalendarClock, Cake, User, Upload,
} from "lucide-react";

// ─── Common ICD-10 codes (expandable; backend search in Phase 2) ─────────────
const ICD10_CODES = [
  { code: "J06.9",  desc: "Acute upper respiratory infection, unspecified" },
  { code: "J02.9",  desc: "Acute pharyngitis, unspecified" },
  { code: "J00",    desc: "Acute nasopharyngitis (common cold)" },
  { code: "J18.9",  desc: "Pneumonia, unspecified" },
  { code: "J45.9",  desc: "Asthma, unspecified" },
  { code: "A09",    desc: "Gastroenteritis and colitis of unspecified origin" },
  { code: "K21.0",  desc: "GERD with esophagitis" },
  { code: "K29.7",  desc: "Gastritis, unspecified" },
  { code: "E11.9",  desc: "Type 2 diabetes mellitus without complications" },
  { code: "E11.65", desc: "Type 2 diabetes mellitus with hyperglycemia" },
  { code: "I10",    desc: "Essential (primary) hypertension" },
  { code: "I25.1",  desc: "Atherosclerotic heart disease" },
  { code: "I50.9",  desc: "Heart failure, unspecified" },
  { code: "N39.0",  desc: "Urinary tract infection, unspecified" },
  { code: "N18.9",  desc: "Chronic kidney disease, unspecified" },
  { code: "M54.5",  desc: "Low back pain" },
  { code: "M54.2",  desc: "Cervicalgia" },
  { code: "G43.9",  desc: "Migraine, unspecified" },
  { code: "G89.29", desc: "Pain, unspecified" },
  { code: "R50.9",  desc: "Fever, unspecified" },
  { code: "R05",    desc: "Cough" },
  { code: "R06.00", desc: "Dyspnea, unspecified" },
  { code: "R07.9",  desc: "Chest pain, unspecified" },
  { code: "R51",    desc: "Headache" },
  { code: "R11.2",  desc: "Nausea with vomiting, unspecified" },
  { code: "R10.9",  desc: "Abdominal pain, unspecified" },
  { code: "R42",    desc: "Dizziness and giddiness" },
  { code: "B34.9",  desc: "Viral infection, unspecified" },
  { code: "A91",    desc: "Dengue haemorrhagic fever" },
  { code: "B50.9",  desc: "Plasmodium falciparum malaria, unspecified" },
  { code: "L50.0",  desc: "Allergic urticaria" },
  { code: "L20.9",  desc: "Atopic dermatitis, unspecified" },
  { code: "F32.9",  desc: "Major depressive episode, unspecified" },
  { code: "F41.1",  desc: "Generalized anxiety disorder" },
  { code: "Z30.0",  desc: "Encounter for general examination" },
  { code: "Z00.0",  desc: "General adult medical examination" },
];

const FREQ_LABELS = { od:"OD", bd:"BD", td:"TD", qid:"QID", sos:"SOS", stat:"Stat", nocte:"Nocte", mane:"Mane" };
const ROUTE_LABELS = { oral:"Oral", iv:"IV", im:"IM", sc:"SC", topical:"Topical", inhaled:"Inhaled", rectal:"Rectal", sublingual:"SL" };

// ─── Tiny helpers ─────────────────────────────────────────────────────────────
function SectionCard({ title, badge, extra, children }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{
        padding: "10px 18px",
        borderBottom: "1px solid var(--color-border)",
        background: "#FAFAFA",
        fontWeight: 700, fontSize: 13,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        {title}
        {badge !== undefined && (
          <span style={{
            padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 700,
            background: badge > 0 ? "var(--color-primary)" : "var(--color-border)",
            color: badge > 0 ? "#fff" : "var(--color-text-muted)",
          }}>{badge}</span>
        )}
        {extra && <span style={{ marginLeft: "auto" }}>{extra}</span>}
      </div>
      <div style={{ padding: "16px 18px" }}>{children}</div>
    </div>
  );
}

// ─── Voice dictation button (Whisper) ────────────────────────────────────────
// Shared: send an audio Blob/File to the transcription endpoint and hand the
// resulting text back. Used by both live mic recording and file upload —
// TranscribeView on the backend just reads request.FILES["audio"], it
// doesn't care whether the bytes came from MediaRecorder or a picked file.
async function transcribeAudio(blob, filename) {
  const fd = new FormData();
  fd.append("audio", blob, filename);
  const { data } = await apiClient.post(API_ENDPOINTS.OPD.TRANSCRIBE, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data?.text || data?.data?.text || "";
}

function DictateButton({ onTranscript, disabled }) {
  const [state, setState] = useState("idle"); // idle | rec | busy
  const recRef = useRef(null);
  const chunksRef = useRef([]);
  const fileInputRef = useRef(null);

  async function toggle() {
    if (disabled || state === "busy") return;
    if (state === "rec") { recRef.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = e => { if (e.data.size) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        setState("busy");
        try {
          const blob = new Blob(chunksRef.current, { type: mr.mimeType || "audio/webm" });
          const text = await transcribeAudio(blob, "dictation.webm");
          if (text.trim()) onTranscript(text.trim());
          else window.alert("Nothing was transcribed — please try again, speaking clearly.");
        } catch (err) {
          window.alert(err?.data?.error || err?.message || "Transcription failed. Is faster-whisper installed on the server?");
        }
        setState("idle");
      };
      mr.start();
      recRef.current = mr;
      setState("rec");
    } catch {
      window.alert("Microphone access denied. Allow the mic in your browser settings.");
    }
  }

  async function onFilePicked(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file later
    if (!file || disabled || state === "busy") return;
    setState("busy");
    try {
      const text = await transcribeAudio(file, file.name || "upload.wav");
      if (text.trim()) onTranscript(text.trim());
      else window.alert("Nothing was transcribed from that file — try a clearer recording.");
    } catch (err) {
      window.alert(err?.data?.error || err?.message || "Transcription failed. Is faster-whisper installed on the server?");
    }
    setState("idle");
  }

  const looks = {
    idle: { label: "🎙 Dictate", bg: "var(--color-primary-light)", color: "var(--color-primary)", border: "1px solid var(--color-primary)" },
    rec:  { label: "⏹ Stop",    bg: "var(--color-error)",          color: "#fff",                   border: "1px solid var(--color-error)" },
    busy: { label: "… Transcribing", bg: "var(--color-border)",     color: "var(--color-text-muted)", border: "1px solid var(--color-border)" },
  }[state];

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <button type="button" onClick={toggle} disabled={disabled || state === "busy"}
        style={{
          fontSize: 11, fontWeight: 700, padding: "4px 12px", borderRadius: 20,
          background: looks.bg, color: looks.color, border: looks.border,
          cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
          animation: state === "rec" ? "pulse 1.2s infinite" : "none",
        }}>
        {looks.label}
      </button>
      {/* Upload-audio alternative — lets you test the dictation pipeline with
          a pre-recorded file instead of a live mic (e.g. no mic on this
          machine, or you want a repeatable sample clip). Goes through the
          exact same transcribe endpoint as live recording. */}
      <button type="button" title="Upload an audio file instead of recording live"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled || state !== "idle"}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 22, height: 22, borderRadius: "50%",
          background: "var(--color-surface)", color: "var(--color-text-muted)",
          border: "1px solid var(--color-border)",
          cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
        }}>
        <Upload size={12} />
      </button>
      <input ref={fileInputRef} type="file" accept="audio/*" onChange={onFilePicked} style={{ display: "none" }} />
    </span>
  );
}

// ─── Speech parsers (best-effort; doctor reviews before insert) ──────────────
// Rule-based, not model-based — deliberately kept that way (no LLM wired into
// this backend). Generalises across patients because it works purely on the
// SHAPE of the sentence (dose/unit/frequency/duration patterns), not on any
// patient-specific content, so it applies the same way to every dictation.
// Widened here to catch more of how doctors actually phrase things out loud —
// spelled-out numbers/durations, "every N hours" cadences, filler-word
// prefixes — while still leaving the doctor to review/edit before it's applied.

const WORD_NUM = {
  half: 0.5, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7,
  eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, twenty: 20,
};
function wordsToNumber(str) {
  const s = str.trim().toLowerCase();
  if (/^\d+(\.\d+)?$/.test(s)) return parseFloat(s);
  const parts = s.split(/\s+/);
  if (parts.length === 2 && parts[1] === "hundred" && WORD_NUM[parts[0]] != null) {
    return WORD_NUM[parts[0]] * 100;
  }
  return WORD_NUM[s] ?? null;
}

function parseDrugSpeech(t) {
  const text = t.toLowerCase().replace(/[.,]/g, " ").replace(/\s+/g, " ").trim();
  const d = { ...EMPTY_DRUG };

  // Dose — numeric ("500 mg") or spelled-out ("five hundred milligrams").
  const UNIT_RE = "mg|milligrams?|ml|millilit(?:re|er)s?|mcg|micrograms?|g|grams?|units?|iu";
  let dose = text.match(new RegExp(`(\\d+(?:\\.\\d+)?)\\s*(${UNIT_RE})\\b`));
  let doseIndex = dose?.index;
  if (dose) {
    const unit = dose[2].startsWith("milligram") ? "mg"
      : dose[2].startsWith("millilit") ? "ml"
      : dose[2].startsWith("microgram") ? "mcg"
      : dose[2].startsWith("gram") ? "g"
      : dose[2];
    d.dosage = `${dose[1]}${unit}`;
  } else {
    const spelled = text.match(new RegExp(`\\b((?:${Object.keys(WORD_NUM).join("|")})(?:\\s+hundred)?)\\s+(${UNIT_RE})\\b`));
    if (spelled) {
      const n = wordsToNumber(spelled[1]);
      const unit = spelled[2].startsWith("milligram") ? "mg"
        : spelled[2].startsWith("millilit") ? "ml"
        : spelled[2].startsWith("microgram") ? "mcg"
        : spelled[2].startsWith("gram") ? "g"
        : spelled[2];
      if (n != null) { d.dosage = `${n}${unit}`; doseIndex = spelled.index; }
    }
  }

  // Duration — digits or spelled-out, days/weeks/months all normalised to days.
  const durNum = "(\\d+|" + Object.keys(WORD_NUM).join("|") + "|a|an|couple(?:\\s+of)?)";
  const dur = text.match(new RegExp(`for\\s+${durNum}\\s+(day|days|week|weeks|month|months)\\b`));
  if (dur) {
    let n = /^\d+$/.test(dur[1]) ? parseInt(dur[1], 10)
      : /^(a|an)$/.test(dur[1]) ? 1
      : /couple/.test(dur[1]) ? 2
      : wordsToNumber(dur[1]);
    if (n != null) {
      const unit = dur[2].startsWith("week") ? 7 : dur[2].startsWith("month") ? 30 : 1;
      d.duration_days = String(Math.round(n * unit));
    }
  }

  // Frequency — including "every N hours" cadences and common shorthand.
  const everyHrs = text.match(/every\s+(\d+)\s*hours?/);
  if (everyHrs) {
    const h = parseInt(everyHrs[1], 10);
    d.frequency = h <= 6 ? "qid" : h <= 8 ? "td" : h <= 12 ? "bd" : "od";
  } else if (/four times|qid/.test(text)) d.frequency = "qid";
  else if (/three times|thrice|\btid\b|\btds\b/.test(text)) d.frequency = "td";
  else if (/twice|two times|\bbd\b|morning and (night|evening)/.test(text)) d.frequency = "bd";
  else if (/at night|nocte|bedtime|before (bed|sleep)/.test(text)) d.frequency = "nocte";
  else if (/every morning|in the morning|\bmane\b/.test(text)) d.frequency = "mane";
  else if (/as needed|\bsos\b|when required|if required|if needed/.test(text)) d.frequency = "sos";
  else if (/once (a day|daily)|one time|\bod\b/.test(text)) d.frequency = "od";
  else d.frequency = "od";

  const instr = text.match(/(after (food|meals)|before (food|meals)|with (food|milk|water)|on an? empty stomach|empty stomach)/);
  if (instr) d.instructions = instr[1].charAt(0).toUpperCase() + instr[1].slice(1);

  // Drug name — strip common spoken filler before/around the dose so the
  // remaining words are (usually) just the drug name.
  const FILLER = /\b(please|start|prescribe|give|add|put (?:him|her|them) on|let'?s start|tab|tablet|cap|capsule|syrup|syp|inj|injection|the patient on|patient on)\b/g;
  if (doseIndex != null) {
    const before = text.slice(0, doseIndex).replace(FILLER, "").trim();
    const words = before.split(/\s+/).filter(Boolean);
    d.drug_name = words.slice(-2).join(" ").trim() || before;
  } else {
    const cleaned = text.replace(FILLER, "").trim();
    d.drug_name = cleaned.split(/\s+/).slice(0, 2).join(" ");
  }
  d.drug_name = d.drug_name.replace(/\b\w/g, c => c.toUpperCase());
  return d;
}

// Lay-term → clinical-keyword expansions so common ways patients/doctors
// actually describe a complaint out loud ("sugar", "high bp") still match
// the ICD-10 description text, not just exact clinical vocabulary. Purely a
// static synonym table — still pattern matching, not model understanding, so
// it won't catch phrasing outside this list, but it materially widens what
// "for all the patients" dictation this can handle without an LLM.
const SYMPTOM_SYNONYMS = {
  sugar: ["diabetes"], fever: ["pyrexia", "fever"], "high bp": ["hypertension"],
  "high blood pressure": ["hypertension"], "low bp": ["hypotension"],
  cold: ["rhinitis", "cough"], flu: ["influenza"], cough: ["cough", "bronchitis"],
  "chest pain": ["angina", "chest"], "throat pain": ["pharyngitis", "throat"],
  "sore throat": ["pharyngitis", "throat"], "stomach pain": ["gastritis", "abdominal"],
  "stomach ache": ["gastritis", "abdominal"], "loose motion": ["diarrhea", "diarrhoea"],
  "loose motions": ["diarrhea", "diarrhoea"], "joint pain": ["arthritis"],
  "skin rash": ["dermatitis"], rash: ["dermatitis"], "urine infection": ["urinary", "infection"],
  breathless: ["asthma", "dyspnea"], breathlessness: ["asthma", "dyspnea"],
  "back pain": ["back", "spine"], headache: ["headache", "migraine"],
};

function matchICD(t) {
  const lower = t.toLowerCase();
  let expanded = lower;
  for (const [phrase, syns] of Object.entries(SYMPTOM_SYNONYMS)) {
    if (lower.includes(phrase)) expanded += " " + syns.join(" ");
  }
  const words = expanded.split(/[^a-z]+/).filter(w => w.length > 3);
  return ICD10_CODES
    .map(c => ({ c, score: words.filter(w => c.desc.toLowerCase().includes(w)).length }))
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 6)
    .map(x => x.c);
}

// ─── Visit summary — auto-assembled from what the doctor has already typed
// (chief complaint, working diagnosis, plan, follow-up). This is template
// text stitched from the doctor's own entries, not a model-generated
// clinical interpretation — labelled plainly in the UI as such rather than
// as "AI", since no LLM is wired into this backend yet.
function buildVisitSummary(form, diagnoses) {
  const parts = [];
  if (form.subjective?.trim()) parts.push(`Patient reports: ${form.subjective.trim()}.`);
  if (diagnoses.length > 0) {
    const primary = diagnoses.find(d => d.is_primary) || diagnoses[0];
    parts.push(`Working diagnosis: ${primary.description}${diagnoses.length > 1 ? ` (+${diagnoses.length - 1} more)` : ""}.`);
  } else if (form.assessment?.trim()) {
    parts.push(`Assessment: ${form.assessment.trim()}.`);
  }
  if (form.plan?.trim()) parts.push(`Plan: ${form.plan.trim()}.`);
  if (form.follow_up_in_days) parts.push(`Follow-up in ${form.follow_up_in_days} day(s).`);
  return parts.join(" ");
}

// Plain-text visit summary, built client-side from what's already on
// screen — no server round trip, works the moment the encounter is signed.
function downloadVisitSummary(enc, form, diagnoses, rxItems) {
  const lines = [
    `Consultation Summary — ${enc.patient_name || "Patient"}`,
    `UHID: ${enc.patient_uhid || "—"}    Date: ${enc.encounter_date || "—"}`,
    "",
    `Chief Complaint: ${enc.chief_complaint || "—"}`,
    "",
    "Diagnoses:",
    ...(diagnoses.length ? diagnoses.map(d => `  - ${d.code} — ${d.description}${d.is_primary ? " (Primary)" : ""}`) : ["  (none recorded)"]),
    "",
    "Prescription:",
    ...(rxItems.length ? rxItems.map(i => `  - ${i.drug_name} ${i.dosage} — ${i.frequency} · ${i.route}${i.duration_days ? ` × ${i.duration_days}d` : ""}${i.instructions ? ` (${i.instructions})` : ""}`) : ["  (none recorded)"]),
    "",
    `Advice: ${form.advice_to_patient || "—"}`,
    form.follow_up_in_days ? `Follow-up: ${form.follow_up_in_days} day(s)` : "",
  ].filter(l => l !== "");

  const blob = new Blob([lines.join("\n")], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(enc.patient_uhid || "consultation").replace(/\s+/g, "_")}_summary.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── Patient history sidebar (Overleaf-style collapsible rail) ──────────────
// Cross-visit history — past diagnoses, vitals, allergies, lab results,
// prescriptions — pulled from the shared HIE record. Collapses to a thin
// icon rail so it never eats into the SOAP/vitals/diagnoses workspace; the
// main content's own layout is completely untouched either way.
function HistorySection({ title, icon, count, defaultOpen, urgent, children }) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div style={{ borderBottom: "1px solid var(--color-border)" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 8,
          padding: "10px 14px", background: "none", border: "none", cursor: "pointer",
          fontSize: 12, fontWeight: 700, color: "var(--color-text)", textAlign: "left",
        }}
      >
        <span style={{ fontSize: 10, color: "var(--color-text-muted)", width: 10, display: "inline-block" }}>
          {open ? "▾" : "▸"}
        </span>
        {icon && (
          <span style={{ display: "flex", color: urgent && count > 0 ? "#DC2626" : "var(--color-text-secondary)" }}>
            {icon}
          </span>
        )}
        <span style={{ flex: 1 }}>{title}</span>
        {count !== undefined && (
          <span style={{
            fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 10,
            background: urgent && count > 0 ? "#FEE2E2" : count > 0 ? "var(--color-primary-light)" : "var(--color-border)",
            color: urgent && count > 0 ? "#DC2626" : count > 0 ? "var(--color-primary)" : "var(--color-text-muted)",
          }}>{count}</span>
        )}
      </button>
      {open && <div style={{ padding: "0 14px 12px" }}>{children}</div>}
    </div>
  );
}

function EmptyNote({ children }) {
  return <p style={{ fontSize: 12, color: "var(--color-text-muted)", margin: 0 }}>{children}</p>;
}

function HistorySidebar({ patientPk, patientUhid, history, isLoading, open, onToggle, onOpenDocument }) {
  // Real visit timeline for this patient at this hospital — reuses the same
  // searchable visit-history endpoint the "History" nav page already uses,
  // filtered to this one patient by UHID. No fabricated entries: only
  // appointments that actually exist show up.
  const { data: timelineData, isLoading: timelineLoading } = useApi(
    patientUhid ? API_ENDPOINTS.OPD.HISTORY : null,
    { params: { patient: patientUhid, page_size: 12 }, skip: !patientUhid }
  );
  const timeline = timelineData?.results || [];

  // Collapsed: thin icon rail — doesn't reflow the workspace next to it.
  if (!open) {
    return (
      <div style={{
        width: 40, flexShrink: 0, alignSelf: "stretch",
        borderLeft: "1px solid var(--color-border)", background: "var(--color-surface)",
        display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 14,
      }}>
        <button
          onClick={onToggle}
          title="Show patient history"
          style={{
            background: "none", border: "1px solid var(--color-border)", borderRadius: 8,
            width: 28, height: 28, cursor: "pointer", fontSize: 13, color: "var(--color-text-secondary)",
            display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12,
          }}
        >
          ⟨
        </button>
        <span style={{
          writingMode: "vertical-rl", transform: "rotate(180deg)",
          fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", letterSpacing: 0.5,
        }}>
          HISTORY
        </span>
      </div>
    );
  }

  const diagnoses    = history?.diagnoses     || [];
  const vitals       = history?.vitals        || [];
  const allergies    = history?.allergies     || [];
  const labResults   = history?.lab_results   || [];
  const prescriptions = history?.prescriptions || [];
  const documents    = history?.documents     || [];

  return (
    <div style={{
      width: 320, flexShrink: 0, alignSelf: "flex-start",
      position: "sticky", top: 14,
      borderLeft: "1px solid var(--color-border)", background: "var(--color-surface)",
      borderRadius: "0 var(--radius-card) var(--radius-card) 0",
      maxHeight: "calc(100vh - 28px)", overflowY: "auto",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 14px", borderBottom: "1px solid var(--color-border)",
        position: "sticky", top: 0, background: "var(--color-surface)", zIndex: 1,
      }}>
        <div style={{ fontWeight: 700, fontSize: 13 }}>Patient History</div>
        <button
          onClick={onToggle}
          title="Collapse"
          style={{
            background: "none", border: "1px solid var(--color-border)", borderRadius: 8,
            width: 26, height: 26, cursor: "pointer", fontSize: 13, color: "var(--color-text-secondary)",
          }}
        >
          ⟩
        </button>
      </div>

      {isLoading ? (
        <div style={{ padding: 20, textAlign: "center", fontSize: 12, color: "var(--color-text-muted)" }}>
          Loading history…
        </div>
      ) : !patientPk ? (
        <div style={{ padding: 20, fontSize: 12, color: "var(--color-text-muted)" }}>
          Patient record unavailable.
        </div>
      ) : history && history.consent_given === false ? (
        <div style={{ padding: 20, fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
          <div style={{ fontWeight: 700, marginBottom: 6, color: "var(--color-text)" }}>
            No cross-hospital history on file
          </div>
          This patient hasn't consented to sharing records from other hospitals with this one, so
          only what's recorded here is visible. Anything documented at this hospital going forward
          will still show up normally.
        </div>
      ) : (
        // Ordered by clinical priority, not alphabetically: what could hurt
        // the patient (allergies) comes first, followed by what's currently
        // being managed (active problems, current meds), then supporting
        // evidence (labs, vitals trend), then the longitudinal record.
        <div>
          <HistorySection title="Allergies" icon={<AlertTriangle size={13} />} count={allergies.length} urgent defaultOpen>
            {allergies.length === 0 ? <EmptyNote>No known allergies on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {allergies.map((a, i) => (
                  <div key={i} style={{
                    borderRadius: 8, background: "#FEF2F2", border: "1.5px solid #FCA5A5",
                    padding: "10px 12px",
                  }}>
                    <div style={{
                      display: "flex", alignItems: "center", gap: 5, fontSize: 10, fontWeight: 800,
                      color: "#B91C1C", letterSpacing: 0.4, marginBottom: 6, textTransform: "uppercase",
                    }}>
                      <AlertTriangle size={12} /> Allergy Alert
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#7F1D1D", marginBottom: 4 }}>{a.substance}</div>
                    <div style={{ fontSize: 11, color: "#991B1B" }}>
                      {a.reaction || "Reaction not specified"}
                      {a.severity && (
                        <span style={{
                          marginLeft: 6, padding: "1px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
                          background: "#FEE2E2", color: "#B91C1C", textTransform: "capitalize",
                        }}>{a.severity}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Active Diagnoses" icon={<Stethoscope size={13} />} count={diagnoses.length} defaultOpen>
            {diagnoses.length === 0 ? <EmptyNote>No prior diagnoses on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {diagnoses.map((d, i) => (
                  <div key={i} style={{
                    borderRadius: 8, border: "1px solid var(--color-border)", padding: "8px 10px",
                    background: "var(--color-bg)",
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)" }}>{d.description}</div>
                    <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 3, display: "flex", gap: 6, alignItems: "center" }}>
                      <span style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--color-primary)" }}>{d.icd10_code}</span>
                      <span style={{ textTransform: "capitalize" }}>{d.clinical_status}</span>
                      {d.created_at && <span>· {new Date(d.created_at).toLocaleDateString("en-IN")}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Current Medications" icon={<Pill size={13} />} count={prescriptions.length}>
            {prescriptions.length === 0 ? <EmptyNote>No prior prescriptions on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {prescriptions.map((rx, i) => (
                  <div key={i} style={{ borderRadius: 8, border: "1px solid var(--color-border)", padding: "8px 10px" }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", marginBottom: 4 }}>
                      {rx.prescribed_on ? new Date(rx.prescribed_on).toLocaleDateString("en-IN") : "—"}
                    </div>
                    {(rx.items || []).map((it, j) => (
                      <div key={j} style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: j === (rx.items.length - 1) ? 0 : 3 }}>
                        <strong style={{ color: "var(--color-text)" }}>{it.drug_name}</strong> {it.dose}{it.unit} — {it.frequency} · {it.route}
                        {it.duration_days ? ` × ${it.duration_days}d` : ""}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Latest Labs" icon={<FlaskConical size={13} />} count={labResults.length}>
            {labResults.length === 0 ? <EmptyNote>No prior lab results on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 6 }}>
                {labResults.map((l, i) => {
                  const clickable = !!l.has_file;
                  const Wrapper = clickable ? "button" : "div";
                  return (
                    <Wrapper
                      key={i}
                      onClick={clickable ? () => onOpenDocument?.({
                        id: l.id, title: l.test_name, doc_type: "lab_report",
                        created_at: l.delivered_at,
                        fetchUrl: API_ENDPOINTS.PATIENTS.LAB_RESULT(l.id),
                      }) : undefined}
                      style={{
                        display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left", fontSize: 12,
                        background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: 8,
                        padding: "8px 10px", cursor: clickable ? "pointer" : "default",
                      }}
                    >
                      <span style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700 }}>{l.test_name}</div>
                        <div style={{ color: "var(--color-text-muted)", fontSize: 11 }}>
                          {l.result_summary || "No summary"} · {l.delivered_at ? new Date(l.delivered_at).toLocaleDateString("en-IN") : ""}
                        </div>
                      </span>
                      {clickable && <Paperclip size={13} style={{ color: "var(--color-primary)", flexShrink: 0 }} />}
                    </Wrapper>
                  );
                })}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Vitals Trend" icon={<Activity size={13} />} count={vitals.length}>
            {vitals.length === 0 ? <EmptyNote>No prior vitals on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {vitals.slice(0, 8).map((v, i) => (
                  <div key={i} style={{ fontSize: 11, borderBottom: "1px dashed var(--color-border)", paddingBottom: 6 }}>
                    <div style={{ color: "var(--color-text-muted)", marginBottom: 2 }}>
                      {v.recorded_at ? new Date(v.recorded_at).toLocaleDateString("en-IN") : "—"}
                      {v.source && ` · ${v.source}`}
                    </div>
                    <div>
                      {v.bp_systolic && v.bp_diastolic && `BP ${v.bp_systolic}/${v.bp_diastolic}  `}
                      {v.pulse_rate && `HR ${v.pulse_rate}  `}
                      {v.temperature && `Temp ${v.temperature}°F  `}
                      {v.spo2 && `SpO₂ ${v.spo2}%`}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Previous Visits" icon={<Clock size={13} />} count={timeline.length}>
            {timelineLoading ? <EmptyNote>Loading visit timeline…</EmptyNote> : timeline.length === 0 ? (
              <EmptyNote>No prior visits at this hospital.</EmptyNote>
            ) : (
              <div style={{ display: "grid", gap: 0, position: "relative" }}>
                {timeline.map((v, i) => (
                  <div key={v.id || i} style={{
                    display: "flex", gap: 10, paddingBottom: i === timeline.length - 1 ? 0 : 12,
                  }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                      <div style={{
                        width: 8, height: 8, borderRadius: "50%", marginTop: 4,
                        background: v.status === "done" ? "var(--color-primary)" : "var(--color-border)",
                      }} />
                      {i !== timeline.length - 1 && <div style={{ width: 1.5, flex: 1, background: "var(--color-border)", marginTop: 2 }} />}
                    </div>
                    <div style={{ fontSize: 11, minWidth: 0, flex: 1 }}>
                      <div style={{ fontWeight: 700, color: "var(--color-text)" }}>
                        {new Date(v.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
                        {v.visit_type === "followup" && (
                          <span style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, color: "var(--color-primary)", textTransform: "uppercase" }}>Follow-up</span>
                        )}
                      </div>
                      <div style={{ color: "var(--color-text-muted)" }}>
                        Dr. {v.doctor} {v.chief_complaint && `· ${v.chief_complaint}`}
                      </div>
                      <div style={{ color: "var(--color-text-muted)", textTransform: "capitalize" }}>{v.status?.replace("_", " ")}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Attachments" icon={<Paperclip size={13} />} count={documents.length} defaultOpen>
            {documents.length === 0 ? <EmptyNote>No reports attached by the patient.</EmptyNote> : (
              <div style={{ display: "grid", gap: 6 }}>
                {documents.map(d => (
                  <button
                    key={d.id}
                    onClick={() => onOpenDocument?.({ ...d, fetchUrl: API_ENDPOINTS.PATIENTS.DOCUMENT(d.id) })}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left",
                      padding: "8px 10px", borderRadius: 6, border: "1px solid var(--color-border)",
                      background: "var(--color-bg)", cursor: "pointer", fontSize: 12,
                    }}
                  >
                    <Paperclip size={14} style={{ color: "var(--color-text-secondary)", flexShrink: 0 }} />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.title}</div>
                      <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                        {d.doc_type?.replace("_", " ")}
                        {d.created_at && ` · ${new Date(d.created_at).toLocaleDateString("en-IN")}`}
                        {d.uploaded_by === "patient" && " · uploaded by patient"}
                      </div>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </HistorySection>
        </div>
      )}
    </div>
  );
}

// ─── Document viewer drawer (Overleaf-style resizable pane) ─────────────────
// Fixed to the right edge, drag the left border to resize, scrolls entirely
// within itself — the SOAP/vitals workspace behind it is untouched.
// `doc` can either carry file_data/mime_type directly (e.g. a lab report
// already fetched as part of this tenant's own lab-order list — no extra
// round trip needed) or a `fetchUrl` to load full content from (cross-tenant
// HIE attachments / lab results, kept out of the summary payload for size).
const DRAWER_DEFAULT_WIDTH = 520;
const DRAWER_MIN_WIDTH = 320;

function DocumentViewerDrawer({ doc, onClose }) {
  const [width, setWidth] = useState(DRAWER_DEFAULT_WIDTH);
  const [dragging, setDragging] = useState(false);
  const [handleHover, setHandleHover] = useState(false);
  const draggingRef = useRef(false);

  const hasInlineData = !!doc?.file_data;
  const { data: fetched, isLoading: fetchLoading } = useApi(
    doc && !hasInlineData && doc.fetchUrl ? doc.fetchUrl : null,
    { skip: !doc || hasInlineData || !doc?.fetchUrl }
  );
  const full = hasInlineData ? doc : fetched;
  const isLoading = hasInlineData ? false : fetchLoading;

  useEffect(() => {
    function onMove(e) {
      if (!draggingRef.current) return;
      const next = window.innerWidth - e.clientX;
      setWidth(Math.min(Math.max(next, DRAWER_MIN_WIDTH), window.innerWidth - 200));
    }
    function onUp() {
      draggingRef.current = false;
      setDragging(false);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  if (!doc) return null;

  const mime = full?.mime_type || "";
  const isPdf   = mime.includes("pdf");
  const isImage = mime.startsWith("image/");
  const handleActive = dragging || handleHover;

  return (
    <div style={{
      position: "fixed", top: 0, right: 0, bottom: 0, width,
      background: "var(--color-surface)", zIndex: 500,
      boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
      display: "flex", flexDirection: "column",
      userSelect: dragging ? "none" : undefined,
    }}>
      {/* Full-viewport overlay while dragging — keeps the mousemove/mouseup
          listeners reliable even when the cursor passes over the PDF <iframe>,
          which otherwise "eats" mouse events since it's a separate document. */}
      {dragging && (
        <div style={{ position: "fixed", inset: 0, zIndex: 600, cursor: "col-resize" }} />
      )}

      {/* Drag handle — an always-visible, Overleaf-style resize bar rather than
          an invisible hit zone, so it reads as adjustable at a glance. */}
      <div
        onMouseDown={() => { draggingRef.current = true; setDragging(true); }}
        onMouseEnter={() => setHandleHover(true)}
        onMouseLeave={() => setHandleHover(false)}
        onDoubleClick={() => setWidth(DRAWER_DEFAULT_WIDTH)}
        title="Drag to resize · double-click to reset"
        style={{
          position: "absolute", left: -7, top: 0, bottom: 0, width: 14,
          cursor: "col-resize", zIndex: 2,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        <div style={{
          width: handleActive ? 4 : 3, height: 56, borderRadius: 4,
          background: handleActive ? "var(--color-primary)" : "var(--color-border)",
          boxShadow: handleActive ? "0 0 0 3px rgba(27,94,67,0.12)" : "none",
          transition: "background 0.15s, width 0.1s, box-shadow 0.15s",
        }} />
      </div>

      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 16px", borderBottom: "1px solid var(--color-border)", flexShrink: 0,
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {doc.title}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
            {doc.doc_type?.replace("_", " ")}
            {doc.created_at && ` · ${new Date(doc.created_at).toLocaleDateString("en-IN")}`}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none", border: "1px solid var(--color-border)", borderRadius: 8,
            width: 28, height: 28, cursor: "pointer", fontSize: 14, flexShrink: 0,
          }}
        >
          ✕
        </button>
      </div>

      {/* Scrollable viewer body — its own scroll container, independent of the page */}
      <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", background: "#525659" }}>
        {isLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: "#fff", fontSize: 13 }}>Loading document…</div>
        ) : !full ? (
          <div style={{ padding: 40, textAlign: "center", color: "#fff", fontSize: 13 }}>Could not load this document.</div>
        ) : isPdf ? (
          <iframe
            title={doc.title}
            src={full.file_data}
            style={{ width: "100%", height: "100%", minHeight: "100%", border: "none", display: "block" }}
          />
        ) : isImage ? (
          <div style={{ padding: 16, display: "flex", justifyContent: "center" }}>
            <img src={full.file_data} alt={doc.title} style={{ maxWidth: "100%", height: "auto", borderRadius: 4 }} />
          </div>
        ) : (
          <div style={{ padding: 40, textAlign: "center", color: "#fff", fontSize: 13 }}>
            This file type can't be previewed.{" "}
            <a href={full.file_data} download={full.file_name || doc.title} style={{ color: "#93c5fd" }}>
              Download instead
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-secondary)", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </label>
      {children}
    </div>
  );
}

function Textarea({ value, onChange, disabled, placeholder, rows = 3 }) {
  return (
    <textarea
      value={value || ""}
      onChange={e => onChange(e.target.value)}
      disabled={disabled}
      placeholder={placeholder}
      rows={rows}
      className="form-input"
      style={{ resize: "vertical", fontFamily: "inherit", width: "100%", boxSizing: "border-box", fontSize: 14, lineHeight: 1.55, color: "var(--color-text)" }}
    />
  );
}

// ─── Vitals display ───────────────────────────────────────────────────────────
// Standard adult clinical reference ranges (textbook values, not
// patient-specific data) — used only to badge a recorded vital as
// Normal/Watch/High so a doctor doesn't have to do the mental math on
// every patient. Never invents a reading; only classifies one already
// recorded by nursing staff.
function classifyVital(key, val) {
  if (val == null || val === "") return null;
  const n = Number(val);
  if (Number.isNaN(n)) return null;
  switch (key) {
    // Pulse: 60-99 Green, 100-120 Amber, >120 Red (below 60 flagged Amber too — bradycardia).
    case "pulse":   return n > 120 ? "high" : n >= 100 ? "watch" : n < 60 ? "watch" : "normal";
    // SpO2: >=95 Green, 90-94 Amber, <90 Red.
    case "spo2":    return n < 90 ? "high" : n < 95 ? "watch" : "normal";
    // Temp: 97-99 Green, 99-101 Amber, >101 Red (below 97 flagged Amber too — hypothermia caution).
    case "temp":    return n > 101 ? "high" : n >= 99 ? "watch" : n < 97 ? "watch" : "normal";
    case "rr":      return n < 12 || n > 20 ? "watch" : "normal";
    default:        return null;
  }
}
function classifyBP(sys, dia) {
  if (sys == null || dia == null) return null;
  if (sys >= 140 || dia >= 90) return "high";
  if (sys >= 120 || dia >= 80) return "watch";
  return "normal";
}
const VITAL_BADGE = {
  normal: { label: "Normal", bg: "#DCFCE7", color: "#166534" },
  watch:  { label: "Watch",  bg: "#FEF3C7", color: "#92400E" },
  high:   { label: "High",   bg: "#FEE2E2", color: "#991B1B" },
};

function VitalsDisplay({ vitals }) {
  if (!vitals) {
    return (
      <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>
        No vitals recorded by nursing staff.
      </p>
    );
  }
  const items = [
    { label: "BP",       value: vitals.systolic_bp && vitals.diastolic_bp ? `${vitals.systolic_bp}/${vitals.diastolic_bp} mmHg` : null,
      status: classifyBP(vitals.systolic_bp, vitals.diastolic_bp) },
    { label: "Pulse",    value: vitals.pulse_rate   ? `${vitals.pulse_rate} bpm`   : null, status: classifyVital("pulse", vitals.pulse_rate) },
    { label: "SpO₂",     value: vitals.spo2         ? `${vitals.spo2}%`             : null, status: classifyVital("spo2", vitals.spo2) },
    { label: "Temp",     value: vitals.temperature  ? `${vitals.temperature}°F`    : null, status: classifyVital("temp", vitals.temperature) },
    { label: "Weight",   value: vitals.weight_kg    ? `${vitals.weight_kg} kg`     : null, status: null },
    { label: "RR",       value: vitals.respiratory_rate ? `${vitals.respiratory_rate}/min` : null, status: classifyVital("rr", vitals.respiratory_rate) },
  ].filter(i => i.value);

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: vitals.nurse_notes ? 12 : 0 }}>
        {items.length === 0
          ? <p style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>All vitals not recorded.</p>
          : items.map(({ label, value, status }) => {
            const badge = status && VITAL_BADGE[status];
            return (
              <div key={label} style={{
                background: badge ? badge.bg : "#EFF6FF", borderRadius: 8, padding: "8px 14px",
                textAlign: "center", minWidth: 86,
              }}>
                <div style={{ fontSize: 15, fontWeight: 800, color: badge ? badge.color : "var(--color-primary)" }}>{value}</div>
                <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 2 }}>{label}</div>
                {badge && (
                  <div style={{ fontSize: 9, fontWeight: 700, color: badge.color, marginTop: 3, letterSpacing: 0.3 }}>
                    {status === "normal" ? "✓ " : "⚠ "}{badge.label}
                  </div>
                )}
              </div>
            );
          })
        }
      </div>
      {vitals.nurse_notes && (
        <div style={{
          background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 8,
          padding: "8px 12px", fontSize: 12, color: "#92400E",
        }}>
          <strong>Nurse note:</strong> {vitals.nurse_notes}
        </div>
      )}
    </div>
  );
}

// ─── Lab orders — structured picker against the catalog ─────────────────────
// Lives inside the "Investigations / Orders" card itself (the free-text box
// there is now only for imaging/misc orders that aren't in the lab catalog).
// Ordering here creates real LabRequest rows the patient sees on their
// portal to choose in-house vs outside, and that the nurse/lab-tech
// workflows key off.
const CHOICE_BADGE = {
  pending:  { label: "Awaiting patient choice", bg: "var(--color-border)", color: "var(--color-text-muted)" },
  in_house: { label: "In-house",  bg: "#DBEAFE", color: "#1E40AF" },
  outside:  { label: "Outside",   bg: "#FEF3C7", color: "#92400E" },
};
const LAB_STATUS_BADGE = {
  ordered:    { label: "Ordered",    bg: "var(--color-border)", color: "var(--color-text-muted)" },
  collected:  { label: "Collected",  bg: "#DBEAFE", color: "#1E40AF" },
  processing: { label: "Processing", bg: "#FEF3C7", color: "#92400E" },
  completed:  { label: "Completed",  bg: "#D1FAE5", color: "#065F46" },
  cancelled:  { label: "Cancelled",  bg: "#FEE2E2", color: "#991B1B" },
};

function LabOrderSection({ encounterId, isClosed, onViewReport }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data: catalogData } = useApi(API_ENDPOINTS.LAB.CATALOG);
  const catalog = catalogData || [];

  const { data: ordersData, refetch: refetchOrders } = useApi(
    API_ENDPOINTS.LAB.REQUESTS, { params: { encounter_id: encounterId } }
  );
  const orders = ordersData?.results || [];
  const orderedTestIds = new Set(orders.map(o => o.test));

  const [selected, setSelected] = useState([]); // [{id, name}]
  const [ordering, setOrdering] = useState(false);
  const [q, setQ] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setDropdownOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const results = catalog
    .filter(t => !selected.some(s => s.id === t.id) && !orderedTestIds.has(t.id))
    .filter(t => q.length === 0 || t.name.toLowerCase().includes(q.toLowerCase()) || (t.code || "").toLowerCase().includes(q.toLowerCase()));

  function addTest(t) {
    setSelected(prev => [...prev, { id: t.id, name: t.name }]);
    setQ("");
  }

  function removeSelected(id) {
    setSelected(prev => prev.filter(s => s.id !== id));
  }

  async function orderSelected() {
    if (selected.length === 0) return;
    setOrdering(true);
    try {
      await apiClient.post(API_ENDPOINTS.LAB.REQUESTS, { encounter_id: encounterId, tests: selected.map(s => s.id) });
      toastSuccess(`${selected.length} test(s) ordered.`);
      setSelected([]);
      refetchOrders();
    } catch (err) {
      toastApiError(err, "Could not order tests.");
    } finally {
      setOrdering(false);
    }
  }

  return (
    <div style={{ marginBottom: 14 }}>
      {!isClosed && (
        <div style={{ marginBottom: 12 }}>
          <div ref={ref} style={{ position: "relative" }}>
            <input
              className="form-input"
              value={q}
              onChange={e => { setQ(e.target.value); setDropdownOpen(true); }}
              onFocus={() => setDropdownOpen(true)}
              placeholder="Search the lab catalog — add multiple tests…"
              style={{ width: "100%", boxSizing: "border-box" }}
            />
            {dropdownOpen && (
              <div style={{
                position: "absolute", zIndex: 100, top: "calc(100% + 4px)", left: 0, right: 0,
                background: "#fff", border: "1px solid var(--color-border)", borderRadius: 8,
                boxShadow: "0 4px 24px rgba(0,0,0,0.12)", maxHeight: 220, overflowY: "auto",
              }}>
                {catalog.length === 0 ? (
                  <div style={{ padding: "10px 14px", fontSize: 12, color: "var(--color-text-muted)" }}>
                    No tests in the catalog yet — ask lab staff to add tests under "Test Catalog".
                  </div>
                ) : results.length === 0 ? (
                  <div style={{ padding: "10px 14px", fontSize: 12, color: "var(--color-text-muted)" }}>
                    No matching tests.
                  </div>
                ) : results.map(t => (
                  <div key={t.id}
                    onMouseDown={() => addTest(t)}
                    style={{ padding: "9px 14px", cursor: "pointer", borderBottom: "1px solid var(--color-border)", display: "flex", justifyContent: "space-between", gap: 8 }}
                    className="hover-row"
                  >
                    <span style={{ fontSize: 13 }}>{t.name}{t.code && <span style={{ color: "var(--color-text-muted)" }}> ({t.code})</span>}</span>
                    <span style={{ fontSize: 11, color: "var(--color-text-muted)", whiteSpace: "nowrap" }}>
                      {t.price != null && `₹${t.price} · `}~{t.turnaround_hours}h
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {selected.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
              {selected.map(s => (
                <span key={s.id} style={{
                  display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12,
                  padding: "4px 6px 4px 10px", borderRadius: 20, background: "var(--color-primary-light)", color: "var(--color-primary)",
                }}>
                  {s.name}
                  <button type="button" onClick={() => removeSelected(s.id)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-primary)", fontSize: 13, lineHeight: 1, padding: 0 }}>
                    ✕
                  </button>
                </span>
              ))}
              <button type="button" className="btn-primary" style={{ fontSize: 12, padding: "4px 14px" }}
                disabled={ordering} onClick={orderSelected}>
                {ordering ? "Ordering…" : `Order ${selected.length} test(s)`}
              </button>
            </div>
          )}
        </div>
      )}

      {orders.length > 0 && (
        <div style={{ display: "grid", gap: 8, marginBottom: 4 }}>
          {orders.map(o => {
            const choiceBadge = CHOICE_BADGE[o.patient_choice] || CHOICE_BADGE.pending;
            const statusBadge = LAB_STATUS_BADGE[o.status] || LAB_STATUS_BADGE.ordered;
            const hasReportFile = !!o.report?.file_data;
            return (
              <div key={o.id} style={{
                display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
                padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12,
              }}>
                <span style={{ fontWeight: 700, flex: 1, minWidth: 100 }}>{o.test_name}</span>
                <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: statusBadge.bg, color: statusBadge.color }}>
                  {statusBadge.label}
                </span>
                <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: choiceBadge.bg, color: choiceBadge.color }}>
                  {choiceBadge.label}
                </span>
                {o.patient_choice === "in_house" && o.payment_status && (
                  <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                    {o.payment_status.replace("_", " ")}
                  </span>
                )}
                {o.report?.result_summary && (
                  <span style={{ color: "var(--color-text-secondary)", fontSize: 11, width: "100%" }}>
                    {o.report.result_summary}
                  </span>
                )}
                {hasReportFile && (
                  <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "3px 10px" }}
                    onClick={() => onViewReport?.({
                      title: o.test_name, doc_type: "lab_report", created_at: o.report.delivered_at,
                      file_data: o.report.file_data, mime_type: o.report.mime_type || "",
                    })}>
                    View Report
                  </button>
                )}
                {o.patient_choice === "outside" && o.attached_document && (
                  <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "3px 10px" }}
                    onClick={() => onViewReport?.({
                      title: o.test_name, doc_type: "lab_report", created_at: o.attached_document.created_at,
                      fetchUrl: API_ENDPOINTS.PATIENTS.DOCUMENT(o.attached_document.id),
                    })}>
                    View Uploaded Report
                  </button>
                )}
                {o.patient_choice === "outside" && !o.attached_document && (
                  <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Awaiting patient's upload</span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── ICD-10 search + add ─────────────────────────────────────────────────────
function DiagnosisSearch({ onAdd, disabled }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const results = q.length >= 2
    ? ICD10_CODES.filter(c =>
        c.code.toLowerCase().includes(q.toLowerCase()) ||
        c.desc.toLowerCase().includes(q.toLowerCase())
      ).slice(0, 10)
    : [];

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function select(code) {
    onAdd({ code: code.code, description: code.desc, clinical_status: "active", is_primary: false });
    setQ("");
    setOpen(false);
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <input
        className="form-input"
        disabled={disabled}
        value={q}
        onChange={e => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        placeholder="Search ICD-10 code or description…"
        style={{ width: "100%", boxSizing: "border-box" }}
      />
      {open && results.length > 0 && (
        <div style={{
          position: "absolute", zIndex: 100, top: "calc(100% + 4px)", left: 0, right: 0,
          background: "#fff", border: "1px solid var(--color-border)", borderRadius: 8,
          boxShadow: "0 4px 24px rgba(0,0,0,0.12)", maxHeight: 260, overflowY: "auto",
        }}>
          {results.map(c => (
            <div key={c.code}
              onMouseDown={() => select(c)}
              style={{ padding: "10px 14px", cursor: "pointer", borderBottom: "1px solid var(--color-border)" }}
              className="hover-row"
            >
              <span style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--color-primary)", marginRight: 10 }}>{c.code}</span>
              <span style={{ fontSize: 13 }}>{c.desc}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Drug entry form ──────────────────────────────────────────────────────────
const EMPTY_DRUG = { drug_name: "", dosage: "", frequency: "od", route: "oral", duration_days: "", instructions: "" };

function DrugForm({ onSave, disabled }) {
  const [d, setD] = useState(EMPTY_DRUG);
  function upd(k, v) { setD(p => ({ ...p, [k]: v })); }

  function submit(e) {
    e.preventDefault();
    if (!d.drug_name.trim() || !d.dosage.trim()) return;
    onSave({ ...d, duration_days: d.duration_days ? parseInt(d.duration_days) : null });
    setD(EMPTY_DRUG);
  }

  return (
    <form onSubmit={submit} style={{ background: "#FBF9F5", borderRadius: 10, padding: 14, border: "1px dashed var(--color-primary)", marginBottom: 16 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>DRUG NAME *</label>
          <input className="form-input" value={d.drug_name} onChange={e => upd("drug_name", e.target.value)} placeholder="e.g. Amoxicillin" required disabled={disabled} />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>DOSE *</label>
          <input className="form-input" value={d.dosage} onChange={e => upd("dosage", e.target.value)} placeholder="e.g. 500mg" required disabled={disabled} />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>FREQUENCY</label>
          <select className="form-input" value={d.frequency} onChange={e => upd("frequency", e.target.value)} disabled={disabled}>
            {Object.entries(FREQ_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>ROUTE</label>
          <select className="form-input" value={d.route} onChange={e => upd("route", e.target.value)} disabled={disabled}>
            {Object.entries(ROUTE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "120px 1fr auto", gap: 10, alignItems: "end" }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>DURATION (days)</label>
          <input className="form-input" type="number" min="1" value={d.duration_days} onChange={e => upd("duration_days", e.target.value)} placeholder="5" disabled={disabled} />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 4 }}>INSTRUCTIONS</label>
          <input className="form-input" value={d.instructions} onChange={e => upd("instructions", e.target.value)} placeholder="e.g. Take after food" disabled={disabled} />
        </div>
        <button type="submit" disabled={disabled || !d.drug_name.trim() || !d.dosage.trim()} className="btn-primary" style={{ height: 38, whiteSpace: "nowrap" }}>
          + Add Drug
        </button>
      </div>
    </form>
  );
}

// ─── Compact clinical summary header ─────────────────────────────────────────
// A doctor with a full queue shouldn't have to scroll to understand who
// they're seeing. Everything here is real: age/gender/UHID/last-visit come
// from the encounter serializer, allergies and active problems come from
// the same cross-hospital history the sidebar shows, vitals are today's
// own recorded reading.
function ClinicalSummaryHeader({ enc, history, allergies, activeProblems, vitals, isClosed }) {
  const genderLabel = { M: "Male", F: "Female", O: "Other" }[enc.patient_gender] || null;
  return (
    <div className="card" style={{ padding: "16px 20px", background: "var(--color-primary-light)", border: "1.5px solid var(--color-primary)" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: 14 }}>
        <div style={{ minWidth: 200 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 600 }}>{enc.patient_name || "Patient"}</div>
            <DependentBadge patient={enc} />
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
            {(genderLabel || enc.patient_age != null) && (
              <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                {genderLabel && <><User size={12} /> {genderLabel}</>}
                {genderLabel && enc.patient_age != null && " · "}
                {enc.patient_age != null && <><Cake size={12} /> {enc.patient_age} yrs</>}
              </span>
            )}
            <span>· UHID: {enc.patient_uhid || "—"}</span>
            <span>· {enc.encounter_date}</span>
            {enc.patient_last_visit && (
              <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                <CalendarClock size={12} /> Last visit {new Date(enc.patient_last_visit).toLocaleDateString("en-IN")}
              </span>
            )}
            <span style={{ textTransform: "capitalize", fontWeight: 600, color: isClosed ? "#065F46" : "var(--color-primary)" }}>
              {enc.status}
            </span>
          </div>
        </div>

        {enc.chief_complaint && (
          <div style={{
            background: "#fff", borderRadius: 8, padding: "6px 14px",
            fontSize: 13, fontStyle: "italic", color: "var(--color-text-secondary)",
            border: "1px solid var(--color-border)", maxWidth: 360,
          }}>
            "{enc.chief_complaint}"
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
        {allergies.length > 0 && (
          <span style={{
            display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
            background: "#FEE2E2", color: "#B91C1C", padding: "4px 10px", borderRadius: 20,
          }}>
            <AlertTriangle size={12} /> {allergies.map(a => a.substance).join(", ")}
          </span>
        )}
        {activeProblems.map((p, i) => (
          <span key={i} style={{
            display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
            background: "#fff", border: "1px solid var(--color-primary)", color: "var(--color-primary)",
            padding: "4px 10px", borderRadius: 20,
          }}>
            <Stethoscope size={12} /> {p}
          </span>
        ))}
        {vitals && (vitals.systolic_bp || vitals.pulse_rate || vitals.spo2) && (
          <span style={{
            display: "flex", alignItems: "center", gap: 8, fontSize: 11, fontWeight: 600,
            background: "#fff", border: "1px solid var(--color-border)", color: "var(--color-text-secondary)",
            padding: "4px 10px", borderRadius: 20,
          }}>
            <Activity size={12} />
            {vitals.systolic_bp && vitals.diastolic_bp && `BP ${vitals.systolic_bp}/${vitals.diastolic_bp}`}
            {vitals.pulse_rate && `  HR ${vitals.pulse_rate}`}
            {vitals.spo2 && `  SpO₂ ${vitals.spo2}%`}
          </span>
        )}
        {allergies.length === 0 && activeProblems.length === 0 && !vitals && (
          <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>No known allergies or active problems on record.</span>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
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
      await apiClient.patch(API_ENDPOINTS.OPD.ENCOUNTER(id), payload);
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
    const res = await apiClient.post(API_ENDPOINTS.OPD.PRESCRIPTIONS, { encounter_id: id });
    const newId = res.data?.id || res.data?.data?.id;
    setRxId(newId);
    return newId;
  }

  async function addDrug(drugData) {
    setAddingRx(true);
    try {
      const pid = await ensureRx();
      const res = await apiClient.post(API_ENDPOINTS.OPD.PRESCRIPTION_ITEMS(pid), drugData);
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
      await apiClient.delete(API_ENDPOINTS.OPD.PRESCRIPTION_ITEM(rxId, itemId));
      setRxItems(prev => prev.filter(i => i.id !== itemId));
    } catch (err) {
      toastApiError(err, "Failed to remove drug.");
    } finally {
      setRemovingItem(null);
    }
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
      await apiClient.patch(API_ENDPOINTS.OPD.ENCOUNTER(id), payload);
      await apiClient.post(API_ENDPOINTS.OPD.ENCOUNTER_SIGN(id), {});
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
            {isClosed ? (
              <>
                <button className="btn-outline" onClick={() => window.print()} title="Print this consultation" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                  <Printer size={14} /> Print
                </button>
                <button className="btn-outline" onClick={() => downloadVisitSummary(enc, form, diagnoses, rxItems)} title="Download a text summary of this visit" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
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
                <button className="btn-primary" disabled={signing} onClick={signAndClose} style={{ background: "#10B981", minWidth: 130 }}>
                  {signing ? "Signing…" : "Sign & Close"}
                </button>
              </>
            )}
          </div>
        }
      >
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
            extra={<DictateButton disabled={isClosed} onTranscript={t => openDictation("soap", t)} />}>
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
                <DiagnosisSearch onAdd={addDiagnosis} disabled={isClosed} />
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                  Type ICD-10 code or description to search. First diagnosis is automatically marked Primary.
                </div>
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
            {!isClosed && <DrugForm onSave={addDrug} disabled={addingRx} />}
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
                onChange={e => upd("follow_up_in_days", e.target.value)}
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
              <button className="btn-primary" disabled={signing} onClick={signAndClose} style={{ background: "#10B981", minWidth: 160 }}>
                {signing ? "Signing…" : "Sign & Close Encounter"}
              </button>
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <div style={{ color: "#10B981", fontWeight: 700, marginBottom: 10 }}>
                ✓ Encounter signed and submitted to Health Exchange.
              </div>
              <button className="btn-outline" onClick={() => navigate("/doctor/queue")}>← Back to Queue</button>
            </div>
          )}

        </div>

        {/* ── Dictation review modal (human-in-the-loop) ─────────────────── */}
        {dictation && (
          <div style={{
            position: "fixed", inset: 0, background: "rgba(12, 42, 31, 0.5)",
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
      <DocumentViewerDrawer doc={viewerDoc} onClose={() => setViewerDoc(null)} />
    </AppShell>
  );
}
