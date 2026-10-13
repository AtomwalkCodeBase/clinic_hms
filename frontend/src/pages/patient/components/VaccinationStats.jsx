// The four counts above the vaccination timeline: completed, upcoming, needs review, and doses given outside.
import { CheckCircle2, Calendar, HelpCircle, Syringe } from "lucide-react";
import StatCard from "./StatCard";

const nextUpcoming = (roadmap) =>
  (roadmap || []).find(item => !item.extra && item.status === "unknown" && item.timing === "upcoming");

export default function VaccinationStats({ vax }) {
  const stats = vax?.stats ?? { completed: 0, upcoming: 0, needs_review: 0, outside: 0 };
  const next = nextUpcoming(vax?.roadmap);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 20 }} className="vax-stats-grid">
      <StatCard icon={CheckCircle2} theme="success" value={stats.completed} label="Completed" subtext="Vaccines taken" />
      <StatCard
        icon={Calendar} theme="upcoming" value={stats.upcoming} label="Upcoming"
        subtext={next ? `Next: ${next.vaccine_name}${next.scheduled_label ? ` · ${next.scheduled_label}` : ""}` : "Nothing due yet"}
      />
      <StatCard icon={HelpCircle} theme="review" value={stats.needs_review} label="Needs Review" subtext="No record available" />
      <StatCard icon={Syringe} theme="outside" value={stats.outside} label="Outside Vaccines" subtext="Added by doctor" />
    </div>
  );
}
