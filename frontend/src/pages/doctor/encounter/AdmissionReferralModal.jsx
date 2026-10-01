import { useToast } from "../../../hooks/useToast";
import { useApi } from "../../../hooks/useApi";
import API_ENDPOINTS from "../../../config/api.config";
import { useState } from "react";
import { encounterApi } from "../../../api";
import { EXTERNAL_ADMISSION_SOURCES } from "./constants";

export function AdmissionReferralModal({ patientId, patientName, patientUhid, encounterId, onClose }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data: departments } = useApi(API_ENDPOINTS.ORG.DEPARTMENTS);
  const { data: admissionTypes } = useApi(API_ENDPOINTS.IPD.ADMISSION_TYPES);
  const { data: admissionSources } = useApi(API_ENDPOINTS.IPD.ADMISSION_SOURCES);

  const [form, setForm] = useState({
    department: "", admission_type: "", admission_source: "",
    reason_for_admission: "",
    external_referring_doctor_name: "", external_referring_facility: "",
    is_mlc: false, guardian_consent_by: "",
  });
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const activeTypes = (admissionTypes || []).filter((t) => t.is_active !== false);
  const activeSources = (admissionSources || []).filter((s) => s.is_active !== false);
  const isExternal = EXTERNAL_ADMISSION_SOURCES.has(form.admission_source);
  const canSubmit = patientId && form.department && form.admission_type && form.admission_source && form.reason_for_admission.trim().length > 0;

  async function submit(e) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    try {
      await encounterApi.recommendAdmission({
        patient_id: patientId,
        department_id: form.department,
        admission_type: form.admission_type,
        admission_source: form.admission_source,
        reason_for_admission: form.reason_for_admission,
        source_encounter_id: encounterId,
        external_referring_doctor_name: form.external_referring_doctor_name,
        external_referring_facility: form.external_referring_facility,
        is_mlc: form.is_mlc,
        guardian_consent_by: form.guardian_consent_by,
      });
      toastSuccess(`Admission recommended for ${patientName}. Front desk can now complete registration.`);
      setSubmitted(true);
    } catch (err) {
      toastApiError(err, "Could not create the admission referral.");
    } finally {
      setSaving(false);
    }
  }

  if (submitted) {
    return (
      <div style={{ position: "fixed", inset: 0, background: "rgba(12,42,31,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
        <div className="card" style={{ width: 480, borderLeft: "3px solid var(--color-success, #1a7f37)" }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Referral submitted for {patientName}</div>
          <div style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>
            It's on front desk's Admissions worklist now{isExternal ? " — it will need a doctor's countersign before they can register it" : ""}.
          </div>
          <button className="btn-primary" style={{ marginTop: 12 }} onClick={onClose}>Done</button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(12,42,31,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
      <div className="card" style={{ width: 640, maxHeight: "88vh", overflowY: "auto" }}>
        <div className="page-header" style={{ marginBottom: 14 }}>
          <div className="page-title" style={{ fontSize: 20 }}>Recommend Admission</div>
          <button className="btn-outline" onClick={onClose}>Cancel</button>
        </div>
        <div style={{ display: "grid", gap: 16 }}>
      <div className="callout">
        <div>
          <div className="callout-title">This creates the referral that gates admission</div>
          <div className="callout-body">
            Front desk cannot register an inpatient admission without a referral from here. It links
            back to this consultation automatically.
          </div>
        </div>
      </div>

      <form className="card" onSubmit={submit} style={{ maxWidth: 720, display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="form-field" style={{ background: "var(--color-table-header)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-input)", padding: "12px 14px" }}>
          <div style={{ fontWeight: 700, fontSize: 13.5 }}>{patientName}</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>UHID {patientUhid || "—"}</div>
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
            <div className="hint">Urgency — configurable in hospital admin settings</div>
          </div>
        </div>

        <div className="form-field">
          <label className="form-label">Admission Source</label>
          <select className="form-input" value={form.admission_source} onChange={set("admission_source")}>
            <option value="">Select source…</option>
            {activeSources.map((s) => <option key={s.id ?? s.value} value={s.value}>{s.label}</option>)}
          </select>
          <div className="hint">How the patient is arriving — configurable in hospital admin settings</div>
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
    </div>
  );
}
