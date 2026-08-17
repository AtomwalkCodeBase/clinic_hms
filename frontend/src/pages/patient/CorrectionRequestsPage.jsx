/**
 * pages/patient/CorrectionRequestsPage.jsx
 * -------------------------------------------
 * DPDP Act 2023, Article 13 — patient right to correction. Lets a patient
 * (or a linked family member, via PatientContext) ask a hospital to fix
 * something in their record, and shows the status of past requests across
 * every hospital they've visited.
 *
 * resource_id is optional on purpose — a patient describing "my address is
 * wrong" has no way to know an internal database row id; the reviewing
 * staff member resolves the exact record (see apps/compliance/views.py).
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { usePatientContext } from "../../context/PatientContext";
import { ShieldCheck, Send } from "lucide-react";

const RESOURCE_TYPES = [
  { value: "Patient",      label: "Personal / Contact Information" },
  { value: "Diagnosis",    label: "Diagnosis" },
  { value: "Prescription", label: "Prescription" },
  { value: "Vitals",       label: "Vitals" },
  { value: "LabResult",    label: "Lab Result" },
  { value: "Other",        label: "Other" },
];

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function StatusPill({ status }) {
  const map = {
    pending:  { bg: "var(--color-warning-bg, #fef3c7)", fg: "var(--color-warning, #b45309)", label: "Pending review" },
    approved: { bg: "var(--color-success-bg, #dcfce7)", fg: "var(--color-success, #15803d)", label: "Approved" },
    rejected: { bg: "var(--color-danger-bg, #fee2e2)",  fg: "var(--color-danger, #b91c1c)",  label: "Rejected" },
  };
  const s = map[status] || map.pending;
  return (
    <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 999, background: s.bg, color: s.fg }}>
      {s.label}
    </span>
  );
}

export default function CorrectionRequestsPage() {
  const { selectedPatient } = usePatientContext();
  const { toastSuccess, toastError, toastApiError } = useToast();
  const { data: hospitalsData } = useApi(API_ENDPOINTS.PORTAL.HOSPITALS);
  const hospitals = hospitalsData?.results || [];

  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.COMPLIANCE.PORTAL_AMENDMENTS, {
    params: selectedPatient?.awpid ? { patient_awpid: selectedPatient.awpid } : {},
  });
  // COMPLIANCE.PORTAL_AMENDMENTS already scopes to patient_awpid server-side
  // (see apps/compliance/views.py::PortalRecordAmendmentView.get), so no
  // extra client-side filtering is needed here.
  const requests = data?.results || [];

  const [form, setForm] = useState({
    tenant_id: "", resource_type: "Patient", field_name: "",
    current_value: "", requested_value: "", reason: "",
  });
  const [submitting, setSubmitting] = useState(false);

  const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    if (!form.tenant_id) return toastError("Choose which hospital this request is for.");
    if (!form.field_name.trim()) return toastError("Tell us which field needs correcting.");
    if (!form.requested_value.trim()) return toastError("Enter what it should say instead.");

    setSubmitting(true);
    try {
      await apiClient.post(API_ENDPOINTS.COMPLIANCE.PORTAL_AMENDMENTS, {
        tenant_id: form.tenant_id,
        patient_awpid: selectedPatient?.awpid || undefined,
        resource_type: form.resource_type,
        field_name: form.field_name.trim(),
        current_value: form.current_value.trim(),
        requested_value: form.requested_value.trim(),
        reason: form.reason.trim(),
      });
      toastSuccess("Correction request submitted.");
      setForm({ tenant_id: "", resource_type: "Patient", field_name: "", current_value: "", requested_value: "", reason: "" });
      refetch();
    } catch (err) {
      toastApiError(err, "Could not submit this request.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AppShell>
      <PageShell title="Request a Correction">
        <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginBottom: 20, marginTop: -8, display: "flex", alignItems: "center", gap: 6 }}>
          <ShieldCheck size={14} /> Under the DPDP Act 2023, you can ask a hospital to correct inaccurate personal data they hold about you.
        </div>

        <form onSubmit={submit} className="card" style={{ padding: 20, marginBottom: 24, display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, display: "block" }}>Hospital</label>
              <select className="form-input" style={{ appearance: "auto" }} value={form.tenant_id} onChange={set("tenant_id")} required>
                <option value="">Select hospital…</option>
                {hospitals.map(h => <option key={h.tenant_id} value={h.tenant_id}>{h.name}</option>)}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, display: "block" }}>What kind of record?</label>
              <select className="form-input" style={{ appearance: "auto" }} value={form.resource_type} onChange={set("resource_type")}>
                {RESOURCE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, display: "block" }}>Which field is wrong?</label>
            <input className="form-input" placeholder="e.g. Date of birth, Phone number, Allergy list…"
              value={form.field_name} onChange={set("field_name")} required />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, display: "block" }}>What it currently says (optional)</label>
              <input className="form-input" value={form.current_value} onChange={set("current_value")} />
            </div>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, display: "block" }}>What it should say</label>
              <input className="form-input" value={form.requested_value} onChange={set("requested_value")} required />
            </div>
          </div>

          <div>
            <label style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, display: "block" }}>Reason (optional)</label>
            <textarea className="form-input" rows={2} value={form.reason} onChange={set("reason")} />
          </div>

          <div>
            <button type="submit" className="btn-primary" disabled={submitting}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, padding: "8px 18px" }}>
              <Send size={14} /> {submitting ? "Submitting…" : "Submit request"}
            </button>
          </div>
        </form>

        <h3 style={{ fontSize: 14, margin: "0 0 12px" }}>Your requests</h3>
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {isLoading ? (
            <div style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : requests.length === 0 ? (
            <div style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
              You haven't submitted any correction requests yet.
            </div>
          ) : (
            <div style={{ display: "grid" }}>
              {requests.map(r => (
                <div key={`${r.hospital}-${r.id}`} style={{ padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700 }}>{r.field_name}</div>
                      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                        {r.hospital} · requested {fmtDate(r.requested_at)}
                      </div>
                    </div>
                    <StatusPill status={r.status} />
                  </div>
                  <div style={{ fontSize: 12, marginTop: 6 }}>
                    Requested: <strong>{r.requested_value}</strong>
                  </div>
                  {r.status !== "pending" && r.review_notes && (
                    <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 6 }}>
                      Hospital's note: "{r.review_notes}"
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
