/**
 * pages/patient/components/MilestonesRoadmap.jsx
 * ------------------------------------------------
 * Read-only developmental-milestone roadmap for the patient portal — same
 * data (PortalMilestoneListView -> apps/registry/milestone_roadmap.py) and
 * status vocabulary the doctor's EncounterPage assesses against, just
 * without the assess form: a parent can see what's been recorded, not
 * record it themselves.
 */
import { CheckCircle2, Calendar, HelpCircle, ListTree } from "lucide-react";

const STATUS_STYLE = {
  achieved:   { bg: "#ECFDF5", color: "#047857", label: "Achieved" },
  not_yet:    { bg: "#F3F4F6", color: "#6B7280", label: "Not Yet" },
  concern:    { bg: "#FEF2F2", color: "#B91C1C", label: "Concern — flagged for follow-up" },
  unassessed: { bg: "var(--color-bg)", color: "var(--color-text-muted)", label: "Not Assessed" },
};

const CARD_THEMES = {
  achieved: {
    bg: "linear-gradient(135deg, var(--color-primary-light) 0%, var(--color-bg) 100%)",
    iconBg: "var(--color-primary)", numColor: "var(--color-primary)", labelColor: "var(--color-primary)",
    border: "color-mix(in srgb, var(--color-primary) 30%, white)",
  },
  upcoming: {
    bg: "linear-gradient(135deg, #FEF3DC 0%, #FFF9EF 100%)",
    iconBg: "var(--color-warning)", numColor: "#7A5418", labelColor: "var(--color-warning)", border: "#EDD49A",
  },
  needs_review: {
    bg: "linear-gradient(135deg, #F1E9FA 0%, #F8F3FD 100%)",
    iconBg: "#6B3FA0", numColor: "#4A2872", labelColor: "#6B3FA0", border: "#CDB8E8",
  },
  not_yet: {
    bg: "linear-gradient(135deg, #F3F4F6 0%, #FAFAFA 100%)",
    iconBg: "#6B7280", numColor: "#374151", labelColor: "#6B7280", border: "#D1D5DB",
  },
};

function StatCard({ icon: Icon, theme, value, label }) {
  const t = CARD_THEMES[theme];
  return (
    <div style={{
      background: t.bg, border: `1.5px solid ${t.border}`, borderRadius: 16,
      padding: "18px 20px", position: "relative", overflow: "hidden",
    }}>
      <div style={{
        position: "absolute", right: -16, top: -16, width: 80, height: 80, borderRadius: "50%",
        background: t.iconBg, opacity: 0.08, pointerEvents: "none",
      }} />
      <div style={{
        width: 38, height: 38, borderRadius: 12, background: t.iconBg, color: "#fff",
        display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12,
      }}>
        <Icon size={18} />
      </div>
      <div style={{
        fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 34, lineHeight: 1,
        color: t.numColor, letterSpacing: "-0.02em", marginBottom: 6,
      }}>
        {value}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.labelColor }}>{label}</div>
    </div>
  );
}

export default function MilestonesRoadmap({ milestones, isLoading }) {
  const roadmap = milestones?.roadmap || [];
  const stats = milestones?.stats ?? { achieved: 0, upcoming: 0, needs_review: 0, not_yet: 0 };

  if (isLoading) {
    return (
      <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
        Loading milestone roadmap…
      </div>
    );
  }

  if (!roadmap.length) {
    return (
      <div className="card" style={{ padding: 44, textAlign: "center" }}>
        <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
          No milestone schedule available
        </div>
        <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
          Your doctor will record developmental milestones during check-ups.
        </div>
      </div>
    );
  }

  return (
    <>
      {milestones?.next_recommended && (
        <div className="card" style={{
          padding: "12px 16px", marginBottom: 16, display: "flex", alignItems: "center", gap: 10,
          border: "1px solid #EDD49A", background: "linear-gradient(135deg, #FEF3DC 0%, #FFF9EF 100%)",
        }}>
          <Calendar size={16} color="var(--color-warning)" />
          <div style={{ fontSize: 12.5, color: "#7A5418" }}>
            <strong>{milestones.next_recommended.milestone}</strong> ({milestones.next_recommended.scheduled_label})
            {" "}is due for assessment at your next visit.
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 20 }}
        className="vax-stats-grid">
        <StatCard icon={CheckCircle2} theme="achieved" value={stats.achieved} label="Achieved" />
        <StatCard icon={Calendar} theme="upcoming" value={stats.upcoming} label="Upcoming" />
        <StatCard icon={HelpCircle} theme="needs_review" value={stats.needs_review} label="Needs Review" />
        <StatCard icon={ListTree} theme="not_yet" value={stats.not_yet} label="Not Yet" />
      </div>

      <div className="card" style={{ padding: 16 }}>
        <div style={{ display: "grid", gap: 8 }}>
          {roadmap.map((m, i) => {
            const st = STATUS_STYLE[m.status] || STATUS_STYLE.unassessed;
            return (
              <div key={m.record_id ?? `${m.domain}:${m.milestone}:${i}`} style={{
                borderRadius: 10, border: "1px solid var(--color-border)", padding: "10px 14px",
                background: "var(--color-bg)", display: "flex", alignItems: "center",
                justifyContent: "space-between", gap: 10, flexWrap: "wrap",
              }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text)" }}>{m.milestone}</div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2, textTransform: "capitalize" }}>
                    {m.domain?.replace("_", " ")} · {m.scheduled_label}
                    {m.assessed_date && ` · assessed ${new Date(m.assessed_date).toLocaleDateString("en-IN")}`}
                    {m.recorded_by_name && ` by ${m.recorded_by_name}`}
                    {m.status === "unassessed" && m.timing === "due_now" && " · recommended now"}
                    {m.status === "unassessed" && m.timing === "past_window" && " · past the usual window"}
                  </div>
                  {m.notes && (
                    <div style={{ fontSize: 11.5, color: "var(--color-text)", marginTop: 4, fontStyle: "italic" }}>
                      "{m.notes}"
                    </div>
                  )}
                </div>
                <span style={{
                  fontSize: 10.5, fontWeight: 700, padding: "3px 10px", borderRadius: 10,
                  background: st.bg, color: st.color, whiteSpace: "nowrap", flexShrink: 0,
                }}>
                  {st.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
