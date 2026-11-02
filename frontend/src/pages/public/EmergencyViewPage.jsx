/** pages/public/EmergencyViewPage.jsx */
import { useState, useEffect, useMemo } from "react";
import { useParams } from "react-router-dom";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { formatYearsMonths } from "../../utils/age";
import HealthJourney from "../../components/healthJourneyDoctor/HealthJourney";
import DoctorInsights from "../../components/healthJourneyDoctor/DoctorInsights";
import {
  ShieldAlert, AlertTriangle, Pill, Stethoscope, Phone, User,
  Activity, Syringe, FileText, FlaskConical, ExternalLink, Baby,
  HeartPulse, Wind, Thermometer, Droplet, Ruler, Weight, Info, Clock,
} from "lucide-react";

function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtDateTime(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function FileLink({ url, label = "View file" }) {
  if (!url) return null;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer"
      style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11.5, color: "#1B5E43", fontWeight: 700 }}>
      <ExternalLink size={11} /> {label}
    </a>
  );
}

const VACCINE_STATUS_LABEL = {
  verified: "Verified", pending_review: "Pending review", rejected: "Rejected",
  ordered: "Ordered", declined: "Declined",
};

const DELIVERY_MODE_LABEL = {
  normal: "Normal vaginal delivery", c_section: "C-section",
  assisted: "Assisted (forceps/vacuum)", unknown: "Unknown",
};

// Colour identity per priority section — a left accent bar + a numbered
const THEME = {
  red:    { border: "#DC2626", badgeBg: "#DC2626", chipBg: "#FEF2F2", chipBorder: "#FECACA", text: "#991B1B" },
  orange: { border: "#D97706", badgeBg: "#D97706", chipBg: "#FFFBEB", chipBorder: "#FDE68A", text: "#92400E" },
  green:  { border: "#059669", badgeBg: "#059669", chipBg: "#ECFDF5", chipBorder: "#A7F3D0", text: "#065F46" },
  blue:   { border: "#2563EB", badgeBg: "#2563EB", chipBg: "#EFF6FF", chipBorder: "#BFDBFE", text: "#1E40AF" },
  purple: { border: "#7C3AED", badgeBg: "#7C3AED", chipBg: "#F5F3FF", chipBorder: "#DDD6FE", text: "#5B21B6" },
  teal:   { border: "#0D9488", badgeBg: "#0D9488", chipBg: "#F0FDFA", chipBorder: "#99F6E4", text: "#115E59" },
  violet: { border: "#6B3FA0", badgeBg: "#6B3FA0", chipBg: "#F1E9FA", chipBorder: "#DDC9F0", text: "#4A2872" },
  slate:  { border: "#475569", badgeBg: "#475569", chipBg: "#F8FAFC", chipBorder: "#E2E8F0", text: "#334155" },
};

