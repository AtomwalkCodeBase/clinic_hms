/**
 * pages/nurse/DashboardPage.jsx
 * --------------------------------
 * Nurse dashboard — shows today's queue with a focus on vitals pending.
 * Quick-action: click any waiting patient to go to VitalsPage.
 */

import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell }   from "../../components/layout/AppShell";
import { PageShell }  from "../../components/common/PageShell";
import { useToast }   from "../../hooks/useToast";
import { useApi }     from "../../hooks/useApi";
import PaginationControls from "../../components/common/PaginationControls";
import apiClient      from "../../services/api.client";
import API_ENDPOINTS  from "../../config/api.config";
import {
  AlertCircle, ClipboardList, CalendarClock, ChevronDown, ChevronUp,
  Filter, X, Stethoscope,
} from "lucide-react";

// Groups a flat appointment list into [ [doctorName, items[]], ... ] sorted
// alphabetically by doctor — a nurse assigned to more than one doctor
// otherwise sees every patient jumbled together with no way to tell whose
// queue is whose.
function groupByDoctor(list) {
  const map = new Map();
  for (const a of list) {
    const key = a.doctor_name || "Unassigned";
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(a);
  }
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

const TODAY = new Date().toISOString().slice(0, 10);
const TOMORROW = (() => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
})();

function formatScheduleDate(dateStr) {
  if (dateStr === TODAY) return "Today";
  if (dateStr === TOMORROW) return "Tomorrow";
  try {
    return new Date(dateStr + "T00:00:00").toLocaleDateString("en-IN", {
      weekday: "short", day: "2-digit", month: "short",
    });
  } catch {
    return dateStr;
  }
}

const STATUS_CONFIG = {
  scheduled:    { label: "Scheduled",    color: "#64748b", bg: "#f1f5f9" },
  waiting:      { label: "Waiting",      color: "#d97706", bg: "#fef3c7" },
  vitals_done:  { label: "Vitals Done",  color: "#0891b2", bg: "#e0f2fe" },
  in_progress:  { label: "With Doctor",  color: "#7c3aed", bg: "#ede9fe" },
  done:         { label: "Done",         color: "#16a34a", bg: "#dcfce7" },
  cancelled:    { label: "Cancelled",    color: "#dc2626", bg: "#fee2e2" },
};

function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status] || { label: status, color: "#64748b", bg: "#f1f5f9" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 9px", borderRadius: 20,
      fontSize: 11, fontWeight: 600, background: c.bg, color: c.color,
    }}>{c.label}</span>
  );
}

