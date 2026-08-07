/**
 * components/common/DoctorCard.jsx
 * ------------------------------------
 * Rich horizontal doctor card used across the patient portal (dashboard
 * search results, hospital doctor listing). Photo + identity on the left,
 * fee + booking CTAs on the right, expandable bio/qualifications below —
 * every field is read straight off the doctor object the backend already
 * returns (org.DoctorProfile via _doctor_card in portal_views.py), nothing
 * here is placeholder/fabricated data.
 */
import { useState } from "react";
import { Building2, ChevronDown, ChevronUp } from "lucide-react";

export default function DoctorCard({ d, hospitalName, hospitalCity, onBook, onViewProfile }) {
  const [expanded, setExpanded] = useState(false);

  const languages = (d.languages || "").split(",").map(s => s.trim()).filter(Boolean);
  const qualifications = (d.qualification || "").split(",").map(s => s.trim()).filter(Boolean);
  const knownForTags = (d.known_for || "").split(",").map(s => s.trim()).filter(Boolean);
  const hospital = hospitalName || d.hospital;
  const city = hospitalCity ?? d.hospital_city;

  return (
    <div
      className="card"
      style={{ padding: 0, overflow: "hidden", cursor: onViewProfile ? "pointer" : "default" }}
      onClick={onViewProfile}
    >
      <div style={{ display: "flex", gap: 16, padding: "18px 20px 14px", flexWrap: "wrap" }}>
        {/* Photo */}
        <div style={{
          width: 84, height: 84, borderRadius: 12, background: "var(--color-primary-light)", flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28, fontWeight: 700,
          color: "var(--color-primary)", overflow: "hidden",
        }}>
          {d.photo
            ? <img src={d.photo} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            : (d.name || "D").replace("Dr. ", "").charAt(0)}
        </div>

        {/* Identity */}
        <div style={{ flex: "1 1 260px", minWidth: 0 }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 18 }}>{d.name}</div>
          {hospital && (
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3, display: "flex", alignItems: "center", gap: 5 }}>
              <Building2 size={12} style={{ flexShrink: 0 }} />
              {hospital}{city ? `, ${city}` : ""}
            </div>
          )}
          <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 6 }}>
            {d.specialisation || "Specialisation not listed"}
            {d.experience_years != null && ` · ${d.experience_years} years experience`}
          </div>
          {languages.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
              {languages.map(l => <span key={l} className="tag-pill">{l}</span>)}
            </div>
          )}
        </div>

        {/* Fee + CTAs */}
        <div style={{ flex: "0 0 auto", textAlign: "right", minWidth: 160 }}>
          {d.consultation_fee ? (
            <>
              <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 22 }}>
                ₹{d.consultation_fee}
              </div>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 10 }}>
                Per consultation
              </div>
            </>
          ) : (
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 10 }}>
              Fee not listed
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <button
              onClick={(e) => { e.stopPropagation(); onBook?.(); }}
              style={{
                padding: "9px 18px", borderRadius: "var(--radius-button)", border: "none",
                background: "var(--color-accent)", color: "#fff", fontWeight: 700, fontSize: 13, cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              Book Appointment
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onViewProfile?.(); }}
              style={{
                padding: "8px 18px", borderRadius: "var(--radius-button)", border: "1.5px solid var(--color-primary)",
                background: "transparent", color: "var(--color-primary)", fontWeight: 700, fontSize: 12, cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              View Profile
            </button>
          </div>
        </div>
      </div>

      {(d.bio || qualifications.length > 0 || knownForTags.length > 0) && (
        <>
          {expanded && (
            <div style={{ padding: "0 20px 16px", display: "grid", gap: 12 }}>
              {d.bio && (
                <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
                  {d.bio}
                </div>
              )}
              {qualifications.length > 0 && (
                <div>
                  <div className="stat-label" style={{ marginBottom: 6 }}>Qualifications</div>
                  <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 3 }}>
                    {qualifications.map(q => (
                      <li key={q} style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}
              {knownForTags.length > 0 && (
                <div>
                  <div className="stat-label" style={{ marginBottom: 6 }}>Known for</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {knownForTags.map(t => <span key={t} className="tag-pill">{t}</span>)}
                  </div>
                </div>
              )}
            </div>
          )}
          <div style={{
            padding: "10px 20px", borderTop: "1px solid var(--color-border)",
          }}>
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded(v => !v); }}
              style={{
                display: "flex", alignItems: "center", gap: 4, background: "none", border: "none", cursor: "pointer",
                fontSize: 12, fontWeight: 700, color: "var(--color-primary)", padding: 0,
              }}
            >
              {expanded ? "View less" : "View more"}
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