// One numbered priority card — colour, step number, icon+title, a short
function PriorityCard({ n, color, icon: Icon, title, hint, count, children }) {
  const t = THEME[color];
  return (
    <div style={{
      background: "#fff", borderRadius: 12, borderLeft: `4px solid ${t.border}`,
      boxShadow: "0 1px 3px rgba(0,0,0,0.06)", padding: "14px 16px", marginBottom: 12,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
          <span style={{
            flexShrink: 0, width: 22, height: 22, borderRadius: "50%", background: t.badgeBg, color: "#fff",
            fontSize: 11.5, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center",
          }}>{n}</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13.5, fontWeight: 800, color: "#111" }}>
              <Icon size={14} color={t.border} /> {title}
            </div>
            {hint && <div style={{ fontSize: 11, color: "#888", marginTop: 1 }}>{hint}</div>}
          </div>
        </div>
        {count != null && (
          <span style={{
            flexShrink: 0, fontSize: 10.5, fontWeight: 700, padding: "2px 9px", borderRadius: 20,
            background: t.chipBg, color: t.text, border: `1px solid ${t.chipBorder}`, whiteSpace: "nowrap",
          }}>{count}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function Empty({ text }) {
  return <div style={{ fontSize: 12.5, color: "#999" }}>{text}</div>;
}

function StatTile({ icon: Icon, label, value, unit, color }) {
  if (value == null || value === "") return null;
  const t = THEME[color];
  return (
    <div style={{
      background: t.chipBg, border: `1px solid ${t.chipBorder}`, borderRadius: 10,
      padding: "10px 12px", minWidth: 90, flex: "1 1 90px",
    }}>
      <Icon size={14} color={t.border} style={{ marginBottom: 4 }} />
      <div style={{ fontSize: 17, fontWeight: 800, color: "#111" }}>
        {value}{unit && <span style={{ fontSize: 11, fontWeight: 600, color: "#666" }}> {unit}</span>}
      </div>
      <div style={{ fontSize: 10, color: "#888", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3 }}>{label}</div>
    </div>
  );
}

// Simple two-column responsive table for a list of plain-object rows.
function DataTable({ columns, rows }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead>
          <tr>
            {columns.map(c => (
              <th key={c.key} style={{
                textAlign: "left", padding: "0 8px 6px 0", fontSize: 10.5, fontWeight: 700,
                color: "#999", textTransform: "uppercase", letterSpacing: 0.3, whiteSpace: "nowrap",
              }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ borderTop: "1px solid #f1f1f1" }}>
              {columns.map(c => (
                <td key={c.key} style={{ padding: "7px 8px 7px 0", verticalAlign: "top" }}>
                  {c.render ? c.render(row) : (row[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// The health journey asks for /peds/patients/<id>/<part>/ with a signed-in client. Here the emergency code takes the place of the id and the
// public client is used: each call is sent to the code's own read-only endpoint, and anything that would change data is refused.
function emergencyHttp(token) {
  const refuse = () => Promise.reject({ response: { data: { detail: "Not available with an emergency code." } }, message: "Not available with an emergency code." });
  return {
    get: (url, config) => publicClient.get(url.replace(/\/peds\/patients\/[^/]+\//, `/emergency/${token}/`), config),
    post: refuse, put: refuse, patch: refuse, delete: refuse,
  };
}

const DAY_MS = 24 * 60 * 60 * 1000;
function daysAgo(d) {
  if (!d) return "";
  const n = Math.floor((Date.now() - new Date(d).getTime()) / DAY_MS);
  return n <= 0 ? "today" : n === 1 ? "yesterday" : `${n} days ago`;
}

export default function EmergencyViewPage() {
  const { token } = useParams();
  const http = useMemo(() => emergencyHttp(token), [token]);
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [loadedAt] = useState(() => new Date());

  useEffect(() => {
    let cancelled = false;
    publicClient.get(API_ENDPOINTS.EMERGENCY.SUMMARY(token))
      .then(({ data: res }) => { if (!cancelled) setState({ loading: false, data: res.data, error: null }); })
      .catch((err) => { if (!cancelled) setState({ loading: false, data: null, error: err.message || "This code is invalid or has expired." }); });
    return () => { cancelled = true; };
  }, [token]);

  const { loading, data, error } = state;

  return (
    <div style={{
      minHeight: "100vh", background: "#f4f6f5", display: "flex", justifyContent: "center",
      padding: "16px 12px 32px", fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      <div style={{ width: "100%", maxWidth: 1600 }}>

        {/* ── Header ─────────────────────────────────────────────── */}
        <div style={{
          display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12,
          flexWrap: "wrap", marginBottom: 14,
        }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
            <span style={{
              width: 36, height: 36, borderRadius: 10, background: "#ECFDF5", color: "#1B5E43",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <ShieldAlert size={19} />
            </span>
            <div>
              <div style={{ fontWeight: 800, fontSize: 17, color: "#111" }}>Emergency Medical Summary</div>
              <div style={{ fontSize: 11.5, color: "#888" }}>Critical information at a glance for emergency care</div>
            </div>
          </div>
          {!loading && data && (
            <div style={{
              background: "#ECFDF5", border: "1px solid #A7F3D0", borderRadius: 10, padding: "8px 12px",
              fontSize: 11, color: "#065F46", maxWidth: 260,
            }}>
              <div style={{ fontWeight: 800, marginBottom: 1 }}>Health journey below</div>
              Illnesses, hospital stays, vaccines and growth over time.
            </div>
          )}
        </div>

        {loading && (
          <div style={{ background: "#fff", borderRadius: 12, padding: 30, textAlign: "center", color: "#666", fontSize: 13 }}>
            Loading…
          </div>
        )}

        {!loading && error && (
          <div style={{ background: "#fff", borderRadius: 12, padding: 24, textAlign: "center" }}>
            <AlertTriangle size={28} color="#b91c1c" style={{ marginBottom: 10 }} />
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>Can't show this summary</div>
            <div style={{ fontSize: 13, color: "#666" }}>{error}</div>
          </div>
        )}

        {!loading && data && (() => {
          const isMinor = data.age_years != null && data.age_years < 18;
          let step = 0;
          const next = () => ++step;

          return (
          <>
            {/* ── Patient strip ──────────────────────────────────── */}
            <div style={{
              background: "#fff", borderRadius: 12, boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
              padding: "14px 16px", marginBottom: 14, display: "flex", alignItems: "center",
              gap: 12, flexWrap: "wrap",
            }}>
              <span style={{
                width: 44, height: 44, borderRadius: "50%", background: "#F1F5F9", color: "#64748B",
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              }}>
                <User size={22} />
              </span>
              <div style={{ flex: 1, minWidth: 160 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <div style={{ fontSize: 17, fontWeight: 800, color: "#111" }}>{data.full_name}</div>
                  {isMinor && (
                    <span style={{
                      display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10.5, fontWeight: 700,
                      padding: "2px 8px", borderRadius: 10, background: "#EDE9FE", color: "#6B3FA0",
                    }}>
                      <Baby size={11} /> Pediatric patient
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12.5, color: "#666", marginTop: 2 }}>
                  {data.age_years != null ? (formatYearsMonths(data.age_years, data.age_months) || `${data.age_years} yrs`) : "Age unknown"}
                  {data.gender ? ` · ${data.gender}` : ""}
                  {data.blood_group ? ` · Blood group ${data.blood_group}` : ""}
                </div>
              </div>
              <div style={{ fontSize: 10.5, color: "#aaa", display: "flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
                <Clock size={11} /> Generated {fmtDateTime(loadedAt)}
              </div>
            </div>

            {/* Health journey: the same timeline, vaccine record and growth the patient and their doctors see, read through the emergency code */}
            <div style={{ marginBottom: 14 }}>
              <HealthJourney
                http={http}
                children={[{ id: token, name: data.full_name }]}
                view="doctor"
                initialPeriod="all"
                canAddVaccine={false}
                canReview={false}
                onOpenDocument={(id) => {
                  const doc = (data.documents || []).find((d) => d.medical_document_id === id);
                  if (doc?.file_url) window.open(doc.file_url, "_blank", "noopener");
                }}
                clinicalExtra={<DoctorInsights http={http} awpid={token} onOpenDocument={(id) => {
                  const doc = (data.documents || []).find((d) => d.medical_document_id === id);
                  if (doc?.file_url) window.open(doc.file_url, "_blank", "noopener");
                }} />}
              />
            </div>

            {/* Emergency contact — utility footer card, not part of the numbered clinical flow */}
            <div style={{
              background: "#fff", borderRadius: 12, boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
              padding: "14px 16px", marginBottom: 14,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 800, color: "#111", marginBottom: 8 }}>
                <Phone size={13} color="#475569" /> Emergency Contact
              </div>
              {!data.emergency_contact ? <Empty text="Not provided." /> : (
                <div style={{ fontSize: 13 }}>
                  <div style={{ fontWeight: 600 }}>
                    <User size={12} style={{ marginRight: 4, verticalAlign: -1 }} />
                    {data.emergency_contact.name} <span style={{ color: "#999", fontWeight: 400 }}>({data.emergency_contact.relation})</span>
                  </div>
                  {data.emergency_contact.phone && (
                    <a href={`tel:${data.emergency_contact.phone}`} style={{ color: "#1B5E43", fontWeight: 700 }}>
                      {data.emergency_contact.phone}
                    </a>
                  )}
                </div>
              )}
            </div>

            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 5,
              fontSize: 10.5, color: "#aaa", textAlign: "center", padding: "4px 0",
            }}>
              <Info size={11} /> This is a time-limited summary shared by the patient for emergency use only — refer to full records for complete history.
            </div>
          </>
          );
        })()}
      </div>
    </div>
  );
}