export default function NurseDashboardPage() {
  const navigate = useNavigate();
  const { toastApiError } = useToast();

  const [appointments, setAppointments] = useState([]);
  const [loading,      setLoading]      = useState(true);

  useEffect(() => {
    setLoading(true);
    apiClient.get(`${API_ENDPOINTS.OPD.APPOINTMENTS}?date=${TODAY}`)
      .then(r => setAppointments(r.data?.results || r.data?.data || []))
      .catch(() => toastApiError(null, "Failed to load today's queue."))
      .finally(() => setLoading(false));
  }, []);

  // ── Today's Queue — search + status filter, grouped by doctor. Filtered
  // client-side (the full unfiltered `appointments` list is already loaded
  // above, and the stat cards need that full list's true counts, so
  // filtering happens only on what's displayed here, not on the fetch).
  const [showTodayFilters, setShowTodayFilters] = useState(false);
  const [todaySearch,      setTodaySearch]      = useState("");
  const [todayStatusFilter, setTodayStatusFilter] = useState("");
  const hasActiveTodayFilters = !!(todaySearch || todayStatusFilter);

  const filteredAppointments = useMemo(() => {
    const q = todaySearch.trim().toLowerCase();
    return appointments.filter(a => {
      if (todayStatusFilter && a.status !== todayStatusFilter) return false;
      if (!q) return true;
      return [a.patient_name, a.patient_uhid, a.chief_complaint, String(a.token_number || "")]
        .some(v => (v || "").toLowerCase().includes(q));
    });
  }, [appointments, todaySearch, todayStatusFilter]);

  const todayByDoctor = useMemo(() => groupByDoctor(filteredAppointments), [filteredAppointments]);

  // ── Upcoming schedule — everything from tomorrow onward, for the
  // doctor(s) this nurse is assigned to (server-side scoped, same as the
  // queue above — see NurseDoctorAssignment). Mirrors the doctor
  // dashboard's own upcoming-schedule panel: collapsed to 5 by default,
  // full pagination once expanded. Search/status filter go straight to the
  // backend (same params AppointmentUpcomingView already supports) since
  // this list is itself paginated server-side, unlike today's queue above.
  const [upcomingExpanded, setUpcomingExpanded] = useState(false);
  const [upcomingPage, setUpcomingPage] = useState(1);
  const [upcomingPageSize, setUpcomingPageSize] = useState(5);
  const [showUpcomingFilters, setShowUpcomingFilters] = useState(false);
  const [upcomingSearch, setUpcomingSearch] = useState("");
  const [upcomingStatusFilter, setUpcomingStatusFilter] = useState("");
  const hasActiveUpcomingFilters = !!(upcomingSearch || upcomingStatusFilter);

  const { data: upcomingData, isLoading: upcomingLoading } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS_UPCOMING, {
    params: {
      date_from: TOMORROW,
      page: upcomingPage,
      page_size: upcomingExpanded ? upcomingPageSize : 5,
      ...(upcomingSearch ? { patient: upcomingSearch } : {}),
      ...(upcomingStatusFilter ? { status: upcomingStatusFilter } : {}),
    },
    pollMs: 30000,
  });
  const upcomingList = useMemo(() => upcomingData?.results || [], [upcomingData]);
  const upcomingPagination = upcomingData?.pagination || null;
  const upcomingRemaining = Math.max(0, (upcomingPagination?.total_count || 0) - upcomingList.length);
  const upcomingByDoctor = useMemo(() => groupByDoctor(upcomingList), [upcomingList]);

  // Re-page to 1 whenever a filter changes, so a narrowed result set doesn't
  // land on what's now an out-of-range page.
  useEffect(() => { setUpcomingPage(1); }, [upcomingSearch, upcomingStatusFilter]);

  function collapseUpcoming() {
    setUpcomingExpanded(false);
    setUpcomingPage(1);
    setUpcomingPageSize(5);
  }

  const waiting     = appointments.filter(a => a.status === "waiting" || a.status === "scheduled");
  const vitalsDone  = appointments.filter(a => a.status === "vitals_done");
  const withDoctor  = appointments.filter(a => a.status === "in_progress");
  const done        = appointments.filter(a => a.status === "done");

  const stats = [
    { label: "Total",        value: appointments.length, color: "#5B52EE" },
    { label: "Needs Vitals", value: waiting.length,      color: "#d97706" },
    { label: "Vitals Done",  value: vitalsDone.length,   color: "#0891b2" },
    { label: "With Doctor",  value: withDoctor.length,   color: "#7c3aed" },
    { label: "Completed",    value: done.length,         color: "#16a34a" },
  ];

  return (
    <AppShell>
      <PageShell title="Nurse Dashboard">

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 24 }}>
          {stats.map(s => (
            <div key={s.label} className="card" style={{ padding: "16px 20px", textAlign: "center" }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Needs Vitals — primary action area */}
        {waiting.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 15 }}>
                <AlertCircle size={15} /> Needs Vitals ({waiting.length})
              </div>
              <button className="btn-primary" onClick={() => navigate("/nurse/vitals")}
                style={{ fontSize: 13, padding: "7px 16px" }}>
                Open Vitals Entry →
              </button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {waiting.map(appt => (
                <div key={appt.id} className="card"
                  onClick={() => navigate("/nurse/vitals")}
                  style={{ padding: "12px 20px", cursor: "pointer", display: "flex", alignItems: "center", gap: 14,
                    border: "1.5px solid #fde68a", background: "#fffbeb" }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: "50%",
                    background: "#d97706", color: "#fff",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontWeight: 700, fontSize: 14, flexShrink: 0,
                  }}>
                    {appt.token_number || "?"}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>{appt.patient_name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                      {appt.patient_uhid}
                      {appt.scheduled_time && ` · ${appt.scheduled_time.slice(0, 5)}`}
                      {appt.room_name && ` · ${appt.room_name}${appt.floor ? ` (Fl ${appt.floor})` : ""}`}
                      {appt.chief_complaint && ` · ${appt.chief_complaint}`}
                    </div>
                    {appt.doctor_name && (
                      <div style={{ fontSize: 11, color: "#92400e", display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
                        <Stethoscope size={11} /> Dr. {appt.doctor_name}
                      </div>
                    )}
                  </div>
                  <StatusBadge status={appt.status} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Full queue — search + status filter, grouped by doctor */}
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>
              Today's Queue
            </div>
            <button
              className={hasActiveTodayFilters ? "btn-primary" : "btn-outline"}
              style={{ fontSize: 12, padding: "5px 14px", display: "flex", alignItems: "center", gap: 6 }}
              onClick={() => setShowTodayFilters(v => !v)}
            >
              <Filter size={13} /> Filters{hasActiveTodayFilters ? " •" : ""}
            </button>
          </div>

          {showTodayFilters && (
            <div className="card" style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10,
              padding: "14px 16px", marginBottom: 10,
            }}>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Search</label>
                <input className="form-input" placeholder="Patient name, UHID, token, complaint…"
                  value={todaySearch} onChange={e => setTodaySearch(e.target.value)} />
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Status</label>
                <select className="form-input" style={{ appearance: "auto" }} value={todayStatusFilter} onChange={e => setTodayStatusFilter(e.target.value)}>
                  <option value="">All statuses</option>
                  <option value="scheduled">Scheduled</option>
                  <option value="waiting">Waiting</option>
                  <option value="vitals_done">Vitals Done</option>
                  <option value="in_progress">With Doctor</option>
                  <option value="done">Done</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
              {hasActiveTodayFilters && (
                <div style={{ display: "flex", alignItems: "flex-end" }}>
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "8px 12px", display: "flex", alignItems: "center", gap: 4 }}
                    onClick={() => { setTodaySearch(""); setTodayStatusFilter(""); }}>
                    <X size={12} /> Clear
                  </button>
                </div>
              )}
            </div>
          )}

          {loading ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
              Loading…
            </div>
          ) : appointments.length === 0 ? (
            <div className="card" style={{ padding: 60, textAlign: "center" }}>
              <ClipboardList size={40} style={{ color: "var(--color-text-muted)", marginBottom: 12 }} />
              <div style={{ fontWeight: 600, marginBottom: 6 }}>No appointments today</div>
              <div style={{ color: "var(--color-text-muted)", fontSize: 14 }}>
                Patients will appear here once appointments are booked.
              </div>
            </div>
          ) : filteredAppointments.length === 0 ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
              No patients match these filters.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              {todayByDoctor.map(([doctorName, items]) => (
                <div key={doctorName}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700,
                    color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.04em",
                    marginBottom: 8,
                  }}>
                    <Stethoscope size={13} /> Dr. {doctorName} ({items.length})
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {items.map(appt => (
                      <div key={appt.id} className="card" style={{ padding: "12px 20px", display: "flex", alignItems: "center", gap: 14 }}>
                        <div style={{
                          width: 36, height: 36, borderRadius: "50%",
                          background: "var(--color-primary-light)", color: "var(--color-primary)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontWeight: 700, fontSize: 14, flexShrink: 0,
                        }}>
                          {appt.token_number || "?"}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600 }}>{appt.patient_name}</div>
                          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                            {appt.patient_uhid}
                            {appt.scheduled_time && ` · ${appt.scheduled_time.slice(0, 5)}`}
                            {appt.room_name && ` · ${appt.room_name}${appt.floor ? ` (Fl ${appt.floor})` : ""}`}
                            {appt.chief_complaint && ` · ${appt.chief_complaint}`}
                          </div>
                        </div>
                        <StatusBadge status={appt.status} />
                        {(appt.status === "waiting" || appt.status === "scheduled") && (
                          <button onClick={() => navigate("/nurse/vitals")}
                            className="btn-primary"
                            style={{ fontSize: 12, padding: "5px 12px" }}>
                            Enter Vitals
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Upcoming schedule (tomorrow onward, assigned doctor(s) only) ── */}
        <div className="card" style={{ padding: 0, overflow: "hidden", marginTop: 22 }}>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)", flexWrap: "wrap", gap: 8,
          }}>
            <span style={{ display: "flex", alignItems: "center", gap: 7, fontWeight: 700, fontSize: 15 }}>
              <CalendarClock size={15} /> Upcoming Schedule
            </span>
            <button
              className={hasActiveUpcomingFilters ? "btn-primary" : "btn-outline"}
              style={{ fontSize: 12, padding: "5px 14px", display: "flex", alignItems: "center", gap: 6 }}
              onClick={() => setShowUpcomingFilters(v => !v)}
            >
              <Filter size={13} /> Filters{hasActiveUpcomingFilters ? " •" : ""}
            </button>
          </div>

          {showUpcomingFilters && (
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10,
              padding: "14px 20px", borderBottom: "1px solid var(--color-border)", background: "var(--color-bg)",
            }}>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Search</label>
                <input className="form-input" placeholder="Patient name, UHID, mobile…"
                  value={upcomingSearch} onChange={e => setUpcomingSearch(e.target.value)} />
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Status</label>
                <select className="form-input" style={{ appearance: "auto" }} value={upcomingStatusFilter} onChange={e => setUpcomingStatusFilter(e.target.value)}>
                  <option value="">All (except cancelled/no-show)</option>
                  <option value="scheduled">Scheduled</option>
                  <option value="waiting">Waiting</option>
                  <option value="vitals_done">Vitals Done</option>
                  <option value="in_progress">With Doctor</option>
                  <option value="done">Done</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
              {hasActiveUpcomingFilters && (
                <div style={{ display: "flex", alignItems: "flex-end" }}>
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "8px 12px", display: "flex", alignItems: "center", gap: 4 }}
                    onClick={() => { setUpcomingSearch(""); setUpcomingStatusFilter(""); }}>
                    <X size={12} /> Clear
                  </button>
                </div>
              )}
            </div>
          )}

          {upcomingLoading && upcomingList.length === 0 ? (
            <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : upcomingList.length === 0 ? (
            <div style={{ padding: 36, textAlign: "center" }}>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                {hasActiveUpcomingFilters ? "Nothing matches these filters" : "Nothing booked beyond today"}
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                {hasActiveUpcomingFilters ? "Try clearing a filter." : "Future bookings for your assigned doctor(s) will show up here."}
              </div>
            </div>
          ) : (
            <>
              {upcomingByDoctor.map(([doctorName, items]) => (
                <div key={doctorName}>
                  <div style={{
                    padding: "9px 20px", fontSize: 11, fontWeight: 700, letterSpacing: "0.04em",
                    textTransform: "uppercase", color: "var(--color-text-muted)", background: "var(--color-bg)",
                    borderBottom: "1px solid var(--color-border)", display: "flex", alignItems: "center", gap: 6,
                  }}>
                    <Stethoscope size={13} /> Dr. {doctorName} ({items.length})
                  </div>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Time</th>
                        <th>Patient</th>
                        <th>Room</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map(a => (
                        <tr key={a.id}>
                          <td style={{ fontSize: 12, fontWeight: 700 }}>{formatScheduleDate(a.scheduled_date)}</td>
                          <td style={{ fontSize: 12, fontWeight: 700 }}>{a.scheduled_time ? a.scheduled_time.slice(0, 5) : "—"}</td>
                          <td style={{ fontSize: 13, fontWeight: 600 }}>{a.patient_name || "—"}</td>
                          <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                            {a.room_name ? `${a.room_name}${a.floor ? ` · Fl ${a.floor}` : ""}` : "—"}
                          </td>
                          <td><StatusBadge status={a.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}

              {upcomingExpanded ? (
                <>
                  <PaginationControls
                    pagination={upcomingPagination}
                    page={upcomingPage} pageSize={upcomingPageSize}
                    onPageChange={setUpcomingPage} onPageSizeChange={setUpcomingPageSize}
                  />
                  <div style={{ padding: "10px 20px 16px", textAlign: "center" }}>
                    <button className="btn-outline" style={{ fontSize: 12, padding: "6px 16px" }} onClick={collapseUpcoming}>
                      <ChevronUp size={13} style={{ verticalAlign: -2, marginRight: 4 }} /> View less
                    </button>
                  </div>
                </>
              ) : upcomingRemaining > 0 ? (
                <div style={{ padding: "12px 20px 16px", textAlign: "center", borderTop: "1px solid var(--color-border)" }}>
                  <button className="btn-outline" style={{ fontSize: 12.5, padding: "7px 18px", fontWeight: 700 }}
                    onClick={() => setUpcomingExpanded(true)}>
                    <ChevronDown size={13} style={{ verticalAlign: -2, marginRight: 4 }} /> View more ({upcomingRemaining} more)
                  </button>
                </div>
              ) : null}
            </>
          )}
        </div>

      </PageShell>
    </AppShell>
  );
}
