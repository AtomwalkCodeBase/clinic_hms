/**
 * pages/front-desk/AppointmentsPage.jsx
 * ---------------------------------------
 * Book OPD appointments: search patient → pick doctor → book.
 * Lists today's appointments below the booking card.
 */
import { useState, useCallback, useRef, useEffect } from "react";
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

  // ── Booking form state ──────────────────────────────────────────────
  const [patientQuery,  setPatientQuery]  = useState("");
  const [patientOpts,   setPatientOpts]   = useState([]);
  const [patient,       setPatient]       = useState(null);   // selected patient
  const [doctorId,      setDoctorId]      = useState("");
  const [date,          setDate]          = useState(TODAY);
  const [slots,         setSlots]         = useState([]);
  const [slot,          setSlot]          = useState("");
  const [complaint,     setComplaint]     = useState("");
  const [booking,       setBooking]       = useState(false);
  const [searchOpen,    setSearchOpen]    = useState(false);
  const searchRef = useRef(null);

  const { data: doctors } = useApi(API_ENDPOINTS.ORG.DOCTORS);
  const doctorList = doctors || [];

  // page_size: 100 — this is an informational "today's bookings" list under
  // the booking form, not a paged screen; request the max page size so it
  // isn't silently missing appointments on a busy day.
  const { data: apptData, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY, page_size: 100 },
  });
  const appointments = apptData?.results || [];

  // ── Patient search (debounced) ─────────────────────────────────────
  useEffect(() => {
    if (patientQuery.length < 2) { setPatientOpts([]); return; }
    const t = setTimeout(async () => {
      try {
        const { data } = await apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, {
          params: { q: patientQuery },
        });
        setPatientOpts(data?.data || data?.results || data || []);
        setSearchOpen(true);
      } catch { /* ignore */ }
    }, 300);
    return () => clearTimeout(t);
  }, [patientQuery]);

  useEffect(() => {
    function handler(e) {
      if (searchRef.current && !searchRef.current.contains(e.target)) setSearchOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Load slots when doctor / date changes
  useEffect(() => {
    setSlots([]); setSlot("");
    if (!doctorId || !date || !user?.tenant_id) return;
    apiClient.get(API_ENDPOINTS.PORTAL.SLOTS(user.tenant_id, doctorId), { params: { date } })
      .then(({ data }) => setSlots(data?.results || []))
      .catch(() => setSlots([]));
  }, [doctorId, date, user]);

  const book = useCallback(async () => {
    if (!patient || !doctorId) return;
    const doc = doctorList.find(d => String(d.id) === String(doctorId));
    setBooking(true);
    try {
      await apiClient.post(API_ENDPOINTS.OPD.APPOINTMENTS, {
        patient_id:      patient.uuid,
        patient_awpid:   patient.awpid,
        doctor_user_id:  doctorId,
        doctor_name:     doc ? `${doc.first_name || ""} ${doc.last_name || ""}`.trim() || doc.full_name || doc.email : "",
        appointment_type: "opd",
        scheduled_date:  date,
        ...(slot ? { scheduled_time: slot } : {}),
        chief_complaint: complaint,
      });
      toastSuccess(`Appointment booked for ${patient.full_name}.`);
      setPatient(null); setPatientQuery(""); setComplaint(""); setSlot("");
      refetch();
    } catch (err) {
      toastApiError(err, "Could not book appointment.");
    } finally {
      setBooking(false);
    }
  }, [patient, doctorId, date, complaint, doctorList, refetch, toastSuccess, toastApiError]);

  return (
    <AppShell>
      <PageShell title="Appointments">

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
                <input className="form-input" placeholder="Search name / UHID / mobile…"
                  value={patientQuery} onChange={e => setPatientQuery(e.target.value)} />
              )}
              {searchOpen && !patient && patientOpts.length > 0 && (
                <div style={{
                  position: "absolute", top: "100%", left: 0, right: 0, zIndex: 30,
                  background: "var(--color-surface)", border: "1px solid var(--color-border)",
                  borderRadius: 10, boxShadow: "var(--shadow-dropdown)", marginTop: 4,
                  maxHeight: 220, overflowY: "auto",
                }}>
                  {patientOpts.map(p => (
                    <button key={p.uuid || p.id}
                      onClick={() => { setPatient(p); setSearchOpen(false); }}
                      style={{
                        display: "block", width: "100%", textAlign: "left",
                        padding: "9px 12px", border: "none", background: "transparent",
                        borderBottom: "1px solid var(--color-border)", cursor: "pointer", fontSize: 13,
                      }}>
                      <span style={{ fontWeight: 600 }}>{p.full_name}</span>{" "}
                      <DependentBadge patient={p} style={{ marginLeft: 4 }} />
                      <span style={{ color: "var(--color-text-muted)", marginLeft: 8, fontSize: 12 }}>
                        {p.uhid} · {p.mobile || (p.is_dependent ? "no mobile (dependent)" : "no mobile")}
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
                    <td style={{ fontSize: 12, fontWeight: 700 }}>{a.scheduled_time ? a.scheduled_time.slice(0, 5) : "—"}</td>
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
