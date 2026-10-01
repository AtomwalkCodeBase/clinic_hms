import { useApi } from "../../../hooks/useApi";
import API_ENDPOINTS from "../../../config/api.config";
import { useToast } from "../../../hooks/useToast";
import { useState } from "react";
import { encounterApi } from "../../../api";
import { AlertTriangle, Stethoscope, Pill, FlaskConical, Paperclip, Activity, TrendingUp, Syringe, Check, X as XIcon, Baby, Clock } from "lucide-react";
import { fileToDataUrl } from "../../../utils/files";
import { EmptyNote, HistorySection } from "./HistorySection";
import { todayLocal } from "../../../utils/dates";

export function HistorySidebar({ patientPk, patientUhid, history, isLoading, open, onToggle, onOpenDocument }) {
  // Real visit timeline for this patient at this hospital — reuses the same
  // searchable visit-history endpoint the "History" nav page already uses,
  // filtered to this one patient by UHID. No fabricated entries: only
  // appointments that actually exist show up.
  const { data: timelineData, isLoading: timelineLoading } = useApi(
    patientUhid ? API_ENDPOINTS.OPD.HISTORY : null,
    { params: { patient: patientUhid, page_size: 12 }, skip: !patientUhid }
  );
  const timeline = timelineData?.results || [];

  // Growth trend + vaccination roadmap — reuses the same patient record this
  // sidebar already has open. Growth blends this hospital's own vitals with
  // cross-hospital ones (gated on hie_consent, same as the rest of this
  // sidebar); vaccinations merges real records with the default schedule so
  // a nurse/doctor sees exactly what's due, not just what's been logged.
  const { data: growthData, isLoading: growthLoading } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.GROWTH(patientPk) : null, { skip: !patientPk }
  );
  const { data: vaxData, isLoading: vaxLoading, refetch: refetchVax } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.VACCINATIONS(patientPk) : null, { skip: !patientPk }
  );
  // Pediatric-only additions — Birth History + developmental-milestone
  // roadmap. Both fetch unconditionally alongside growth/vaccinations (the
  // request is cheap and the response is small); the panels themselves are
  // gated to growthData.is_minor === true, same as Vaccinations above, so
  // an adult patient's sidebar never shows or fetches-for-display these.
  const { data: birthHistoryData, isLoading: birthHistoryLoading, refetch: refetchBirthHistory } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.BIRTH_HISTORY(patientPk) : null, { skip: !patientPk }
  );
  const { data: milestoneData, isLoading: milestoneLoading, refetch: refetchMilestones } = useApi(
    patientPk ? API_ENDPOINTS.PATIENTS.MILESTONES(patientPk) : null, { skip: !patientPk }
  );
  const { toastSuccess, toastApiError } = useToast();

  // Ad-hoc "Order Vaccine" inline form — matches this file's existing
  // lightweight-inline-form convention (LabOrderSection's search box,
  // DrugForm's "+ Add Drug" panel) rather than a modal.
  const [orderFormOpen, setOrderFormOpen] = useState(false);
  const [orderForm, setOrderForm] = useState({ vaccine_name: "", reason: "", due_date: "", dose_number: "" });
  const [ordering, setOrdering] = useState(false);
  const [decliningId, setDecliningId] = useState(null);
  const [administeringId, setAdministeringId] = useState(null);
  // Optional certificate to attach when administering a roadmap row —
  // keyed by the same itemKey (record_id or vaccine_name) the row's
  // Administer button uses, so each row can carry its own selected file
  // without a full modal per row.
  const [administerFileByKey, setAdministerFileByKey] = useState({});

  // "Log Vaccination" manual-entry form — a doctor/nurse recording a past
  // or outside vaccination (with an optional scanned certificate) the same
  // way a parent can from the portal's "Add Records" flow, rather than only
  // being able to act on today's due roadmap slots via Administer/Order.
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
  // optional reason matches this file's existing convention for quick
  // secondary actions (no dedicated modal/inline-text-input elsewhere for
  // something this minor).
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
  // vaccine right from this sidebar instead of routing through TasksPage.
  // Attaches whatever file (if any) was picked for this row's key via the
  // paperclip input next to the Administer button — e.g. a photo of the
  // vial/batch label or a printed certificate handed to the clinic.
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
  // certificate, the doctor/nurse-side equivalent of the patient portal's
  // "Add Records" upload. Uses the plain create endpoint (previously had no
  // frontend caller) rather than Administer/Order, since this isn't tied to
  // a specific roadmap slot — any vaccine name and any past date is valid.
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
  // Front desk may already have captured this at registration (see
  // RegisterPatientPage.jsx) — the doctor's job here is to review and, if
  // needed, add or correct it during consultation. POST creates the record
  // (first capture), PATCH edits an existing one — same create-vs-edit split
  // as apps.patients.pediatric_views.BirthHistoryView.
  const [bhFormOpen, setBhFormOpen] = useState(false);
  const [bhForm, setBhForm] = useState(null); // populated on open, from birthHistoryData or blank
  const [bhSaving, setBhSaving] = useState(false);
  const bhExists = !!birthHistoryData?.id;

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

  // ── Developmental Milestones (pediatric-only) ───────────────────────────
  const [assessingKey, setAssessingKey] = useState(null); // which roadmap row's mini-form is open
  const [assessForm, setAssessForm] = useState({ status: "achieved", notes: "" });
  const [assessSaving, setAssessSaving] = useState(false);

  function openAssess(item) {
    const key = item.record_id ?? `${item.domain}:${item.milestone}`;
    setAssessingKey(k => (k === key ? null : key));
    setAssessForm({ status: "achieved", notes: "" });
  }

  async function submitAssessment(item) {
    if (!patientPk) return;
    setAssessSaving(true);
    try {
      await encounterApi.addMilestone(patientPk, {
        domain: item.domain,
        milestone: item.milestone,
        scheduled_label: item.scheduled_label,
        status: assessForm.status,
        notes: assessForm.notes || undefined,
      });
      toastSuccess("Milestone assessment recorded.");
      setAssessingKey(null);
      refetchMilestones?.();
    } catch (err) {
      toastApiError(err, "Could not record the milestone assessment.");
    } finally {
      setAssessSaving(false);
    }
  }

  const MILESTONE_STATUS_STYLE = {
    achieved:   { bg: "#ECFDF5", color: "#047857", label: "Achieved" },
    not_yet:    { bg: "#F3F4F6", color: "#6B7280", label: "Not Yet" },
    concern:    { bg: "#FEF2F2", color: "#B91C1C", label: "Concern" },
    unassessed: { bg: "var(--color-bg)", color: "var(--color-text-muted)", label: "Not Assessed" },
  };

  // Status values from build_roadmap() (apps/registry/vaccine_schedule.py):
  // "completed"/"pending_review"/"rejected"/"ordered"/"declined" when a real
  // record matches the slot, or "unknown" when none does — "unknown" is
  // never shown as "due"/"overdue"/"not yet due"; the backend genuinely
  // doesn't know whether the vaccine was given elsewhere, only that
  // nothing's on file. `timing` ("upcoming"/"due_now"/"past_window") is
  // separate informational metadata, surfaced in the subtitle text below
  // rather than the status badge. "past_window" = the age window opened
  // long ago with no record — still "unknown" status, just needs copy that
  // doesn't read as "recommended now" (misleading once the window's long
  // closed, e.g. a birth-window vaccine on a 5-year-old).
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
  const allergies    = history?.allergies     || [];
  const labResults   = history?.lab_results   || [];
  // Grouped by calendar date (already newest-first from the API) so nine
  // near-identical rows read as "two visits' worth of tests" at a glance,
  // instead of a flat wall of repeated dates and "No summary" text.
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
        <div style={{ fontWeight: 700, fontSize: 13 }}>Patient History</div>
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
      ) : history && history.consent_given === false ? (
        <div style={{ padding: 20, fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
          <div style={{ fontWeight: 700, marginBottom: 6, color: "var(--color-text)" }}>
            No cross-hospital history on file
          </div>
          This patient hasn't consented to sharing records from other hospitals with this one, so
          only what's recorded here is visible. Anything documented at this hospital going forward
          will still show up normally.
        </div>
      ) : (
        // Ordered by clinical priority, not alphabetically: what could hurt
        // the patient (allergies) comes first, followed by what's currently
        // being managed (active problems, current meds), then supporting
        // evidence (labs, vitals trend), then the longitudinal record.
        <div>
          <HistorySection title="Allergies" icon={<AlertTriangle size={13} />} count={allergies.length} urgent defaultOpen>
            {allergies.length === 0 ? <EmptyNote>No known allergies on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {allergies.map((a, i) => (
                  <div key={i} style={{
                    borderRadius: 8, background: "#FEF2F2", border: "1.5px solid #FCA5A5",
                    padding: "10px 12px",
                  }}>
                    <div style={{
                      display: "flex", alignItems: "center", gap: 5, fontSize: 10, fontWeight: 800,
                      color: "#B91C1C", letterSpacing: 0.4, marginBottom: 6, textTransform: "uppercase",
                    }}>
                      <AlertTriangle size={12} /> Allergy Alert
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#7F1D1D", marginBottom: 4 }}>{a.substance}</div>
                    <div style={{ fontSize: 11, color: "#991B1B" }}>
                      {a.reaction || "Reaction not specified"}
                      {a.severity && (
                        <span style={{
                          marginLeft: 6, padding: "1px 7px", borderRadius: 10, fontSize: 10, fontWeight: 700,
                          background: "#FEE2E2", color: "#B91C1C", textTransform: "capitalize",
                        }}>{a.severity}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Active Diagnoses" icon={<Stethoscope size={13} />} count={diagnoses.length} defaultOpen>
            {diagnoses.length === 0 ? <EmptyNote>No prior diagnoses on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {diagnoses.map((d, i) => (
                  <div key={i} style={{
                    borderRadius: 8, border: "1px solid var(--color-border)", padding: "8px 10px",
                    background: "var(--color-bg)",
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)" }}>{d.description}</div>
                    <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 3, display: "flex", gap: 6, alignItems: "center" }}>
                      <span style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--color-primary)" }}>{d.icd10_code}</span>
                      <span style={{ textTransform: "capitalize" }}>{d.clinical_status}</span>
                      {d.created_at && <span>· {new Date(d.created_at).toLocaleDateString("en-IN")}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Current Medications" icon={<Pill size={13} />} count={prescriptions.length}>
            {prescriptions.length === 0 ? <EmptyNote>No prior prescriptions on record.</EmptyNote> : (
              <div style={{ display: "grid", gap: 8 }}>
                {prescriptions.map((rx, i) => (
                  <div key={i} style={{ borderRadius: 8, border: "1px solid var(--color-border)", padding: "8px 10px" }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-muted)", marginBottom: 4 }}>
                      {rx.prescribed_on ? new Date(rx.prescribed_on).toLocaleDateString("en-IN") : "—"}
                    </div>
                    {(rx.items || []).map((it, j) => (
                      <div key={j} style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: j === (rx.items.length - 1) ? 0 : 3 }}>
                        <strong style={{ color: "var(--color-text)" }}>{it.drug_name}</strong> {it.dose}{it.unit} — {it.frequency} · {it.route}
                        {it.duration_days ? ` × ${it.duration_days}d` : ""}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </HistorySection>

          <HistorySection title="Latest Labs" icon={<FlaskConical size={13} />} count={labResults.length}>
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
                            key={l.id ?? i}
                            onClick={clickable ? () => onOpenDocument?.({
                              id: l.id, title: l.test_name, doc_type: "lab_report",
                              created_at: l.delivered_at,
                              fetchUrl: API_ENDPOINTS.PATIENTS.LAB_RESULT(l.id),
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

          <HistorySection title="Vitals Trend" icon={<Activity size={13} />} count={vitals.length}>
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
                {growthData.consent_given === false && (
                  <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                    Only this hospital's own records — patient hasn't consented to cross-hospital sharing.
                  </div>
                )}
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
          <HistorySection title="Birth History" icon={<Baby size={13} />} count={bhExists ? 1 : 0}>
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

          {growthData?.is_minor === true && (
          <HistorySection title="Developmental Milestones" icon={<Baby size={13} />} count={milestoneData?.roadmap?.length}>
            {milestoneLoading ? <EmptyNote>Loading milestone roadmap…</EmptyNote> : !milestoneData?.roadmap?.length ? (
              <EmptyNote>No milestone schedule available.</EmptyNote>
            ) : (
              <div style={{ display: "grid", gap: 6 }}>
                {milestoneData.roadmap.map((m, i) => {
                  const st = MILESTONE_STATUS_STYLE[m.status] || MILESTONE_STATUS_STYLE.unassessed;
                  const key = m.record_id ?? `${m.domain}:${m.milestone}`;
                  const isOpen = assessingKey === key;
                  return (
                    <div key={i} style={{
                      borderRadius: 8, border: "1px solid var(--color-border)", padding: "8px 10px",
                      background: "var(--color-bg)",
                    }}>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text)" }}>{m.milestone}</span>
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
                          background: st.bg, color: st.color, whiteSpace: "nowrap",
                        }}>{st.label}</span>
                      </div>
                      <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 3, textTransform: "capitalize" }}>
                        {m.domain?.replace("_", " ")} · {m.scheduled_label}
                        {m.assessed_date && ` · assessed ${new Date(m.assessed_date).toLocaleDateString("en-IN")}`}
                        {m.status === "unassessed" && m.timing === "due_now" && " · recommended now"}
                        {m.status === "unassessed" && m.timing === "past_window" && " · past the usual window"}
                      </div>
                      <button
                        type="button" onClick={() => openAssess(m)}
                        style={{
                          marginTop: 6, fontSize: 10, fontWeight: 700, padding: "4px 8px", borderRadius: 6,
                          border: "1px solid var(--color-primary)", background: isOpen ? "var(--color-primary-light)" : "var(--color-bg)",
                          color: "var(--color-primary)", cursor: "pointer",
                        }}
                      >
                        {isOpen ? "− Cancel" : "Assess"}
                      </button>
                      {isOpen && (
                        <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
                          <select className="form-input" value={assessForm.status}
                            onChange={e => setAssessForm(f => ({ ...f, status: e.target.value }))}
                            style={{ fontSize: 12 }}>
                            <option value="achieved">Achieved</option>
                            <option value="not_yet">Not Yet</option>
                            <option value="concern">Concern — flag for follow-up</option>
                          </select>
                          <input className="form-input" placeholder="Notes (optional)" value={assessForm.notes}
                            onChange={e => setAssessForm(f => ({ ...f, notes: e.target.value }))}
                            style={{ fontSize: 12 }} />
                          <button
                            type="button" onClick={() => submitAssessment(m)} disabled={assessSaving}
                            className="btn-primary" style={{ fontSize: 11, padding: "5px 8px" }}
                          >
                            {assessSaving ? "Saving…" : "Save Assessment"}
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </HistorySection>
          )}

          <HistorySection title="Previous Visits" icon={<Clock size={13} />} count={timeline.length}>
            {timelineLoading ? <EmptyNote>Loading visit timeline…</EmptyNote> : timeline.length === 0 ? (
              <EmptyNote>No prior visits at this hospital.</EmptyNote>
            ) : (
              <div style={{ display: "grid", gap: 0, position: "relative" }}>
                {timeline.map((v, i) => (
                  <div key={v.id || i} style={{
                    display: "flex", gap: 10, paddingBottom: i === timeline.length - 1 ? 0 : 12,
                  }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                      <div style={{
                        width: 8, height: 8, borderRadius: "50%", marginTop: 4,
                        background: v.status === "done" ? "var(--color-primary)" : "var(--color-border)",
                      }} />
                      {i !== timeline.length - 1 && <div style={{ width: 1.5, flex: 1, background: "var(--color-border)", marginTop: 2 }} />}
                    </div>
                    <div style={{ fontSize: 11, minWidth: 0, flex: 1 }}>
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

          <HistorySection title="Attachments" icon={<Paperclip size={13} />} count={documents.length} defaultOpen>
            {documents.length === 0 ? <EmptyNote>No documents or handwritten notes on file yet.</EmptyNote> : (
              <div style={{ display: "grid", gap: 6 }}>
                {documents.map(d => (
                  <button
                    key={d.id}
                    onClick={() => onOpenDocument?.({ ...d, fetchUrl: API_ENDPOINTS.PATIENTS.DOCUMENT(d.id) })}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left",
                      padding: "8px 10px", borderRadius: 6, border: "1px solid var(--color-border)",
                      background: "var(--color-bg)", cursor: "pointer", fontSize: 12,
                    }}
                  >
                    <Paperclip size={14} style={{ color: "var(--color-text-secondary)", flexShrink: 0 }} />
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.title}</div>
                      <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                        {d.doc_type === "consult_note" ? "handwritten note" : d.doc_type?.replace("_", " ")}
                        {d.created_at && ` · ${new Date(d.created_at).toLocaleDateString("en-IN")}`}
                        {d.uploaded_by === "patient" && " · uploaded by patient"}
                        {d.doc_type === "consult_note" && d.uploaded_by === "staff" && " · written by doctor"}
                      </div>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </HistorySection>
        </div>
      )}
    </div>
  );
}
