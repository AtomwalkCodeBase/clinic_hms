/**
 * pages/patient/components/HealthSummaryCard.jsx
 * -----------------------------------------------
 * Rich hero header for the Health Journey page — gradient dark-green
 * background (matching the app sidebar), prominent avatar, patient
 * identity row, and a dismissible "add records" nudge banner below.
 */
import { useState } from "react";
import { X, Building2, CalendarDays, Plus } from "lucide-react";

function ageFromYears(ageYears) {
  if (ageYears == null) return null;
  return `${ageYears} yr${ageYears === 1 ? "" : "s"}`;
}

const GENDER_LABEL = { M: "Male", F: "Female", O: "Other" };

export default function HealthSummaryCard({
  patientAwpid, displayName, photo, gender,
  summary, summaryLoading, summaryError,
  growth, vax,
  onAddRecords,
}) {
  const [bannerDismissed, setBannerDismissed] = useState(false);

  if (summaryLoading) {
    return (
      <div style={{
        borderRadius: 20, marginBottom: 20, overflow: "hidden",
        background: "linear-gradient(135deg, #1B5E43 0%, #123828 100%)",
        padding: "28px 28px 24px", color: "#8FA89A", fontSize: 13,
      }}>
        Loading patient profile…
      </div>
    );
  }

  if (summaryError && !summary) {
    return (
      <div style={{
        borderRadius: 20, marginBottom: 20, overflow: "hidden",
        background: "linear-gradient(135deg, #1B5E43 0%, #123828 100%)",
        padding: "28px 28px 24px", color: "#8FA89A", fontSize: 13,
      }}>
        Could not load patient profile right now.
      </div>
    );
  }

  const name         = displayName || summary?.patient_name || null;
  const ageLabel     = ageFromYears(growth?.age_years ?? null);
  const genderLabel  = gender ? GENDER_LABEL[gender] || null : null;
  const initial      = (name || "?")[0].toUpperCase();
  const hospitalName = summary?.last_hospital || null;
  const lastVisitDate = summary?.last_visit
    ? new Date(summary.last_visit).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : null;

  const ageYears = growth?.age_years ?? null;
  const isAdult  = ageYears !== null && ageYears >= 18;
  // Vaccination nudge banner is only relevant for children under 18
  const noVaxHistory = !isAdult && (vax ? (vax.total_count > 0 && vax.completed_count === 0) : true);

  return (
    <div style={{ borderRadius: 20, marginBottom: 20, overflow: "hidden", boxShadow: "0 12px 32px rgba(15,61,43,0.22)" }}>
      {/* ── Dark gradient hero section ─────────────────────────────── */}
      <div style={{
        background: "linear-gradient(135deg, #1B5E43 0%, #123828 100%)",
        padding: "24px 28px 22px",
        position: "relative",
        overflow: "hidden",
      }}>
        {/* subtle radial glow */}
        <div style={{
          position: "absolute", top: -40, right: -40,
          width: 200, height: 200, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(201,162,75,0.12) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />

        <div style={{ display: "flex", alignItems: "center", gap: 20, position: "relative" }}>
          {/* Avatar */}
          <div style={{
            width: 72, height: 72, borderRadius: "50%", flexShrink: 0,
            overflow: "hidden", position: "relative",
            border: "3px solid rgba(201,162,75,0.55)",
            boxShadow: "0 0 0 4px rgba(201,162,75,0.15), 0 8px 20px rgba(0,0,0,0.3)",
            background: "linear-gradient(135deg, #2C7A5A 0%, #1B5E43 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#F4F1E8", fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 28,
          }}>
            {photo
              ? <img src={photo} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              : initial}
          </div>

          {/* Patient info */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 22,
              color: "#F4F1E8", letterSpacing: "-0.01em", lineHeight: 1.2,
            }}>
              {name ?? "—"}
            </div>
            <div style={{ fontSize: 13, color: "#8FA89A", marginTop: 5, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              {[ageLabel, genderLabel].filter(Boolean).map((t, i) => (
                <span key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  {i > 0 && <span style={{ opacity: 0.4 }}>•</span>}
                  {t}
                </span>
              ))}
            </div>
            {hospitalName && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6 }}>
                <Building2 size={12} style={{ color: "#C9A24B", flexShrink: 0 }} />
                <span style={{ fontSize: 12, color: "#C9A24B", fontWeight: 500 }}>{hospitalName}</span>
              </div>
            )}
            {lastVisitDate && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                <CalendarDays size={12} style={{ color: "#8FA89A", flexShrink: 0 }} />
                <span style={{ fontSize: 12, color: "#8FA89A" }}>Last visit: {lastVisitDate}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Nudge banner ───────────────────────────────────────────── */}
      {noVaxHistory && !bannerDismissed && (
        <div style={{
          background: "#FFFDF5",
          borderTop: "1px solid rgba(201,162,75,0.25)",
          padding: "14px 24px",
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap",
        }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#1A1F1B", marginBottom: 2 }}>
              Vaccination history not complete
            </div>
            <div style={{ fontSize: 12, color: "#8A9088" }}>
              Add previous records to get a personalised recommendation.
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
            <button
              onClick={onAddRecords}
              style={{
                background: "var(--color-primary)", color: "#fff",
                border: "none", borderRadius: 10, padding: "7px 16px",
                fontSize: 12, fontWeight: 600, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 6,
              }}
            >
              <Plus size={13} /> Add Records
            </button>
            <button
              onClick={() => setBannerDismissed(true)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#8A9088", display: "flex", padding: 2 }}
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
