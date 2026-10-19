/** components/common/DependentBadge.jsx */
import { Users2 } from "lucide-react";

export default function DependentBadge({ patient, isDependent, guardianName, guardianRelation, style }) {
  const dependent = isDependent ?? patient?.is_dependent;
  if (!dependent) return null;
  const gName = guardianName ?? patient?.guardian_name;
  const gRel  = guardianRelation ?? patient?.guardian_relation;

  return (
    <span
      title={gName ? `Guardian: ${gName}${gRel ? ` (${gRel})` : ""}` : "Dependent patient"}
      style={{
        display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 700,
        padding: "2px 8px", borderRadius: 20, background: "var(--color-accent-light)", color: "var(--color-accent)",
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      <Users2 size={10} />
      {gName ? `Dependent · ${gName}${gRel ? ` (${gRel})` : ""}` : "Dependent"}
    </span>
  );
}
