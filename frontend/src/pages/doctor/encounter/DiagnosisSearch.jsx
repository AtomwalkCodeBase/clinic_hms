import { useState, useRef, useEffect } from "react";
import { ICD10_CODES } from "./constants";
import { matchICD } from "./diagnosis";

// ─── ICD-10 search + add ─────────────────────────────────────────────────────
// `chiefComplaint` (the appointment's booked complaint) drives a "Suggested
// for this visit" chip row via matchICD — the same complaint→code matching
// used for voice dictation, just run against the typed booking reason
// instead of a transcript. `existingCodes` filters out anything already
// added so suggestions/results don't offer a duplicate.
export function DiagnosisSearch({ onAdd, disabled, chiefComplaint, existingCodes = [] }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const results = q.length >= 2
    ? ICD10_CODES.filter(c =>
        c.code.toLowerCase().includes(q.toLowerCase()) ||
        c.desc.toLowerCase().includes(q.toLowerCase()) ||
        (c.keywords || []).some(k => k.includes(q.toLowerCase()))
      ).filter(c => !existingCodes.includes(c.code)).slice(0, 10)
    : [];

  const suggested = chiefComplaint
    ? matchICD(chiefComplaint, 6).filter(c => !existingCodes.includes(c.code))
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
      {suggested.length > 0 && !open && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", marginBottom: 4 }}>
            Suggested for this visit{chiefComplaint ? ` — "${chiefComplaint}"` : ""}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {suggested.map(c => (
              <button key={c.code} type="button" disabled={disabled} onClick={() => select(c)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  padding: "4px 10px", borderRadius: 20, fontSize: 12,
                  background: "var(--color-primary-light)", color: "var(--color-primary)",
                  border: "1px solid var(--color-primary)", cursor: disabled ? "not-allowed" : "pointer",
                }}>
                <span style={{ fontFamily: "monospace", fontWeight: 700 }}>{c.code}</span>
                {c.desc}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
