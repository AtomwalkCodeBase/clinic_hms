/**
 * pages/nurse/TasksPage.jsx
 * ---------------------------
 * Patient monitoring — every patient consulted today with the doctor's
 * orders: tests to chase, medication given, advice, follow-up. Lets the
 * nurse track condition and make sure lab work actually happens.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { Syringe, FlaskConical } from "lucide-react";
import { dataUrlToBlob, openDataUrlInNewTab } from "../../utils/fileViewer";

const TODAY = new Date().toISOString().split("T")[0];

const STATUS_BADGE = {
  in_progress: "badge--info",
  done:        "badge--success",
  waiting:     "badge--warning",
  vitals_done: "badge--success",
};

const LAB_STATUS_BADGE = {
  ordered:    { label: "Ordered",    bg: "var(--color-border)", color: "var(--color-text-muted)" },
  collected:  { label: "Collected",  bg: "#DBEAFE", color: "#1E40AF" },
  processing: { label: "Processing", bg: "#FEF3C7", color: "#92400E" },
  completed:  { label: "Completed",  bg: "#D1FAE5", color: "#065F46" },
  cancelled:  { label: "Cancelled",  bg: "#FEE2E2", color: "#991B1B" },
};

// ─── One ordered test — nurse sets/corrects the patient's in-house/outside
// choice here (folded in from the old standalone Lab Orders page). ─────────
const PAY_PREF_LABEL = { pay_at_lab: "Pay at lab", pay_online: "Pay online" };
const CHOICE_MADE_BY_LABEL = { patient: "patient", nurse: "nurse" };

function LabOrderRow({ order, onChoiceSaved }) {
  const { toastSuccess, toastApiError } = useToast();
  const [payPref, setPayPref] = useState(order.payment_preference || "pay_at_lab");
  const [saving, setSaving] = useState(false);
  // Once a choice exists, show it as a confirmed record rather than live
  // buttons — otherwise every nurse who opens this page after the first
  // one sees the same "unset" picker and can't tell anything happened.
  // "Change" reveals the picker again for a correction.
  const [editing, setEditing] = useState(order.patient_choice === "pending");
  const status = LAB_STATUS_BADGE[order.status] || LAB_STATUS_BADGE.ordered;
  const hasChoice = order.patient_choice !== "pending";

  async function save(newChoice, payPrefOverride) {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.LAB.REQUEST_CHOICE(order.id), {
        patient_choice: newChoice,
        payment_preference: newChoice === "in_house" ? (payPrefOverride ?? payPref) : "",
      });
      toastSuccess("Choice updated.");
      setEditing(false);
      onChoiceSaved?.();
    } catch (err) {
      toastApiError(err, "Could not update choice.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ padding: "8px 12px", border: "1px solid var(--color-border)", borderRadius: 8 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <span style={{ fontWeight: 700, fontSize: 13 }}>{order.test_name}</span>
        <span style={{ padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, background: status.bg, color: status.color }}>
          {status.label}
        </span>
      </div>

      {hasChoice && !editing ? (
        // ── Confirmed record — read-only summary, same for every viewer ──
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 12 }}>
          <span style={{
            padding: "2px 9px", borderRadius: 10, fontWeight: 700,
            background: order.patient_choice === "in_house" ? "#DBEAFE" : "#FEF3C7",
            color: order.patient_choice === "in_house" ? "#1E40AF" : "#92400E",
          }}>
            ✓ {order.patient_choice === "in_house" ? "In-house" : "Outside"}
          </span>
          {order.patient_choice === "in_house" && order.payment_preference && (
            <span style={{ color: "var(--color-text-muted)" }}>
              {PAY_PREF_LABEL[order.payment_preference] || order.payment_preference}
            </span>
          )}
          {order.choice_made_by && (
            <span style={{ color: "var(--color-text-muted)" }}>
              · set by {CHOICE_MADE_BY_LABEL[order.choice_made_by] || order.choice_made_by}
            </span>
          )}
          <button
            type="button"
            onClick={() => setEditing(true)}
            style={{ background: "none", border: "none", color: "var(--color-primary)", fontSize: 11, cursor: "pointer", padding: 0, marginLeft: "auto" }}
          >
            Change
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button
            className={order.patient_choice === "in_house" ? "btn-primary" : "btn-outline"}
            style={{ fontSize: 11, padding: "4px 10px" }}
            disabled={saving}
            onClick={() => save("in_house")}
          >
            In-house
          </button>
          <button
            className={order.patient_choice === "outside" ? "btn-primary" : "btn-outline"}
            style={{ fontSize: 11, padding: "4px 10px" }}
            disabled={saving}
            onClick={() => save("outside")}
          >
            Outside
          </button>
          {order.patient_choice === "in_house" && (
            <select
              className="form-input"
              style={{ fontSize: 11, padding: "3px 6px", width: "auto" }}
              value={payPref}
              disabled={saving}
              onChange={e => { setPayPref(e.target.value); save("in_house", e.target.value); }}
            >
              <option value="pay_at_lab">Pay at lab</option>
              <option value="pay_online">Pay online</option>
            </select>
          )}
          {!hasChoice && (
            <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Not chosen yet — ask the patient</span>
          )}
          {hasChoice && (
            <button
              type="button"
              onClick={() => setEditing(false)}
              style={{ background: "none", border: "none", color: "var(--color-text-muted)", fontSize: 11, cursor: "pointer", padding: 0, marginLeft: "auto" }}
            >
              Cancel
            </button>
          )}
        </div>
      )}

      {order.report?.result_summary && (
        <div style={{ marginTop: 8, fontSize: 12, color: "#166534" }}>
          <strong>Result:</strong> {order.report.result_summary}
        </div>
      )}

      {order.report?.file_data && (
        <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "3px 10px", marginTop: 8 }}
          onClick={() => { const url = URL.createObjectURL(dataUrlToBlob(order.report.file_data)); window.open(url, "_blank"); setTimeout(() => URL.revokeObjectURL(url), 60000); }}>
          View Report
        </button>
      )}

      {order.patient_choice === "outside" && (
        order.attached_document ? (
          <ViewUploadedReportButton documentId={order.attached_document.id} />
        ) : (
          <div style={{ marginTop: 8, fontSize: 11, color: "var(--color-text-muted)" }}>
            Awaiting the patient's upload.
          </div>
        )
      )}
    </div>
  );
}

// Opens the patient's outside-lab upload in a new tab — same underlying
// document the doctor's History sidebar and the patient portal both show,
// fetched on demand (base64 content is never loaded until asked for).
function ViewUploadedReportButton({ documentId }) {
  const { toastApiError } = useToast();
  const [loading, setLoading] = useState(false);

  async function open() {
    const win = window.open("", "_blank");
    setLoading(true);
    try {
      const res = await apiClient.get(API_ENDPOINTS.PATIENTS.DOCUMENT(documentId));
      const doc = res.data?.data || res.data;
      if (doc?.file_data) {
        openDataUrlInNewTab(win, doc.file_data);
      } else if (win) {
        win.close();
      }
    } catch (err) {
      if (win) win.close();
      toastApiError(err, "Could not load the report.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "3px 10px", marginTop: 8 }}
      disabled={loading} onClick={open}>
      {loading ? "Loading…" : "View Uploaded Report"}
    </button>
  );
}

// Fetches this encounter's structured lab orders and renders them alongside
// (not instead of) the doctor's free-text investigations note above.
function LabOrdersForEncounter({ encounterId }) {
  const { data, refetch } = useApi(API_ENDPOINTS.LAB.REQUESTS, { params: { encounter_id: encounterId } });
  const orders = data?.results || [];
  if (orders.length === 0) return null;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {orders.map(o => <LabOrderRow key={o.id} order={o} onChoiceSaved={refetch} />)}
    </div>
  );
}

// ─── Vaccinations due today — mirrors the LabOrdersForEncounter pattern:
// fetch this patient's roadmap (apps/registry/vaccine_schedule.py
// build_roadmap(), same GET the doctor's EncounterPage history sidebar
// uses) and surface only what's actionable for a nurse right now: a
// doctor-ordered vaccine not yet given ("ordered"), or a routine schedule
// slot that's reached its recommended age window with no record on file
// ("unknown" + timing "due_now"). Nothing renders if there's nothing to do
// — same "only show if there's something real" convention as LabOrders.
function VaccinationsForPatient({ patientPk }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data, refetch } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.VACCINATIONS(patientPk) : null, { skip: !patientPk }
  );
  const [administeringKey, setAdministeringKey] = useState(null);
  const roadmap = data?.roadmap || [];
  const actionable = roadmap.filter(
    v => v.status === "ordered" || (v.status === "unknown" && v.timing === "due_now")
  );
  if (!patientPk || actionable.length === 0) return null;

  async function administer(v) {
    const key = v.record_id ?? v.vaccine_name;
    setAdministeringKey(key);
    try {
      await apiClient.post(API_ENDPOINTS.PATIENTS.VACCINATION_ADMINISTER(patientPk), {
        record_id: v.record_id || undefined,
        vaccine_name: v.vaccine_name,
        scheduled_label: v.scheduled_label,
      });
      toastSuccess(`${v.vaccine_name} recorded as administered.`);
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
              <button
                type="button" className="btn-primary" style={{ fontSize: 11, padding: "4px 10px" }}
                disabled={busy} onClick={() => administer(v)}
              >
                {busy ? "Recording…" : "Administer"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function NurseTasksPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.MONITORING, {
    params: { date: TODAY, page, page_size: 20 },
  });
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

                  <LabOrdersForEncounter encounterId={t.encounter_id} />

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
