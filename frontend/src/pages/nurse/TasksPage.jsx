/** pages/nurse/TasksPage.jsx */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { Syringe, FlaskConical, Paperclip } from "lucide-react";
import { dataUrlToBlob, openDataUrlInNewTab } from "../../utils/fileViewer";
import { LAB_STATUS_BADGE } from "../../constants/badges";
import { fileToDataUrl } from "../../utils/files";
import { todayLocal } from "../../utils/dates";

const TODAY = todayLocal();


const STATUS_BADGE = {
  in_progress: "badge--info",
  done:        "badge--success",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
};


// ─── Vaccinations due today:
function VaccinationsForPatient({ patientPk }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data, refetch } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.VACCINATIONS(patientPk) : null, { skip: !patientPk }
  );
  const [administeringKey, setAdministeringKey] = useState(null);
  // Optional certificate/photo to attach when administering — keyed by the
  const [fileByKey, setFileByKey] = useState({});
  const roadmap = data?.roadmap || [];
  const actionable = roadmap.filter(
    v => v.status === "ordered" || (v.status === "unknown" && v.timing === "due_now")
  );
  if (!patientPk || actionable.length === 0) return null;

  async function administer(v) {
    const key = v.record_id ?? v.vaccine_name;
    setAdministeringKey(key);
    try {
      const body = {
        record_id: v.record_id || undefined,
        vaccine_name: v.vaccine_name,
        scheduled_label: v.scheduled_label,
      };
      const file = fileByKey[key];
      if (file) {
        body.file_data = await fileToDataUrl(file);
        body.file_name = file.name;
        body.mime_type = file.type;
      }
      await apiClient.post(API_ENDPOINTS.PATIENTS.VACCINATION_ADMINISTER(patientPk), body);
      toastSuccess(`${v.vaccine_name} recorded as administered.`);
      setFileByKey(p => { const n = { ...p }; delete n[key]; return n; });
      refetch?.();
    } catch (err) {
      toastApiError(err, "Could not record the vaccination.");
    } finally {
      setAdministeringKey(null);
    }
  }

  return (
    <div style={{
      background: "var(--color-primary-light)", border: "1px solid var(--color-primary)",
      borderRadius: 8, padding: "10px 14px",
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-primary)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
        <Syringe size={13} /> Vaccinations due
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        {actionable.map((v, i) => {
          const key = v.record_id ?? v.vaccine_name;
          const busy = administeringKey === key;
          return (
            <div key={i} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap",
              background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 8, padding: "8px 10px",
            }}>
              <span style={{ fontSize: 12 }}>
                <strong>{v.vaccine_name}</strong>
                {v.scheduled_label && <span style={{ color: "var(--color-text-muted)" }}> · {v.scheduled_label}</span>}
                {v.status === "ordered" && (
                  <span style={{ color: "var(--color-text-muted)" }}> · ordered by {v.verified_by_name || "doctor"}{v.due_date ? ` — due ${new Date(v.due_date).toLocaleDateString("en-IN")}` : ""}</span>
                )}
              </span>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
                <button
                  type="button" className="btn-primary" style={{ fontSize: 11, padding: "4px 10px" }}
                  disabled={busy} onClick={() => administer(v)}
                >
                  {busy ? "Recording…" : "Administer"}
                </button>
                <label
                  title="Attach a certificate/photo before administering (optional)"
                  style={{
                    display: "flex", alignItems: "center", gap: 4, fontSize: 9.5,
                    color: fileByKey[key] ? "var(--color-primary)" : "var(--color-text-muted)",
                    cursor: "pointer", maxWidth: 130, overflow: "hidden",
                  }}
                >
                  <Paperclip size={10} style={{ flexShrink: 0 }} />
                  <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {fileByKey[key]?.name || "Attach report"}
                  </span>
                  <input
                    type="file" accept="image/*,application/pdf"
                    style={{ display: "none" }}
                    onChange={e => {
                      const f = e.target.files?.[0] || null;
                      setFileByKey(p => ({ ...p, [key]: f }));
                    }}
                  />
                </label>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function NurseTasksPage() {
  const { toastSuccess, toastApiError } = useToast();
  const [page, setPage] = useState(1);
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.MONITORING, {
    params: { date: TODAY, page, page_size: 20 },
    pollMs: 15000,
  });

  // Follow-ups a doctor asked a nurse to book — see FollowUpTab in
  const { data: followupData, refetch: refetchFollowups } = useApi(API_ENDPOINTS.OPD.FOLLOWUP_NURSE_WORKLIST, { pollMs: 30000 });
  const followups = followupData?.results || [];
  const [markingBooked, setMarkingBooked] = useState(null);

  async function markFollowupBooked(encounterId) {
    setMarkingBooked(encounterId);
    try {
      await apiClient.post(API_ENDPOINTS.OPD.FOLLOWUP_MARK_BOOKED(encounterId));
      toastSuccess("Marked as booked.");
      refetchFollowups();
    } catch (err) {
      toastApiError(err, "Could not update this follow-up.");
    } finally {
      setMarkingBooked(null);
    }
  }
  const tasks = data?.results || [];
  const pagination = data?.pagination || null;
  // Server-computed totals for the whole day (not just the current page).
  const summary = data?.summary || {};
  const totalToday = summary.total ?? tasks.length;
  const withTests = summary.with_tests ?? tasks.filter(t => t.investigations).length;
  const withFollowup = summary.with_followup ?? tasks.filter(t => t.follow_up_in_days).length;

  return (
    <AppShell>
      <PageShell
        title="Patient Monitoring"
        action={<button className="btn-outline" style={{ fontSize: 12 }} onClick={refetch}>Refresh</button>}
      >
        {/* Follow-ups to book — doctor asked a nurse to handle the next visit */}
        {followups.length > 0 && (
          <div className="card" style={{ padding: 16, marginBottom: 22 }}>
            <div className="dot-label dot-label--gold" style={{ marginBottom: 10 }}>Follow-ups to Book ({followups.length})</div>
            <div style={{ display: "grid", gap: 10 }}>
              {followups.map(f => (
                <div key={f.encounter_id} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
                  padding: "10px 14px", background: "var(--color-table-header)", borderRadius: "var(--radius-input)",
                }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>{f.patient_name} <span style={{ fontWeight: 400, color: "var(--color-text-muted)", fontSize: 11.5 }}>UHID {f.patient_uhid}</span></div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                      Dr. {f.doctor_name}{f.note ? ` — ${f.note}` : ""}
                    </div>
                  </div>
                  <button
                    className="btn-outline" style={{ fontSize: 11, padding: "6px 12px", whiteSpace: "nowrap" }}
                    disabled={markingBooked === f.encounter_id}
                    onClick={() => markFollowupBooked(f.encounter_id)}
                  >
                    {markingBooked === f.encounter_id ? "Saving…" : "Mark as Booked"}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Summary strip */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginBottom: 22 }}>
          {[
            { label: "Consulted today", value: totalToday,    dot: "dot-label--green" },
            { label: "Tests to chase",  value: withTests,     dot: "dot-label--gold" },
            { label: "Follow-ups set",  value: withFollowup,  dot: "dot-label--blue" },
          ].map(({ label, value, dot }) => (
            <div key={label} className="card" style={{ padding: "16px 20px" }}>
              <div className={`dot-label ${dot}`} style={{ marginBottom: 8 }}>{label}</div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 600 }}>
                {isLoading ? "—" : value}
              </div>
            </div>
          ))}
        </div>

        {isLoading ? (
          <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
            Loading…
          </div>
        ) : tasks.length === 0 ? (
          <div className="card" style={{ padding: 44, textAlign: "center" }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
              No consultations yet today
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              Once the doctor starts seeing patients, their orders appear here to monitor.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {tasks.map(t => (
              <div key={t.encounter_id} className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 12,
                  padding: "12px 18px", borderBottom: "1px solid var(--color-border)", background: "#FAFAF7",
                }}>
                  <span style={{
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    width: 30, height: 30, borderRadius: 8,
                    background: "var(--color-primary-light)", color: "var(--color-primary)",
                    fontWeight: 800, fontSize: 13,
                  }}>{t.token_number}</span>
                  <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 700, fontSize: 14 }}>{t.patient_name}</span>
                    <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{t.patient_uhid}</span>
                    <DependentBadge patient={t} />
                  </div>
                  {!t.has_vitals && <span className="badge badge--error">No vitals</span>}
                  <span className={`badge ${STATUS_BADGE[t.appointment_status] || "badge--neutral"}`}>
                    {t.appointment_status?.replace("_", " ")}
                  </span>
                  <span className={`badge ${t.encounter_status === "signed" ? "badge--success" : "badge--warning"}`}>
                    {t.encounter_status === "signed" ? "Signed off" : "Consult open"}
                  </span>
                </div>

                <div style={{ padding: "14px 18px", display: "grid", gap: 10 }}>
                  {t.chief_complaint && (
                    <div style={{ fontSize: 13, color: "var(--color-text-secondary)", fontStyle: "italic" }}>
                      "{t.chief_complaint}"
                    </div>
                  )}

                  {(t.diagnoses || []).length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {t.diagnoses.map((d, i) => (
                        <span key={i} className="badge badge--primary">{d.code} — {d.description}</span>
                      ))}
                    </div>
                  )}

                  {t.investigations && (
                    <div style={{
                      background: "var(--color-warning-light)", border: "1px solid var(--color-warning)",
                      borderRadius: 8, padding: "10px 14px", fontSize: 13,
                    }}>
                      <strong style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "var(--color-warning)" }}><FlaskConical size={13} /> Other orders:</strong>{" "}
                      {t.investigations}
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                        Guide the patient to the laboratory and confirm samples are collected.
                      </div>
                    </div>
                  )}

                  <VaccinationsForPatient patientPk={t.patient_pk} />

                  {t.prescription.length > 0 && (
                    <div style={{ fontSize: 13 }}>
                      <strong>Medication:</strong> {t.prescription.join(" · ")}
                    </div>
                  )}

                  {(t.advice || t.follow_up_in_days || t.referred_to) && (
                    <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
                      {t.advice && <span><strong>Advice:</strong> {t.advice} </span>}
                      {t.follow_up_in_days && <span>· <strong>Follow-up:</strong> {t.follow_up_in_days}d </span>}
                      {t.referred_to && <span>· <strong>Referred to:</strong> {t.referred_to}</span>}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {pagination && pagination.total_pages > 1 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 20 }}>
            <button
              className="btn-outline"
              style={{ fontSize: 12, padding: "6px 14px" }}
              disabled={!pagination.has_previous}
              onClick={() => setPage(p => Math.max(1, p - 1))}
            >
              ← Previous
            </button>
            <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
              Page {pagination.page} of {pagination.total_pages}
            </span>
            <button
              className="btn-outline"
              style={{ fontSize: 12, padding: "6px 14px" }}
              disabled={!pagination.has_next}
              onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))}
            >
              Next →
            </button>
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
