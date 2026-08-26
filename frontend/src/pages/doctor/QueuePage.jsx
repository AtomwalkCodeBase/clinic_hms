/**
 * pages/doctor/QueuePage.jsx
 * ---------------------------
 * Doctor's live OPD queue for today.
 * Calls GET /api/v1/opd/appointments/?date=today
 * Status actions: waiting → in_progress → done
 * "Start" opens the encounter page.
 */

import { useState, useCallback, useMemo, useEffect } from "react";
import { useNavigate }      from "react-router-dom";
import { AppShell }         from "../../components/layout/AppShell";
import { PageShell }        from "../../components/common/PageShell";
import DependentBadge       from "../../components/common/DependentBadge";
import { useAuth }          from "../../hooks/useAuth";
import { useToast }         from "../../hooks/useToast";
import { useApi }           from "../../hooks/useApi";
import { useActiveBranch }  from "../../hooks/useActiveBranch";
import BranchSwitcher       from "../../components/common/BranchSwitcher";
import apiClient            from "../../services/api.client";
import API_ENDPOINTS        from "../../config/api.config";
import { Building2, CalendarDays, Filter, X } from "lucide-react";
import { ROUTES }           from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];

function addDays(dateStr, n) {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().split("T")[0];
}
const TOMORROW = addDays(TODAY, 1);
const WEEK_END = addDays(TODAY, 7);

function formatDateLabel(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

/** Buckets a flat, date-ascending appointment list into Today / Tomorrow /
 * This Week / Later sections so a doctor can see their whole upcoming
 * schedule at a glance instead of just today's queue. */
function groupUpcoming(list) {
  const groups = { today: [], tomorrow: [], thisWeek: [], later: [] };
  for (const a of list) {
    if (a.scheduled_date === TODAY) groups.today.push(a);
    else if (a.scheduled_date === TOMORROW) groups.tomorrow.push(a);
    else if (a.scheduled_date < WEEK_END) groups.thisWeek.push(a);
    else groups.later.push(a);
  }
  return groups;
}

const STATUS_COLORS = {
  scheduled:   { bg: "#EDE9FF", color: "#5B52EE" },
  waiting:     { bg: "#FEF3C7", color: "#92400E" },
  vitals_done: { bg: "#DCFCE7", color: "#166534" },
  in_progress: { bg: "#DBEAFE", color: "#1E40AF" },
  done:        { bg: "#D1FAE5", color: "#065F46" },
  cancelled:   { bg: "#FEE2E2", color: "#991B1B" },
  no_show:     { bg: "#F3F4F6", color: "#6B7280" },
};

function StatusBadge({ status }) {
  const s = STATUS_COLORS[status] || { bg: "#F3F4F6", color: "#6B7280" };
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 20,
      fontSize: 11, fontWeight: 700, background: s.bg, color: s.color,
      textTransform: "capitalize",
    }}>
      {status?.replace("_", " ")}
    </span>
  );
}

