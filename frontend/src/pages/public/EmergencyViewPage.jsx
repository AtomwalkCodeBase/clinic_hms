/**
 * pages/public/EmergencyViewPage.jsx
 * -------------------------------------
 * What opens when a doctor scans a patient's Emergency QR (see
 * pages/patient/EmergencyQRPage.jsx for where the code is generated — and
 * where the patient explicitly confirms sharing this — and
 * apps/patients/emergency_views.py for the backend design reasoning).
 *
 * Deliberately outside AppShell/ProtectedRoute — the person opening this
 * has no Atomwalk login at all, possibly at a hospital that isn't even on
 * this platform. Fetched with publicClient (no Authorization header),
 * mobile-first (this is opened on a phone camera scan). Renders the
 * patient's full shared clinical history — the same shape a consenting
 * cross-hospital doctor sees via the HIE roadmap, just resolved by a
 * token instead of a session — including viewable lab reports, uploaded
 * documents, and vaccination certificates via signed URLs the backend
 * already resolved (no further auth needed to open them).
 *
 * Layout: numbered, colour-coded priority sections (vitals first, then
 * context, then everything else) — every value shown is real data straight
 * off the API response; nothing here is a placeholder or an inferred
 * status. Where the backend doesn't carry a field (e.g. no "is this
 * prescription still active" flag), the section simply doesn't claim one,
 * rather than showing a plausible-looking but fabricated badge.
 */
import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { formatYearsMonths } from "../../utils/age";
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
// badge in the same colour, same visual language throughout.
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
// "why this matters" line, and its content.
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

