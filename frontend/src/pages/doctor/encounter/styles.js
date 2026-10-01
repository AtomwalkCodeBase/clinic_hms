// Small pill button used in the SOAP card header row.
export function miniBtn(border, color, bg, disabled) {
  return {
    display: "inline-flex", alignItems: "center", gap: 4,
    fontSize: 11, fontWeight: 600, padding: "4px 8px", borderRadius: 6,
    border: `1px solid ${border}`, background: bg, color,
    cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
  };
}
