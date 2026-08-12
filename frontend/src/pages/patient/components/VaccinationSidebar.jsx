/**
 * pages/patient/components/VaccinationSidebar.jsx
 * ---------------------------------------------------
 * Two exported pieces, split so the page can lay them out separately
 * (RecordsPage.jsx puts RecommendedByDoctor next to the Growth &
 * Vaccination Chart, and the rest of this sidebar next to the Vaccination
 * Timeline below it — both are the same width as whatever they sit beside
 * instead of the old always-full-width single column):
 *   - RecommendedByDoctor (named export) — gold/amber gradient header
 *   - VaccinationSidebar  (default export) — Update Your Records + Helpful
 *     Tips, green accent + warm neutral headers
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Stethoscope, Camera, FileText, Calendar, Lightbulb, X, Upload, ArrowRight } from "lucide-react";
import ROUTES from "../../../config/routes.config";

function orderedVaccines(roadmap) {
  return (roadmap || []).filter(v => v.status === "ordered");
}

// Section card with a coloured gradient header bar
function SectionCard({ headerBg, headerIcon, headerIconBg, title, children, style = {} }) {
  return (
    <div style={{
      borderRadius: 16, overflow: "hidden",
      border: "1px solid var(--color-border)",
      boxShadow: "0 2px 12px rgba(15,61,43,0.07)",
      ...style,
    }}>
      {/* Gradient header */}
      <div style={{
        background: headerBg,
        padding: "12px 16px",
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <div style={{
          width: 30, height: 30, borderRadius: 9,
          background: headerIconBg,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 2px 6px rgba(0,0,0,0.2)",
        }}>
          {headerIcon}
        </div>
        <span style={{
          fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14,
          color: "#F4F1E8",
        }}>
          {title}
        </span>
      </div>
      {/* Body */}
      <div style={{ background: "var(--color-surface)", padding: "16px" }}>
        {children}
      </div>
    </div>
  );
}

