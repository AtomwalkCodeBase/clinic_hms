// Read-only developmental-milestone roadmap for the patient portal: what the doctor has recorded, without the form to record it.
import { CheckCircle2, Calendar, HelpCircle, ListTree } from "lucide-react";
import StatCard from "./StatCard";

const STATUS_STYLE = {
  achieved:   { bg: "#ECFDF5", color: "#047857", label: "Achieved" },
  not_yet:    { bg: "#F3F4F6", color: "#6B7280", label: "Not Yet" },
  concern:    { bg: "#FEF2F2", color: "#B91C1C", label: "Concern — flagged for follow-up" },
  unassessed: { bg: "var(--color-bg)", color: "var(--color-text-muted)", label: "Not Assessed" },
};

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
        <StatCard icon={CheckCircle2} theme="success" value={stats.achieved} label="Achieved" />
        <StatCard icon={Calendar} theme="upcoming" value={stats.upcoming} label="Upcoming" />
        <StatCard icon={HelpCircle} theme="review" value={stats.needs_review} label="Needs Review" />
        <StatCard icon={ListTree} theme="neutral" value={stats.not_yet} label="Not Yet" />
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
