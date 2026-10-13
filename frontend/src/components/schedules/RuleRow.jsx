import { labelStyle, adminInputStyle as inputStyle } from "../../styles/formStyles";
import { MILESTONE_DOMAIN_OPTIONS as DOMAIN_OPTIONS } from "../../constants/labels";

const arrowStyle = (disabled) => ({
  padding: "5px 10px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none",
  cursor: disabled ? "not-allowed" : "pointer", fontSize: 13, opacity: disabled ? 0.4 : 1,
});

/** One editable rule of a schedule. `kind` (scheduleKinds.js) decides whether the first row is vaccine + dose or domain + milestone. */
export function RuleRow({ kind, rule, onChange, onRemove, onMove, isFirst, isLast }) {
  const set = (k) => (v) => onChange({ ...rule, [k]: v });
  const t = kind.text;
  const isVaccine = kind.extraKey === "dose_number";
  const nameField = (
    <div>
      <label style={labelStyle}>{t.nameLabel}</label>
      <input style={inputStyle} value={rule[kind.nameKey]} onChange={e => set(kind.nameKey)(e.target.value)}
        placeholder={t.nameExample} required />
    </div>
  );
  return (
    <div className="card" style={{ padding: "14px 16px", display: "grid", gap: 10 }}>
      {isVaccine ? (
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
          {nameField}
          <div>
            <label style={labelStyle}>Dose #</label>
            <input type="number" min={1} style={inputStyle} value={rule.dose_number}
              onChange={e => set("dose_number")(Number(e.target.value))} />
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 10 }}>
          <div>
            <label style={labelStyle}>Domain *</label>
            <select style={inputStyle} value={rule.domain} onChange={e => set("domain")(e.target.value)}>
              {DOMAIN_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          {nameField}
        </div>
      )}

      <div>
        <label style={labelStyle}>{t.labelLabel}</label>
        <input style={inputStyle} value={rule.scheduled_label}
          onChange={e => set("scheduled_label")(e.target.value)} placeholder={t.labelExample} required />
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
          {t.mandatory}
        </label>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" onClick={() => onMove(-1)} disabled={isFirst} title="Move up" style={arrowStyle(isFirst)}>↑</button>
          <button type="button" onClick={() => onMove(1)} disabled={isLast} title="Move down" style={arrowStyle(isLast)}>↓</button>
          <button type="button" onClick={onRemove}
            style={{ padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-error)", background: "none", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "var(--color-error)" }}>
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}
