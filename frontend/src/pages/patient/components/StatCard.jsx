// One coloured number card (icon, big number, label, optional note). Used by the vaccination stats row and the milestones roadmap.
const THEMES = {
  success: {          // completed / achieved
    bg: "linear-gradient(135deg, var(--color-primary-light) 0%, var(--color-bg) 100%)",
    iconBg: "var(--color-primary)", numColor: "var(--color-primary)", labelColor: "var(--color-primary)",
    border: "color-mix(in srgb, var(--color-primary) 30%, white)",
  },
  upcoming: {
    bg: "linear-gradient(135deg, #FEF3DC 0%, #FFF9EF 100%)",
    iconBg: "var(--color-warning)", numColor: "#7A5418", labelColor: "var(--color-warning)", border: "#EDD49A",
  },
  review: {
    bg: "linear-gradient(135deg, #F1E9FA 0%, #F8F3FD 100%)",
    iconBg: "#6B3FA0", numColor: "#4A2872", labelColor: "#6B3FA0", border: "#CDB8E8",
  },
  outside: {
    bg: "linear-gradient(135deg, #E5EEF3 0%, #EEF4F8 100%)",
    iconBg: "#2C5D7C", numColor: "#1E4259", labelColor: "#2C5D7C", border: "#AECAD8",
  },
  neutral: {          // "not yet"
    bg: "linear-gradient(135deg, #F3F4F6 0%, #FAFAFA 100%)",
    iconBg: "#6B7280", numColor: "#374151", labelColor: "#6B7280", border: "#D1D5DB",
  },
};

export default function StatCard({ icon: Icon, theme, value, label, subtext }) {
  const t = THEMES[theme];
  return (
    <div style={{
      background: t.bg, border: `1.5px solid ${t.border}`, borderRadius: 16, padding: "18px 20px",
      display: "flex", flexDirection: "column", gap: 0, position: "relative", overflow: "hidden",
    }}>
      <div style={{
        position: "absolute", right: -16, top: -16, width: 80, height: 80, borderRadius: "50%",
        background: t.iconBg, opacity: 0.08, pointerEvents: "none",
      }} />
      <div style={{
        width: 38, height: 38, borderRadius: 12, background: t.iconBg, color: "#fff",
        display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12, flexShrink: 0,
      }}>
        <Icon size={18} />
      </div>
      <div style={{
        fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 34, lineHeight: 1,
        color: t.numColor, letterSpacing: "-0.02em", marginBottom: 6,
      }}>
        {value}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.labelColor, marginBottom: subtext ? 4 : 0 }}>{label}</div>
      {subtext && (
        <div style={{ fontSize: 11, color: t.numColor, opacity: 0.7, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {subtext}
        </div>
      )}
    </div>
  );
}
