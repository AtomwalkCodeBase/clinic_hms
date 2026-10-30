import { useApi } from "../../../hooks/useApi";
import API_ENDPOINTS from "../../../config/api.config";
import { useToast } from "../../../hooks/useToast";
import { useState } from "react";
import { encounterApi } from "../../../api";
import { Stethoscope, Pill, FlaskConical, Paperclip, Activity, TrendingUp, Syringe, Check, X as XIcon, Baby, Clock } from "lucide-react";
import { fileToDataUrl } from "../../../utils/files";
import { EmptyNote, HistorySection } from "./HistorySection";
import { todayLocal } from "../../../utils/dates";

export function HistorySidebar({ patientPk, patientUhid, history, isLoading, open, onToggle, onOpenDocument }) {
  // Real visit timeline for this patient at this hospital — reuses the same
  const { data: timelineData, isLoading: timelineLoading } = useApi(
    patientUhid ? API_ENDPOINTS.OPD.HISTORY : null,
    { params: { patient: patientUhid, page_size: 12 }, skip: !patientUhid }
  );
  const timeline = timelineData?.results || [];

  // Growth trend + vaccination roadmap — reuses the same patient record this
  const growthData = null;
  const growthLoading = false;
  const { data: vaxData, isLoading: vaxLoading, refetch: refetchVax } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.VACCINATIONS(patientPk) : null, { skip: !patientPk }
  );
  // Pediatric-only additions — Birth History + developmental-milestone
  const { data: birthHistoryData, isLoading: birthHistoryLoading, refetch: refetchBirthHistory } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.BIRTH_HISTORY(patientPk) : null, { skip: !patientPk }
  );
  const { toastSuccess, toastApiError } = useToast();

  // Ad-hoc "Order Vaccine" inline form — matches this file's existing
  const [orderFormOpen, setOrderFormOpen] = useState(false);
  const [showAllDocs, setShowAllDocs] = useState(false);          // Attachments: the first 5, or all of them
  const [orderForm, setOrderForm] = useState({ vaccine_name: "", reason: "", due_date: "", dose_number: "" });
  const [ordering, setOrdering] = useState(false);
  const [decliningId, setDecliningId] = useState(null);
  const [administeringId, setAdministeringId] = useState(null);
  // Optional certificate to attach when administering a roadmap row —
  const [administerFileByKey, setAdministerFileByKey] = useState({});

  // "Log Vaccination" manual-entry form — a doctor/nurse recording a past
  const [logFormOpen, setLogFormOpen] = useState(false);
  const [logForm, setLogForm] = useState({ vaccine_name: "", administered_date: "" });
  const [logFile, setLogFile] = useState(null);
  const [logging, setLogging] = useState(false);

  const knownVaccineNames = Array.from(
    new Set((vaxData?.roadmap || []).map(v => v.vaccine_name).filter(Boolean))
  );

  function updOrderForm(k, v) { setOrderForm(p => ({ ...p, [k]: v })); }
  function updLogForm(k, v) { setLogForm(p => ({ ...p, [k]: v })); }

  async function submitOrder(e) {
    e.preventDefault();
    if (!orderForm.vaccine_name.trim() || !orderForm.reason.trim() || !patientPk) return;
    setOrdering(true);
    try {
      await encounterApi.orderVaccination(patientPk, {
        vaccine_name: orderForm.vaccine_name.trim(),
        reason: orderForm.reason.trim(),
        due_date: orderForm.due_date || undefined,
        dose_number: orderForm.dose_number || undefined,
      });
      toastSuccess("Vaccine order recorded.");
      setOrderForm({ vaccine_name: "", reason: "", due_date: "", dose_number: "" });
      setOrderFormOpen(false);
      refetchVax?.();
    } catch (err) {
      toastApiError(err, "Could not record the vaccine order.");
    } finally {
      setOrdering(false);
    }
  }

  async function reviewVaccination(recordId, action) {
    try {
      await encounterApi.verifyVaccination(recordId, action);
      toastSuccess(action === "verify" ? "Marked verified." : "Marked rejected.");
      refetchVax?.();
    } catch (err) {
      toastApiError(err, "Could not update that record.");
    }
  }

  // Quick, low-friction "not required" action — window.prompt for an
  async function declineVaccination(v) {
    if (!patientPk) return;
    const reason = window.prompt("Reason (optional) — why isn't this vaccine required for this patient?", v.reason || "");
    if (reason === null) return; // cancelled
    setDecliningId(v.record_id ?? v.vaccine_name);
    try {
      await encounterApi.declineVaccination(patientPk, {
        record_id: v.record_id || undefined,
        vaccine_name: v.vaccine_name,
        scheduled_label: v.scheduled_label,
        reason: reason.trim(),
      });
      toastSuccess("Marked as not required.");
      refetchVax?.();
    } catch (err) {
      toastApiError(err, "Could not update that record.");
    } finally {
      setDecliningId(null);
    }
  }

  // Nurse/doctor "give it now" shortcut — administers an ordered/due
  async function administerVaccination(v) {
    if (!patientPk) return;
    const key = v.record_id ?? v.vaccine_name;
    setAdministeringId(key);
    try {
      const body = {
        record_id: v.record_id || undefined,
        vaccine_name: v.vaccine_name,
        scheduled_label: v.scheduled_label,
      };
      const file = administerFileByKey[key];
      if (file) {
        body.file_data = await fileToDataUrl(file);
        body.file_name = file.name;
        body.mime_type = file.type;
      }
      await encounterApi.administerVaccination(patientPk, body);
      toastSuccess("Vaccination recorded as administered.");
      setAdministerFileByKey(p => { const n = { ...p }; delete n[key]; return n; });
      refetchVax?.();
    } catch (err) {
      toastApiError(err, "Could not record the vaccination.");
    } finally {
      setAdministeringId(null);
    }
  }

  // "Log Vaccination" — manual historical/outside entry with an optional
  async function submitLogVaccination(e) {
    e.preventDefault();
    if (!logForm.vaccine_name.trim() || !logForm.administered_date || !patientPk) return;
    setLogging(true);
    try {
      const body = {
        vaccine_name: logForm.vaccine_name.trim(),
        administered_date: logForm.administered_date,
      };
      if (logFile) {
        body.file_data = await fileToDataUrl(logFile);
        body.file_name = logFile.name;
        body.mime_type = logFile.type;
      }
      await encounterApi.recordVaccination(patientPk, body);
      toastSuccess("Vaccination logged.");
      setLogForm({ vaccine_name: "", administered_date: "" });
      setLogFile(null);
      setLogFormOpen(false);
      refetchVax?.();
    } catch (err) {
      toastApiError(err, "Could not log that vaccination.");
    } finally {
      setLogging(false);
    }
  }

  // ── Birth History (pediatric-only) ──────────────────────────────────────
  const [bhFormOpen, setBhFormOpen] = useState(false);
  const [bhForm, setBhForm] = useState(null); // populated on open, from birthHistoryData or blank
  const [bhSaving, setBhSaving] = useState(false);
  const bhExists = !!birthHistoryData?.birth_history_id;

  function openBhForm() {
    setBhForm({
      gestational_age_weeks: birthHistoryData?.gestational_age_weeks ?? "",
      birth_weight_kg: birthHistoryData?.birth_weight_kg ?? "",
      delivery_mode: birthHistoryData?.delivery_mode ?? "",
      multiple_birth: birthHistoryData?.multiple_birth ?? "",
      nicu_admission: birthHistoryData?.nicu_admission ?? false,
      nicu_days: birthHistoryData?.nicu_days ?? "",
      birth_complications: birthHistoryData?.birth_complications ?? "",
      congenital_conditions: birthHistoryData?.congenital_conditions ?? "",
      apgar_score_1min: birthHistoryData?.apgar_score_1min ?? "",
      apgar_score_5min: birthHistoryData?.apgar_score_5min ?? "",
      notes: birthHistoryData?.notes ?? "",
    });
    setBhFormOpen(true);
  }
  function updBhForm(k, v) { setBhForm(p => ({ ...p, [k]: v })); }

  async function submitBirthHistory(e) {
    e.preventDefault();
    if (!bhForm || !patientPk) return;
    setBhSaving(true);
    try {
      const body = {};
      Object.entries(bhForm).forEach(([k, v]) => {
        if (v === "" || v === null || v === undefined) return;
        body[k] = v;
      });
      body.nicu_admission = !!bhForm.nicu_admission;
      await encounterApi.saveBirthHistory(patientPk, body, bhExists);
      toastSuccess(bhExists ? "Birth history updated." : "Birth history recorded.");
      setBhFormOpen(false);
      refetchBirthHistory?.();
    } catch (err) {
      toastApiError(err, "Could not save birth history.");
    } finally {
      setBhSaving(false);
    }
  }

  // Status values from build_roadmap() (apps/hospital_patients/pediatrics/vaccine_schedule.py):
  const VAX_STATUS_STYLE = {
    completed:       { label: "Done",              bg: "#D1FAE5", color: "#065F46" },
    pending_review:  { label: "Unverified upload", bg: "#F9F0DC", color: "#92400E" },
    rejected:        { label: "Rejected",          bg: "#FEE2E2", color: "#991B1B" },
    ordered:         { label: "Ordered",           bg: "#DBEAFE", color: "#1E40AF" },
    declined:        { label: "Not required",      bg: "var(--color-border)", color: "var(--color-text-muted)" },
    unknown:         { label: "Record unavailable", bg: "var(--color-border)", color: "var(--color-text-muted)" },
  };

  // Collapsed: thin icon rail — doesn't reflow the workspace next to it.
  if (!open) {
    return (
      <div style={{
        width: 40, flexShrink: 0, alignSelf: "stretch",
        borderLeft: "1px solid var(--color-border)", background: "var(--color-surface)",
        display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 14,
      }}>
        <button
          onClick={onToggle}
          title="Show patient history"
          style={{
            background: "none", border: "1px solid var(--color-border)", borderRadius: 8,
            width: 28, height: 28, cursor: "pointer", fontSize: 13, color: "var(--color-text-secondary)",
            display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 12,
          }}
        >
          ⟨
        </button>
        <span style={{
          writingMode: "vertical-rl", transform: "rotate(180deg)",
          fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", letterSpacing: 0.5,
        }}>
          HISTORY
        </span>
      </div>
    );
  }

  const diagnoses    = history?.diagnoses     || [];
  const vitals       = history?.vitals        || [];
  const labResults   = history?.lab_results   || [];
  // Grouped by calendar date (already newest-first from the API) so nine
  const labGroups = [];
  for (const l of labResults) {
    const dateLabel = l.delivered_at
      ? new Date(l.delivered_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
      : "Date unknown";
    const lastGroup = labGroups[labGroups.length - 1];
    if (lastGroup && lastGroup.dateLabel === dateLabel) lastGroup.items.push(l);
    else labGroups.push({ dateLabel, items: [l] });
  }
  const prescriptions = history?.prescriptions || [];
  const documents    = history?.documents     || [];

  return (
    <div style={{
      width: 320, flexShrink: 0, alignSelf: "flex-start",
      position: "sticky", top: 14,
      borderLeft: "1px solid var(--color-border)", background: "var(--color-surface)",
      borderRadius: "0 var(--radius-card) var(--radius-card) 0",
      maxHeight: "calc(100vh - 28px)", overflowY: "auto",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 14px", borderBottom: "1px solid var(--color-border)",
        position: "sticky", top: 0, background: "var(--color-surface)", zIndex: 1,
      }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>Patient history</div>
        <button
          onClick={onToggle}
          title="Collapse"
          style={{
            background: "none", border: "1px solid var(--color-border)", borderRadius: 8,
            width: 26, height: 26, cursor: "pointer", fontSize: 13, color: "var(--color-text-secondary)",
          }}
        >
          ⟩
        </button>
      </div>

      {isLoading ? (
        <div style={{ padding: 20, textAlign: "center", fontSize: 12, color: "var(--color-text-muted)" }}>
          Loading history…
        </div>
      ) : !patientPk ? (
        <div style={{ padding: 20, fontSize: 12, color: "var(--color-text-muted)" }}>
          Patient record unavailable.
        </div>
      ) : (
        // Ordered by clinical priority, not alphabetically: what could hurt
        <div>
          <HistorySection title="Active diagnoses" icon={<Stethoscope size={13} />} count={diagnoses.length} defaultOpen={diagnoses.length > 0}>
            {diagnoses.length === 0 ? <EmptyNote>No prior diagnoses on record.</EmptyNote> : (
              <div>
                {diagnoses.map((d, i) => (
                  <div key={i} style={{ padding: "8px 0", borderTop: i ? "1px solid var(--color-border)" : "none" }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)" }}>{d.description}</div>
                    <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 2, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontFamily: "monospace", fontWeight: 600, color: "var(--color-primary)" }}>{d.icd10_code}</span>
                      <span style={{ textTransform: "capitalize" }}>{d.clinical_status}</span>
                      {d.created_at && <span>· {new Date(d.created_at).toLocaleDateString("en-IN")}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Current medications" icon={<Pill size={13} />} count={prescriptions.length} defaultOpen={prescriptions.length > 0}>
            {prescriptions.length === 0 ? <EmptyNote>No prior prescriptions on record.</EmptyNote> : (
              <div>
                {prescriptions.map((rx, i) => (
                  <div key={i} style={{ padding: "8px 0", borderTop: i ? "1px solid var(--color-border)" : "none" }}>
                    <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 4 }}>
                      {rx.prescribed_on ? new Date(rx.prescribed_on).toLocaleDateString("en-IN") : "—"}
                    </div>
                    {(rx.items || []).map((it, j) => (
                      <div key={j} style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginBottom: j === (rx.items.length - 1) ? 0 : 3 }}>
                        <strong style={{ color: "var(--color-text)" }}>{it.drug_name}</strong> {it.dose}{it.unit} — {it.frequency} · {it.route}
                        {it.duration_days ? ` × ${it.duration_days}d` : ""}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Latest labs" icon={<FlaskConical size={13} />} count={labResults.length}>
            {labResults.length === 0 ? <EmptyNote>No prior lab results on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 12 }}>
                {labGroups.map((group, gi) => (
                  <div key={gi}>
                    <div style={{
                      fontSize: 10, fontWeight: 800, color: "var(--color-text-muted)",
                      textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6,
                    }}>
                      {group.dateLabel} · {group.items.length} test{group.items.length > 1 ? "s" : ""}
                    </div>
                    <div style={{ display: "grid", gap: 5 }}>
                      {group.items.map((l, i) => {
                        const clickable = !!l.has_file;
                        const Wrapper = clickable ? "button" : "div";
                        const subtitle = l.result_summary || (clickable ? "Report attached" : "Awaiting report");
                        return (
                          <Wrapper
                            key={l.lab_result_id ?? i}
                            onClick={clickable ? () => onOpenDocument?.({
                              id: l.lab_result_id, title: l.test_name, doc_type: "lab_report",
                              created_at: l.delivered_at,
                              fetchUrl: API_ENDPOINTS.PATIENTS.LAB_RESULT(l.lab_result_id),
                            }) : undefined}
                            style={{
                              display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left", fontSize: 12,
                              background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: 8,
                              padding: "7px 10px", cursor: clickable ? "pointer" : "default",
                            }}
                          >
                            <span style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontWeight: 700 }}>{l.test_name}</div>
                              <div style={{ color: "var(--color-text-muted)", fontSize: 11 }}>{subtitle}</div>
                            </span>
                            {clickable && <Paperclip size={13} style={{ color: "var(--color-primary)", flexShrink: 0 }} />}
                          </Wrapper>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Vitals trend" icon={<Activity size={13} />} count={vitals.length}>
            {vitals.length === 0 ? <EmptyNote>No prior vitals on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {vitals.slice(0, 8).map((v, i) => (
                  <div key={i} style={{ fontSize: 11, borderBottom: "1px dashed var(--color-border)", paddingBottom: 6 }}>
                    <div style={{ color: "var(--color-text-muted)", marginBottom: 2 }}>
                      {v.recorded_at ? new Date(v.recorded_at).toLocaleDateString("en-IN") : "—"}
                      {v.source && ` · ${v.source}`}
                    </div>
                    <div>
                      {v.bp_systolic && v.bp_diastolic && `BP ${v.bp_systolic}/${v.bp_diastolic}  `}
                      {v.pulse_rate && `HR ${v.pulse_rate}  `}
                      {v.temperature && `Temp ${v.temperature}°F  `}
                      {v.spo2 && `SpO₂ ${v.spo2}%`}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Growth" icon={<TrendingUp size={13} />} count={growthData?.series?.length}>
            {growthLoading ? <EmptyNote>Loading growth data…</EmptyNote> : !growthData?.series?.length ? (
              <EmptyNote>No height/weight recorded yet.</EmptyNote>
            ) : (
              <div style={{ display: "grid", gap: 6 }}>
                {growthData.is_minor === false && (
                  <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginBottom: 2 }}>
                    Adult patient — trend shown, no pediatric percentile applies.
                  </div>
                )}
                {growthData.series.slice(-6).reverse().map((p, i) => {
                  const pct = p.percentiles || {};
                  return (
                  <div key={i} style={{ fontSize: 11, borderBottom: "1px dashed var(--color-border)", paddingBottom: 6 }}>
                    <div style={{ color: "var(--color-text-muted)", marginBottom: 2 }}>
                      {new Date(p.date).toLocaleDateString("en-IN")}{p.source === "other_hospital" ? " · other hospital" : ""}
                    </div>
                    <div>
                      {p.height_cm != null && (
                        <>{p.height_cm} cm{pct.height && ` (${pct.height.percentile}th pctl)`}{"  "}</>
                      )}
                      {p.weight_kg != null && (
                        <>{p.weight_kg} kg{pct.weight && ` (${pct.weight.percentile}th pctl)`}{"  "}</>
                      )}
                      {p.head_circumference_cm != null && (
                        <>HC {p.head_circumference_cm} cm{pct.head_circumference && ` (${pct.head_circumference.percentile}th pctl)`}{"  "}</>
                      )}
                      {p.bmi != null && `BMI ${p.bmi}`}
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
          </HistorySection>

          {growthData?.is_minor === true && (
          <HistorySection title="Vaccinations" icon={<Syringe size={13} />} count={vaxData?.roadmap?.length}>
            <div style={{ marginBottom: 10 }}>
              <button
                type="button"
                onClick={() => setOrderFormOpen(o => !o)}
                disabled={!patientPk}
                style={{
                  width: "100%", fontSize: 11, fontWeight: 700, padding: "6px 10px", borderRadius: 6,
                  border: "1px dashed var(--color-primary)", background: orderFormOpen ? "var(--color-primary-light)" : "var(--color-bg)",
                  color: "var(--color-primary)", cursor: patientPk ? "pointer" : "not-allowed",
                }}
              >
                {orderFormOpen ? "− Cancel Order" : "+ Order Vaccine"}
              </button>
              {orderFormOpen && (
                <form onSubmit={submitOrder} style={{
                  marginTop: 8, background: "#FBF9F5", borderRadius: 10, padding: 10,
                  border: "1px dashed var(--color-primary)", display: "grid", gap: 8,
                }}>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>VACCINE *</label>
                    <input
                      className="form-input" list="known-vaccine-names"
                      value={orderForm.vaccine_name}
                      onChange={e => updOrderForm("vaccine_name", e.target.value)}
                      placeholder="e.g. Hepatitis B - 2"
                      required
                      style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }}
                    />
                    <datalist id="known-vaccine-names">
                      {knownVaccineNames.map(n => <option key={n} value={n} />)}
                    </datalist>
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>REASON *</label>
                    <input
                      className="form-input"
                      value={orderForm.reason}
                      onChange={e => updOrderForm("reason", e.target.value)}
                      placeholder="Clinical reason for this order"
                      required
                      style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }}
                    />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>DUE DATE</label>
                      <input
                        type="date" className="form-input"
                        value={orderForm.due_date}
                        onChange={e => updOrderForm("due_date", e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>DOSE #</label>
                      <input
                        type="number" min="1" className="form-input"
                        value={orderForm.dose_number}
                        onChange={e => updOrderForm("dose_number", e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }}
                      />
                    </div>
                  </div>
                  <button
                    type="submit" className="btn-primary" style={{ fontSize: 12, padding: "6px 10px" }}
                    disabled={ordering || !orderForm.vaccine_name.trim() || !orderForm.reason.trim()}
                  >
                    {ordering ? "Ordering…" : "Order Vaccine"}
                  </button>
                </form>
              )}
            </div>

            <div style={{ marginBottom: 10 }}>
              <button
                type="button"
                onClick={() => setLogFormOpen(o => !o)}
                disabled={!patientPk}
                style={{
                  width: "100%", fontSize: 11, fontWeight: 700, padding: "6px 10px", borderRadius: 6,
                  border: "1px dashed var(--color-primary)", background: logFormOpen ? "var(--color-primary-light)" : "var(--color-bg)",
                  color: "var(--color-primary)", cursor: patientPk ? "pointer" : "not-allowed",
                }}
              >
                {logFormOpen ? "− Cancel" : "+ Log Vaccination"}
              </button>
              {logFormOpen && (
                <form onSubmit={submitLogVaccination} style={{
                  marginTop: 8, background: "#FBF9F5", borderRadius: 10, padding: 10,
                  border: "1px dashed var(--color-primary)", display: "grid", gap: 8,
                }}>
                  <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                    Record a past or outside vaccination for this patient — not tied to a schedule
                    slot. The certificate is optional.
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>VACCINE *</label>
                    <input
                      className="form-input" list="known-vaccine-names"
                      value={logForm.vaccine_name}
                      onChange={e => updLogForm("vaccine_name", e.target.value)}
                      placeholder="e.g. Hepatitis B - 2"
                      required
                      style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>DATE GIVEN *</label>
                    <input
                      type="date" className="form-input"
                      value={logForm.administered_date}
                      max={todayLocal()}
                      onChange={e => updLogForm("administered_date", e.target.value)}
                      required
                      style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>
                      CERTIFICATE (OPTIONAL)
                    </label>
                    <input
                      type="file" accept="image/*,application/pdf"
                      onChange={e => setLogFile(e.target.files?.[0] || null)}
                      style={{ fontSize: 11, width: "100%" }}
                    />
                  </div>
                  <button
                    type="submit" className="btn-primary" style={{ fontSize: 12, padding: "6px 10px" }}
                    disabled={logging || !logForm.vaccine_name.trim() || !logForm.administered_date}
                  >
                    {logging ? "Logging…" : "Log Vaccination"}
                  </button>
                </form>
              )}
            </div>

            {vaxLoading ? <EmptyNote>Loading vaccination roadmap…</EmptyNote> : !vaxData?.roadmap?.length ? (
              <EmptyNote>No vaccination schedule available.</EmptyNote>
            ) : (
              <div style={{ display: "grid", gap: 6 }}>
                {vaxData.roadmap.map((v, i) => {
                  const st = VAX_STATUS_STYLE[v.status] || VAX_STATUS_STYLE.unknown;
                  const needsReview = v.status === "pending_review";
                  const itemKey = v.record_id ?? v.vaccine_name;
                  const canDecline = v.status === "unknown" || v.status === "ordered";
                  const canAdminister = v.status === "ordered" || (v.status === "unknown" && (v.timing === "due_now" || v.timing === "past_window"));
                  return (
                    <div key={i} style={{
                      borderRadius: 8, border: "1px solid var(--color-border)", padding: "8px 10px",
                      background: needsReview ? "#FFFBEB" : "var(--color-bg)",
                    }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)" }}>{v.vaccine_name}</span>
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
                          background: st.bg, color: st.color, whiteSpace: "nowrap",
                        }}>{st.label}</span>
                      </div>
                      <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 3 }}>
                        {v.scheduled_label}
                        {v.administered_date && ` · given ${new Date(v.administered_date).toLocaleDateString("en-IN")}`}
                        {v.source === "self_reported" && " · reported by parent"}
                        {v.status === "unknown" && v.timing === "due_now" && " · recommended now"}
                        {v.status === "unknown" && v.timing === "past_window" && " · no record on file — past the usual window, ask about catch-up"}
                        {v.status === "ordered" && ` · ordered by ${v.verified_by_name || "doctor"}${v.due_date ? ` — due ${new Date(v.due_date).toLocaleDateString("en-IN")}` : ""}`}
                        {v.status === "declined" && ` · marked not required${v.reason ? ` — ${v.reason}` : ""}`}
                      </div>
                      {needsReview && (
                        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                          <button
                            onClick={() => reviewVaccination(v.record_id, "verify")}
                            style={{
                              flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
                              fontSize: 11, fontWeight: 700, padding: "5px 8px", borderRadius: 6,
                              border: "1px solid #10B981", background: "#ECFDF5", color: "#047857", cursor: "pointer",
                            }}
                          >
                            <Check size={12} /> Verify
                          </button>
                          <button
                            onClick={() => reviewVaccination(v.record_id, "reject")}
                            style={{
                              flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
                              fontSize: 11, fontWeight: 700, padding: "5px 8px", borderRadius: 6,
                              border: "1px solid #EF4444", background: "#FEF2F2", color: "#B91C1C", cursor: "pointer",
                            }}
                          >
                            <XIcon size={12} /> Reject
                          </button>
                        </div>
                      )}
                      {(canDecline || canAdminister) && (
                        <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "flex-start" }}>
                          {canAdminister && (
                            <div style={{ flex: 1, display: "grid", gap: 4 }}>
                              <button
                                onClick={() => administerVaccination(v)}
                                disabled={administeringId === itemKey}
                                style={{
                                  width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
                                  fontSize: 11, fontWeight: 700, padding: "5px 8px", borderRadius: 6,
                                  border: "1px solid #10B981", background: "#ECFDF5", color: "#047857",
                                  cursor: administeringId === itemKey ? "not-allowed" : "pointer",
                                  opacity: administeringId === itemKey ? 0.6 : 1,
                                }}
                              >
                                <Syringe size={12} /> {administeringId === itemKey ? "Recording…" : "Administer"}
                              </button>
                              <label
                                title="Attach a certificate/photo before administering (optional)"
                                style={{
                                  display: "flex", alignItems: "center", gap: 4, fontSize: 9.5,
                                  color: administerFileByKey[itemKey] ? "var(--color-primary)" : "var(--color-text-muted)",
                                  cursor: "pointer", overflow: "hidden",
                                }}
                              >
                                <Paperclip size={10} style={{ flexShrink: 0 }} />
                                <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {administerFileByKey[itemKey]?.name || "Attach report"}
                                </span>
                                <input
                                  type="file" accept="image/*,application/pdf"
                                  style={{ display: "none" }}
                                  onChange={e => {
                                    const f = e.target.files?.[0] || null;
                                    setAdministerFileByKey(p => ({ ...p, [itemKey]: f }));
                                  }}
                                />
                              </label>
                            </div>
                          )}
                          {canDecline && (
                            <button
                              onClick={() => declineVaccination(v)}
                              disabled={decliningId === itemKey}
                              style={{
                                flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 4,
                                fontSize: 11, fontWeight: 700, padding: "5px 8px", borderRadius: 6,
                                border: "1px solid var(--color-border)", background: "var(--color-bg)", color: "var(--color-text-secondary)",
                                cursor: decliningId === itemKey ? "not-allowed" : "pointer",
                                opacity: decliningId === itemKey ? 0.6 : 1,
                              }}
                            >
                              <XIcon size={12} /> Not Required
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </HistorySection>
          )}

          {growthData?.is_minor === true && (
          <HistorySection title="Birth history" icon={<Baby size={13} />} count={bhExists ? 1 : 0}>
            <div style={{ marginBottom: 10 }}>
              <button
                type="button"
                onClick={() => (bhFormOpen ? setBhFormOpen(false) : openBhForm())}
                disabled={!patientPk}
                style={{
                  width: "100%", fontSize: 11, fontWeight: 700, padding: "6px 10px", borderRadius: 6,
                  border: "1px dashed var(--color-primary)", background: bhFormOpen ? "var(--color-primary-light)" : "var(--color-bg)",
                  color: "var(--color-primary)", cursor: patientPk ? "pointer" : "not-allowed",
                }}
              >
                {bhFormOpen ? "− Cancel" : bhExists ? "Edit Birth History" : "+ Record Birth History"}
              </button>
              {bhFormOpen && bhForm && (
                <form onSubmit={submitBirthHistory} style={{
                  marginTop: 8, background: "#FBF9F5", borderRadius: 10, padding: 10,
                  border: "1px dashed var(--color-primary)", display: "grid", gap: 8,
                }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>GESTATIONAL AGE (WEEKS)</label>
                      <input type="number" className="form-input" value={bhForm.gestational_age_weeks}
                        onChange={e => updBhForm("gestational_age_weeks", e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }} />
                    </div>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>BIRTH WEIGHT (KG)</label>
                      <input type="number" step="0.01" className="form-input" value={bhForm.birth_weight_kg}
                        onChange={e => updBhForm("birth_weight_kg", e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }} />
                    </div>
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>DELIVERY MODE</label>
                    <select className="form-input" value={bhForm.delivery_mode}
                      onChange={e => updBhForm("delivery_mode", e.target.value)}
                      style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }}>
                      <option value="">—</option>
                      <option value="normal">Normal Vaginal Delivery</option>
                      <option value="c_section">C-Section</option>
                      <option value="assisted">Assisted (Forceps/Vacuum)</option>
                      <option value="unknown">Unknown</option>
                    </select>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
                        <input type="checkbox" checked={!!bhForm.nicu_admission}
                          onChange={e => updBhForm("nicu_admission", e.target.checked)} />
                        NICU ADMISSION
                      </label>
                      {bhForm.nicu_admission && (
                        <input type="number" className="form-input" placeholder="Days in NICU" value={bhForm.nicu_days}
                          onChange={e => updBhForm("nicu_days", e.target.value)}
                          style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }} />
                      )}
                    </div>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>MULTIPLE BIRTH</label>
                      <input className="form-input" placeholder="e.g. twin" value={bhForm.multiple_birth}
                        onChange={e => updBhForm("multiple_birth", e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }} />
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>APGAR (1 MIN)</label>
                      <input type="number" min="0" max="10" className="form-input" value={bhForm.apgar_score_1min}
                        onChange={e => updBhForm("apgar_score_1min", e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }} />
                    </div>
                    <div>
                      <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>APGAR (5 MIN)</label>
                      <input type="number" min="0" max="10" className="form-input" value={bhForm.apgar_score_5min}
                        onChange={e => updBhForm("apgar_score_5min", e.target.value)}
                        style={{ width: "100%", boxSizing: "border-box", fontSize: 12 }} />
                    </div>
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>BIRTH COMPLICATIONS</label>
                    <textarea className="form-input" rows={2} value={bhForm.birth_complications}
                      onChange={e => updBhForm("birth_complications", e.target.value)}
                      style={{ width: "100%", boxSizing: "border-box", fontSize: 12, resize: "vertical" }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", display: "block", marginBottom: 3 }}>CONGENITAL CONDITIONS</label>
                    <textarea className="form-input" rows={2} value={bhForm.congenital_conditions}
                      onChange={e => updBhForm("congenital_conditions", e.target.value)}
                      style={{ width: "100%", boxSizing: "border-box", fontSize: 12, resize: "vertical" }} />
                  </div>
                  <button type="submit" className="btn-primary" style={{ fontSize: 12, padding: "6px 10px" }} disabled={bhSaving}>
                    {bhSaving ? "Saving…" : bhExists ? "Save Changes" : "Record Birth History"}
                  </button>
                </form>
              )}
            </div>

            {birthHistoryLoading ? <EmptyNote>Loading birth history…</EmptyNote> : !bhExists ? (
              <EmptyNote>No birth history recorded yet.</EmptyNote>
            ) : (
              <div style={{ display: "grid", gap: 4, fontSize: 11 }}>
                {birthHistoryData.gestational_age_weeks != null && (
                  <div>Gestational age: <strong>{birthHistoryData.gestational_age_weeks} weeks</strong></div>
                )}
                {birthHistoryData.birth_weight_kg != null && (
                  <div>Birth weight: <strong>{birthHistoryData.birth_weight_kg} kg</strong></div>
                )}
                {birthHistoryData.delivery_mode_display && (
                  <div>Delivery: <strong>{birthHistoryData.delivery_mode_display}</strong></div>
                )}
                {birthHistoryData.multiple_birth && <div>Multiple birth: <strong>{birthHistoryData.multiple_birth}</strong></div>}
                {birthHistoryData.nicu_admission && (
                  <div>NICU: <strong>Yes{birthHistoryData.nicu_days ? ` — ${birthHistoryData.nicu_days} days` : ""}</strong></div>
                )}
                {(birthHistoryData.apgar_score_1min != null || birthHistoryData.apgar_score_5min != null) && (
                  <div>APGAR: <strong>{birthHistoryData.apgar_score_1min ?? "—"} / {birthHistoryData.apgar_score_5min ?? "—"}</strong></div>
                )}
                {birthHistoryData.birth_complications && <div>Complications: {birthHistoryData.birth_complications}</div>}
                {birthHistoryData.congenital_conditions && <div>Congenital conditions: {birthHistoryData.congenital_conditions}</div>}
              </div>
            )}
          </HistorySection>
          )}

          <HistorySection title="Previous visits" icon={<Clock size={13} />} count={timeline.length}>
            {timelineLoading ? <EmptyNote>Loading visit timeline…</EmptyNote> : timeline.length === 0 ? (
              <EmptyNote>No prior visits at this hospital.</EmptyNote>
            ) : (
              <div style={{ display: "grid", gap: 0, position: "relative" }}>
                {timeline.map((v, i) => (
                  <div key={v.opd_encounter_id || i} style={{
                    display: "flex", gap: 10, paddingBottom: i === timeline.length - 1 ? 0 : 12,
                  }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                      <div style={{
                        width: 8, height: 8, borderRadius: "50%", marginTop: 4,
                        background: v.status === "done" ? "var(--color-primary)" : "var(--color-border)",
                      }} />
                      {i !== timeline.length - 1 && <div style={{ width: 1.5, flex: 1, background: "var(--color-border)", marginTop: 2 }} />}
                    </div>
                    <div style={{ fontSize: 12, minWidth: 0, flex: 1 }}>
                      <div style={{ fontWeight: 700, color: "var(--color-text)" }}>
                        {new Date(v.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
                        {v.visit_type === "followup" && (
                          <span style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, color: "var(--color-primary)", textTransform: "uppercase" }}>Follow-up</span>
                        )}
                      </div>
                      <div style={{ color: "var(--color-text-muted)" }}>
                        Dr. {v.doctor} {v.chief_complaint && `· ${v.chief_complaint}`}
                      </div>
                      <div style={{ color: "var(--color-text-muted)", textTransform: "capitalize" }}>{v.status?.replace("_", " ")}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Attachments" icon={<Paperclip size={13} />} count={documents.length} defaultOpen={documents.length > 0}>
            {documents.length === 0 ? <EmptyNote>No documents or handwritten notes on file yet.</EmptyNote> : (
              <div>
                {(showAllDocs ? documents : documents.slice(0, 5)).map((d, i) => (
                  <button
                    key={d.medical_document_id}
                    onClick={() => onOpenDocument?.({ ...d, fetchUrl: API_ENDPOINTS.PATIENTS.DOCUMENT(d.medical_document_id) })}
                    style={{
                      display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left",
                      padding: "8px 0", border: "none", borderTop: i ? "1px solid var(--color-border)" : "none",
                      background: "none", cursor: "pointer", fontSize: 12.5,
                    }}
                  >
                    <span style={{ width: 28, height: 28, borderRadius: 8, background: "var(--color-bg)", display: "grid", placeItems: "center", flexShrink: 0 }}>
                      <Paperclip size={14} style={{ color: "var(--color-text-secondary)" }} />
                    </span>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.title}</div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                        {d.doc_type === "consult_note" ? "handwritten note" : d.doc_type?.replace("_", " ")}
                        {d.created_at && ` · ${new Date(d.created_at).toLocaleDateString("en-IN")}`}
                        {d.uploaded_by === "patient" && " · patient upload"}
                        {d.doc_type === "consult_note" && d.uploaded_by === "staff" && " · written by doctor"}
                      </div>
                    </span>
                  </button>
                ))}
                {documents.length > 5 && (
                  <button onClick={() => setShowAllDocs(v => !v)} style={{ background: "none", border: "none", padding: "8px 0 0", cursor: "pointer", fontSize: 12, fontWeight: 600, color: "var(--color-primary)" }}>
                    {showAllDocs ? "Show fewer" : `Show all ${documents.length}`}
                  </button>
                )}
              </div>
            )}
          </HistorySection>
        </div>
      )}
    </div>
  );
}
