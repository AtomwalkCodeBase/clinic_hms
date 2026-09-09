/**
 * pages/front-desk/AdmissionsPage.jsx
 * -------------------------------------
 * IPD Admission — Phase 1 (admission intake) only.
 *
 * Deliberately has NO "create admission" button anywhere on this page.
 * Front desk can only act on a referral a doctor already recommended
 * (RecommendAdmissionView, apps/ipd/views.py, IsDoctor-gated) — see the
 * callout below and the knowledge-map discussion this page implements.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const TYPE_BADGE = {
  emergency: "badge--error",
  urgent:    "badge--warning",
  elective:  "badge--primary",
  day_care:  "badge--info",
  newborn:   "badge--success",
};

function timeAgo(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return new Date(iso).toLocaleDateString();
}

function CompleteAdmissionModal({ referral, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [form, setForm] = useState({
    attendant_name: "", attendant_phone: "",
    payer_type: "self", insurance_provider: "",
    expected_discharge_date: "", consent_given: false,
  });
  const [saving, setSaving] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const submit = async () => {
    if (!form.consent_given) {
      toastApiError({ message: "Consent must be captured before completing registration." });
      return;
    }
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_REGISTER, {
        referral_id: referral.id,
        attendant_name: form.attendant_name,
        attendant_phone: form.attendant_phone,
        payer_type: form.payer_type,
        insurance_provider: form.insurance_provider,
        expected_discharge_date: form.expected_discharge_date || null,
        consent_given: form.consent_given,
      });
      toastSuccess(`Admission completed — ${referral.patient_name} moved to bed allocation queue.`);
      onDone();
    } catch (err) {
      toastApiError(err, "Could not complete registration.");
    } finally {
      setSaving(false);
    }
  };

  const requiresAcceptance = referral.requires_acceptance;
  const blockedOnAcceptance = requiresAcceptance && !referral.accepted_by;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(12,42,31,0.35)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
      <div className="card" style={{ width: 640, maxHeight: "88vh", overflowY: "auto" }}>
        <div className="page-header" style={{ marginBottom: 14 }}>
          <div className="page-title" style={{ fontSize: 20 }}>Complete Admission</div>
          <button className="btn-outline" onClick={onClose}>Cancel</button>
        </div>

        <div style={{ background: "var(--color-table-header)", border: "1px dashed var(--color-border)", borderRadius: "var(--radius-card)", padding: 16, marginBottom: 18 }}>
          <div className="dot-label" style={{ marginBottom: 10 }}>Doctor's Referral — read-only</div>
          <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 4 }}>{referral.patient_name} · UHID {referral.patient_uhid}</div>
          <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            Ordered by <b>{referral.recommended_by_name}</b> · {referral.department_name}
            {" "}<span className={`badge ${TYPE_BADGE[referral.admission_type] || "badge--neutral"}`}>{referral.admission_type}</span>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)" }}>{referral.reason_for_admission}</div>
          {requiresAcceptance && (
            <div style={{ marginTop: 8, fontSize: 11.5 }}>
              {referral.accepted_by
                ? <span className="badge badge--success">Countersigned by {referral.accepted_by_name}</span>
                : <span className="badge badge--warning">Awaiting a hospital doctor's countersign</span>}
            </div>
          )}
        </div>

        {blockedOnAcceptance ? (
          <div className="callout">
            <div>
              <div className="callout-title">Cannot register yet</div>
              <div className="callout-body">
                This referral came from outside the hospital ({referral.admission_source}) and needs one of
                this hospital's own doctors to accept it before front desk can complete registration.
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="form-grid-2">
              <div className="form-field">
                <label className="form-label">Attendant / Next of Kin — Name</label>
                <input className="form-input" value={form.attendant_name} onChange={set("attendant_name")} placeholder="e.g. Sunita Kumar (spouse)" />
              </div>
              <div className="form-field">
                <label className="form-label">Attendant Phone</label>
                <input className="form-input" value={form.attendant_phone} onChange={set("attendant_phone")} placeholder="+91 9xxxxxxxxx" />
              </div>
            </div>
            <div className="form-grid-2">
              <div className="form-field">
                <label className="form-label">Payer Type</label>
                <select className="form-input" value={form.payer_type} onChange={set("payer_type")}>
                  <option value="self">Self Pay</option>
                  <option value="insurance">Insurance</option>
                  <option value="corporate">Corporate</option>
                </select>
              </div>
              <div className="form-field">
                <label className="form-label">Insurance Provider</label>
                <input className="form-input" value={form.insurance_provider} onChange={set("insurance_provider")} />
              </div>
            </div>
            <div className="form-field" style={{ maxWidth: 220 }}>
              <label className="form-label">Expected Discharge Date</label>
              <input className="form-input" type="date" value={form.expected_discharge_date} onChange={set("expected_discharge_date")} />
              <div className="hint">Planning estimate — not a hard constraint</div>
            </div>
            <div className="form-field" style={{ background: "var(--color-bg)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-input)", padding: "12px 14px" }}>
              <div className="checkbox-row" style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                <input type="checkbox" checked={form.consent_given} onChange={set("consent_given")} style={{ marginTop: 3 }} />
                <label style={{ fontSize: 12.5, color: "var(--color-text-secondary)" }}>
                  Patient / attendant consents to inpatient treatment and admission (recorded as a DPDP-style consent event).
                </label>
              </div>
            </div>
            <button className="btn-primary" disabled={saving || !form.consent_given} onClick={submit}>
              {saving ? "Saving…" : "Complete Registration & Mark Admitted"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function AdmissionsPage() {
  const { data: referrals, isLoading, refetch } = useApi(API_ENDPOINTS.IPD.REFERRALS, { params: { status: "pending" } });
  const { data: admitted } = useApi(API_ENDPOINTS.IPD.ADMISSIONS, { params: { status: "admitted" } });
  const [active, setActive] = useState(null);

  return (
    <AppShell>
      <PageShell title="Admissions">
        <div className="callout">
          <div>
            <div className="callout-title">Front desk completes registration only</div>
            <div className="callout-body">
              The clinical decision to admit always starts with a doctor's referral. There is no
              "create admission" action here — only the worklist below, populated by doctors via
              Recommend Admission.
            </div>
          </div>
        </div>

        <div className="dot-label">Pending Registration ({referrals?.length ?? (isLoading ? "…" : 0)})</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 26 }}>
          {(referrals || []).map((r) => (
            <div key={r.id} className="card card--interactive" style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 14.5 }}>{r.patient_name}</span>
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>UHID {r.patient_uhid}</span>
                  <span className={`badge ${TYPE_BADGE[r.admission_type] || "badge--neutral"}`}>{r.admission_type}</span>
                  {r.requires_acceptance && !r.accepted_by && <span className="badge badge--warning">Needs doctor countersign</span>}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)" }}>
                  Ordered by <b>{r.recommended_by_name}</b> · {r.department_name}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--color-text-secondary)", marginTop: 4 }}>{r.reason_for_admission}</div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
                <span style={{ fontSize: 11, color: "var(--color-text-disabled)" }}>{timeAgo(r.recommended_at)}</span>
                <button className="btn-primary" onClick={() => setActive(r)}>Complete Registration</button>
              </div>
            </div>
          ))}
          {!isLoading && (referrals || []).length === 0 && (
            <div className="card" style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
              No admissions are waiting on registration right now.
            </div>
          )}
        </div>

        <div className="dot-label dot-label--muted">Admitted — Awaiting Bed ({admitted?.length ?? 0})</div>
        <div className="card" style={{ padding: "6px 16px" }}>
          {(admitted || []).map((a) => (
            <div key={a.id} style={{ display: "flex", justifyContent: "space-between", padding: "10px 4px", borderBottom: "1px solid var(--color-border)", fontSize: 12.5 }}>
              <span style={{ fontWeight: 600 }}>{a.patient_name} — {a.admission_number}</span>
              <span style={{ color: "var(--color-text-muted)" }}>{new Date(a.created_at).toLocaleString()}</span>
            </div>
          ))}
          {(admitted || []).length === 0 && <div style={{ padding: "10px 4px", fontSize: 12.5, color: "var(--color-text-muted)" }}>None yet today.</div>}
        </div>
      </PageShell>

      {active && (
        <CompleteAdmissionModal
          referral={active}
          onClose={() => setActive(null)}
          onDone={() => { setActive(null); refetch(); }}
        />
      )}
    </AppShell>
  );
}
