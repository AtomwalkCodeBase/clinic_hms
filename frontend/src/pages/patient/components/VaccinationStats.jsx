/**
 * pages/patient/components/VaccinationStats.jsx
 * ------------------------------------------------
 * 4-card stats row — each card has its own colour identity:
 *   Completed    → forest green
 *   Upcoming     → warm amber
 *   Needs Review → purple
 *   Outside      → steel blue
 */
import { CheckCircle2, Calendar, HelpCircle, Syringe } from "lucide-react";

function nextUpcoming(roadmap) {
  return (roadmap || []).find(item => !item.extra && item.status === "unknown" && item.timing === "upcoming") || null;
}

const CARD_THEMES = {
  completed: {
    bg: "linear-gradient(135deg, #E9F1EC 0%, #F4F1E8 100%)",
    iconBg: "#1B5E43",
    iconColor: "#fff",
    numColor: "#1B5E43",
    labelColor: "#1B5E43",
    border: "#C2DFCb",
  },
  upcoming: {
    bg: "linear-gradient(135deg, #FEF3DC 0%, #FFF9EF 100%)",
    iconBg: "#B07C24",
    iconColor: "#fff",
    numColor: "#7A5418",
    labelColor: "#B07C24",
    border: "#EDD49A",
  },
  needs_review: {
    bg: "linear-gradient(135deg, #F1E9FA 0%, #F8F3FD 100%)",
    iconBg: "#6B3FA0",
    iconColor: "#fff",
    numColor: "#4A2872",
    labelColor: "#6B3FA0",
    border: "#CDB8E8",
  },
  outside: {
    bg: "linear-gradient(135deg, #E5EEF3 0%, #EEF4F8 100%)",
    iconBg: "#2C5D7C",
    iconColor: "#fff",
    numColor: "#1E4259",
    labelColor: "#2C5D7C",
    border: "#AECAD8",
  },
};

function StatCard({ icon: Icon, theme, value, label, subtext }) {
  const t = CARD_THEMES[theme];
  return (
    <div style={{
      background: t.bg,
      border: `1.5px solid ${t.border}`,
      borderRadius: 16,
      padding: "18px 20px",
      display: "flex", flexDirection: "column", gap: 0,
      position: "relative", overflow: "hidden",
      boxShadow: "0 2px 8px rgba(15,61,43,0.06)",
    }}>
      {/* Background circle decoration */}
      <div style={{
        position: "absolute", right: -16, top: -16,
        width: 80, height: 80, borderRadius: "50%",
        background: t.iconBg, opacity: 0.08,
        pointerEvents: "none",
      }} />

      {/* Icon */}
      <div style={{
        width: 38, height: 38, borderRadius: 12,
        background: t.iconBg, color: t.iconColor,
        display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: `0 4px 10px ${t.iconBg}44`,
        marginBottom: 12, flexShrink: 0,
      }}>
        <Icon size={18} />
      </div>

      {/* Number */}
      <div style={{
        fontFamily: "var(--font-display)", fontWeight: 700,
        fontSize: 34, lineHeight: 1, color: t.numColor,
        letterSpacing: "-0.02em", marginBottom: 6,
      }}>
        {value}
      </div>

      {/* Label */}
      <div style={{ fontSize: 13, fontWeight: 600, color: t.labelColor, marginBottom: 4 }}>
        {label}
      </div>

      {/* Subtext */}
      {subtext && (
        <div style={{
          fontSize: 11, color: t.numColor, opacity: 0.7,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {subtext}
        </div>
      )}
    </div>
  );
}

export default function VaccinationStats({ vax }) {
  const stats = vax?.stats ?? { completed: 0, upcoming: 0, needs_review: 0, outside: 0 };
  const upcomingNext = nextUpcoming(vax?.roadmap) ?? null;

  return (
    <div
      style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 20 }}
      className="vax-stats-grid"
    >
      <StatCard
        icon={CheckCircle2}
        theme="completed"
        value={stats.completed}
        label="Completed"
        subtext="Vaccines taken"
      />
      <StatCard
        icon={Calendar}
        theme="upcoming"
        value={stats.upcoming}
        label="Upcoming"
        subtext={upcomingNext
          ? `Next: ${upcomingNext.vaccine_name}${upcomingNext.scheduled_label ? ` · ${upcomingNext.scheduled_label}` : ""}`
          : "Nothing due yet"}
      />
      <StatCard
        icon={HelpCircle}
        theme="needs_review"
        value={stats.needs_review}
        label="Needs Review"
        subtext="No record available"
      />
      <StatCard
        icon={Syringe}
        theme="outside"
        value={stats.outside}
        label="Outside Vaccines"
        subtext="Added by doctor"
      />
    </div>
  );
}
