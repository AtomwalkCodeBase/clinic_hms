import { cloneElement, isValidElement, useState } from "react";
import { ChevronDown } from "lucide-react";

// ─── Patient history sidebar (Overleaf-style collapsible rail) ──────────────
// Cross-visit history — past diagnoses, vitals, allergies, lab results,
// prescriptions — pulled from the shared HIE record. Collapses to a thin
// icon rail so it never eats into the SOAP/vitals/diagnoses workspace; the
// main content's own layout is completely untouched either way.
//
// A section with something in it is a full row (icon in a tinted tile, title, count, chevron). A section with
// nothing in it (count 0) is a slim, muted row, so six empty sections don't read as six full ones; it still opens
// (some hold an "add" action). `urgent` (allergies) turns red as soon as it has an entry.
export function HistorySection({ title, icon, count, defaultOpen, urgent, children }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const empty = count === 0;
  const alert = urgent && count > 0;
  const tile = alert ? { bg: "#FEE2E2", color: "#DC2626" } : { bg: "var(--color-primary-light)", color: "var(--color-primary)" };
  return (
    <div style={{ borderBottom: "1px solid var(--color-border)" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 10,
          padding: empty && !open ? "8px 14px" : "11px 14px", background: "none", border: "none", cursor: "pointer",
          fontSize: 13, textAlign: "left", color: empty ? "var(--color-text-muted)" : "var(--color-text)",
        }}
      >
        {icon && (
          <span style={{
            width: empty && !open ? 22 : 26, height: empty && !open ? 22 : 26, borderRadius: 8, flexShrink: 0,
            display: "grid", placeItems: "center",
            background: empty ? "var(--color-bg)" : tile.bg, color: empty ? "var(--color-text-muted)" : tile.color,
          }}>
            {isValidElement(icon) ? cloneElement(icon, { size: 15 }) : icon}
          </span>
        )}
        <span style={{ flex: 1, fontWeight: empty ? 500 : 600 }}>{title}</span>
        {count > 0 && (
          <span style={{
            fontSize: 11, fontWeight: 600, padding: "1px 8px", borderRadius: 10,
            background: alert ? "#FEE2E2" : "var(--color-primary-light)", color: alert ? "#DC2626" : "var(--color-primary)",
          }}>{count}</span>
        )}
        <ChevronDown size={15} style={{ color: "var(--color-text-muted)", flexShrink: 0, transform: open ? "rotate(180deg)" : "none" }} />
      </button>
      {open && <div style={{ padding: "2px 14px 14px" }}>{children}</div>}
    </div>
  );
}

export function EmptyNote({ children }) {
  return <p style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: 0 }}>{children}</p>;
}
