/**
 * pages/front-desk/AppointmentsPage.jsx
 * ---------------------------------------
 * Front desk's search-and-book hub: find or register a patient (by name,
 * mobile, UHID, AWPID, or a dependent's parent's name), see their family
 * so any member can be booked without a second search, search/filter
 * doctors by name or specialisation, check real availability, and only
 * then book — a slot must be picked before the Book button unlocks
 * whenever the doctor actually has slots configured for that day.
 */
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Search, User, CalendarPlus, Users, Siren, UserPlus, Stethoscope, X } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import DependentBadge from "../../components/common/DependentBadge";
import QuickRegisterModal from "../../components/front-desk/QuickRegisterModal";
import { useApi }    from "../../hooks/useApi";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

const TODAY = new Date().toISOString().split("T")[0];

// ── Family tree strip ─────────────────────────────────────────────────────
function FamilyStrip({ members, selfAwpid, onSelectExisting, onRegisterNew, loading }) {
  if (loading) {
    return (
      <div style={{
        marginTop: 14, padding: "12px 14px", borderRadius: 10, fontSize: 12.5,
        color: "var(--color-text-muted)", border: "1px dashed var(--color-border)",
      }}>
        Loading linked family members…
      </div>
    );
  }
  if (!members || members.length <= 1) return null; // just self, or nobody linked

  return (
    <div style={{
      marginTop: 14, padding: 14, borderRadius: 12,
      background: "var(--color-accent-light)", border: "1.5px solid color-mix(in srgb, var(--color-accent) 45%, transparent)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 10 }}>
        <Users size={15} style={{ color: "var(--color-accent)" }} />
        <span style={{ fontSize: 13, fontWeight: 800, color: "var(--color-accent)" }}>
          Family linked to this patient — book for any of them
        </span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        {members.map(m => {
          const isSelf = m.awpid === selfAwpid;
          return (
            <div key={m.awpid} style={{
              display: "flex", alignItems: "center", gap: 10,
              border: isSelf ? "1.5px solid var(--color-primary)" : "1px solid var(--color-border)",
              borderRadius: 10, padding: "8px 12px",
              background: isSelf ? "var(--color-primary-light)" : "var(--color-surface)",
            }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>
                {m.full_name}
                <span style={{ fontWeight: 500, color: "var(--color-text-muted)", marginLeft: 6, textTransform: "capitalize" }}>
                  ({m.relationship})
                </span>
              </span>
              {isSelf ? null : m.already_registered_here ? (
                <button type="button" className="btn-primary" style={{ fontSize: 11.5, padding: "4px 12px" }}
                  onClick={() => onSelectExisting(m)}>
                  Book for them
                </button>
              ) : (
                <button type="button" className="btn-outline" style={{ fontSize: 11.5, padding: "4px 12px" }}
                  onClick={() => onRegisterNew(m)}>
                  Register here
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function AppointmentsPage() {
  const { toastSuccess, toastApiError } = useToast();
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  // Arrives here two ways: from PatientsPage's "Book Appointment" button, or
  // straight after RegisterPatientPage's submit (justRegistered) — either
  // way, a patient was handed off via navigation state and the booking form
  // should already have them selected instead of front desk having to
  // search for the person they just came from.
  const [justRegistered] = useState(() => !!location.state?.justRegistered);

  // ── Patient / booking form state ────────────────────────────────────
  const [patientQuery,  setPatientQuery]  = useState(() => location.state?.prefillQuery || "");
  const [patientOpts,   setPatientOpts]   = useState([]);
  const [patient,       setPatient]       = useState(() => location.state?.patient || null);
  const [doctorId,      setDoctorId]      = useState("");
  const [date,          setDate]          = useState(TODAY);
  const [slots,         setSlots]         = useState([]);
  const [slot,          setSlot]          = useState("");
  const [complaint,     setComplaint]     = useState("");
  const [booking,       setBooking]       = useState(false);
  const [searchOpen,    setSearchOpen]    = useState(() => !!location.state?.prefillQuery);
  const searchRef = useRef(null);

  // ── Family tree ──────────────────────────────────────────────────────
  const [family,             setFamily]             = useState([]);
  const [familyGuardianAwpid, setFamilyGuardianAwpid] = useState(null);
  const [familyLoading,      setFamilyLoading]       = useState(false);
  const fetchFamily = useCallback((awpid) => {
    if (!awpid) { setFamily([]); setFamilyGuardianAwpid(null); return; }
    setFamilyLoading(true);
    apiClient.get(API_ENDPOINTS.PATIENTS.FAMILY_TREE, { params: { awpid } })
      .then(({ data }) => {
        const d = data?.data || data;
        setFamily(d?.members || []);
        setFamilyGuardianAwpid(d?.guardian_awpid || null);
      })
      .catch(() => { setFamily([]); setFamilyGuardianAwpid(null); })
      .finally(() => setFamilyLoading(false));
  }, []);
  useEffect(() => { fetchFamily(patient?.awpid); }, [patient?.awpid, fetchFamily]);
  // The household head, resolved from the tree itself rather than assumed to
  // be whichever patient is currently selected — front desk can search up
  // any member (a dependent included), and the guardian is still whoever
  // the backend resolved, not necessarily "self".
  const familyGuardian = useMemo(
    () => family.find(m => m.awpid === familyGuardianAwpid) || null,
    [family, familyGuardianAwpid]
  );

  // ── Emergency / dependent quick-register modal ───────────────────────
  // null | "emergency" | a family-tree member entry (the person TO register
  // — e.g. Ria — not the guardian; see familyGuardian above for that).
  const [quickRegisterFor, setQuickRegisterFor] = useState(null);
  const { data: branchesData } = useApi(API_ENDPOINTS.ORG.BRANCHES);
  const branches = branchesData?.data || branchesData || [];
  const defaultBranchId = user?.branch_id || branches?.[0]?.id || "";

  function handleRegistered(created) {
    setQuickRegisterFor(null);
    setPatient(created);
    setPatientQuery("");
    setSearchOpen(false);
  }

  // Selecting an "already registered here" family member — the search
  // endpoint returns full local records (with the uuid booking needs) when
  // queried by AWPID, unlike the lightweight family-tree entry itself.
  async function selectExistingFamilyMember(member) {
    try {
      const { data } = await apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, { params: { q: member.awpid } });
      const results = data?.data?.results || data?.results || [];
      const match = results.find(p => p.awpid === member.awpid) || results[0];
      if (match) { setPatient(match); setPatientQuery(""); setSearchOpen(false); }
      else toastApiError(null, "Couldn't load that family member's record.");
    } catch {
      toastApiError(null, "Couldn't load that family member's record.");
    }
  }

  // ── Registered today, not yet booked ─────────────────────────────────
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

  const { data: apptData, isLoading, refetch } = useApi(API_ENDPOINTS.OPD.APPOINTMENTS, {
    params: { date: TODAY, page_size: 100 },
  });
  const appointments = apptData?.results || [];

  // ── Patient search / browse — name, mobile, UHID, AWPID, or a
  // dependent's guardian/parent name (backend now matches guardian_name
  // too — see PatientService.search) ───────────────────────────────────
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

  // True when the query itself is a precise identifier (UHID/AWPID/mobile)
  // that resolved to exactly one record — there's no real ambiguity to
  // escape from in that case, unlike a fuzzy name search that can surface
  // the wrong "Rohan" or several. Drives whether the "register instead"
  // fallback appears under the results (see the dropdown below).
  const isPreciseMatch = useMemo(() => {
    if (patientOpts.length !== 1) return false;
    const q = patientQuery.trim().toLowerCase();
    if (!q) return false;
    const p = patientOpts[0];
    return (
      q === (p.uhid || "").toLowerCase() ||
      q === (p.awpid || "").toLowerCase() ||
      (!!p.mobile && q === p.mobile.toLowerCase())
    );
  }, [patientOpts, patientQuery]);

  useEffect(() => {
    function handler(e) {
      if (searchRef.current && !searchRef.current.contains(e.target)) setSearchOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    if (location.state) navigate(location.pathname, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Doctor search / filter — name or specialisation, availability-first
  // (task: search doctors before booking, not just pick from a flat list) ──
  const [doctorQuery,   setDoctorQuery]   = useState("");
  const [specFilter,    setSpecFilter]    = useState("");
  const [doctorList,    setDoctorList]    = useState([]);
  const { data: specData } = useApi(API_ENDPOINTS.ORG.DOCTOR_SPECIALISATIONS);
  const specialisations = specData?.data || specData || [];

  useEffect(() => {
    const t = setTimeout(() => {
      apiClient.get(API_ENDPOINTS.ORG.DOCTORS, {
        params: { ...(doctorQuery ? { q: doctorQuery } : {}), ...(specFilter ? { specialisation: specFilter } : {}) },
      })
        .then(({ data }) => setDoctorList(data?.data || data || []))
        .catch(() => setDoctorList([]));
    }, 250);
    return () => clearTimeout(t);
  }, [doctorQuery, specFilter]);

  // Load slots when doctor / date changes
  useEffect(() => {
    setSlots([]); setSlot("");
    if (!doctorId || !date || !user?.tenant_id) return;
    apiClient.get(API_ENDPOINTS.PORTAL.SLOTS(user.tenant_id, doctorId), { params: { date } })
      .then(({ data }) => setSlots((data?.results || []).filter(s => !s.past)))
      .catch(() => setSlots([]));
  }, [doctorId, date, user]);

  // Live availability — same fix as the patient portal's slot picker: if
  // someone else books this slot while front desk has it open, silently
  // refresh in the background so it greys out instead of failing at
  // confirm time, and drop the current selection if it was the one taken.
  useEffect(() => {
    if (!doctorId || !date || !user?.tenant_id || booking) return undefined;
    const id = setInterval(() => {
      if (document.hidden) return;
      apiClient.get(API_ENDPOINTS.PORTAL.SLOTS(user.tenant_id, doctorId), { params: { date } })
        .then(({ data }) => {
          const fresh = (data?.results || []).filter(s => !s.past);
          setSlots(fresh);
          setSlot(prev => {
            if (!prev) return prev;
            const stillOpen = fresh.find(s => s.time === prev && s.available);
            return stillOpen ? prev : "";
          });
        })
        .catch(() => {});
    }, 15000);
    return () => clearInterval(id);
  }, [doctorId, date, user, booking]);

  // A slot must be chosen whenever the doctor actually has any configured
  // for the day — front desk defaulting to "first available" silently was
  // the bug (see spreadsheet row 45); a doctor with zero slots set up for
  // that day (no working hours configured) still allows a walk-in booking
  // with no fixed time.
  const slotRequired = slots.length > 0;
  const canBook = !!patient && !!doctorId && (!slotRequired || !!slot) && !booking;

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
      // Reset the whole form for the next patient — including the date,
      // which used to stay on whatever day was just booked and quietly
      // carry over into the next booking (front desk booking a future
      // follow-up, then the next walk-in accidentally landing on that same
      // future date instead of today).
      setPatient(null); setPatientQuery(""); setComplaint(""); setSlot(""); setDoctorId("");
      setDate(TODAY);
      refetch();
      fetchTodayPatients();
    } catch (err) {
      toastApiError(err, "Could not book appointment.");
    } finally {
      setBooking(false);
    }
  }, [patient, doctorId, date, slot, complaint, doctorList, refetch, fetchTodayPatients, toastSuccess, toastApiError]);

  return (
    <AppShell>
      <PageShell title="Appointments">

        <QuickRegisterModal
          // Forces a fresh mount per target — the modal stays in the tree
          // between opens (only its internal `open` check hides it), so
          // without a key its form state would carry over from whoever was
          // last registered (e.g. still showing Ria's prefilled age/gender
          // after closing and reopening for a different family member).
          key={quickRegisterFor === "emergency" ? "emergency" : quickRegisterFor?.awpid || "closed"}
          open={!!quickRegisterFor}
          onClose={() => setQuickRegisterFor(null)}
          onRegistered={handleRegistered}
          branchId={defaultBranchId}
          // The GUARDIAN this new record gets attached to — resolved from
          // the family tree itself (familyGuardian), not from
          // quickRegisterFor, which is the person we're registering (e.g.
          // Ria), not her guardian. Getting this backwards is what made the
          // modal ask "Register Ria's family member" while asking for Ria's
          // own name/age/gender all over again — she was already fully known
          // from the family-tree lookup that surfaced her chip in the first
          // place. Falls back to the currently selected patient if the
          // guardian entry didn't resolve for some reason.
          guardian={quickRegisterFor && quickRegisterFor !== "emergency" ? {
            awpid: (familyGuardian || patient)?.awpid,
            full_name: (familyGuardian || patient)?.full_name,
            relation: quickRegisterFor.relationship,
          } : null}
          // Everything already known about the person being registered —
          // came straight from the same family-tree lookup that put their
          // chip on screen, so front desk isn't re-typing what the system
          // already has on file.
          prefill={quickRegisterFor && quickRegisterFor !== "emergency" ? {
            full_name: quickRegisterFor.full_name,
            date_of_birth: quickRegisterFor.date_of_birth,
            gender: quickRegisterFor.gender,
          } : null}
        />

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
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 0.8fr 1.4fr auto", gap: 12, alignItems: "end" }}>

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
                    placeholder="Name, mobile, UHID, AWPID, or parent's name…"
                    value={patientQuery}
                    onFocus={() => setSearchOpen(true)}
                    onChange={e => setPatientQuery(e.target.value)} />
                </div>
              )}
              {!patient && (
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 5 }}>
                  Select a result to book, and see their family below. No match?{" "}
                  <button type="button" onClick={() => setQuickRegisterFor("emergency")}
                    style={{ background: "none", border: "none", padding: 0, font: "inherit", fontWeight: 700, color: "var(--color-primary)", cursor: "pointer" }}>
                    Register them
                  </button>.
                </div>
              )}
              {searchOpen && !patient && (
                <div style={{
                  position: "absolute", top: "100%", left: 0, right: 0, zIndex: 30,
                  background: "var(--color-surface)", border: "1px solid var(--color-border)",
                  borderRadius: 10, boxShadow: "var(--shadow-dropdown)", marginTop: 4,
                  maxHeight: 340, overflowY: "auto",
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
                    <div style={{ padding: "14px", fontSize: 12.5, color: "var(--color-text-muted)" }}>
                      {patientQuery.length >= 2 ? `No patients matched "${patientQuery}".` : "No patients registered here yet."}
                      {patientQuery.length >= 2 && (
                        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                          <button type="button" className="btn-outline" style={{ fontSize: 11.5, padding: "5px 10px" }}
                            onClick={() => { setSearchOpen(false); navigate("/front-desk/register-patient", { state: { prefillQuery: patientQuery } }); }}>
                            <UserPlus size={12} style={{ marginRight: 4, verticalAlign: -2 }} />
                            Full registration
                          </button>
                          <button type="button" className="btn-primary" style={{ fontSize: 11.5, padding: "5px 10px" }}
                            onClick={() => { setSearchOpen(false); setQuickRegisterFor("emergency"); }}>
                            <Siren size={12} style={{ marginRight: 4, verticalAlign: -2 }} />
                            Emergency register
                          </button>
                        </div>
                      )}
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
                          {p.uhid} · {p.mobile || (p.is_dependent ? `no mobile — ${p.guardian_name || "dependent"}` : "no mobile")}
                        </span>
                      </span>
                    </button>
                  ))}
                  {/* Only offer the "register instead" escape hatch when the match
                      is genuinely uncertain — a fuzzy name search can turn up the
                      wrong person, or several. It shouldn't appear when the query
                      was a precise identifier (UHID/AWPID/mobile) that hit exactly
                      one record — that IS the patient, full stop, and showing a
                      register button right next to a confirmed match reads as an
                      invitation to create a duplicate registration for someone
                      who's already on file. */}
                  {!isBrowseMode && patientOpts.length > 0 && !isPreciseMatch && (
                    <div style={{
                      padding: "9px 12px", borderTop: "1px solid var(--color-border)",
                      background: "var(--color-bg)", fontSize: 11.5, color: "var(--color-text-muted)",
                      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap",
                    }}>
                      <span>None of these the right person?</span>
                      <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "4px 10px", flexShrink: 0 }}
                        onClick={() => { setSearchOpen(false); setQuickRegisterFor("emergency"); }}>
                        <Siren size={11} style={{ marginRight: 4, verticalAlign: -2 }} />
                        Emergency register instead
                      </button>
                    </div>
                  )}
                </div>
              )}
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
              disabled={!canBook}
              title={slotRequired && !slot ? "Pick a slot before booking" : undefined}
              onClick={book}>
              {booking ? "Booking…" : "Book"}
            </button>
          </div>

          {/* Family tree — book for anyone linked to the selected patient */}
          {patient && (
            <FamilyStrip
              members={family} selfAwpid={patient.awpid} loading={familyLoading}
              onSelectExisting={selectExistingFamilyMember}
              onRegisterNew={(m) => setQuickRegisterFor(m)}
            />
          )}

          {/* Doctor search + filter */}
          <div style={{ marginTop: 22 }}>
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              marginBottom: 12, flexWrap: "wrap", gap: 10,
              padding: "12px 14px", borderRadius: 12,
              background: "var(--color-primary-light)", border: "1.5px solid color-mix(in srgb, var(--color-primary) 35%, transparent)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7, flexShrink: 0 }}>
                <Stethoscope size={16} style={{ color: "var(--color-primary)" }} />
                <span style={{ fontSize: 13.5, fontWeight: 800, color: "var(--color-primary)" }}>Find a doctor</span>
              </div>
              <div style={{ display: "flex", gap: 10, flex: "1 1 380px", justifyContent: "flex-end", flexWrap: "wrap" }}>
                <div style={{ position: "relative", flex: "1 1 220px", maxWidth: 280 }}>
                  <Search size={14} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--color-text-muted)" }} />
                  <input className="form-input" style={{ width: "100%", boxSizing: "border-box", paddingLeft: 32, fontSize: 13, fontWeight: 600 }}
                    placeholder="Search doctor by name…"
                    value={doctorQuery} onChange={e => setDoctorQuery(e.target.value)} />
                </div>
                <select className="form-input" style={{ appearance: "auto", fontSize: 13, fontWeight: 600, flex: "0 1 220px" }}
                  value={specFilter} onChange={e => setSpecFilter(e.target.value)}>
                  <option value="">All specialisations</option>
                  {specialisations.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                {(doctorQuery || specFilter) && (
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "0 12px", fontWeight: 700 }}
                    onClick={() => { setDoctorQuery(""); setSpecFilter(""); }}>
                    <X size={13} /> Clear
                  </button>
                )}
              </div>
            </div>
            {doctorList.length === 0 ? (
              <div style={{
                padding: "14px 16px", fontSize: 12.5, color: "var(--color-text-muted)",
                border: "1px dashed var(--color-border)", borderRadius: 10,
              }}>
                {doctorQuery || specFilter ? "No doctors matched that search/filter." : "No doctors are set up for this branch yet — invite one from Staff."}
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
                {doctorList.map(d => {
                  const name = `${d.first_name || ""} ${d.last_name || ""}`.trim() || d.full_name || d.email;
                  const prof = d.doctor_profile || {};
                  const photo = d.photo || prof.photo_url;
                  const selected = String(doctorId) === String(d.id);
                  return (
                    <button key={d.id} type="button" onClick={() => setDoctorId(d.id)}
                      style={{
                        display: "flex", alignItems: "center", gap: 10, textAlign: "left",
                        padding: "10px 12px", borderRadius: 10, cursor: "pointer",
                        border: selected ? "2px solid var(--color-primary)" : "1px solid var(--color-border)",
                        background: selected ? "var(--color-primary-light)" : "var(--color-surface)",
                      }}>
                      <span style={{
                        width: 36, height: 36, borderRadius: "50%", flexShrink: 0, overflow: "hidden",
                        background: "var(--color-primary-light)", color: "var(--color-primary)",
                        display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 14,
                      }}>
                        {photo
                          ? <img src={photo} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                          : (name.replace("Dr. ", "").charAt(0) || "D")}
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <div style={{
                          fontSize: 13, fontWeight: 700, whiteSpace: "nowrap",
                          overflow: "hidden", textOverflow: "ellipsis",
                        }}>
                          {name}
                        </div>
                        <div style={{
                          fontSize: 11, color: "var(--color-text-muted)", whiteSpace: "nowrap",
                          overflow: "hidden", textOverflow: "ellipsis",
                        }}>
                          {prof.specialisation || "General"}{prof.consultation_fee ? ` · ₹${prof.consultation_fee}` : ""}
                        </div>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Slot picker — required whenever the doctor has slots configured */}
          {doctorId && (
            <div style={{ marginTop: 16 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 10 }}>
                Slot {slot && <span style={{ color: "var(--color-primary)" }}>— {slot}</span>}
                {!slotRequired && (
                  <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}> (no fixed slots configured — walk-in booking)</span>
                )}
                {slotRequired && !slot && (
                  <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0, color: "var(--color-error)" }}> — pick a slot to book</span>
                )}
              </label>
              {slots.length > 0 && (
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
              )}
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
