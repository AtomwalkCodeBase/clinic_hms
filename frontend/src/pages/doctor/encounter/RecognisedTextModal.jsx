import { openDataUrlInNewTab } from "../../../utils/fileViewer";

/**
 * Read-only view of the handwriting session's recognised content — the
 * Prescription tab's extracted drugs and the Internal Note tab's SOAP split
 * + verbatim transcription. The form on the left is already populated; this
 * is the "what was actually read" reference.
 */
export function RecognisedTextModal({ data, onClose }) {
  const note = data?.note || {};
  const rx = data?.rx || {};
  const rxPages = Array.isArray(data?.rxPages) ? data.rxPages : [];
  const notePages = Array.isArray(data?.notePages) ? data.notePages : [];
  const rxItems = Array.isArray(rx.items) ? rx.items : Array.isArray(rx.prescription) ? rx.prescription : [];
  const Section = ({ label, text }) => (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--color-text-muted)", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 12, whiteSpace: "pre-wrap", color: "var(--color-text)" }}>{text?.trim?.() || text || <span style={{ color: "var(--color-text-muted)" }}>—</span>}</div>
    </div>
  );
  const Pages = ({ label, pages }) => (
    pages.length ? (
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 10, fontWeight: 800, textTransform: "uppercase", letterSpacing: 0.4, color: "var(--color-text-muted)", marginBottom: 3 }}>{label}</div>
        <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 4 }}>
          {pages.map((src, i) => (
            <img key={i} src={src} alt={`${label} page ${i + 1}`}
              onClick={() => openDataUrlInNewTab(src)}
              style={{ height: 150, width: "auto", flexShrink: 0, cursor: "zoom-in", border: "1px solid var(--color-border)", borderRadius: 6, background: "#fff" }} />
          ))}
        </div>
      </div>
    ) : null
  );
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: "var(--color-surface, #fff)", borderRadius: 12, padding: 20, maxWidth: 560, width: "100%", maxHeight: "85vh", overflow: "auto", boxShadow: "0 12px 40px rgba(0,0,0,0.25)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <strong style={{ fontSize: 14 }}>Handwriting — what was read</strong>
          <button onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>×</button>
        </div>
        <p style={{ fontSize: 11, color: "var(--color-text-muted)", margin: "0 0 12px" }}>
          Auto-transcribed from the phone. Note text on the left was filled from this; prescription lines and diagnoses are staged under their cards for you to review, edit and add.
        </p>

        <div style={{ fontSize: 11, fontWeight: 800, color: "var(--color-primary)", margin: "0 0 6px" }}>PRESCRIPTION TAB</div>
        <Pages label="Prescription — handwriting" pages={rxPages} />
        {rxItems.length ? (
          <Section label="Medications extracted" text={rxItems.map(m => {
            const corrected = (m.name_source === "catalog" || m.name_source === "catalog_fuzzy") &&
              (m.drug_name_raw || "").trim() &&
              (m.drug_name_raw || "").trim().toLowerCase() !== (m.drug_name || "").trim().toLowerCase();
            const tag = m.name_source === "catalog_fuzzy" ? " (best-guess)" : corrected ? " (catalog)" : "";
            const name = corrected ? `${m.drug_name_raw} → ${m.drug_name}${tag}` : m.drug_name;
            return [name, m.dosage, m.frequency, m.route && m.route !== "oral" ? m.route : "", m.duration_days ? `x ${m.duration_days}d` : "", m.instructions]
              .filter(Boolean).join(" · ");
          }).join("\n")} />
        ) : <Section label="Medications extracted" text="" />}
        {rx.raw_text?.trim() && <Section label="Prescription — verbatim" text={rx.raw_text} />}

        <div style={{ borderTop: "1px solid var(--color-border)", margin: "12px 0" }} />
        <div style={{ fontSize: 11, fontWeight: 800, color: "var(--color-primary)", margin: "0 0 6px" }}>INTERNAL NOTE TAB</div>
        <Pages label="Internal note — handwriting" pages={notePages} />
        <Section label="S — Subjective" text={note.subjective} />
        <Section label="O — Objective" text={note.objective} />
        <Section label="A — Assessment" text={note.assessment} />
        <Section label="P — Plan" text={note.plan} />
        {(note.diagnoses?.length > 0) && (
          <Section label="Diagnoses extracted" text={note.diagnoses.map(d => d.code ? `${d.description} (${d.code})` : d.description).join("\n")} />
        )}
        {note.investigations?.trim() && (
          <Section label="Investigations" text={
            Array.isArray(note.investigations_resolved) && note.investigations_resolved.length
              ? note.investigations_resolved.map(r => {
                  const raw = (r.raw || "").trim();
                  const name = (r.name || "").trim();
                  const corrected = raw && name && raw.toLowerCase() !== name.toLowerCase();
                  const tag = r.source === "catalog_fuzzy" ? " (best-guess)" : corrected ? " (standardised)" : "";
                  const line = corrected ? `${raw} → ${name}${tag}` : (name || raw);
                  return Array.isArray(r.flags) && r.flags.length ? `${line}  —  ${r.flags.join(" · ")}` : line;
                }).join("\n")
              : note.investigations
          } />
        )}
        {note.advice?.trim() && <Section label="Advice" text={note.advice} />}
        {note.follow_up_days != null && note.follow_up_days !== "" && (
          <Section label="Follow-up" text={`in ${note.follow_up_days} day(s)`} />
        )}
        {note.raw_text?.trim() && <Section label="Note — verbatim" text={note.raw_text} />}
      </div>
    </div>
  );
}
