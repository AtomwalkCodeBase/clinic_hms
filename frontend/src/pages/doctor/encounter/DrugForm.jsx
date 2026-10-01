import { useState } from "react";
import { EMPTY_DRUG, FREQ_LABELS, ROUTE_LABELS } from "./constants";
import { DrugNameSearch } from "./DrugNameSearch";

export function DrugForm({ onSave, disabled }) {
  const [d, setD] = useState(EMPTY_DRUG);
  function upd(k, v) { setD(p => ({ ...p, [k]: v, ...(k === "drug_name" ? { drug: null } : {}) })); }

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
          <DrugNameSearch
            value={d.drug_name}
            onChange={v => upd("drug_name", v)}
            onSelectCatalog={c => setD(p => ({
              ...p,
              drug: c.id,
              drug_name: c.strength ? `${c.name} ${c.strength}` : c.name,
              dosage: c.strength || p.dosage,
            }))}
            disabled={disabled}
          />
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
