/**
 * pages/doctor/IpdReferralsPage.jsx
 * -------------------------------------
 * "IPD Referrals" — a persistent, findable place for a doctor's admission
 * referrals, added directly in response to feedback that "Recommend
 * Admission" was hard to find (it only existed as a button inside an
 * active encounter, with no way afterward to see what happened to that
 * referral — front desk still needs to register it, and an external-source
 * one still needs a colleague's countersign before that can happen).
 *
 * Two things live here:
 *   - Every referral this doctor has personally recommended or
 *     countersigned, any status (IPD.REFERRALS_MINE) — a history/tracking
 *     view, distinct from IPD.REFERRALS (an action worklist elsewhere).
 *   - "+ New Referral", for starting one without first opening a specific
 *     patient's encounter (e.g. after a phone consult, or reviewing a
 *     transfer-in case) — the same fields/behavior as EncounterPage.jsx's
 *     own AdmissionReferralModal, just patient-search-first instead of
 *     already having a patientId from an open consultation.
 */
import { useState, useEffect } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi } from "../../hooks/useApi";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

// Mirrors AdmissionReferral.SOURCES_REQUIRING_ACCEPTANCE (apps/ipd/models.py)
// — sources that need a hospital doctor's own countersign before front desk
// can register the admission.
const EXTERNAL_ADMISSION_SOURCES = new Set(["external_referral", "transfer_in", "ambulance_ems", "medical_tourism"]);

const STATUS_BADGE = {
  pending: "badge--warning",
  converted: "badge--success",
  withdrawn: "badge--neutral",
};
const STATUS_LABEL = {
  pending: "Pending",
  converted: "Admitted",
  withdrawn: "Withdrawn",
};

function timeAgo(iso) {
  if (!iso) return "—";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return new Date(iso).toLocaleDateString();
}