export default function EmergencyViewPage() {
  const { token } = useParams();
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
      <div style={{ width: "100%", maxWidth: 720 }}>

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
              <div style={{ fontWeight: 800, marginBottom: 1 }}>Read top to bottom</div>
              Vitals and allergies first, then diagnoses and treatment history.
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
          const latestVital = data.vitals?.[0] || null;
          const earlierVitals = data.vitals?.slice(1, 5) || [];
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

            {/* 1 — Vitals */}
            <PriorityCard n={next()} color="red" icon={Activity} title="Current Vitals" hint="Assess immediate condition">
              {!latestVital ? <Empty text="No vitals on record." /> : (
                <>
                  <div style={{ fontSize: 10.5, color: "#999", marginBottom: 8 }}>Latest: {fmtDateTime(latestVital.recorded_at)}</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: earlierVitals.length ? 10 : 0 }}>
                    <StatTile icon={HeartPulse} label="BP" color="red"
                      value={latestVital.bp_systolic && latestVital.bp_diastolic ? `${latestVital.bp_systolic}/${latestVital.bp_diastolic}` : null} unit="mmHg" />
                    <StatTile icon={HeartPulse} label="Pulse" color="orange" value={latestVital.pulse_rate} unit="bpm" />
                    <StatTile icon={Wind} label="SpO2" color="green" value={latestVital.spo2} unit="%" />
                    <StatTile icon={Thermometer} label="Temp" color="orange" value={latestVital.temperature} unit="°F" />
                    <StatTile icon={Droplet} label="Sugar" color="red" value={latestVital.blood_sugar_mgdl} unit="mg/dL" />
                    <StatTile icon={Weight} label="Weight" color="blue" value={latestVital.weight_kg} unit="kg" />
                    <StatTile icon={Ruler} label="Height" color="blue" value={latestVital.height_cm} unit="cm" />
                    <StatTile icon={Ruler} label="Head circ." color="violet" value={latestVital.head_circumference_cm} unit="cm" />
                  </div>
                  {earlierVitals.length > 0 && (
                    <div style={{ display: "grid", gap: 4, paddingTop: 8, borderTop: "1px dashed #eee" }}>
                      <div style={{ fontSize: 10.5, fontWeight: 700, color: "#999", textTransform: "uppercase", letterSpacing: 0.3 }}>Earlier readings</div>
                      {earlierVitals.map((v, i) => (
                        <div key={i} style={{ fontSize: 11.5, color: "#666" }}>
                          <span style={{ color: "#aaa" }}>{fmtDateTime(v.recorded_at)} — </span>
                          {[
                            v.bp_systolic && v.bp_diastolic ? `BP ${v.bp_systolic}/${v.bp_diastolic}` : null,
                            v.pulse_rate ? `Pulse ${v.pulse_rate}` : null,
                            v.spo2 ? `SpO2 ${v.spo2}%` : null,
                            v.temperature ? `Temp ${v.temperature}°` : null,
                            v.blood_sugar_mgdl ? `Sugar ${v.blood_sugar_mgdl}` : null,
                            v.weight_kg ? `Weight ${v.weight_kg}kg` : null,
                          ].filter(Boolean).join(" · ") || "—"}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </PriorityCard>

            {/* 2 / 3 — Diagnoses + Allergies, side by side */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12, marginBottom: 0 }}>
              <PriorityCard n={next()} color="orange" icon={Stethoscope} title="Active Diagnoses" hint="Understand existing conditions"
                count={data.diagnoses.length ? `${data.diagnoses.length} on record` : null}>
                {data.diagnoses.length === 0 ? <Empty text="None on record." /> : (
                  <div style={{ display: "grid", gap: 6 }}>
                    {data.diagnoses.map((d, i) => (
                      <div key={i} style={{ fontSize: 13 }}>
                        {d.description || d.icd10_code}
                        {d.clinical_status && <span style={{ color: "#999", fontSize: 11 }}> · {d.clinical_status}</span>}
                        {d.onset_date && <span style={{ color: "#999", fontSize: 11 }}> · since {fmtDate(d.onset_date)}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </PriorityCard>

              <PriorityCard n={next()} color="green" icon={AlertTriangle} title="Allergies" hint="Check before prescribing">
                {data.allergies.length === 0 ? (
                  <div style={{
                    display: "flex", alignItems: "flex-start", gap: 8, background: "#ECFDF5",
                    border: "1px solid #A7F3D0", borderRadius: 8, padding: "9px 10px", fontSize: 12.5, color: "#065F46",
                  }}>
                    No known allergies on record.
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: 6 }}>
                    {data.allergies.map((a, i) => (
                      <div key={i} style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "8px 10px" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#991b1b" }}>
                          {a.substance} {a.severity && <span style={{ fontWeight: 400, fontSize: 11 }}>({a.severity})</span>}
                        </div>
                        {a.reaction && <div style={{ fontSize: 12, color: "#7f1d1d" }}>{a.reaction}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </PriorityCard>
            </div>

            {/* 4 — Medications */}
            <PriorityCard n={next()} color="blue" icon={Pill} title="Current / Recent Medications" hint="Check recent treatment history"
              count={data.prescriptions.length ? `${data.prescriptions.length} prescription${data.prescriptions.length === 1 ? "" : "s"}` : null}>
              {data.prescriptions.length === 0 ? <Empty text="None on record." /> : (
                <DataTable
                  columns={[
                    { key: "drug", label: "Drug / Item", render: r => <strong>{r.drug_name}</strong> },
                    { key: "dose", label: "Dose", render: r => r.dose ? `${r.dose}${r.unit || ""}` : "—" },
                    { key: "freq", label: "Frequency", render: r => r.frequency || "—" },
                    { key: "prescribed", label: "Prescribed On", render: r => fmtDate(r.prescribed_on) },
                  ]}
                  rows={data.prescriptions.flatMap(rx => rx.items.map(it => ({ ...it, prescribed_on: rx.prescribed_on })))}
                />
              )}
            </PriorityCard>

            {/* 5 — Lab reports */}
            <PriorityCard n={next()} color="purple" icon={FlaskConical} title="Recent Lab Reports" hint="Check for abnormal results"
              count={data.lab_results.length ? `${data.lab_results.length} report${data.lab_results.length === 1 ? "" : "s"}` : null}>
              {data.lab_results.length === 0 ? <Empty text="None on record." /> : (
                <div style={{ display: "grid", gap: 8 }}>
                  {data.lab_results.map((r, i) => (
                    <div key={i} style={{ fontSize: 13, borderTop: i ? "1px solid #f1f1f1" : "none", paddingTop: i ? 8 : 0 }}>
                      <div>
                        <span style={{ fontWeight: 700 }}>{r.test_name}</span>
                        <span style={{ color: "#999", fontSize: 11 }}> · {fmtDate(r.delivered_at)}</span>
                      </div>
                      {r.result_summary && <div style={{ fontSize: 12, color: "#555", marginTop: 2 }}>{r.result_summary}</div>}
                      <FileLink url={r.file_url} label="View report" />
                    </div>
                  ))}
                </div>
              )}
            </PriorityCard>

            {/* 6 — Vaccinations */}
            <PriorityCard n={next()} color="teal" icon={Syringe} title="Vaccinations" hint="Immunization history"
              count={data.vaccinations.length ? `${data.vaccinations.length} on record` : null}>
              {data.vaccinations.length === 0 ? <Empty text="None on record." /> : (
                <div style={{ display: "grid", gap: 6 }}>
                  {data.vaccinations.map((v, i) => (
                    <div key={i} style={{ fontSize: 13 }}>
                      <span style={{ fontWeight: 600 }}>{v.vaccine_name}</span>
                      {v.dose_number ? ` (dose ${v.dose_number})` : ""}
                      <span style={{ color: "#999", fontSize: 11 }}>
                        {" "}· {VACCINE_STATUS_LABEL[v.verification_status] || v.verification_status}
                        {v.administered_date && ` · ${fmtDate(v.administered_date)}`}
                      </span>
                      <div><FileLink url={v.certificate_url} label="View certificate" /></div>
                    </div>
                  ))}
                </div>
              )}
            </PriorityCard>

            {/* 7 — Pediatric context (minor patients only) */}
            {isMinor && (
              <PriorityCard n={next()} color="violet" icon={Baby} title="Pediatric History" hint="Birth history and flagged developmental concerns">
                <div style={{ fontSize: 11, fontWeight: 700, color: "#999", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 6 }}>
                  Birth history
                </div>
                {!data.birth_history ? <Empty text="None on record." /> : (
                  <div style={{ display: "grid", gap: 3, fontSize: 13, marginBottom: 14 }}>
                    {data.birth_history.gestational_age_weeks != null && (
                      <div>Gestational age: <strong>{data.birth_history.gestational_age_weeks} weeks</strong></div>
                    )}
                    {data.birth_history.birth_weight_kg != null && (
                      <div>Birth weight: <strong>{data.birth_history.birth_weight_kg} kg</strong></div>
                    )}
                    {data.birth_history.delivery_mode && (
                      <div>Delivery: <strong>{DELIVERY_MODE_LABEL[data.birth_history.delivery_mode] || data.birth_history.delivery_mode}</strong></div>
                    )}
                    {data.birth_history.multiple_birth && <div>Multiple birth: <strong>{data.birth_history.multiple_birth}</strong></div>}
                    {data.birth_history.nicu_admission && (
                      <div>NICU: <strong>Yes{data.birth_history.nicu_days ? ` — ${data.birth_history.nicu_days} days` : ""}</strong></div>
                    )}
                    {(data.birth_history.apgar_score_1min != null || data.birth_history.apgar_score_5min != null) && (
                      <div>APGAR: <strong>{data.birth_history.apgar_score_1min ?? "—"} / {data.birth_history.apgar_score_5min ?? "—"}</strong></div>
                    )}
                    {data.birth_history.birth_complications && (
                      <div style={{ color: "#b91c1c" }}>Birth complications: {data.birth_history.birth_complications}</div>
                    )}
                    {data.birth_history.congenital_conditions && (
                      <div style={{ color: "#b91c1c" }}>Congenital conditions: {data.birth_history.congenital_conditions}</div>
                    )}
                  </div>
                )}
                <div style={{ fontSize: 11, fontWeight: 700, color: "#999", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 6 }}>
                  Developmental concerns flagged
                </div>
                {!data.milestone_concerns?.length ? <Empty text="None flagged." /> : (
                  <div style={{ display: "grid", gap: 6 }}>
                    {data.milestone_concerns.map((m, i) => (
                      <div key={i} style={{ background: "#fef2f2", border: "1px solid #fecaca", borderRadius: 8, padding: "8px 10px" }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#991b1b" }}>{m.milestone}</div>
                        <div style={{ fontSize: 11, color: "#7f1d1d" }}>
                          {m.domain?.replace("_", " ")}{m.assessed_date && ` · flagged ${fmtDate(m.assessed_date)}`}
                        </div>
                        {m.notes && <div style={{ fontSize: 12, color: "#7f1d1d", marginTop: 2 }}>{m.notes}</div>}
                      </div>
                    ))}
                  </div>
                )}
              </PriorityCard>
            )}

            {/* 8 — Documents */}
            <PriorityCard n={next()} color="slate" icon={FileText} title="Uploaded Documents" hint="Old reports, scans, discharge summaries"
              count={data.documents.length ? `${data.documents.length} file${data.documents.length === 1 ? "" : "s"}` : null}>
              {data.documents.length === 0 ? <Empty text="None on record." /> : (
                <div style={{ display: "grid", gap: 8 }}>
                  {data.documents.map((doc, i) => (
                    <div key={i} style={{ fontSize: 13 }}>
                      <span style={{ fontWeight: 600 }}>{doc.title}</span>
                      <span style={{ color: "#999", fontSize: 11 }}> · {fmtDate(doc.created_at)}</span>
                      <div><FileLink url={doc.file_url} label="View document" /></div>
                    </div>
                  ))}
                </div>
              )}
            </PriorityCard>

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
