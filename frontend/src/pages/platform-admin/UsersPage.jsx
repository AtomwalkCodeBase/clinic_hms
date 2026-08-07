/**
 * pages/platform-admin/UsersPage.jsx
 * --------------------------------------
 * Global cross-tenant staff directory — every staff member at every
 * hospital, searchable/filterable, with disable-account and reset-password
 * actions. Backed by PlatformUserListView, which loops each tenant DB.
 */
import { useState, useEffect, useCallback } from "react";
import { Ban, CheckCircle2, KeyRound } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";

const ROLE_LABELS = {
  hospital_admin: "Hospital Admin", doctor: "Doctor", nurse: "Nurse",
  front_desk: "Front Desk", lab_tech: "Lab Technician", pharmacist: "Pharmacist",
};
const ROLES = Object.keys(ROLE_LABELS);

export default function UsersPage() {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [hospitals, setHospitals] = useState([]);
  const [hospitalFilter, setHospitalFilter] = useState("");
  const [busyKey, setBusyKey] = useState(null);
  const [pagination, setPagination] = useState(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.get(`${API_ENDPOINTS.PLATFORM.TENANTS}?page=1&page_size=100`)
      .then(({ data: res }) => setHospitals(res.data?.results || []))
      .catch(() => setHospitals([]));
  }, [api]);

  const fetchUsers = useCallback(async (targetPage) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(targetPage), page_size: "50" });
      if (search) params.set("search", search);
      if (roleFilter) params.set("role", roleFilter);
      if (statusFilter) params.set("status", statusFilter);
      if (hospitalFilter) params.set("hospital_id", hospitalFilter);
      const { data: res } = await api.get(`${API_ENDPOINTS.PLATFORM.USERS}?${params.toString()}`);
      setUsers(res.data?.results || []);
      setPagination(res.data?.pagination || null);
    } catch {
      setUsers([]);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, search, roleFilter, statusFilter, hospitalFilter]);

  useEffect(() => {
    const t = setTimeout(() => { setPage(1); fetchUsers(1); }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, roleFilter, statusFilter, hospitalFilter]);

  useEffect(() => {
    if (page !== 1) fetchUsers(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  async function toggleActive(u) {
    const key = `${u.hospital_id}:${u.id}`;
    setBusyKey(key);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT_STAFF_DETAIL(u.hospital_id, u.id), { is_active: !u.is_active });
      toastSuccess(`${u.full_name} ${u.is_active ? "deactivated" : "reactivated"}.`);
      fetchUsers(page);
    } catch (err) {
      toastApiError(err, "Failed to update.");
    } finally {
      setBusyKey(null);
    }
  }

  async function resetPassword(u) {
    const key = `${u.hospital_id}:${u.id}`;
    setBusyKey(key);
    try {
      const { data: res } = await api.post(API_ENDPOINTS.PLATFORM.TENANT_STAFF_RESET_PASSWORD(u.hospital_id, u.id));
      navigator.clipboard?.writeText(res.data.temp_password).catch(() => {});
      toastSuccess(`Temp password for ${u.email || u.full_name}: ${res.data.temp_password} (copied to clipboard)`, { duration: 15000 });
    } catch (err) {
      toastApiError(err, "Failed to reset password.");
    } finally {
      setBusyKey(null);
    }
  }

  async function changeRole(u, newRole) {
    if (newRole === u.role) return;
    const key = `${u.hospital_id}:${u.id}`;
    setBusyKey(key);
    try {
      await api.patch(API_ENDPOINTS.PLATFORM.TENANT_STAFF_DETAIL(u.hospital_id, u.id), { role: newRole });
      toastSuccess(`${u.full_name}'s role changed to ${ROLE_LABELS[newRole] || newRole}.`);
      fetchUsers(page);
    } catch (err) {
      toastApiError(err, "Failed to change role.");
    } finally {
      setBusyKey(null);
    }
  }

  const selectStyle = {
    padding: "9px 12px", borderRadius: 8, fontSize: 13.5,
    border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
    color: "var(--color-text)", outline: "none",
  };

  return (
    <AppShell>
      <PageShell title="Users">
        <div style={{ display: "flex", gap: 12, marginBottom: 18, flexWrap: "wrap" }}>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search name or email…"
            style={{
              flex: "1 1 220px", padding: "9px 14px", borderRadius: 8, fontSize: 14,
              border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
              color: "var(--color-text)", outline: "none",
            }}
          />
          <select value={hospitalFilter} onChange={e => setHospitalFilter(e.target.value)} style={selectStyle}>
            <option value="">All hospitals</option>
            {hospitals.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
          <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} style={selectStyle}>
            <option value="">All roles</option>
            {ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </select>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={selectStyle}>
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {loading ? (
            <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
          ) : users.length === 0 ? (
            <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>No users match.</div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Name", "Hospital", "Role", "Status", "Last Login", "Actions"].map(h => (
                      <th key={h} style={{ textAlign: "left", padding: "10px 14px", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-muted)" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => {
                    const key = `${u.hospital_id}:${u.id}`;
                    return (
                      <tr key={key} style={{ borderTop: "1px solid var(--color-border)" }}>
                        <td style={{ padding: "10px 14px", fontSize: 13.5 }}>
                          <div style={{ fontWeight: 600 }}>{u.full_name}</div>
                          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{u.email || "—"}</div>
                        </td>
                        <td style={{ padding: "10px 14px", fontSize: 13.5 }}>{u.hospital_name}</td>
                        <td style={{ padding: "10px 14px" }}>
                          <select value={u.role} disabled={busyKey === key}
                            onChange={e => changeRole(u, e.target.value)}
                            style={{ padding: "5px 8px", borderRadius: 6, fontSize: 12.5, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)" }}>
                            {ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                          </select>
                        </td>
                        <td style={{ padding: "10px 14px" }}>
                          <span className={`badge badge--${u.is_active ? "success" : "error"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                        </td>
                        <td style={{ padding: "10px 14px", fontSize: 12.5, color: "var(--color-text-muted)" }}>
                          {u.last_login ? new Date(u.last_login).toLocaleDateString() : "Never"}
                        </td>
                        <td style={{ padding: "10px 14px" }}>
                          <div style={{ display: "flex", gap: 6 }}>
                            <button onClick={() => resetPassword(u)} disabled={busyKey === key}
                              title="Reset password"
                              style={{ background: "none", border: "1.5px solid var(--color-border)", borderRadius: 6, padding: "4px 8px", cursor: "pointer" }}>
                              <KeyRound size={13} />
                            </button>
                            <button onClick={() => toggleActive(u)} disabled={busyKey === key}
                              title={u.is_active ? "Deactivate" : "Reactivate"}
                              style={{
                                background: "none", borderRadius: 6, padding: "4px 8px", cursor: "pointer",
                                border: `1.5px solid ${u.is_active ? "var(--color-error)" : "var(--color-success)"}`,
                                color: u.is_active ? "var(--color-error)" : "var(--color-success)",
                              }}>
                              {u.is_active ? <Ban size={13} /> : <CheckCircle2 size={13} />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {pagination && pagination.total_pages > 1 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 20 }}>
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={!pagination.has_previous}
              style={{ padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", cursor: pagination.has_previous ? "pointer" : "not-allowed", opacity: pagination.has_previous ? 1 : 0.5 }}>
              ← Previous
            </button>
            <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
              Page {pagination.page} of {pagination.total_pages} · {pagination.total_count} users
            </span>
            <button onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))} disabled={!pagination.has_next}
              style={{ padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-text)", cursor: pagination.has_next ? "pointer" : "not-allowed", opacity: pagination.has_next ? 1 : 0.5 }}>
              Next →
            </button>
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
