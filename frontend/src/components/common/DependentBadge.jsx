/**
 * components/common/DependentBadge.jsx
 * -------------------------------------
 * Small inline tag shown next to a patient's name wherever staff (front
 * desk, nurse, doctor) view a patient list — flags patients registered as
 * a dependent (child/ward/etc. with no mobile/login of their own) so staff
 * know to loop in the guardian for consent, contact, or ID verification.
 *
 * Accepts either a full patient-like object ({ is_dependent, guardian_name,
 * guardian_relation }) via `patient`, or the individual fields directly —
 * whichever the call site already has in scope.
 */
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
