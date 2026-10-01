import { useState } from "react";

// ─── Patient history sidebar (Overleaf-style collapsible rail) ──────────────
// Cross-visit history — past diagnoses, vitals, allergies, lab results,
// prescriptions — pulled from the shared HIE record. Collapses to a thin
// icon rail so it never eats into the SOAP/vitals/diagnoses workspace; the
// main content's own layout is completely untouched either way.
export function HistorySection({ title, icon, count, defaultOpen, urgent, children }) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div style={{ borderBottom: "1px solid var(--color-border)" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 8,
          padding: "10px 14px", background: "none", border: "none", cursor: "pointer",
          fontSize: 12, fontWeight: 700, color: "var(--color-text)", textAlign: "left",
        }}
      >
        <span style={{ fontSize: 10, color: "var(--color-text-muted)", width: 10, display: "inline-block" }}>
          {open ? "▾" : "▸"}
        </span>
        {icon && (
          <span style={{ display: "flex", color: urgent && count > 0 ? "#DC2626" : "var(--color-text-secondary)" }}>
            {icon}
          </span>
        )}
        <span style={{ flex: 1 }}>{title}</span>
        {count !== undefined && (
          <span style={{
            fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 10,
            background: urgent && count > 0 ? "#FEE2E2" : count > 0 ? "var(--color-primary-light)" : "var(--color-border)",
            color: urgent && count > 0 ? "#DC2626" : count > 0 ? "var(--color-primary)" : "var(--color-text-muted)",
          }}>{count}</span>
        )}
      </button>
      {open && <div style={{ padding: "0 14px 12px" }}>{children}</div>}
    </div>
  );
}

export function EmptyNote({ children }) {
  return <p style={{ fontSize: 12, color: "var(--color-text-muted)", margin: 0 }}>{children}</p>;
}
