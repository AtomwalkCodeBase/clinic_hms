import { useToast } from "../../../hooks/useToast";
import { useState } from "react";
import { encounterApi } from "../../../api";

// ─── Book Follow-up modal ─── doctor picks exactly one path for the NEXT
// visit: hand it to a nurse to actually book, or just send the patient a
// reminder and let them / front desk book it later (existing behaviour).
// Available even after Sign & Close — see FollowUpActionView's docstring on
// why this is a separate endpoint from the general SOAP-notes PATCH.
// A button + modal (mirrors AdmissionReferralModal) — NOT a tab. The
// "Follow-up" heading on the consultation itself is handled separately by
// isFollowUp further down; this modal is only for planning the NEXT visit.
export function FollowUpModal({ enc, encounterId, refetch, onClose }) {
  const { toastSuccess, toastApiError } = useToast();
  const [mode, setMode] = useState(enc.followup_ask_nurse ? "nurse" : "reminder");
  const [note, setNote] = useState(enc.followup_nurse_note || "");
  const [days, setDays] = useState(enc.follow_up_in_days ? String(enc.follow_up_in_days) : "");
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function submit() {
    setSaving(true);
    try {
      await encounterApi.bookFollowUp(encounterId, {
        mode,
        note: mode === "nurse" ? note : "",
        follow_up_in_days: mode === "reminder" ? (days ? parseInt(days) : null) : null,
      });
      toastSuccess(mode === "nurse" ? "A nurse will book this patient's next visit." : "Reminder set — the patient/front desk can book it later.");
      refetch();
      setSubmitted(true);
    } catch (err) {
      toastApiError(err, "Could not save the follow-up plan.");
    } finally {
      setSaving(false);
    }
  }

  const alreadySet = enc.followup_ask_nurse || enc.follow_up_in_days;

  if (submitted) {
    return (
      <div style={{ position: "fixed", inset: 0, background: "rgba(12,42,31,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
        <div className="card" style={{ width: 480, borderLeft: "3px solid var(--color-success, #1a7f37)" }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Follow-up plan saved</div>
          <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>
            {mode === "nurse" ? "A nurse will see this on their worklist and book the next visit." : "The patient/front desk will get a reminder to book when it's due."}
          </div>
          <button className="btn-primary" style={{ marginTop: 12 }} onClick={onClose}>Done</button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(12,42,31,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
      <div className="card" style={{ width: 640, maxHeight: "88vh", overflowY: "auto" }}>
        <div className="page-header" style={{ marginBottom: 14 }}>
          <div className="page-title" style={{ fontSize: 20 }}>Book Follow-up</div>
          <button className="btn-outline" onClick={onClose}>Cancel</button>
        </div>
        <div style={{ display: "grid", gap: 16 }}>
          {alreadySet && (
            <div className="card" style={{ borderLeft: "3px solid var(--color-primary)" }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {enc.followup_ask_nurse
                  ? (enc.followup_nurse_booked ? "Nurse has booked the next visit." : "Waiting on a nurse to book the next visit.")
                  : `Reminder set for ${enc.follow_up_in_days} day(s) out.`}
              </div>
            </div>
          )}

          <div className="card" style={{ display: "grid", gap: 14 }}>
            <div
              onClick={() => setMode("nurse")}
              style={{
                border: `1.5px solid ${mode === "nurse" ? "var(--color-primary)" : "var(--color-border)"}`,
                borderRadius: "var(--radius-input)", padding: 14, cursor: "pointer",
                background: mode === "nurse" ? "var(--color-table-header)" : "transparent",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 4 }}>Patient wants a follow-up — ask a nurse to book it</div>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>A nurse will see this on their worklist and coordinate the actual appointment with the patient/front desk.</div>
              {mode === "nurse" && (
                <input
                  className="form-input" style={{ marginTop: 10 }}
                  placeholder="Optional note for the nurse (e.g. 'in 2 weeks, after repeat labs')"
                  value={note} onChange={(e) => setNote(e.target.value)}
                />
              )}
            </div>

            <div
              onClick={() => setMode("reminder")}
              style={{
                border: `1.5px solid ${mode === "reminder" ? "var(--color-primary)" : "var(--color-border)"}`,
                borderRadius: "var(--radius-input)", padding: 14, cursor: "pointer",
                background: mode === "reminder" ? "var(--color-table-header)" : "transparent",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 4 }}>Not sure yet — just send a reminder</div>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>The patient gets a reminder to book when it's due; they or front desk book it later.</div>
              {mode === "reminder" && (
                <input
                  className="form-input" type="number" min="1" style={{ marginTop: 10, maxWidth: 160 }}
                  placeholder="Days from now"
                  value={days} onChange={(e) => setDays(e.target.value)}
                />
              )}
            </div>

            <button className="btn-primary" disabled={saving || (mode === "reminder" && !days)} onClick={submit}>
              {saving ? "Saving…" : "Save Follow-up Plan"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