function NewReferralModal({ onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data: departments } = useApi(API_ENDPOINTS.ORG.DEPARTMENTS);
  const { data: admissionTypes } = useApi(API_ENDPOINTS.IPD.ADMISSION_TYPES);
  const { data: admissionSources } = useApi(API_ENDPOINTS.IPD.ADMISSION_SOURCES);

  // Patient search — same debounced pattern as front-desk/AppointmentsPage.jsx.
  const [patientQuery, setPatientQuery] = useState("");
  const [patientOpts, setPatientOpts] = useState([]);
  const [patient, setPatient] = useState(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (patient || patientQuery.trim().length < 2) { setPatientOpts([]); return; }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const { data } = await apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, { params: { q: patientQuery } });
        const payload = data?.data || data || {};
        setPatientOpts(payload.results || []);
      } catch {
        setPatientOpts([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [patientQuery, patient]);

  const [form, setForm] = useState({
    department: "", admission_type: "", admission_source: "",
    reason_for_admission: "",
    external_referring_doctor_name: "", external_referring_facility: "",
    is_mlc: false, guardian_consent_by: "",
  });
  const [saving, setSaving] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const activeTypes = (admissionTypes || []).filter((t) => t.is_active !== false);
  const activeSources = (admissionSources || []).filter((s) => s.is_active !== false);
  const isExternal = EXTERNAL_ADMISSION_SOURCES.has(form.admission_source);
  const canSubmit = patient && form.department && form.admission_type && form.admission_source
    && form.reason_for_admission.trim().length > 0;

  async function submit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.REFERRAL_RECOMMEND, {
        patient_id: patient.id,
        department_id: form.department,
        admission_type: form.admission_type,
        admission_source: form.admission_source,
        reason_for_admission: form.reason_for_admission,
        external_referring_doctor_name: form.external_referring_doctor_name,
        external_referring_facility: form.external_referring_facility,
        is_mlc: form.is_mlc,
        guardian_consent_by: form.guardian_consent_by,
      });
      toastSuccess(`Admission recommended for ${patient.full_name}. Front desk can now complete registration.`);
      onDone();
    } catch (err) {
      toastApiError(err, "Could not create the admission referral.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(12,42,31,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40, padding: 24 }}>
      <div className="card" style={{ width: 640, maxHeight: "88vh", overflowY: "auto" }}>
        <div className="page-header" style={{ marginBottom: 14 }}>
          <div className="page-title" style={{ fontSize: 20 }}>Recommend Admission</div>
          <button className="btn-outline" onClick={onClose}>Cancel</button>
        </div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="form-field">
            <label className="form-label">Patient</label>
            {patient ? (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "var(--color-table-header)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-input)", padding: "10px 14px" }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 13.5 }}>{patient.full_name}</div>
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>UHID {patient.uhid}</div>
                </div>
                <button type="button" className="btn-outline" onClick={() => { setPatient(null); setPatientQuery(""); }}>Change</button>
              </div>
            ) : (
              <>
                <input className="form-input" value={patientQuery} onChange={(e) => setPatientQuery(e.target.value)} placeholder="Search by name, UHID, or phone…" />
                {patientQuery.trim().length >= 2 && (
                  <div style={{ border: "1px solid var(--color-border)", borderRadius: "var(--radius-input)", marginTop: 4, maxHeight: 180, overflowY: "auto" }}>
                    {searching && <div style={{ padding: 10, fontSize: 12, color: "var(--color-text-muted)" }}>Searching…</div>}
                    {!searching && patientOpts.length === 0 && <div style={{ padding: 10, fontSize: 12, color: "var(--color-text-muted)" }}>No matching patients.</div>}
                    {patientOpts.map((p) => (
                      <div key={p.id} style={{ padding: "8px 10px", cursor: "pointer", borderBottom: "1px solid var(--color-border)" }}
                        onClick={() => { setPatient(p); setPatientOpts([]); }}>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>{p.full_name}</div>
                        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>UHID {p.uhid}{p.mobile ? ` · ${p.mobile}` : ""}</div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="form-grid-2">
            <div className="form-field">
              <label className="form-label">Department</label>
              <select className="form-input" value={form.department} onChange={set("department")}>
                <option value="">Select department…</option>
                {(departments || []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div className="form-field">
              <label className="form-label">Admission Type</label>
              <select className="form-input" value={form.admission_type} onChange={set("admission_type")}>
                <option value="">Select type…</option>
                {activeTypes.map((t) => <option key={t.id ?? t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
          </div>

          <div className="form-field">
            <label className="form-label">Admission Source</label>
            <select className="form-input" value={form.admission_source} onChange={set("admission_source")}>
              <option value="">Select source…</option>
              {activeSources.map((s) => <option key={s.id ?? s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>

          {isExternal && (
            <div style={{ background: "var(--color-table-header)", border: "1px dashed var(--color-border)", borderRadius: "var(--radius-card)", padding: 14 }}>
              <div className="dot-label" style={{ marginBottom: 10 }}>External source — needs a countersign</div>
              <div className="form-grid-2">
                <div className="form-field">
                  <label className="form-label">Referring Doctor (external)</label>
                  <input className="form-input" value={form.external_referring_doctor_name} onChange={set("external_referring_doctor_name")} />
                </div>
                <div className="form-field">
                  <label className="form-label">Referring Facility</label>
                  <input className="form-input" value={form.external_referring_facility} onChange={set("external_referring_facility")} />
                </div>
              </div>
            </div>
          )}

          <div className="form-field">
            <label className="form-label">Reason for Admission</label>
            <textarea className="form-input" rows={3} value={form.reason_for_admission} onChange={set("reason_for_admission")} placeholder="Clinical justification for inpatient admission…" />
          </div>

          <div className="form-grid-2">
            <div className="form-field" style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-input)", padding: "10px 14px" }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <input type="checkbox" checked={form.is_mlc} onChange={set("is_mlc")} />
                <label style={{ fontSize: 12.5 }}>Medico-Legal Case (MLC)</label>
              </div>
            </div>
            <div className="form-field">
              <label className="form-label">Guardian Consent By (if minor / unconscious)</label>
              <input className="form-input" value={form.guardian_consent_by} onChange={set("guardian_consent_by")} />
            </div>
          </div>

          <button className="btn-primary" disabled={!canSubmit || saving} type="submit">
            {saving ? "Submitting…" : "Recommend Admission"}
          </button>
        </form>
      </div>
    </div>
  );
}

const TABS = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "converted", label: "Admitted" },
  { key: "withdrawn", label: "Withdrawn" },
];

export default function IpdReferralsPage() {
  const [tab, setTab] = useState("all");
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.IPD.REFERRALS_MINE, {
    params: tab === "all" ? {} : { status: tab },
  });
  const referrals = data || [];
  const [creating, setCreating] = useState(false);

  return (
    <AppShell>
      <PageShell
        title="IPD Referrals"
        action={<button className="btn-primary" onClick={() => setCreating(true)}>+ New Referral</button>}
      >
        <p style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
          Every admission you've recommended or countersigned. Front desk still has to complete registration
          before it becomes a real admission — this is where you track what happened to it afterward.
        </p>

        <div className="fdc-tabs" style={{ marginBottom: 16 }}>
          {TABS.map((t) => (
            <button key={t.key} type="button" className={"fdc-tab" + (tab === t.key ? " active" : "")} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Patient</th>
                <th>Department</th>
                <th>Type / Source</th>
                <th>Status</th>
                <th>Recommended</th>
              </tr>
            </thead>
            <tbody>
              {referrals.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div style={{ fontWeight: 700, fontSize: 13.5 }}>{r.patient_name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>UHID {r.patient_uhid}</div>
                  </td>
                  <td>{r.department_name}</td>
                  <td>
                    {r.admission_type}
                    {r.requires_acceptance && (
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                        {r.accepted_by_name ? `Countersigned by ${r.accepted_by_name}` : "Awaiting countersign"}
                      </div>
                    )}
                  </td>
                  <td><span className={`badge ${STATUS_BADGE[r.status] || "badge--neutral"}`}>{STATUS_LABEL[r.status] || r.status}</span></td>
                  <td style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>{timeAgo(r.recommended_at)}</td>
                </tr>
              ))}
              {!isLoading && referrals.length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: "center", padding: 28, color: "var(--color-text-muted)" }}>
                  No referrals {tab === "all" ? "yet" : `with status "${tab}"`}.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        {creating && (
          <NewReferralModal onClose={() => setCreating(false)} onDone={() => { setCreating(false); refetch(); }} />
        )}
      </PageShell>
    </AppShell>
  );
}