export default function DoctorQueuePage() {
  const { user }   = useAuth();
  const navigate   = useNavigate();
  const { toastSuccess, toastApiError } = useToast();
  const [actionLoading, setActionLoading] = useState(null);
  const [page, setPage] = useState(1);
  const { branches, activeBranchId, setActiveBranchId, hasMultiple } = useActiveBranch();

  // ── Today's queue — search + filter ──────────────────────────────────
  const [showTodayFilters,  setShowTodayFilters]  = useState(false);
  const [todayStatusFilter, setTodayStatusFilter] = useState("");
  const [todayRoomFilter,   setTodayRoomFilter]   = useState("");
  const [todaySearch,       setTodaySearch]       = useState("");
  const hasActiveTodayFilters = !!(todayStatusFilter || todayRoomFilter || todaySearch);

  const { data: roomsData } = useApi(API_ENDPOINTS.ORG.ROOMS);
  const rooms = roomsData?.data || roomsData || [];

  const { data: apptData, isLoading, refetch } = useApi(
    API_ENDPOINTS.OPD.APPOINTMENTS,
    {
      params: {
        date: TODAY, page, page_size: 20,
        ...(hasMultiple && activeBranchId ? { branch_id: activeBranchId } : {}),
        ...(todayStatusFilter ? { status: todayStatusFilter } : {}),
        ...(todayRoomFilter ? { room_id: todayRoomFilter } : {}),
        ...(todaySearch ? { patient: todaySearch } : {}),
      },
      pollMs: 15000,
    }
  );

  // ── Upcoming schedule (today onward) — filters everything the schema
  // exposes: status, room, patient name/UHID/mobile, date range ──────────
  const [showFilters,   setShowFilters]   = useState(false);
  const [statusFilter,  setStatusFilter]  = useState("");
  const [roomFilter,    setRoomFilter]    = useState("");
  const [patientFilter, setPatientFilter] = useState("");
  const [dateFrom,      setDateFrom]      = useState(TODAY);
  const [dateTo,        setDateTo]        = useState("");

  const { data: upcomingData, isLoading: upcomingLoading, refetch: refetchUpcoming } = useApi(
    API_ENDPOINTS.OPD.APPOINTMENTS_UPCOMING,
    {
      params: {
        date_from: dateFrom || TODAY,
        page_size: 200,
        ...(dateTo ? { date_to: dateTo } : {}),
        ...(statusFilter ? { status: statusFilter } : {}),
        ...(roomFilter ? { room_id: roomFilter } : {}),
        ...(patientFilter ? { patient: patientFilter } : {}),
        ...(hasMultiple && activeBranchId ? { branch_id: activeBranchId } : {}),
      },
      pollMs: 30000,
    }
  );
  useEffect(() => { setPage(1); }, [todayStatusFilter, todayRoomFilter, todaySearch]);

  const upcomingList = useMemo(() => upcomingData?.results || [], [upcomingData]);
  const grouped = useMemo(() => groupUpcoming(upcomingList), [upcomingList]);
  const hasActiveFilters = !!(statusFilter || roomFilter || patientFilter || dateTo || dateFrom !== TODAY);

  const appointments = apptData?.results || [];
  const pagination   = apptData?.pagination || null;
  // Stat cards use server-computed totals for the whole day, not just the
  // current page, so they stay accurate regardless of how many pages there are.
  const counts = apptData?.status_counts || {};
  const waiting     = counts.waiting ?? 0;
  const vitalsReady = counts.vitals_done ?? 0;
  const inProgress  = counts.in_progress ?? 0;
  const done        = counts.done ?? 0;
  const total       = counts.total ?? appointments.length;

  const moveStatus = useCallback(async (apptId, newStatus) => {
    setActionLoading(apptId + newStatus);
    try {
      await apiClient.post(API_ENDPOINTS.OPD.APPT_STATUS(apptId), { status: newStatus });
      toastSuccess(`Status updated to ${newStatus.replace("_", " ")}.`);
      refetch();
      refetchUpcoming();
    } catch (err) {
      toastApiError(err, "Could not update status.");
    } finally {
      setActionLoading(null);
    }
  }, [refetch, refetchUpcoming, toastSuccess, toastApiError]);

  const startEncounter = useCallback(async (appt) => {
    setActionLoading(appt.id + "start");
    try {
      // Create encounter — the backend moves status to in_progress automatically
      const { data } = await apiClient.post(API_ENDPOINTS.OPD.ENCOUNTERS, {
        appointment_id: appt.id,
        patient_id:     appt.patient_id,
        doctor_user_id: user?.user_id,
      });
      const encId = data?.id || data?.data?.id;
      navigate(`/doctor/encounter/${encId}`);
    } catch (err) {
      toastApiError(err, "Could not start encounter.");
      setActionLoading(null);
    }
  }, [navigate, user, toastApiError]);

  return (
    <AppShell>
      <PageShell title="Today's OPD Queue">

        {/* Stats row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 14, marginBottom: 24 }}>
          {[
            { label: "Total Today",  value: total,               dot: "dot-label--green" },
            { label: "Waiting",      value: waiting,             dot: "dot-label--gold" },
            { label: "Vitals Ready", value: vitalsReady,         dot: "dot-label--green" },
            { label: "In Progress",  value: inProgress,          dot: "dot-label--blue" },
            { label: "Done",         value: done,                dot: "dot-label--green" },
          ].map(({ label, value, dot }) => (
            <div key={label} className="card" style={{ padding: "16px 18px" }}>
              <div className={`dot-label ${dot}`} style={{ marginBottom: 8 }}>{label}</div>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 600 }}>
                {isLoading ? "—" : value}
              </div>
            </div>
          ))}
        </div>

        {/* Queue table */}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)", flexWrap: "wrap", gap: 10,
          }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>Queue — {TODAY}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <BranchSwitcher branches={branches} activeBranchId={activeBranchId} onChange={setActiveBranchId} />
              <button
                className={hasActiveTodayFilters ? "btn-primary" : "btn-outline"}
                style={{ fontSize: 12, padding: "5px 14px", display: "flex", alignItems: "center", gap: 6 }}
                onClick={() => setShowTodayFilters(v => !v)}
              >
                <Filter size={13} /> Filters{hasActiveTodayFilters ? " •" : ""}
              </button>
              <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }}
                onClick={refetch}>Refresh</button>
            </div>
          </div>

          {showTodayFilters && (
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10,
              padding: "14px 20px", borderBottom: "1px solid var(--color-border)", background: "var(--color-bg)",
            }}>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Search</label>
                <input className="form-input" placeholder="Patient name, UHID, mobile, token, complaint…"
                  value={todaySearch} onChange={e => setTodaySearch(e.target.value)} />
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Status</label>
                <select className="form-input" style={{ appearance: "auto" }} value={todayStatusFilter} onChange={e => setTodayStatusFilter(e.target.value)}>
                  <option value="">All statuses</option>
                  <option value="scheduled">Scheduled</option>
                  <option value="waiting">Waiting</option>
                  <option value="vitals_done">Vitals Done</option>
                  <option value="in_progress">In Progress</option>
                  <option value="done">Done</option>
                  <option value="cancelled">Cancelled</option>
                  <option value="no_show">No Show</option>
                </select>
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Room</label>
                <select className="form-input" style={{ appearance: "auto" }} value={todayRoomFilter} onChange={e => setTodayRoomFilter(e.target.value)}>
                  <option value="">Any room</option>
                  {rooms.map(r => <option key={r.id} value={r.id}>{r.name}{r.floor ? ` (Fl ${r.floor})` : ""}</option>)}
                </select>
              </div>
              {hasActiveTodayFilters && (
                <div style={{ display: "flex", alignItems: "flex-end" }}>
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "8px 12px", display: "flex", alignItems: "center", gap: 4 }}
                    onClick={() => { setTodayStatusFilter(""); setTodayRoomFilter(""); setTodaySearch(""); }}>
                    <X size={12} /> Clear
                  </button>
                </div>
              )}
            </div>
          )}

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>
              Loading queue…
            </div>
          ) : appointments.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center" }}>
              <Building2 size={36} style={{ color: "var(--color-text-muted)", marginBottom: 12 }} />
              <div style={{ fontWeight: 600, marginBottom: 6 }}>No patients in queue today</div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Appointments booked by front desk will appear here.
              </div>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Token</th>
                  <th>Patient</th>
                  <th>UHID</th>
                  <th>Time</th>
                  <th>Chief Complaint</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th style={{ width: 160 }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {appointments.map(appt => {
                  const busy = actionLoading?.startsWith(appt.id);
                  return (
                    <tr key={appt.id}>
                      <td>
                        <span style={{
                          display: "inline-flex", alignItems: "center", justifyContent: "center",
                          width: 32, height: 32, borderRadius: 8,
                          background: "var(--color-primary-light)", color: "var(--color-primary)",
                          fontWeight: 800, fontSize: 14,
                        }}>
                          {appt.token_number}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{appt.patient_name || "—"}</div>
                          <DependentBadge patient={appt} />
                        </div>
                        <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{appt.patient_awpid || ""}</div>
                      </td>
                      <td style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                        {appt.patient_uhid || "—"}
                      </td>
                      <td style={{ fontSize: 12 }}>
                        <div style={{ fontWeight: 700 }}>{appt.scheduled_time ? appt.scheduled_time.slice(0, 5) : "—"}</div>
                        {appt.room_name && (
                          <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                            {appt.room_name}{appt.floor && ` · Fl ${appt.floor}`}
                          </div>
                        )}
                      </td>
                      <td style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {appt.chief_complaint || <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                      </td>
                      <td>
                        <span style={{ fontSize: 11, textTransform: "capitalize" }}>
                          {appt.appointment_type || "opd"}
                        </span>
                      </td>
                      <td><StatusBadge status={appt.status} /></td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          {(appt.status === "waiting" || appt.status === "vitals_done") && (
                            <button
                              className="btn-primary"
                              style={{ fontSize: 11, padding: "5px 12px" }}
                              disabled={busy}
                              onClick={() => startEncounter(appt)}
                            >
                              {busy ? "…" : "▶ Start"}
                            </button>
                          )}
                          {appt.status === "in_progress" && (
                            <button
                              className="btn-primary"
                              style={{ fontSize: 11, padding: "5px 12px" }}
                              disabled={busy}
                              onClick={() => navigate(`/doctor/encounter/${appt.encounter?.id || appt.id}`)}
                            >
                              Open Notes
                            </button>
                          )}
                          {appt.status === "scheduled" && (
                            <button
                              className="btn-outline"
                              style={{ fontSize: 11, padding: "5px 12px" }}
                              disabled={busy}
                              onClick={() => moveStatus(appt.id, "waiting")}
                            >
                              Check In
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          {pagination && pagination.total_pages > 1 && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, padding: "16px 20px", borderTop: "1px solid var(--color-border)" }}>
              <button
                className="btn-outline"
                style={{ fontSize: 12, padding: "6px 14px" }}
                disabled={!pagination.has_previous}
                onClick={() => setPage(p => Math.max(1, p - 1))}
              >
                ← Previous
              </button>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                Page {pagination.page} of {pagination.total_pages}
              </span>
              <button
                className="btn-outline"
                style={{ fontSize: 12, padding: "6px 14px" }}
                disabled={!pagination.has_next}
                onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))}
              >
                Next →
              </button>
            </div>
          )}
        </div>

        {/* ── Upcoming schedule — everything from today onward, grouped ── */}
        <div className="card" style={{ padding: 0, overflow: "hidden", marginTop: 24 }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)", flexWrap: "wrap", gap: 10,
          }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 14 }}>
              <CalendarDays size={16} style={{ color: "var(--color-primary)" }} />
              My upcoming schedule
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button
                className={hasActiveFilters ? "btn-primary" : "btn-outline"}
                style={{ fontSize: 12, padding: "5px 14px", display: "flex", alignItems: "center", gap: 6 }}
                onClick={() => setShowFilters(v => !v)}
              >
                <Filter size={13} /> Filters{hasActiveFilters ? " •" : ""}
              </button>
              <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refetchUpcoming}>Refresh</button>
            </div>
          </div>

          {showFilters && (
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10,
              padding: "14px 20px", borderBottom: "1px solid var(--color-border)", background: "var(--color-bg)",
            }}>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>From date</label>
                <input type="date" className="form-input" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>To date</label>
                <input type="date" className="form-input" value={dateTo} min={dateFrom} onChange={e => setDateTo(e.target.value)} />
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Status</label>
                <select className="form-input" style={{ appearance: "auto" }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                  <option value="">All (except cancelled/no-show)</option>
                  <option value="scheduled">Scheduled</option>
                  <option value="waiting">Waiting</option>
                  <option value="vitals_done">Vitals Done</option>
                  <option value="in_progress">In Progress</option>
                  <option value="done">Done</option>
                  <option value="cancelled">Cancelled</option>
                  <option value="no_show">No Show</option>
                </select>
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Room</label>
                <select className="form-input" style={{ appearance: "auto" }} value={roomFilter} onChange={e => setRoomFilter(e.target.value)}>
                  <option value="">Any room</option>
                  {rooms.map(r => <option key={r.id} value={r.id}>{r.name}{r.floor ? ` (Fl ${r.floor})` : ""}</option>)}
                </select>
              </div>
              <div>
                <label className="stat-label" style={{ display: "block", marginBottom: 5 }}>Patient</label>
                <input className="form-input" placeholder="Name, UHID, mobile…" value={patientFilter}
                  onChange={e => setPatientFilter(e.target.value)} />
              </div>
              {hasActiveFilters && (
                <div style={{ display: "flex", alignItems: "flex-end" }}>
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "8px 12px", display: "flex", alignItems: "center", gap: 4 }}
                    onClick={() => { setStatusFilter(""); setRoomFilter(""); setPatientFilter(""); setDateFrom(TODAY); setDateTo(""); }}>
                    <X size={12} /> Clear
                  </button>
                </div>
              )}
            </div>
          )}

          {upcomingLoading ? (
            <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading schedule…</div>
          ) : upcomingList.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
              Nothing upcoming{hasActiveFilters ? " matches these filters." : "."}
            </div>
          ) : (
            [
              { key: "today",    label: "Today",       items: grouped.today },
              { key: "tomorrow", label: "Tomorrow",    items: grouped.tomorrow },
              { key: "thisWeek", label: "This week",   items: grouped.thisWeek },
              { key: "later",    label: "Later",       items: grouped.later },
            ].filter(g => g.items.length > 0).map(group => (
              <div key={group.key}>
                <div style={{
                  padding: "9px 20px", fontSize: 11, fontWeight: 700, letterSpacing: "0.05em",
                  textTransform: "uppercase", color: "var(--color-text-muted)", background: "var(--color-bg)",
                  borderBottom: "1px solid var(--color-border)",
                }}>
                  {group.label} · {group.items.length}
                </div>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: 110 }}>Date</th>
                      <th style={{ width: 70 }}>Time</th>
                      <th style={{ width: 60 }}>Token</th>
                      <th>Patient</th>
                      <th>Room</th>
                      <th>Complaint</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.items.map(a => (
                      <tr key={a.id}>
                        <td style={{ fontSize: 12 }}>{formatDateLabel(a.scheduled_date)}</td>
                        <td style={{ fontSize: 12, fontWeight: 700 }}>{a.scheduled_time ? a.scheduled_time.slice(0, 5) : "—"}</td>
                        <td style={{ fontSize: 12, fontWeight: 700, color: "var(--color-primary)" }}>{a.token_number}</td>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 600, fontSize: 13 }}>{a.patient_name || "—"}</span>
                            <DependentBadge patient={a} />
                          </div>
                          <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{a.patient_uhid || a.patient_awpid || ""}</div>
                        </td>
                        <td style={{ fontSize: 12 }}>
                          {a.room_name ? `${a.room_name}${a.floor ? ` · Fl ${a.floor}` : ""}` : <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                        </td>
                        <td style={{ fontSize: 12, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {a.chief_complaint || <span style={{ color: "var(--color-text-muted)" }}>—</span>}
                        </td>
                        <td><StatusBadge status={a.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
