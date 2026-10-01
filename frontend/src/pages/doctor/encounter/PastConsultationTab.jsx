import { useApi } from "../../../hooks/useApi";
import API_ENDPOINTS from "../../../config/api.config";

// ─── Past Consultation tab ─── read-only view of the prior signed encounter,
// shown only when today's own appointment is itself a follow-up visit.
export function PastConsultationTab({ encounterId }) {
  const { data: prev, isLoading } = useApi(API_ENDPOINTS.OPD.ENCOUNTER_PREVIOUS(encounterId));
  const previous = prev?.data;

  if (isLoading) {
    return <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>;
  }
  const sharedRef = prev?.shared_reference;

  if (!previous && sharedRef) {
    // No local encounter here at all — but "follow-up" doesn't mean "has a
    // prior visit at THIS hospital"; the patient can be following up on
    // care from elsewhere. We DO have their shared cross-hospital record
    // (same data the Patient History sidebar draws from), so show the most
    // recent documented visit from that instead of a dead end — clearly
    // labeled as a shared-record summary, not a full local SOAP note.
    const rxItems = (sharedRef.prescriptions || []).flatMap(rx => rx.items || []);
    return (
      <div style={{ display: "grid", gap: 16 }}>
        <div className="callout">
          <div>
            <div className="callout-title">
              No visit on record at this hospital — showing shared history from {new Date(sharedRef.visit_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
            </div>
            <div className="callout-body">
              This patient hasn't had a consultation here before — "Follow-up" refers to care they had
              elsewhere. This is a summary from shared cross-hospital records, not a full local
              consultation note.
            </div>
          </div>
        </div>
        <div className="card" style={{ display: "grid", gap: 14 }}>
          {(sharedRef.diagnoses || []).length > 0 && (
            <div>
              <div className="stat-label" style={{ marginBottom: 6 }}>Diagnoses</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {sharedRef.diagnoses.map((d, i) => (
                  <span key={i} className="badge badge--neutral">{d.icd10_code} — {d.description}</span>
                ))}
              </div>
            </div>
          )}
          {(sharedRef.lab_results || []).length > 0 && (
            <div>
              <div className="stat-label" style={{ marginBottom: 6 }}>Lab Results</div>
              <div style={{ display: "grid", gap: 6 }}>
                {sharedRef.lab_results.map((l, i) => (
                  <div key={i} style={{ fontSize: 13 }}>
                    <strong>{l.test_name}</strong>
                    {l.result_summary ? ` — ${l.result_summary}` : ""}
                  </div>
                ))}
              </div>
            </div>
          )}
          {rxItems.length > 0 && (
            <div>
              <div className="stat-label" style={{ marginBottom: 6 }}>Prescribed</div>
              <div style={{ display: "grid", gap: 4 }}>
                {rxItems.map((it, i) => (
                  <div key={i} style={{ fontSize: 13 }}>
                    <strong>{it.drug_name}</strong> {it.dose}{it.unit} — {it.frequency} · {it.route}
                    {it.duration_days ? ` × ${it.duration_days}d` : ""}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (!previous) {
    // Only SIGNED encounters are citable here — a draft could still change.
    // unsigned_pending tells us whether that's actually why nothing showed
    // up (an earlier visit exists but isn't signed & closed yet) versus
    // this genuinely being the first visit for this patient anywhere on
    // file — two very different situations that read identically without
    // this distinction.
    return (
      <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>
        {prev?.unsigned_pending ? (
          <>
            <div style={{ fontWeight: 700, color: "var(--color-text)", marginBottom: 4 }}>
              An earlier visit exists but hasn't been signed &amp; closed yet
            </div>
            <div style={{ fontSize: 12.5 }}>
              Only signed consultations can be shown here for reference. Ask the doctor who saw this
              patient last to complete and sign that visit — it'll then appear here.
            </div>
          </>
        ) : (
          "No prior consultation on record for this patient — this appears to be their first documented visit anywhere on this platform."
        )}
        {prev?.debug && (
          <div style={{ marginTop: 20, textAlign: "left", background: "#fff3cd", border: "1px solid #e0a800", borderRadius: 8, padding: 12 }}>
            <div style={{ fontWeight: 700, color: "#7a5b00", marginBottom: 6 }}>
              TEMP DEBUG — remove after diagnosing (screenshot this box)
            </div>
            <pre style={{ fontSize: 11, whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0, color: "#3a2e00" }}>
              {JSON.stringify(prev.debug, null, 2)}
            </pre>
          </div>
        )}
      </div>
    );
  }

  const rows = [
    ["S — Subjective", previous.subjective],
    ["O — Objective", previous.objective],
    ["A — Assessment", previous.assessment],
    ["P — Plan", previous.plan],
    ["Investigations", previous.investigations],
    ["Advice", previous.advice_to_patient],
  ].filter(([, v]) => v);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="callout">
        <div>
          <div className="callout-title">Read-only — from {previous.encounter_date || "a previous visit"}</div>
          <div className="callout-body">This is the patient's most recent signed consultation at this hospital, for reference while seeing them today.</div>
        </div>
      </div>
      <div className="card" style={{ display: "grid", gap: 14 }}>
        {(previous.diagnoses || []).length > 0 && (
          <div>
            <div className="stat-label" style={{ marginBottom: 6 }}>Diagnoses</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {previous.diagnoses.map((d, i) => (
                <span key={i} className="badge badge--neutral">{d.code} — {d.description}</span>
              ))}
            </div>
          </div>
        )}
        {rows.map(([label, value]) => (
          <div key={label}>
            <div className="stat-label" style={{ marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