export function RecommendedByDoctor({ roadmap }) {
  const navigate = useNavigate();
  const ordered = orderedVaccines(roadmap);

  return (
      <SectionCard
        headerBg="linear-gradient(135deg, #7A5418 0%, #B07C24 100%)"
        headerIconBg="rgba(255,255,255,0.15)"
        headerIcon={<Stethoscope size={15} color="#FFF8E1" />}
        title="Recommended by Doctor"
      >
        {ordered.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", padding: "4px 0" }}>
            No doctor-recommended vaccines right now.
          </div>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {ordered.map((v, idx) => {
              const dueSoon = v.due_date && (new Date(v.due_date) - new Date()) / 86400000 <= 30;
              const docInitial = (v.verified_by_name || "D").replace("Dr. ", "")[0].toUpperCase();
              return (
                <div key={idx} style={{
                  borderRadius: 12, overflow: "hidden",
                  border: "1px solid #EDD49A",
                  background: "linear-gradient(135deg, #FFFDF5 0%, #FEF9EC 100%)",
                }}>
                  {/* Vaccine name row */}
                  <div style={{
                    padding: "10px 14px 8px",
                    borderBottom: "1px solid #F0E4C0",
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                  }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "#4A3010" }}>
                      {v.vaccine_name}
                    </span>
                    {dueSoon && (
                      <span style={{
                        fontSize: 10, fontWeight: 700, padding: "3px 9px", borderRadius: 10,
                        background: "#F9F0DC", color: "#B45309", border: "1px solid #EDD49A",
                      }}>Due Soon</span>
                    )}
                  </div>

                  {/* Doctor + info */}
                  <div style={{ padding: "10px 14px" }}>
                    {v.verified_by_name && (
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                        <div style={{
                          width: 26, height: 26, borderRadius: "50%",
                          background: "linear-gradient(135deg, #2C7A5A 0%, #1B5E43 100%)",
                          color: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: 11, fontWeight: 700, flexShrink: 0,
                          border: "2px solid rgba(27,94,67,0.25)",
                        }}>
                          {docInitial}
                        </div>
                        <div>
                          <div style={{ fontSize: 10, color: "#9B7B40", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3 }}>
                            Recommended by
                          </div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: "#4A3010" }}>
                            {v.verified_by_name}
                          </div>
                        </div>
                      </div>
                    )}

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
                      {v.due_date && (
                        <div style={{
                          background: "#FFF8E8", borderRadius: 8, padding: "7px 10px",
                          border: "1px solid #F0E4C0",
                        }}>
                          <div style={{ fontSize: 9, color: "#9B7B40", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 2 }}>
                            Due date
                          </div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: "#4A3010" }}>
                            {new Date(v.due_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                          </div>
                        </div>
                      )}
                      {v.reason && (
                        <div style={{
                          background: "#FFF8E8", borderRadius: 8, padding: "7px 10px",
                          border: "1px solid #F0E4C0",
                        }}>
                          <div style={{ fontSize: 9, color: "#9B7B40", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 2 }}>
                            Reason
                          </div>
                          <div style={{ fontSize: 12, color: "#7A5418" }}>{v.reason}</div>
                        </div>
                      )}
                    </div>

                    <button
                      onClick={() => navigate(ROUTES.PATIENT.HOSPITALS)}
                      style={{
                        width: "100%", padding: "8px", fontSize: 12, fontWeight: 700,
                        background: "linear-gradient(135deg, #B07C24 0%, #7A5418 100%)",
                        color: "#fff", border: "none", borderRadius: 9, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                        boxShadow: "0 3px 8px rgba(176,124,36,0.3)",
                      }}
                    >
                      <Calendar size={13} /> Book Appointment
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </SectionCard>
  );
}

export default function VaccinationSidebar({ patientAwpid, onOpenUpload }) {
  const navigate = useNavigate();
  const [bannerDismissed, setBannerDismissed] = useState(false);

  return (
    <div style={{ display: "grid", gap: 16, alignContent: "start" }}>

      {/* ── Update Your Records ───────────────────────────────────── */}
      <SectionCard
        headerBg="linear-gradient(135deg, #1B5E43 0%, #123828 100%)"
        headerIconBg="rgba(255,255,255,0.12)"
        headerIcon={<Upload size={14} color="#C9A24B" />}
        title="Update Your Records"
      >
        {!bannerDismissed && (
          <div style={{
            background: "linear-gradient(135deg, #E9F1EC 0%, #F4F1E8 100%)",
            border: "1px solid var(--color-success-light)",
            borderRadius: 10, padding: "10px 12px", marginBottom: 14,
            display: "flex", alignItems: "flex-start", gap: 8,
          }}>
            <div style={{ flex: 1, fontSize: 11, color: "var(--color-primary)", lineHeight: 1.5 }}>
              Upload your vaccination card — we'll extract the details automatically.
            </div>
            <button
              onClick={() => setBannerDismissed(true)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", flexShrink: 0, padding: 0 }}
            >
              <X size={13} />
            </button>
          </div>
        )}

        {/* Upload Card */}
        <button
          onClick={() => onOpenUpload("")}
          style={{
            width: "100%", padding: "10px", fontSize: 12, fontWeight: 700,
            background: "var(--color-primary)", color: "#fff",
            border: "none", borderRadius: 10, cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
            boxShadow: "0 3px 8px rgba(27,94,67,0.25)",
            marginBottom: 12,
          }}
        >
          <Camera size={14} /> Upload Card
        </button>

        {/* OR divider */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
          <div style={{ flex: 1, height: 1, background: "var(--color-border)" }} />
          <span style={{ fontSize: 10, color: "var(--color-text-muted)", fontWeight: 700, letterSpacing: 1 }}>OR</span>
          <div style={{ flex: 1, height: 1, background: "var(--color-border)" }} />
        </div>

        {/* Enter manually */}
        <div style={{
          background: "var(--color-bg)", borderRadius: 10, padding: "12px",
          border: "1px solid var(--color-border)", marginBottom: 10,
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)", marginBottom: 2 }}>
            Enter records manually
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 10, lineHeight: 1.4 }}>
            Add vaccine name, date &amp; hospital.
          </div>
          <button
            onClick={() => onOpenUpload("")}
            style={{
              width: "100%", padding: "8px", fontSize: 12, fontWeight: 600,
              background: "transparent", color: "var(--color-primary)",
              border: "1.5px solid var(--color-primary)", borderRadius: 8, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            }}
          >
            <FileText size={13} /> Enter Manually
          </button>
        </div>

        {/* Book consultation */}
        <div style={{
          background: "var(--color-bg)", borderRadius: 10, padding: "12px",
          border: "1px solid var(--color-border)",
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)", marginBottom: 2 }}>
            Discuss with Doctor
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 10, lineHeight: 1.4 }}>
            Not sure what's needed?
          </div>
          <button
            onClick={() => navigate(ROUTES.PATIENT.HOSPITALS)}
            style={{
              width: "100%", padding: "8px", fontSize: 12, fontWeight: 600,
              background: "transparent", color: "var(--color-primary)",
              border: "1.5px solid var(--color-primary)", borderRadius: 8, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            }}
          >
            <Calendar size={13} /> Book Consultation
          </button>
        </div>
      </SectionCard>

      {/* ── Helpful Tips ─────────────────────────────────────────── */}
      <SectionCard
        headerBg="linear-gradient(135deg, #4A3010 0%, #7A5418 100%)"
        headerIconBg="rgba(255,255,255,0.12)"
        headerIcon={<Lightbulb size={14} color="#C9A24B" />}
        title="Helpful Tips"
      >
        <div style={{ display: "grid", gap: 10 }}>
          {[
            "Keep your child's vaccination card safe and updated.",
            "Timely vaccines protect your child from preventable diseases.",
          ].map((tip, i) => (
            <div key={i} style={{
              display: "flex", gap: 10, alignItems: "flex-start",
              background: "linear-gradient(135deg, #FFF8E8 0%, #FFFDF5 100%)",
              borderRadius: 10, padding: "9px 12px",
              border: "1px solid #F0E4C0",
            }}>
              <div style={{
                width: 20, height: 20, borderRadius: "50%", flexShrink: 0,
                background: "#B07C24", color: "#fff",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 10, fontWeight: 700, marginTop: 1,
              }}>
                {i + 1}
              </div>
              <span style={{ fontSize: 12, color: "#4A3010", lineHeight: 1.5 }}>{tip}</span>
            </div>
          ))}
        </div>
        <button
          style={{
            background: "none", border: "none", cursor: "pointer", padding: 0,
            fontSize: 12, color: "var(--color-primary)", fontWeight: 700,
            marginTop: 12, display: "flex", alignItems: "center", gap: 4,
          }}
        >
          Learn more <ArrowRight size={12} />
        </button>
      </SectionCard>
    </div>
  );
}
