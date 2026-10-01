export const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

export const inputStyle = {
  width: "100%", boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "9px 12px", fontSize: 14,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};

export const adminInputStyle = {
  width: "100%", boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "8px 10px", fontSize: 13.5,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};

export const editorInputStyle = {
  boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "8px 12px", fontSize: 13,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};

export const readOnlyStyle = {
  ...inputStyle,
  background: "var(--color-surface-secondary, #f6f4ee)",
  color: "var(--color-text-muted)",
};

export const authLabelStyle = {
  display: "block", fontSize: 11, fontWeight: 700, letterSpacing: "0.06em",
  textTransform: "uppercase", marginBottom: 7, color: "var(--color-text-secondary)",
};

export const authBareInput = {
  outline: "none", border: "none", background: "transparent", padding: "11px 0",
  fontSize: 14, width: "100%", color: "var(--color-text)", fontFamily: "inherit",
};

export const authFieldWrap = (hasError) => ({
  display: "flex", alignItems: "center", gap: 10,
  border: `1.5px solid ${hasError ? "var(--color-error)" : "var(--color-border)"}`,
  borderRadius: "var(--radius-input)", padding: "0 14px", background: "var(--color-bg)",
});

export const admissionLabelStyle = { display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "var(--color-text-muted)" };
