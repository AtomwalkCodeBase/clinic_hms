/**
 * pages/front-desk/AppointmentsPage.jsx
 * ---------------------------------------
 * Book OPD appointments: search patient → pick doctor → book.
 * Lists today's appointments below the booking card.
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Search, User, CalendarPlus } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import { useApi }    from "../../hooks/useApi";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const TODAY = new Date().toISOString().split("T")[0];

export default function AppointmentsPage() {
  const { toastSuccess, toastApiError } = useToast();
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  // Arrives here two ways: from PatientsPage's "Book Appointment" button, or
  // straight after RegisterPatientPage's submit (justRegistered) — either
  // way, a patient was handed off via navigation state and the booking form
  // should already have them selected instead of front desk having to
  // search for the person they just came from. Captured once into plain
  // state (not read from location.state on every render) because the
  // history-cleanup effect below clears location.state right after mount —
  // reading it directly would make the "just registered" banner vanish on
  // the very next re-render.
  const [justRegistered] = useState(() => !!location.state?.justRegistered);

  // ── Booking form state ──────────────────────────────────────────────
  // prefillQuery arrives from RegisterPatientPage's duplicate-match panels —
  // they only have the matched patient's name/UHID (not the tenant-local
  // uuid the booking API needs), so rather than a fragile "pre-selected but
  // secretly incomplete" patient object, this just pre-fills and opens the
  // search so the right match is one click away instead of retyped from
  // scratch.
  const [patientQuery,  setPatientQuery]  = useState(() => location.state?.prefillQuery || "");
  const [patientOpts,   setPatientOpts]   = useState([]);
  const [patient,       setPatient]       = useState(() => location.state?.patient || null);   // selected patient
  const [doctorId,      setDoctorId]      = useState("");
  const [date,          setDate]          = useState(TODAY);
  const [slots,         setSlots]         = useState([]);
  const [slot,          setSlot]          = useState("");
  const [complaint,     setComplaint]     = useState("");
  const [booking,       setBooking]       = useState(false);
  const [searchOpen,    setSearchOpen]    = useState(() => !!location.state?.prefillQuery);
  const searchRef = useRef(null);

  const { data: doctors } = useApi(API_ENDPOINTS.ORG.DOCTORS);
  const doctorList = doctors || [];

  // ── Registered today, not yet booked — the whole point of registration is
  // to get someone in front of a doctor, so surface today's new patients
  // right here instead of making front desk remember to go search for them.
  const [todayPatients, setTodayPatients] = useState([]);
  const fetchTodayPatients = useCallback(() => {
    apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, { params: { page: 1, page_size: 25 } })
      .then(({ data }) => {
        const results = data?.data?.results || data?.results || [];
        setTodayPatients(results.filter(p => (p.registered_at || "").slice(0, 10) === TODAY));
      })
      .catch(() => setTodayPatients([]));
  }, []);
  useEffect(() => { fetchTodayPatients(); }, [fetchTodayPatients]);

  // page_size: 100 — this is an informational "today's bookings" list under
  // the booking form, not a paged screen; request the max page size so it
  // isn't silently missing appointments on a busy day.
  const { data: apptData, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY, page_size: 100 },
  });
  const appointments = apptData?.results || [];

  // ── Patient search / browse ──────────────────────────────────────────
  // Two modes sharing one dropdown: focus the field with nothing typed yet
  // and it immediately shows the most recently registered patients (browse
  // mode — same endpoint, just no ?q=) so front desk can pick someone they
  // just registered without typing a single character. Type 2+ characters
  // and it becomes a live filtered search, debounced.
  const [isBrowseMode, setIsBrowseMode] = useState(true);
  useEffect(() => {
    if (!searchOpen) return;
    if (patientQuery.length === 1) { setPatientOpts([]); return; }
    const t = setTimeout(async () => {
      try {
        const { data } = await apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, {
          params: patientQuery.length >= 2 ? { q: patientQuery } : {},
        });
        setPatientOpts(data?.data?.results || data?.results || []);
        setIsBrowseMode(!!(data?.data?.is_browse ?? data?.is_browse ?? patientQuery.length < 2));
      } catch { setPatientOpts([]); }
    }, patientQuery.length >= 2 ? 300 : 0);
    return () => clearTimeout(t);
  }, [patientQuery, searchOpen]);

  useEffect(() => {
    function handler(e) {
      if (searchRef.current && !searchRef.current.contains(e.target)) setSearchOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Clear the handed-off navigation state once consumed, so browsing back
  // to this page later (or refreshing) doesn't keep re-showing the
  // "just registered" banner for a patient booked ages ago.
  useEffect(() => {
    if (location.state) navigate(location.pathname, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load slots when doctor / date changes
  useEffect(() => {
    setSlots([]); setSlot("");
    if (!doctorId || !date || !user?.tenant_id) return;
    apiClient.get(API_ENDPOINTS.PORTAL.SLOTS(user.tenant_id, doctorId), { params: { date } })
      // Slots whose time has already passed today aren't a real option —
      // drop them instead of showing a struck-through button for them.
      // Booked-but-still-upcoming slots stay, shown disabled as before.
      .then(({ data }) => setSlots((data?.results || []).filter(s => !s.past)))
      .catch(() => setSlots([]));
  }, [doctorId, date, user]);

  const book = useCallback(async () => {
    if (!patient || !doctorId) return;
    const doc = doctorList.find(d => String(d.id) === String(doctorId));
    setBooking(true);
    try {
      const { data: res } = await apiClient.post(API_ENDPOINTS.OPD.APPOINTMENTS, {
        patient_id:      patient.uuid,
        patient_awpid:   patient.awpid,
        doctor_user_id:  doctorId,
        doctor_name:     doc ? `${doc.first_name || ""} ${doc.last_name || ""}`.trim() || doc.full_name || doc.email : "",
        appointment_type: "opd",
        scheduled_date:  date,
        ...(slot ? { scheduled_time: slot } : {}),
        chief_complaint: complaint,
      });
      const created = res?.data || res;
      const roomNote = created?.room_name
        ? ` — ${created.room_name}${created.floor ? `, Floor ${created.floor}` : ""}`
        : "";
      toastSuccess(`Appointment booked for ${patient.full_name}.${roomNote}`);
      setPatient(null); setPatientQuery(""); setComplaint(""); setSlot("");
      refetch();
      fetchTodayPatients();
    } catch (err) {
      toastApiError(err, "Could not book appointment.");
    } finally {
      setBooking(false);
    }
  }, [patient, doctorId, date, complaint, doctorList, refetch, fetchTodayPatients, toastSuccess, toastApiError]);

  return (
    <AppShell>
      <PageShell title="Appointments">

        {justRegistered && patient && (
          <div className="card" style={{
            marginBottom: 16, padding: "12px 18px", display: "flex", alignItems: "center", gap: 10,
            border: "1px solid var(--color-primary)", background: "var(--color-primary-light)",
          }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-primary)" }}>
              {patient.full_name} is registered — book their first appointment below.
            </span>
          </div>
        )}

        {todayPatients.length > 0 && (
          <div className="card" style={{ marginBottom: 22, padding: 0, overflow: "hidden" }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "12px 20px", borderBottom: "1px solid var(--color-border)",
              background: "var(--color-primary-light)",
            }}>
              <CalendarPlus size={15} style={{ color: "var(--color-primary)" }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-primary)" }}>
                Registered today ({todayPatients.length}) — book their appointment
              </span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, padding: 16 }}>
              {todayPatients.map(p => (
                <div key={p.uuid || p.id} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  border: "1px solid var(--color-border)", borderRadius: 10,
                  padding: "8px 10px 8px 8px", background: "var(--color-surface)",
                }}>
                  <span style={{
                    width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
                    background: "var(--color-primary-light)", color: "var(--color-primary)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <User size={14} />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600 }}>
                      {p.full_name}
                      <DependentBadge patient={p} />
                    </div>
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{p.uhid}</div>
                  </div>
                  <button type="button" className="btn-outline" style={{ fontSize: 11.5, padding: "5px 12px", marginLeft: 4 }}
                    onClick={() => { setPatient(p); setPatientQuery(""); setSearchOpen(false); }}>
                    Book Appointment →
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Booking card ──────────────────────────────────────────── */}
        <div className="card" style={{ marginBottom: 22, padding: 24 }}>
          <div className="dot-label dot-label--green" style={{ marginBottom: 16 }}>Book an appointment</div>
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 0.8fr 1.4fr auto", gap: 12, alignItems: "end" }}>

            {/* Patient search */}
            <div ref={searchRef} style={{ position: "relative" }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Patient</label>
              {patient ? (
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  border: "1.5px solid var(--color-primary)", borderRadius: "var(--radius-input)",
                  padding: "8px 12px", background: "var(--color-primary-light)",
                }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>
                    {patient.full_name} <span style={{ color: "var(--color-text-muted)", fontWeight: 400 }}>· {patient.uhid}</span>
                  </span>
                  <button onClick={() => { setPatient(null); setPatientQuery(""); }}
                    style={{ border: "none", background: "none", color: "var(--color-error)", fontWeight: 700 }}>✕</button>
                </div>
              ) : (
                <div style={{ position: "relative" }}>
                  <Search size={15} style={{
                    position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)",
                    color: "var(--color-text-muted)", pointerEvents: "none",
                  }} />
                  <input className="form-input" style={{ paddingLeft: 32 }}
                    placeholder="Type a name, mobile number, or UHID…"
                    value={patientQuery}
                    onFocus={() => setSearchOpen(true)}
                    onChange={e => setPatientQuery(e.target.value)} />
                </div>
              )}
              {searchOpen && !patient && (
                <div style={{
                  position: "absolute", top: "100%", left: 0, right: 0, zIndex: 30,
                  background: "var(--color-surface)", border: "1px solid var(--color-border)",
                  borderRadius: 10, boxShadow: "var(--shadow-dropdown)", marginTop: 4,
                  maxHeight: 280, overflowY: "auto",
                }}>
                  {patientOpts.length > 0 && (
                    <div style={{
                      padding: "8px 12px", fontSize: 10.5, fontWeight: 700, letterSpacing: "0.06em",
                      textTransform: "uppercase", color: "var(--color-text-muted)",
                      background: "var(--color-bg)", borderBottom: "1px solid var(--color-border)",
                    }}>
                      {isBrowseMode ? "Recently registered — click to select" : "Search results"}
                    </div>
                  )}
                  {patientOpts.length === 0 ? (
                    <div style={{ padding: "16px 14px", fontSize: 12.5, color: "var(--color-text-muted)" }}>
                      {patientQuery.length >= 2 ? `No patients matched "${patientQuery}".` : "No patients registered here yet."}
                    </div>
                  ) : patientOpts.map(p => (
                    <button key={p.uuid || p.id}
                      onClick={() => { setPatient(p); setSearchOpen(false); setPatientQuery(""); }}
                      style={{
                        display: "flex", alignItems: "center", gap: 10, width: "100%", textAlign: "left",
                        padding: "9px 12px", border: "none", background: "transparent",
                        borderBottom: "1px solid var(--color-border)", cursor: "pointer",
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = "var(--color-bg)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                      <span style={{
                        width: 30, height: 30, borderRadius: "50%", flexShrink: 0,
                        background: "var(--color-primary-light)", color: "var(--color-primary)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        <User size={15} />
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600 }}>
                          {p.full_name}
                          <DependentBadge patient={p} />
                        </span>
                        <span style={{ display: "block", fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 1 }}>
                          {p.uhid} · {p.mobile || (p.is_dependent ? "no mobile (dependent)" : "no mobile")}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Doctor */}
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Doctor</label>
              <select className="form-input" style={{ appearance: "auto" }}
                value={doctorId} onChange={e => setDoctorId(e.target.value)}>
                <option value="">Select doctor…</option>
                {doctorList.map(d => (
                  <option key={d.id} value={d.id}>
                    {`${d.first_name || ""} ${d.last_name || ""}`.trim() || d.full_name || d.email}
                  </option>
                ))}
              </select>
            </div>

            {/* Date */}
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Date</label>
              <input type="date" className="form-input" value={date} min={TODAY}
                onChange={e => setDate(e.target.value)} />
            </div>

            {/* Complaint */}
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Chief complaint</label>
              <input className="form-input" placeholder="e.g. High fever for 2 days"
                value={complaint} onChange={e => setComplaint(e.target.value)} />
            </div>

            <button className="btn-primary" style={{ padding: "9px 22px" }}
              disabled={!patient || !doctorId || booking}
              onClick={book}>
              {booking ? "Booking…" : "Book"}
            </button>
          </div>

          {/* Slot picker */}
          {doctorId && slots.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 10 }}>
                Slot {slot && <span style={{ color: "var(--color-primary)" }}>— {slot}</span>}
                <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}> (optional for walk-ins)</span>
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(72px, 1fr))", gap: 8 }}>
                {slots.map(s => (
                  <button key={s.time} type="button" disabled={!s.available}
                    onClick={() => setSlot(slot === s.time ? "" : s.time)}
                    style={{
                      padding: "6px 0", borderRadius: 8, fontSize: 12, fontWeight: 700,
                      border: slot === s.time ? "2px solid var(--color-primary)" : "1px solid var(--color-border)",
                      background: !s.available ? "var(--color-border)"
                        : slot === s.time ? "var(--color-primary)" : "var(--color-surface)",
                      color: !s.available ? "var(--color-text-disabled)"
                        : slot === s.time ? "#fff" : "var(--color-text-secondary)",
                      cursor: s.available ? "pointer" : "not-allowed",
                      textDecoration: !s.available ? "line-through" : "none",
                    }}>
                    {s.time}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Today's list ──────────────────────────────────────────── */}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "14px 20px", borderBottom: "1px solid var(--color-border)",
          }}>
            <span className="dot-label dot-label--gold">Today's appointments</span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refetch}>Refresh</button>
          </div>
          {isLoading ? (
            <div style={{ padding: 32, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : appointments.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>
              Nothing booked for today yet.
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 60 }}>#</th>
                  <th>Patient</th>
                  <th>Doctor</th>
                  <th>Time</th>
                  <th>Complaint</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {appointments.map(a => (
                  <tr key={a.id}>
                    <td style={{ fontWeight: 800, color: "var(--color-primary)" }}>{a.token_number}</td>
                    <td style={{ fontWeight: 600 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        {a.patient_name || a.patient_awpid || "—"}
                        <DependentBadge patient={a} />
                      </div>
                    </td>
                    <td style={{ fontSize: 12 }}>{a.doctor_name || "—"}</td>
                    <td style={{ fontSize: 12 }}>
                      <div style={{ fontWeight: 700 }}>{a.scheduled_time ? a.scheduled_time.slice(0, 5) : "—"}</div>
                      {a.room_name && (
                        <div style={{ fontSize: 10, color: "var(--color-text-muted)" }}>
                          {a.room_name}{a.floor && ` · Fl ${a.floor}`}
                        </div>
                      )}
                    </td>
                    <td style={{ fontSize: 12 }}>{a.chief_complaint || "—"}</td>
                    <td>
                      <span className={`badge ${
                        a.status === "done" ? "badge--success"
                        : a.status === "in_progress" ? "badge--info"
                        : a.status === "cancelled" ? "badge--error"
                        : "badge--warning"}`}>
                        {a.status?.replace("_", " ")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
