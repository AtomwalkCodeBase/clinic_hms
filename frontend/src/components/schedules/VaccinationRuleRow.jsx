import { labelStyle, adminInputStyle as inputStyle } from "../../styles/formStyles";

export function VaccinationRuleRow({ rule, onChange, onRemove, onMove, isFirst, isLast }) {
  const set = (k) => (v) => onChange({ ...rule, [k]: v });
  return (
    <div className="card" style={{ padding: "14px 16px", display: "grid", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
        <div>
          <label style={labelStyle}>Vaccine Name *</label>
          <input style={inputStyle} value={rule.vaccine_name}
            onChange={e => set("vaccine_name")(e.target.value)} placeholder="e.g. BCG" required />
        </div>
        <div>
          <label style={labelStyle}>Dose #</label>
          <input type="number" min={1} style={inputStyle} value={rule.dose_number}
            onChange={e => set("dose_number")(Number(e.target.value))} />
        </div>
      </div>

      <div>
        <label style={labelStyle}>Scheduled Label (milestone) *</label>
        <input style={inputStyle} value={rule.scheduled_label}
          onChange={e => set("scheduled_label")(e.target.value)} placeholder="e.g. Birth, 6 weeks, 9 months" required />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <div>
          <label style={labelStyle}>Min Age (days) *</label>
          <input type="number" min={0} style={inputStyle} value={rule.min_age_days}
            onChange={e => set("min_age_days")(Number(e.target.value))} required />
        </div>
        <div>
          <label style={labelStyle}>Max Age (days)</label>
          <input type="number" min={0} style={inputStyle} value={rule.max_age_days ?? ""}
            onChange={e => set("max_age_days")(e.target.value === "" ? "" : Number(e.target.value))}
            placeholder="optional" />
        </div>
        <div>
          <label style={labelStyle}>Sort Order</label>
          <input type="number" style={inputStyle} value={rule.sort_order}
            onChange={e => set("sort_order")(Number(e.target.value))} />
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 2 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
          <input type="checkbox" checked={!!rule.mandatory} onChange={e => set("mandatory")(e.target.checked)} />
          Mandatory
        </label>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" onClick={onMove ? () => onMove(-1) : undefined} disabled={isFirst}
            title="Move up"
            style={{ padding: "5px 10px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: isFirst ? "not-allowed" : "pointer", fontSize: 13, opacity: isFirst ? 0.4 : 1 }}>
            ↑
          </button>
          <button type="button" onClick={onMove ? () => onMove(1) : undefined} disabled={isLast}
            title="Move down"
            style={{ padding: "5px 10px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: isLast ? "not-allowed" : "pointer", fontSize: 13, opacity: isLast ? 0.4 : 1 }}>
            ↓
          </button>
          <button type="button" onClick={onRemove}
            style={{ padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-error)", background: "none", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "var(--color-error)" }}>
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}
