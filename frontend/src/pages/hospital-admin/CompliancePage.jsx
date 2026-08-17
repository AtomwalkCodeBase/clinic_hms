/**
 * pages/hospital-admin/CompliancePage.jsx
 * ------------------------------------------
 * Hospital admin: DPDP Act compliance tooling. Three tabs:
 *   - Audit Log — every PHI access recorded via core.audit.log_action()
 *     (apps.org.AuditLog), read through apps.compliance.AuditLogListView.
 *   - Correction Requests — patient-submitted RecordAmendment rows
 *     (DPDP Art. 13); approve/reject here, apply the actual field edit
 *     through the normal record screen first.
 *   - Consent Records — the append-only ConsentRecord proof trail behind
 *     each patient's dpdp_consent_captured / hie_consent_given flags.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import PaginationControls from "../../components/common/PaginationControls";
import { useApi }    from "../../hooks/useApi";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { ShieldCheck, FileClock, FileSearch, Check, X } from "lucide-react";

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function StatusPill({ status }) {
  const map = {
    pending:  { bg: "var(--color-warning-bg, #fef3c7)", fg: "var(--color-warning, #b45309)", label: "Pending" },
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

/* ── Audit Log tab ─────────────────────────────────────────────────────── */
function AuditLogTab() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [action, setAction] = useState("");

  const { data, isLoading } = useApi(API_ENDPOINTS.COMPLIANCE.AUDIT_LOG, {
    params: { page, page_size: pageSize, action: action || undefined },
  });
  const rows = data?.results || [];
  const pagination = data?.pagination || null;

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid var(--color-border)", flexWrap: "wrap", gap: 10 }}>
        <span className="dot-label dot-label--blue">
          Every recorded PHI access at this hospital
        </span>
        <input
          className="form-input" style={{ width: 220 }} placeholder="Filter by action (e.g. patient.view)"
          value={action} onChange={e => { setAction(e.target.value); setPage(1); }}
        />
      </div>
      {isLoading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>No access-log entries match this filter.</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>When</th><th>Actor</th><th>Action</th><th>Resource</th><th>IP</th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td style={{ fontSize: 12 }}>{fmtDate(r.created_at)}</td>
                <td style={{ fontSize: 12 }}>
                  {r.actor_email || "—"}
                  {r.actor_role && <span style={{ color: "var(--color-text-muted)" }}> · {r.actor_role}</span>}
                </td>
                <td style={{ fontSize: 12, fontWeight: 700 }}>{r.action}</td>
                <td style={{ fontSize: 12 }}>{r.resource_type}{r.resource_id ? ` #${r.resource_id}` : ""}</td>
                <td style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{r.ip_address || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <PaginationControls pagination={pagination} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={setPageSize} />
    </div>
  );
}

