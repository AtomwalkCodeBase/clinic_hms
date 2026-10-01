// ─── Tiny helpers ─────────────────────────────────────────────────────────────
export function SectionCard({ title, badge, extra, children }) {
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{
        padding: "10px 18px",
        borderBottom: "1px solid var(--color-border)",
        background: "#FAFAFA",
        fontWeight: 700, fontSize: 13,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        {title}
        {badge !== undefined && (
          <span style={{
            padding: "2px 8px", borderRadius: 12, fontSize: 11, fontWeight: 700,
            background: badge > 0 ? "var(--color-primary)" : "var(--color-border)",
            color: badge > 0 ? "#fff" : "var(--color-text-muted)",
          }}>{badge}</span>
        )}
        {extra && <span style={{ marginLeft: "auto" }}>{extra}</span>}
      </div>
      <div style={{ padding: "16px 18px" }}>{children}</div>
    </div>
  );
}
