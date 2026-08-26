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
 */
import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { publicClient } from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import {
  ShieldAlert, AlertTriangle, Pill, Stethoscope, Phone, User,
  Activity, Syringe, FileText, FlaskConical, ExternalLink,
} from "lucide-react";

function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtDateTime(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Section({ icon: Icon, title, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700, marginBottom: 8, color: "#1B5E43" }}>
        <Icon size={15} /> {title}
      </div>
      {children}
    </div>
  );
}

function FileLink({ url, label = "View file" }) {
  if (!url) return null;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer"
      style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11.5, color: "#1B5E43", fontWeight: 700, marginTop: 4 }}>
      <ExternalLink size={11} /> {label}
    </a>
  );
}

const VACCINE_STATUS_LABEL = {
  verified: "Verified", pending_review: "Pending review", rejected: "Rejected",
  ordered: "Ordered", declined: "Declined",
};

export default function EmergencyViewPage() {
  const { token } = useParams();
  const [state, setState] = useState({ loading: true, data: null, error: null });

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
      padding: "20px 12px", fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      <div style={{ width: "100%", maxWidth: 480 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, color: "#1B5E43" }}>
          <ShieldAlert size={20} />
          <span style={{ fontWeight: 800, fontSize: 16 }}>Emergency Medical Summary</span>
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

        {!loading && data && (
          <div style={{ background: "#fff", borderRadius: 12, padding: 20, boxShadow: "0 1px 3px rgba(0,0,0,0.08)" }}>
            <div style={{ borderBottom: "1px solid #eee", paddingBottom: 14, marginBottom: 16 }}>
              <div style={{ fontSize: 19, fontWeight: 800 }}>{data.full_name}</div>
              <div style={{ fontSize: 13, color: "#666", marginTop: 2 }}>
                {data.age_years != null ? `${data.age_years} yrs` : "Age unknown"}
                {data.gender ? ` · ${data.gender}` : ""}
                {data.blood_group ? ` · Blood group ${data.blood_group}` : ""}
              </div>
            </div>

            <Section icon={AlertTriangle} title="Allergies">
              {data.allergies.length === 0 ? (
                <div style={{ fontSize: 13, color: "#999" }}>No known allergies on record.</div>
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
            </Section>

            <Section icon={Stethoscope} title="Diagnoses">
              {data.diagnoses.length === 0 ? (
                <div style={{ fontSize: 13, color: "#999" }}>None on record.</div>
              ) : (
                <div style={{ display: "grid", gap: 4 }}>
                  {data.diagnoses.map((d, i) => (
                    <div key={i} style={{ fontSize: 13 }}>
                      {d.description || d.icd10_code}
                      {d.clinical_status && <span style={{ color: "#999", fontSize: 11.5 }}> · {d.clinical_status}</span>}
                      {d.onset_date && <span style={{ color: "#999", fontSize: 11.5 }}> · since {fmtDate(d.onset_date)}</span>}
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section icon={Activity} title="Recent vitals">
              {data.vitals.length === 0 ? (
                <div style={{ fontSize: 13, color: "#999" }}>None on record.</div>
              ) : (
                <div style={{ display: "grid", gap: 6 }}>
                  {data.vitals.slice(0, 5).map((v, i) => (
                    <div key={i} style={{ fontSize: 12.5 }}>
                      <span style={{ color: "#999", fontSize: 11 }}>{fmtDateTime(v.recorded_at)} — </span>
                      {[
                        v.bp_systolic && v.bp_diastolic ? `BP ${v.bp_systolic}/${v.bp_diastolic}` : null,
                        v.pulse_rate ? `Pulse ${v.pulse_rate}` : null,
                        v.spo2 ? `SpO2 ${v.spo2}%` : null,
                        v.temperature ? `Temp ${v.temperature}°` : null,
                        v.blood_sugar_mgdl ? `Sugar ${v.blood_sugar_mgdl}` : null,
                      ].filter(Boolean).join(" · ") || "—"}
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section icon={Pill} title="Prescriptions">
              {data.prescriptions.length === 0 ? (
                <div style={{ fontSize: 13, color: "#999" }}>None on record.</div>
              ) : (
                <div style={{ display: "grid", gap: 10 }}>
                  {data.prescriptions.map((rx, i) => (
                    <div key={i}>
                      <div style={{ fontSize: 11.5, color: "#999", marginBottom: 4 }}>
                        Prescribed {fmtDate(rx.prescribed_on)}
                      </div>
                      <div style={{ display: "grid", gap: 3 }}>
                        {rx.items.map((it, j) => (
                          <div key={j} style={{ fontSize: 13 }}>
                            {it.drug_name}
                            {it.dose && ` — ${it.dose}${it.unit || ""}`}
                            {it.frequency && `, ${it.frequency}`}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section icon={Syringe} title="Vaccinations">
              {data.vaccinations.length === 0 ? (
                <div style={{ fontSize: 13, color: "#999" }}>None on record.</div>
              ) : (
                <div style={{ display: "grid", gap: 6 }}>
                  {data.vaccinations.map((v, i) => (
                    <div key={i} style={{ fontSize: 13 }}>
                      <span style={{ fontWeight: 600 }}>{v.vaccine_name}</span>
                      {v.dose_number ? ` (dose ${v.dose_number})` : ""}
                      <span style={{ color: "#999", fontSize: 11.5 }}>
                        {" "}· {VACCINE_STATUS_LABEL[v.verification_status] || v.verification_status}
                        {v.administered_date && ` · ${fmtDate(v.administered_date)}`}
                      </span>
                      <div><FileLink url={v.certificate_url} label="View certificate" /></div>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section icon={FlaskConical} title="Lab reports">
              {data.lab_results.length === 0 ? (
                <div style={{ fontSize: 13, color: "#999" }}>None on record.</div>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {data.lab_results.map((r, i) => (
                    <div key={i} style={{ fontSize: 13 }}>
                      <span style={{ fontWeight: 600 }}>{r.test_name}</span>
                      <span style={{ color: "#999", fontSize: 11.5 }}> · {fmtDate(r.delivered_at)}</span>
                      {r.result_summary && <div style={{ fontSize: 12, color: "#555" }}>{r.result_summary}</div>}
                      <div><FileLink url={r.file_url} label="View report" /></div>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section icon={FileText} title="Documents">
              {data.documents.length === 0 ? (
                <div style={{ fontSize: 13, color: "#999" }}>None on record.</div>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {data.documents.map((doc, i) => (
                    <div key={i} style={{ fontSize: 13 }}>
                      <span style={{ fontWeight: 600 }}>{doc.title}</span>
                      <span style={{ color: "#999", fontSize: 11.5 }}> · {fmtDate(doc.created_at)}</span>
                      <div><FileLink url={doc.file_url} label="View document" /></div>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section icon={Phone} title="Emergency contact">
              {!data.emergency_contact ? (
                <div style={{ fontSize: 13, color: "#999" }}>Not provided.</div>
              ) : (
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
            </Section>

            <div style={{ fontSize: 11, color: "#aaa", textAlign: "center", marginTop: 4 }}>
              This is a time-limited summary shared by the patient for emergency care only.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