/* ── Correction Requests tab ──────────────────────────────────────────── */
function AmendmentsTab() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState("pending");
  const [busyId, setBusyId] = useState(null);
  const [noteDraft, setNoteDraft] = useState({});

  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.COMPLIANCE.AMENDMENTS, {
    params: { page, page_size: pageSize, status: status || undefined },
  });
  const rows = data?.results || [];
  const pagination = data?.pagination || null;

  async function resolve(id, decision) {
    setBusyId(id);
    try {
      await apiClient.post(API_ENDPOINTS.COMPLIANCE.AMENDMENT_RESOLVE(id), {
        status: decision,
        review_notes: noteDraft[id] || "",
      });
      refetch();
    } catch (err) {
      alert(err?.response?.data?.message || "Could not resolve this request.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid var(--color-border)", flexWrap: "wrap", gap: 10 }}>
        <span className="dot-label dot-label--gold">
          Patient-submitted correction requests (DPDP Art. 13)
        </span>
        <select className="form-input" style={{ width: 170, appearance: "auto" }} value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}>
          <option value="pending">Pending review</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
      </div>
      {isLoading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>No requests in this view.</div>
      ) : (
        <div style={{ display: "grid", gap: 0 }}>
          {rows.map(r => (
            <div key={r.id} style={{ padding: "16px 20px", borderBottom: "1px solid var(--color-border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>
                    {r.patient_name} <span style={{ color: "var(--color-text-muted)", fontWeight: 400 }}>· {r.patient_uhid}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 2 }}>
                    {r.resource_type} #{r.resource_id} — field <strong>{r.field_name}</strong> — requested {fmtDate(r.requested_at)}
                  </div>
                </div>
                <StatusPill status={r.status} />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
                <div style={{ fontSize: 12 }}>
                  <div style={{ color: "var(--color-text-muted)", marginBottom: 2 }}>Current value</div>
                  <div>{r.current_value || <em style={{ color: "var(--color-text-muted)" }}>not provided</em>}</div>
                </div>
                <div style={{ fontSize: 12 }}>
                  <div style={{ color: "var(--color-text-muted)", marginBottom: 2 }}>Requested value</div>
                  <div style={{ fontWeight: 700 }}>{r.requested_value}</div>
                </div>
              </div>
              {r.reason && (
                <div style={{ fontSize: 12, marginTop: 8 }}>
                  <span style={{ color: "var(--color-text-muted)" }}>Reason: </span>{r.reason}
                </div>
              )}

              {r.status === "pending" ? (
                <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <input
                    className="form-input" style={{ flex: 1, minWidth: 200, fontSize: 12 }}
                    placeholder="Review notes (optional)"
                    value={noteDraft[r.id] || ""}
                    onChange={e => setNoteDraft(d => ({ ...d, [r.id]: e.target.value }))}
                  />
                  <button className="btn-primary" style={{ fontSize: 12, padding: "6px 14px", display: "flex", alignItems: "center", gap: 6 }}
                    disabled={busyId === r.id} onClick={() => resolve(r.id, "approved")}>
                    <Check size={13} /> Approve
                  </button>
                  <button className="btn-outline" style={{ fontSize: 12, padding: "6px 14px", display: "flex", alignItems: "center", gap: 6 }}
                    disabled={busyId === r.id} onClick={() => resolve(r.id, "rejected")}>
                    <X size={13} /> Reject
                  </button>
                </div>
              ) : (
                <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 8 }}>
                  Resolved {fmtDate(r.resolved_at)} by {r.reviewed_by_name || "—"}
                  {r.review_notes && ` — "${r.review_notes}"`}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <PaginationControls pagination={pagination} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={setPageSize} />
    </div>
  );
}

/* ── Consent Records tab ──────────────────────────────────────────────── */
function ConsentsTab() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [patientId, setPatientId] = useState("");

  const { data, isLoading } = useApi(API_ENDPOINTS.COMPLIANCE.CONSENTS, {
    params: { page, page_size: pageSize, patient_id: patientId || undefined },
  });
  const rows = data?.results || [];
  const pagination = data?.pagination || null;

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", borderBottom: "1px solid var(--color-border)", flexWrap: "wrap", gap: 10 }}>
        <span className="dot-label dot-label--green">
          Consent proof trail — DPDP data processing + cross-hospital sharing
        </span>
        <input
          className="form-input" style={{ width: 160 }} placeholder="Filter by patient ID"
          value={patientId} onChange={e => { setPatientId(e.target.value); setPage(1); }}
        />
      </div>
      {isLoading ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>No consent records match this filter.</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>When</th><th>Patient</th><th>Type</th><th>Source</th><th>Recorded by</th><th>Policy</th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td style={{ fontSize: 12 }}>{fmtDate(r.created_at)}</td>
                <td style={{ fontSize: 12 }}>{r.patient_name} <span style={{ color: "var(--color-text-muted)" }}>· {r.patient_uhid}</span></td>
                <td style={{ fontSize: 12 }}>{r.consent_type_display}</td>
                <td style={{ fontSize: 12 }}>{r.source_display}</td>
                <td style={{ fontSize: 12 }}>{r.recorded_by_name || <em style={{ color: "var(--color-text-muted)" }}>patient (self)</em>}</td>
                <td style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{r.policy_version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <PaginationControls pagination={pagination} page={page} pageSize={pageSize} onPageChange={setPage} onPageSizeChange={setPageSize} />
    </div>
  );
}

export default function CompliancePage() {
  const [tab, setTab] = useState("amendments");

  const tabs = [
    ["amendments", "Correction Requests", FileClock],
    ["audit", "Audit Log", FileSearch],
    ["consents", "Consent Records", ShieldCheck],
  ];

  return (
    <AppShell>
      <PageShell title="Compliance">
        <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginBottom: 16, marginTop: -8 }}>
          DPDP Act 2023 — access audit trail, correction requests, and consent proof.
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
          {tabs.map(([val, label, Icon]) => (
            <button key={val} className={tab === val ? "btn-primary" : "btn-outline"}
              style={{ fontSize: 12, padding: "6px 16px", display: "flex", alignItems: "center", gap: 6 }}
              onClick={() => setTab(val)}>
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>

        {tab === "amendments" && <AmendmentsTab />}
        {tab === "audit" && <AuditLogTab />}
        {tab === "consents" && <ConsentsTab />}
      </PageShell>
    </AppShell>
  );
}
