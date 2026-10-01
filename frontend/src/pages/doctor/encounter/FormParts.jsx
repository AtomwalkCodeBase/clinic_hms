export function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-secondary)", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </label>
      {children}
    </div>
  );
}

export function Textarea({ value, onChange, disabled, placeholder, rows = 3 }) {
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
