/**
 * pages/front-desk/IpdPatientsPage.jsx
 * ---------------------------------------
 * "Current Patients" — the single, always-reachable place to find anyone
 * currently admitted, added directly in response to feedback that a
 * front-desk user had no obvious way to find a patient right after
 * completing their admission (it used to be a tab buried inside the
 * Admissions page, only visible in that page's non-embedded view). This
 * page is a permanent sidebar item under IPD.
 *
 * Reuses IPD.ADMISSIONS (the same AdmissionSerializer list every other
 * admission screen already calls) filtered client-side to admitted/active
 * stays — discharged and cancelled admissions belong in Visit History, not
 * here.
 */
import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi } from "../../hooks/useApi";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES } from "../../config/routes.config";

function timeAgo(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return new Date(iso).toLocaleDateString();
}

const FILTERS = [
  { key: "all",      label: "All" },
  { key: "bedded",   label: "Bed Assigned" },
  { key: "awaiting", label: "Awaiting Bed" },
];

export default function IpdPatientsPage() {
  const navigate = useNavigate();
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.IPD.ADMISSIONS, { pollMs: 30000 });
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");

  const current = useMemo(
    () => (data || []).filter((a) => a.status === "admitted" || a.status === "active"),
    [data],
  );

  const filtered = useMemo(() => {
    let rows = current;
    if (filter === "bedded") rows = rows.filter((a) => !!a.bed);
    if (filter === "awaiting") rows = rows.filter((a) => !a.bed);
    const q = query.trim().toLowerCase();
    if (q) {
      rows = rows.filter((a) =>
        a.patient_name?.toLowerCase().includes(q) ||
        a.patient_uhid?.toLowerCase().includes(q) ||
        a.admission_number?.toLowerCase().includes(q) ||
        a.department_name?.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [current, filter, query]);

  const counts = {
    all: current.length,
    bedded: current.filter((a) => !!a.bed).length,
    awaiting: current.filter((a) => !a.bed).length,
  };

  return (
    <AppShell>
      <PageShell title="">
        <div className="fdc-header-row">
          <div>
            <div className="fdc-eyebrow">Front Desk &middot; IPD</div>
            <div className="fdc-title">Current Patients</div>
            <div className="fdc-subtitle">Every patient who is currently admitted — search by name, UHID, admission number, or department.</div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
          <div style={{ position: "relative", flex: "1 1 320px", maxWidth: 420 }}>
            <Search size={15} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search current patients…"
              style={{
                width: "100%", boxSizing: "border-box", padding: "9px 12px 9px 34px", borderRadius: 8,
                border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
                color: "var(--color-text)", fontSize: 13.5, outline: "none",
              }}
            />
          </div>
          <div className="fdc-tabs">
            {FILTERS.map((f) => (
              <button key={f.key} type="button"
                className={"fdc-tab" + (filter === f.key ? " active" : "")}
                onClick={() => setFilter(f.key)}>
                {f.label} ({counts[f.key]})
              </button>
            ))}
          </div>
          <button className="fdc-panel-link" onClick={refetch} style={{ marginLeft: "auto" }}>Refresh</button>
        </div>

        <div className="fdc-panel" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="fdc-table">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Admission #</th>
                  <th>Department</th>
                  <th>Bed / Ward</th>
                  <th>Status</th>
                  <th>Admitted</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => (
                  <tr key={a.id} style={{ cursor: "pointer" }}
                    onClick={() => navigate(ROUTES.FRONT_DESK.ADMISSION_DETAIL(a.id))}>
                    <td>
                      <div style={{ fontWeight: 700 }}>{a.patient_name}</div>
                      <div className="fine">UHID {a.patient_uhid}</div>
                    </td>
                    <td className="iw-mono">{a.admission_number}</td>
                    <td>{a.department_name}</td>
                    <td>
                      {a.bed_number
                        ? `${a.room_name ? a.room_name + " · " : ""}Bed ${a.bed_number}`
                        : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                    </td>
                    <td>
                      <span className={"fdc-pill " + (a.bed ? "fdc-pill-done" : "fdc-pill-waiting")}>
                        {a.bed ? "Bed assigned" : "Awaiting bed"}
                      </span>
                    </td>
                    <td className="fine">{timeAgo(a.created_at)}</td>
                  </tr>
                ))}
                {!isLoading && filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", padding: 28, color: "var(--color-text-muted)" }}>
                      {query || filter !== "all" ? "No matching patients." : "No patients currently admitted."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </PageShell>
    </AppShell>
  );
}
