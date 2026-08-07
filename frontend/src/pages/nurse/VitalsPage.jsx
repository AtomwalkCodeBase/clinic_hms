/**
 * pages/nurse/VitalsPage.jsx
 * ---------------------------
 * Nurse vitals entry. Nurse selects a waiting appointment, fills in vitals,
 * and saves them. Status auto-advances to "vitals_done" so doctor sees them next.
 */

import { useState, useEffect } from "react";
import { AppShell }   from "../../components/layout/AppShell";
import { PageShell }  from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import { useToast }   from "../../hooks/useToast";
import apiClient      from "../../services/api.client";
import API_ENDPOINTS  from "../../config/api.config";

const TODAY = new Date().toISOString().slice(0, 10);

function VitalInput({ label, unit, name, value, onChange, placeholder }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)" }}>
        {label} {unit && <span style={{ fontWeight: 400 }}>({unit})</span>}
      </label>
      <input
        className="form-input"
        type="number"
        step="any"
        name={name}
        value={value}
        onChange={onChange}
        placeholder={placeholder || "—"}
        style={{ textAlign: "center" }}
      />
    </div>
  );
}

export default function VitalsPage() {
  const { toastSuccess, toastApiError } = useToast();

  const [appointments, setAppointments] = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [selected,     setSelected]     = useState(null);
  const [saving,       setSaving]       = useState(false);

  const [form, setForm] = useState({
    systolic_bp:    "",
    diastolic_bp:   "",
    pulse_rate:     "",
    spo2:           "",
    temperature:    "",
    weight_kg:      "",
    height_cm:      "",
    blood_sugar_rbs: "",
    chief_complaint: "",
    nurse_notes:    "",
  });

  useEffect(() => {
    setLoading(true);
    // page_size=100 — this list must show every waiting patient today, not
    // just the first page, since a missed patient here means vitals never
    // get recorded for them.
    apiClient.get(`${API_ENDPOINTS.OPD.APPOINTMENTS}?date=${TODAY}&page_size=100`)
      .then(r => {
        const appts = r.data?.results || [];
        // Show only waiting appointments (haven't had vitals done yet)
        setAppointments(appts.filter(a =>
          a.status === "waiting" || a.status === "scheduled"
        ));
      })
      .catch(() => setAppointments([]))
      .finally(() => setLoading(false));
  }, []);

  function selectAppointment(appt) {
    setSelected(appt);
    setForm({
      systolic_bp:    "",
      diastolic_bp:   "",
      pulse_rate:     "",
      spo2:           "",
      temperature:    "",
      weight_kg:      "",
      height_cm:      "",
      blood_sugar_rbs: "",
      chief_complaint: appt.chief_complaint || "",
      nurse_notes:    "",
    });
  }

  function handleChange(e) {
    const { name, value } = e.target;
    setForm(f => ({ ...f, [name]: value }));
  }

  async function handleSave(e) {
    e.preventDefault();
    if (!selected) return;
    setSaving(true);

    try {
      // Build vitals payload — only send non-empty fields
      const vitals = {};
      const numFields = ["systolic_bp","diastolic_bp","pulse_rate","spo2",
                         "temperature","weight_kg","height_cm","blood_sugar_rbs"];
      numFields.forEach(f => {
        if (form[f] !== "") vitals[f] = parseFloat(form[f]);
      });
      // chief_complaint goes to appointment; nurse_notes goes to Vitals
      if (form.chief_complaint) vitals.chief_complaint = form.chief_complaint;
      if (form.nurse_notes)     vitals.nurse_notes     = form.nurse_notes;

      await apiClient.post(API_ENDPOINTS.OPD.APPT_VITALS(selected.id), vitals);
      toastSuccess(`Vitals saved for ${selected.patient_name}.`);

      // Remove from waiting list
      setAppointments(prev => prev.filter(a => a.id !== selected.id));
      setSelected(null);
    } catch (err) {
      toastApiError(err, "Failed to save vitals.");
    } finally {
      setSaving(false);
    }
  }

  const bpValid = !form.systolic_bp || !form.diastolic_bp ||
    (parseInt(form.systolic_bp) > parseInt(form.diastolic_bp));

  return (
    <AppShell>
      <PageShell title="Vitals Entry">
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 20, alignItems: "start" }}>

          {/* Left — Patient queue */}
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, color: "var(--color-text-muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Waiting for Vitals ({appointments.length})
            </div>

            {loading ? (
              <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>
                Loading…
              </div>
            ) : appointments.length === 0 ? (
              <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
                No patients waiting for vitals.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {appointments.map(appt => (
                  <div key={appt.id}
                    onClick={() => selectAppointment(appt)}
                    className="card"
                    style={{
                      padding: "12px 16px", cursor: "pointer",
                      border: selected?.id === appt.id
                        ? "2px solid var(--color-primary)"
                        : "2px solid transparent",
                      background: selected?.id === appt.id
                        ? "var(--color-primary-light)"
                        : "var(--color-surface)",
                    }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{
                        width: 32, height: 32, borderRadius: "50%",
                        background: "var(--color-primary)", color: "#fff",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontWeight: 700, fontSize: 13, flexShrink: 0,
                      }}>
                        {appt.token_number || "?"}
                      </div>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <div style={{ fontWeight: 600, fontSize: 14 }}>{appt.patient_name}</div>
                          <DependentBadge patient={appt} />
                        </div>
                        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                          {appt.patient_uhid}
                          {appt.chief_complaint && ` · ${appt.chief_complaint}`}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right — Vitals form */}
          <div>
            {!selected ? (
              <div className="card" style={{ padding: 60, textAlign: "center", color: "var(--color-text-muted)" }}>
                <div style={{ fontSize: 40, marginBottom: 12 }}>🩺</div>
                Select a patient from the queue to enter vitals.
              </div>
            ) : (
              <form onSubmit={handleSave}>
                {/* Patient banner */}
                <div className="card" style={{ padding: "14px 20px", marginBottom: 16, background: "var(--color-primary-light)", border: "1.5px solid var(--color-primary)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <div style={{ fontWeight: 700, fontSize: 16 }}>{selected.patient_name}</div>
                        <DependentBadge patient={selected} />
                      </div>
                      <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 2 }}>
                        {selected.patient_uhid} · Token #{selected.token_number}
                      </div>
                    </div>
                    <button type="button" onClick={() => setSelected(null)}
                      style={{ background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "var(--color-text-muted)" }}>
                      ✕
                    </button>
                  </div>
                </div>

                {/* Chief complaint */}
                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>Chief Complaint</div>
                  <textarea
                    className="form-input"
                    name="chief_complaint"
                    value={form.chief_complaint}
                    onChange={handleChange}
                    placeholder="Patient's main complaint in their own words…"
                    rows={2}
                    style={{ resize: "vertical" }}
                  />
                </div>

                {/* Vitals grid */}
                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 16 }}>Vitals</div>

                  {/* Blood pressure */}
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 8 }}>
                      Blood Pressure (mmHg)
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 8, maxWidth: 240 }}>
                      <input className="form-input" type="number" name="systolic_bp"
                        value={form.systolic_bp} onChange={handleChange}
                        placeholder="Systolic" style={{ textAlign: "center" }} />
                      <span style={{ fontWeight: 700, color: "var(--color-text-muted)" }}>/</span>
                      <input className="form-input" type="number" name="diastolic_bp"
                        value={form.diastolic_bp} onChange={handleChange}
                        placeholder="Diastolic" style={{ textAlign: "center" }} />
                    </div>
                    {!bpValid && (
                      <div className="field-error" style={{ marginTop: 4 }}>
                        Systolic must be greater than diastolic.
                      </div>
                    )}
                  </div>

                  {/* Other vitals */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
                    <VitalInput label="Pulse Rate" unit="bpm" name="pulse_rate"
                      value={form.pulse_rate} onChange={handleChange} placeholder="72" />
                    <VitalInput label="SpO₂" unit="%" name="spo2"
                      value={form.spo2} onChange={handleChange} placeholder="98" />
                    <VitalInput label="Temperature" unit="°F" name="temperature"
                      value={form.temperature} onChange={handleChange} placeholder="98.6" />
                    <VitalInput label="Weight" unit="kg" name="weight_kg"
                      value={form.weight_kg} onChange={handleChange} placeholder="70" />
                    <VitalInput label="Height" unit="cm" name="height_cm"
                      value={form.height_cm} onChange={handleChange} placeholder="170" />
                    <VitalInput label="Blood Sugar (RBS)" unit="mg/dL" name="blood_sugar_rbs"
                      value={form.blood_sugar_rbs} onChange={handleChange} placeholder="90" />
                  </div>
                </div>

                {/* Nurse notes */}
                <div className="card" style={{ padding: 20, marginBottom: 16 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>Nurse Notes</div>
                  <textarea
                    className="form-input"
                    name="nurse_notes"
                    value={form.nurse_notes}
                    onChange={handleChange}
                    placeholder="Any observations for the doctor (optional)…"
                    rows={2}
                    style={{ resize: "vertical" }}
                  />
                </div>

                <div style={{ display: "flex", gap: 10 }}>
                  <button type="button" onClick={() => setSelected(null)}
                    style={{ flex: 1, padding: "10px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
                    Cancel
                  </button>
                  <button type="submit" disabled={saving || !bpValid} className="btn-primary" style={{ flex: 2 }}>
                    {saving ? "Saving…" : "Save Vitals & Move to Doctor"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      </PageShell>
    </AppShell>
  );
}
