/**
 * pages/front-desk/AdmissionsPage.jsx
 * -------------------------------------
 * IPD Admission — Phase 1 (admission intake) only. Covers steps 4 and 5 of
 * the approved intake mockup (Referral Queue, then Complete Admission +
 * Bed) — two sections of one screen there, so both render here together;
 * This page renders standalone (own sidebar item) or embedded as the
 * Patient Intake hub's "Referral Queue & Admission" tab.
 *
 * Front desk still can NEVER complete an Admission on its own — that
 * always requires a pending AdmissionReferral, and CompleteAdmissionModal
 * below still won't act on an externally-sourced one until a hospital
 * doctor has countersigned it. What front desk CAN now do (v9 — "front
 * desk must be able to act on an external referral letter"): log the
 * referral itself the moment a patient arrives with an outside doctor's
 * paper/PDF letter, via LogExternalReferralModal / RegisterExternalReferralView
 * — instead of waiting for an in-app doctor to type the same letter into
 * Recommend Admission first. That referral still lands as
 * status=pending/accepted_by=None, same as always, so it still needs a
 * doctor's countersign before this page's own Complete Registration button
 * will do anything with it (see models.AdmissionReferral module docstring,
 * design decision 2). There is still no "create an Admission directly"
 * action anywhere on this page.
 *
 * Standalone (non-embedded) view adds a tab bar: Triage/OPD Booking/
 * Emergency Registration cross-link to Patient Intake's own tabs; Referral
 * Queue is this page's existing content; IPD Admission is a real,
 * read-only list of every Admission record (GET IPD.ADMISSIONS — the same
 * AdmissionSerializer already used for the awaiting-bed list), showing
 * both bed-assigned and still-awaiting-bed admissions together. There is
 * no Discharge tab — apps/ipd has no discharge endpoint, model transition,
 * or field yet (Admission.status's ACTIVE/DISCHARGE_INITIATED states are
 * explicitly Phase 2, not built), so a Discharge tab would have nothing
 * real to show or do.
 *
 * Markup/styling follow the mockup exactly (see intake-workspace.css): the
 * referral queue is a real table (`.wtable`, red-tinted `.row-emergency`
 * rows for MLC/emergency-sourced referrals), and bed assignment is the
 * mockup's visual clickable `.bedgrid` rather than a plain <select>.
 */
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { ROUTES } from "../../config/routes.config";
import { useApi }    from "../../hooks/useApi";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

function timeAgo(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return new Date(iso).toLocaleDateString();
}

function CheckIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <path d="M4 12l5 5L20 6" />
    </svg>
  );
}

// Bed status -> the CSS class from intake-workspace.css that colors it, and
// the label the legend/details panel shows. "available" is styled as
// `.bed.free` (pre-existing class, kept as-is so nothing else regresses);
// the rest render distinctly instead of collapsing into one gray "taken".
const BED_STATUS_META = {
  available:      { cls: "free",     label: "Available" },
  reserved:       { cls: "reserved", label: "Reserved" },
  occupied:       { cls: "occupied", label: "Occupied" },
  cleaning:       { cls: "cleaning", label: "Cleaning" },
  blocked:        { cls: "blocked",  label: "Blocked" },
  out_of_service: { cls: "blocked",  label: "Out of Service" },
};
function bedStatusMeta(status) {
  return BED_STATUS_META[status] || { cls: "taken", label: status || "Unavailable" };
}

// Visual bed picker shared by CompleteAdmissionModal ("assign now") and
// AssignBedModal (the Awaiting Bed worklist's "assign later" action) — one
// fetch-and-render implementation so both stay in sync with what
// org.BedListCreateView actually returns. Fetches every bed in the branch
// (not just available ones) so occupied/cleaning/blocked beds render in
// their own color rather than simply vanishing from a dropdown.
//
// Rooms used to be split into a separate "Ward" concept with its own Ward
// Type catalog — the two were unified (see org.Room's own docstring and
// hospital-admin/RoomsPage.jsx, which manages the same catalog): a "ward"
// is just a Room whose Room Type is bed-based (billing.OptionList's
// is_bed_based flag), so this picker fetches ORG.ROOMS and narrows to the
// bed-based ones client-side. Room Type shown next to each room's name is
// that catalog's configured label, not the raw stored value — so this
// dropdown reads "General Ward (General Ward)" the same way it used to
// read "General Ward (General)". Picking one specific room also surfaces
// its Floor and Department right below the dropdown, and narrows the grid
// to just that room's beds (org.BedListCreateView's own room_id filter,
// already in the GET below); leaving "All rooms" selected groups the full
// branch-wide grid under a heading per room instead of dumping every bed
// into one undifferentiated list.
function BedSelector({ branchId, roomId, setRoomId, bedId, setBedId }) {
  const { data: allRooms } = useApi(API_ENDPOINTS.ORG.ROOMS, {
    params: { branch_id: branchId }, skip: !branchId,
  });
  const { data: roomTypes } = useApi(API_ENDPOINTS.BILLING.ROOM_TYPES);
  const { data: beds, isLoading: bedsLoading } = useApi(API_ENDPOINTS.ORG.BEDS, {
    params: { branch_id: branchId, ...(roomId ? { room_id: roomId } : {}) },
    skip: !branchId,
  });

  const roomTypeMeta = (value) => (roomTypes || []).find((t) => t.value === value) || null;
  // Only bed-based rooms (general ward/private/ICU/etc.) belong in a bed
  // picker — an OPD consultation room never has beds.
  const rooms = (allRooms || []).filter((r) => roomTypeMeta(r.room_type)?.is_bed_based);
  const roomTypeLabel = (value) => roomTypeMeta(value)?.label || value || "—";
  const selectedRoom = rooms.find((r) => String(r.id) === String(roomId));
  const list = beds || [];
  const freeCount = list.filter((b) => b.status === "available").length;
  const pickedBed = list.find((b) => String(b.id) === String(bedId));

  // Group beds by room only when no single room is picked — id -> {room, beds}.
  const groups = !roomId
    ? list.reduce((acc, b) => {
        (acc[b.room] ||= { room: rooms.find((r) => r.id === b.room), beds: [] }).beds.push(b);
        return acc;
      }, {})
    : null;

  function renderBed(b) {
    const meta = bedStatusMeta(b.status);
    const selectable = b.status === "available";
    const picked = String(bedId) === String(b.id);
    return (
      <div
        key={b.id}
        className={"bed" + (picked ? " picked" : ` ${meta.cls}`)}
        title={`${b.room_name} — Bed ${b.bed_number} (${meta.label})`}
        onClick={() => selectable && setBedId(String(b.id))}
      >
        {b.bed_number}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="field" style={{ maxWidth: 320 }}>
        <label>Ward / Room</label>
        <select value={roomId} onChange={(e) => { setRoomId(e.target.value); setBedId(""); }}>
          <option value="">All wards</option>
          {rooms.map((r) => (
            <option key={r.id} value={r.id}>{r.name} ({roomTypeLabel(r.room_type)})</option>
          ))}
        </select>
      </div>

      {selectedRoom && (
        <div className="fine">
          Floor: {selectedRoom.floor_name || "—"} | Department: {selectedRoom.department_name || "—"}
        </div>
      )}

      <div className="bed-legend">
        <span className="dot available">Available</span>
        <span className="dot occupied">Occupied</span>
        <span className="dot cleaning">Cleaning</span>
        <span className="dot blocked">Blocked</span>
      </div>

      <div className="fine">
        {bedsLoading ? "Loading beds…" : `${freeCount} of ${list.length} beds free${roomId ? " in this ward" : ""}`}
      </div>

      {groups ? (
        Object.values(groups)
          .sort((a, b) => (a.room?.name || "").localeCompare(b.room?.name || ""))
          .map((g) => (
            <div key={g.room?.id ?? "unknown"}>
              <div className="ward-group-label">{g.room?.name || "Unknown ward"}</div>
              <div className="bedgrid">{g.beds.map(renderBed)}</div>
            </div>
          ))
      ) : (
        <div className="bedgrid">{list.map(renderBed)}</div>
      )}

      {!bedsLoading && list.length === 0 && (
        <div className="fine">No beds configured{roomId ? " in this ward" : ""}.</div>
      )}

      {pickedBed && (
        <div className="fgrid" style={{ background: "var(--iw-surface-2)", borderRadius: "var(--iw-radius)", padding: 12 }}>
          <div className="field">
            <label>Bed Number</label>
            <div className="val">{pickedBed.bed_number}</div>
          </div>
          <div className="field">
            <label>Ward</label>
            <div className="val">{pickedBed.room_name}</div>
          </div>
          <div className="field">
            <label>Floor</label>
            <div className="val">{rooms.find((r) => r.id === pickedBed.room)?.floor_name || "—"}</div>
          </div>
          <div className="field">
            <label>Department</label>
            <div className="val">{rooms.find((r) => r.id === pickedBed.room)?.department_name || "—"}</div>
          </div>
          <div className="field">
            <label>Status</label>
            <div className="val">{bedStatusMeta(pickedBed.status).label}</div>
          </div>
        </div>
      )}
    </div>
  );
}

// Standalone bed assignment for an admission that was completed with the
// bed deferred — opened from the Awaiting Bed worklist below.
function AssignBedModal({ admission, branchId, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [roomId, setRoomId] = useState("");
  const [bedId, setBedId] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!bedId) {
      toastApiError({ message: "Select a bed first." });
      return;
    }
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_ASSIGN_BED(admission.id), { bed_id: Number(bedId) });
      toastSuccess(`Bed assigned to ${admission.patient_name}.`);
      onDone();
    } catch (err) {
      toastApiError(err, "Could not assign bed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(21,36,32,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
      <div className="intake-workspace" style={{ width: 480 }}>
        <div className="panel">
          <div className="panel-head">
            <h2>Assign bed — {admission.patient_name}</h2>
            <span className="chip chip-shared">step 5</span>
          </div>
          <div className="section">
            <div className="fine">{admission.admission_number} · {admission.department_name}</div>
            <BedSelector branchId={branchId} roomId={roomId} setRoomId={setRoomId} bedId={bedId} setBedId={setBedId} />
          </div>
          <div className="btnbar">
            <button className="primary-btn ipd" disabled={saving || !bedId} onClick={submit}>
              {saving ? "Assigning…" : "Assign Bed"}
            </button>
            <button className="secondary-btn" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CompleteAdmissionModal({ referral, branchId, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [form, setForm] = useState({
    attendant_name: "", attendant_phone: "",
    payer_type: "self", insurance_provider: "",
    expected_discharge_date: "", consent_given: false,
  });
  const [saving, setSaving] = useState(false);

  // Bed assignment — "now" (pick a specific bed as part of this same
  // screen) or "later" (leave it to the Awaiting Bed worklist below). This
  // is a second, separate API call after CompleteAdmissionView succeeds —
  // that view has no bed_id field of its own by design (see
  // apps/ipd/serializers.py::CompleteAdmissionSerializer).
  const [bedChoice, setBedChoice] = useState("later");
  const [roomId, setRoomId] = useState("");
  const [bedId, setBedId] = useState("");

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const submit = async () => {
    if (!form.consent_given) {
      toastApiError({ message: "Consent must be captured before completing registration." });
      return;
    }
    if (bedChoice === "now" && !bedId) {
      toastApiError({ message: 'Select a bed, or switch to "Assign later".' });
      return;
    }
    setSaving(true);
    try {
      const { data: res } = await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_REGISTER, {
        referral_id: referral.id,
        attendant_name: form.attendant_name,
        attendant_phone: form.attendant_phone,
        payer_type: form.payer_type,
        insurance_provider: form.insurance_provider,
        expected_discharge_date: form.expected_discharge_date || null,
        consent_given: form.consent_given,
      });
      const admission = res?.data || res;

      if (bedChoice === "now" && bedId) {
        try {
          await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_ASSIGN_BED(admission.id), { bed_id: Number(bedId) });
          toastSuccess(`Admission completed and bed assigned — ${referral.patient_name} is admitted.`);
        } catch (bedErr) {
          toastApiError(bedErr, "Admission completed, but the bed could not be assigned — assign it from the Awaiting Bed worklist.");
        }
      } else {
        toastSuccess(`Admission completed — ${referral.patient_name} added to the Awaiting Bed worklist.`);
      }
      // Take the user straight to this admission's own page — completing
      // registration used to just close the modal and leave you back on
      // the referral queue with no obvious way to find the patient you
      // just admitted.
      onDone(admission);
    } catch (err) {
      toastApiError(err, "Could not complete registration.");
    } finally {
      setSaving(false);
    }
  };

  const requiresAcceptance = referral.requires_acceptance;
  const blockedOnAcceptance = requiresAcceptance && !referral.accepted_by;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(21,36,32,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
      <div className="intake-workspace" style={{ width: 640, maxHeight: "88vh" }}>
        <div className="panel" style={{ maxHeight: "88vh", overflowY: "auto" }}>
          <div className="panel-head">
            <h2>Complete admission</h2>
            <span className="chip chip-ipd">step 5</span>
          </div>

          <div className="section" style={{ background: "var(--iw-surface-2)" }}>
            <div className="fine" style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: ".03em", fontSize: 11 }}>
              Doctor's referral — read-only
            </div>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>{referral.patient_name} · UHID {referral.patient_uhid}</div>
            <div className="fine">
              Ordered by <b>{referral.recommended_by_name}</b> · {referral.department_name}{" "}
              <span className="chip chip-ipd">{referral.admission_type}</span>
            </div>
            <div className="fine">{referral.reason_for_admission}</div>
            {requiresAcceptance && (
              <div>
                {referral.accepted_by
                  ? <span className="chip chip-opd">Countersigned by {referral.accepted_by_name}</span>
                  : <span className="chip chip-new">Awaiting a hospital doctor's countersign</span>}
              </div>
            )}
          </div>

          {blockedOnAcceptance ? (
            <div className="id-banner">
              Cannot register yet — this referral came from outside the hospital ({referral.admission_source}) and
              needs one of this hospital's own doctors to accept it before front desk can complete registration.
            </div>
          ) : (
            <>
              <div className="section">
                <div className="fgrid">
                  <div className="field">
                    <label>Attendant / next of kin — name</label>
                    <input value={form.attendant_name} onChange={set("attendant_name")} placeholder="e.g. Sunita Kumar (spouse)" />
                  </div>
                  <div className="field">
                    <label>Attendant phone</label>
                    <input value={form.attendant_phone} onChange={set("attendant_phone")} placeholder="+91 9xxxxxxxxx" />
                  </div>
                  <div className="field">
                    <label>Payer type</label>
                    <select value={form.payer_type} onChange={set("payer_type")}>
                      <option value="self">Self Pay</option>
                      <option value="insurance">Insurance</option>
                      <option value="corporate">Corporate</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>Insurance provider</label>
                    <input value={form.insurance_provider} onChange={set("insurance_provider")} />
                  </div>
                  <div className="field">
                    <label>Expected discharge date</label>
                    <input type="date" value={form.expected_discharge_date} onChange={set("expected_discharge_date")} />
                  </div>
                </div>
              </div>

              <div className="section">
                <div className="fine" style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: ".03em", fontSize: 11 }}>
                  Bed assignment
                </div>
                <div className="choice-row">
                  <div className={"choice-card" + (bedChoice === "later" ? " picked" : "")} onClick={() => setBedChoice("later")}>
                    <b>Assign later</b>
                    <span>Adds to the Awaiting Bed worklist</span>
                  </div>
                  <div className={"choice-card" + (bedChoice === "now" ? " picked" : "")} onClick={() => setBedChoice("now")}>
                    <b>Assign now</b>
                    <span>Pick a bed as part of this registration</span>
                  </div>
                </div>
                {bedChoice === "now" && (
                  <BedSelector branchId={branchId} roomId={roomId} setRoomId={setRoomId} bedId={bedId} setBedId={setBedId} />
                )}
              </div>

              <div className="section">
                <label className="toggle-row">
                  <span
                    className={"fakecheck" + (form.consent_given ? " on" : "")}
                    onClick={(e) => { e.preventDefault(); setForm((f) => ({ ...f, consent_given: !f.consent_given })); }}
                  >
                    {form.consent_given && <CheckIcon />}
                  </span>
                  <input type="checkbox" checked={form.consent_given} onChange={set("consent_given")} style={{ display: "none" }} />
                  Patient / attendant consents to inpatient treatment and admission (DPDP-style consent event)
                </label>
              </div>

              <div className="btnbar">
                <button className="primary-btn ipd" disabled={saving || !form.consent_given} onClick={submit}>
                  {saving ? "Saving…" : "Complete Registration & Mark Admitted →"}
                </button>
                <button className="secondary-btn" onClick={onClose}>Cancel</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Sources RegisterExternalReferralView accepts — mirrors
// AdmissionReferral.SOURCES_REQUIRING_ACCEPTANCE on the backend (see
// apps/ipd/models.py) and doctor/EncounterPage.jsx's own
// EXTERNAL_ADMISSION_SOURCES, which the doctor-side Recommend Admission
// form uses for the same reason: these are the only sources a referral can
// ever require a countersign for.
const EXTERNAL_ADMISSION_SOURCES = new Set(["external_referral", "transfer_in", "ambulance_ems", "medical_tourism"]);

// Front desk logging a referral straight from an external letter — the
// front-desk-side counterpart to doctor/EncounterPage.jsx's own
// AdmissionReferralModal, posting to IPD.REFERRAL_REGISTER_EXTERNAL
// instead of IPD.REFERRAL_RECOMMEND. Same two-step outcome either way (the
// referral still needs a doctor's countersign before Complete Registration
// works) — see this file's own module docstring.
function LogExternalReferralModal({ onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data: departments } = useApi(API_ENDPOINTS.ORG.DEPARTMENTS);
  const { data: admissionTypes } = useApi(API_ENDPOINTS.IPD.ADMISSION_TYPES);
  const { data: admissionSources } = useApi(API_ENDPOINTS.IPD.ADMISSION_SOURCES);

  // Patient search — same debounced-search pattern as
  // front-desk/AppointmentsPage.jsx's own patient picker (PATIENTS.SEARCH,
  // ~250ms debounce, `data?.data?.results || data?.results || []`).
  const [patientQuery, setPatientQuery] = useState("");
  const [patientOpts, setPatientOpts] = useState([]);
  const [patient, setPatient] = useState(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (patient || patientQuery.trim().length < 2) { setPatientOpts([]); return; }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const { data } = await apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, { params: { q: patientQuery } });
        const payload = data?.data || data || {};
        setPatientOpts(payload.results || []);
      } catch {
        setPatientOpts([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [patientQuery, patient]);

  const [form, setForm] = useState({
    department: "", admission_type: "", admission_source: "",
    reason_for_admission: "",
    external_referring_doctor_name: "", external_referring_facility: "",
    referral_letter_date: "", referral_letter_reference: "",
    is_mlc: false, guardian_consent_by: "",
  });
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const activeTypes = (admissionTypes || []).filter((t) => t.is_active !== false);
  const activeSources = (admissionSources || []).filter((s) => s.is_active !== false && EXTERNAL_ADMISSION_SOURCES.has(s.value));
  const canSubmit = patient && form.department && form.admission_type && form.admission_source
    && form.reason_for_admission.trim().length > 0
    && form.external_referring_doctor_name.trim().length > 0
    && form.external_referring_facility.trim().length > 0;

  async function submit() {
    if (!canSubmit) return;
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.REFERRAL_REGISTER_EXTERNAL, {
        patient_id: patient.id,
        department_id: form.department,
        admission_type: form.admission_type,
        admission_source: form.admission_source,
        reason_for_admission: form.reason_for_admission,
        external_referring_doctor_name: form.external_referring_doctor_name,
        external_referring_facility: form.external_referring_facility,
        referral_letter_date: form.referral_letter_date || null,
        referral_letter_reference: form.referral_letter_reference,
        is_mlc: form.is_mlc,
        guardian_consent_by: form.guardian_consent_by,
      });
      toastSuccess(`External referral logged for ${patient.full_name}.`);
      setSubmitted(true);
    } catch (err) {
      toastApiError(err, "Could not log the external referral.");
    } finally {
      setSaving(false);
    }
  }

  if (submitted) {
    return (
      <div style={{ position: "fixed", inset: 0, background: "rgba(21,36,32,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
        <div className="intake-workspace" style={{ width: 480 }}>
          <div className="panel">
            <div className="panel-head">
              <h2>Referral logged</h2>
              <span className="chip chip-opd">Done</span>
            </div>
            <div className="section">
              <div className="fine">
                {patient?.full_name}'s referral is on the queue below, marked "Needs countersign" — a hospital
                doctor has to accept it before Complete Registration will work.
              </div>
            </div>
            <div className="btnbar">
              <button className="primary-btn ipd" onClick={() => { onDone(); onClose(); }}>Done</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(21,36,32,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40 }}>
      <div className="intake-workspace" style={{ width: 640, maxHeight: "88vh" }}>
        <div className="panel" style={{ maxHeight: "88vh", overflowY: "auto" }}>
          <div className="panel-head">
            <h2>Log external referral letter</h2>
            <span className="chip chip-ipd">front desk</span>
          </div>

          <div className="section">
            <div className="fine">
              For a patient who arrives with a referral letter from an outside doctor or facility — records it on
              the queue right away, instead of waiting for a doctor to type the same letter into Recommend
              Admission. A hospital doctor still has to countersign it before it can be registered.
            </div>
          </div>

          <div className="section">
            <div className="field">
              <label>Patient</label>
              {patient ? (
                <div className="fgrid" style={{ background: "var(--iw-surface-2)", borderRadius: "var(--iw-radius)", padding: 12, alignItems: "center", gridTemplateColumns: "1fr auto" }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{patient.full_name}</div>
                    <div className="fine">UHID {patient.uhid}</div>
                  </div>
                  <button className="secondary-btn" type="button" onClick={() => { setPatient(null); setPatientQuery(""); }}>Change</button>
                </div>
              ) : (
                <>
                  <input value={patientQuery} onChange={(e) => setPatientQuery(e.target.value)} placeholder="Search by name, UHID, or phone…" />
                  {patientQuery.trim().length >= 2 && (
                    <div style={{ border: "1px solid var(--iw-border)", borderRadius: "var(--iw-radius)", marginTop: 4, maxHeight: 180, overflowY: "auto" }}>
                      {searching && <div className="fine" style={{ padding: 10 }}>Searching…</div>}
                      {!searching && patientOpts.length === 0 && <div className="fine" style={{ padding: 10 }}>No matching patients.</div>}
                      {patientOpts.map((p) => (
                        <div key={p.id} style={{ padding: "8px 10px", cursor: "pointer", borderBottom: "1px solid var(--iw-border)" }}
                          onClick={() => { setPatient(p); setPatientOpts([]); }}>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{p.full_name}</div>
                          <div className="fine">UHID {p.uhid}{p.mobile ? ` · ${p.mobile}` : ""}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <div className="section">
            <div className="fgrid">
              <div className="field">
                <label>Department</label>
                <select value={form.department} onChange={set("department")}>
                  <option value="">Select department…</option>
                  {(departments || []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Admission Type</label>
                <select value={form.admission_type} onChange={set("admission_type")}>
                  <option value="">Select type…</option>
                  {activeTypes.map((t) => <option key={t.id ?? t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
            </div>
            <div className="field">
              <label>How the referral arrived</label>
              <select value={form.admission_source} onChange={set("admission_source")}>
                <option value="">Select source…</option>
                {activeSources.map((s) => <option key={s.id ?? s.value} value={s.value}>{s.label}</option>)}
              </select>
              <div className="fine">Only externally-sourced options are offered here — anything else needs a doctor's own Recommend Admission.</div>
            </div>
          </div>

          <div className="section" style={{ background: "var(--iw-surface-2)" }}>
            <div className="fine" style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: ".03em", fontSize: 11 }}>
              The letter
            </div>
            <div className="fgrid">
              <div className="field">
                <label>Referring doctor (external)</label>
                <input value={form.external_referring_doctor_name} onChange={set("external_referring_doctor_name")} placeholder="Dr. …" />
              </div>
              <div className="field">
                <label>Referring facility</label>
                <input value={form.external_referring_facility} onChange={set("external_referring_facility")} placeholder="e.g. City Care Hospital" />
              </div>
              <div className="field">
                <label>Letter date</label>
                <input type="date" value={form.referral_letter_date} onChange={set("referral_letter_date")} />
              </div>
              <div className="field">
                <label>Letter reference # (optional)</label>
                <input value={form.referral_letter_reference} onChange={set("referral_letter_reference")} />
              </div>
            </div>
          </div>

          <div className="section">
            <div className="field">
              <label>Reason for admission</label>
              <textarea rows={3} value={form.reason_for_admission} onChange={set("reason_for_admission")} placeholder="As stated on the referral letter…" />
            </div>
            <div className="fgrid">
              <div className="field" style={{ flexDirection: "row", alignItems: "center", gap: 10, display: "flex" }}>
                <input type="checkbox" checked={form.is_mlc} onChange={set("is_mlc")} id="ext-ref-mlc" />
                <label htmlFor="ext-ref-mlc" style={{ marginBottom: 0 }}>Medico-Legal Case (MLC)</label>
              </div>
              <div className="field">
                <label>Guardian consent by (if minor / unconscious)</label>
                <input value={form.guardian_consent_by} onChange={set("guardian_consent_by")} />
              </div>
            </div>
          </div>

          <div className="btnbar">
            <button className="primary-btn ipd" disabled={!canSubmit || saving} onClick={submit}>
              {saving ? "Logging…" : "Log Referral →"}
            </button>
            <button className="secondary-btn" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function AdmissionsPageContent({ embedded = false }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const branchId = user?.branch_id;
  const { data: referrals, isLoading, refetch } = useApi(API_ENDPOINTS.IPD.REFERRALS, { params: { status: "pending" } });
  const { data: awaitingBed, refetch: refetchAwaitingBed } = useApi(API_ENDPOINTS.IPD.ADMISSION_AWAITING_BED);
  const [active, setActive] = useState(null);
  const [assigningFor, setAssigningFor] = useState(null);
  const [loggingExternal, setLoggingExternal] = useState(false);

  const frame = (content) => embedded ? content : <AppShell><PageShell title="">{content}</PageShell></AppShell>;

  return frame(
    <>
      {!embedded && (
        <div className="fdc-header-row">
          <div>
            <div className="fdc-eyebrow">Front Desk &middot; IPD</div>
            <div className="fdc-title">Admission Requests</div>
            <div className="fdc-subtitle">
              Referrals waiting on registration, and completed admissions still waiting on a bed. Once a patient
              is admitted, find them under <b>Current Patients</b> in the sidebar.
            </div>
          </div>
        </div>
      )}

      <div className="intake-workspace">
          <div className="panel" style={{ marginTop: 14 }}>
            <div className="panel-head">
              <h2>Referral queue — pending registration</h2>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span className="chip chip-ipd">{referrals?.length ?? (isLoading ? "…" : 0)} pending</span>
                <button className="primary-btn ipd" onClick={() => setLoggingExternal(true)}>
                  + Log External Referral Letter
                </button>
              </div>
            </div>
            <div className="section">
              <div className="fine">
                Front desk completes registration only — the clinical decision to admit always starts with a
                referral. Most of this queue comes from a doctor's own Recommend Admission; when a patient arrives
                with a referral letter from an outside doctor, front desk can log it directly above instead of
                waiting for someone in-app to type it in — it still needs a hospital doctor's countersign before
                registration can be completed.
              </div>
            </div>
            <div className="section" style={{ overflowX: "auto" }}>
              <table className="wtable">
                <thead>
                  <tr>
                    <th>Patient</th>
                    <th>Source</th>
                    <th>Department</th>
                    <th>Logged by</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(referrals || []).map((r) => {
                    const emergency = r.admission_source === "involuntary_mlc" || r.is_mlc;
                    const blocked = r.requires_acceptance && !r.accepted_by;
                    return (
                      <tr key={r.id} className={emergency ? "row-emergency" : ""}>
                        <td>
                          <div style={{ fontWeight: 700 }}>{r.patient_name}</div>
                          <div className="fine">UHID {r.patient_uhid} · {timeAgo(r.recommended_at)}</div>
                        </td>
                        <td>
                          {emergency
                            ? <span className="chip chip-critical">MLC / Emergency</span>
                            : <span className="chip chip-shared">{r.admission_type}</span>}
                        </td>
                        <td>{r.department_name}</td>
                        <td>
                          {r.recommended_by_name}
                          {r.front_desk_logged && <div className="fine">from an external letter</div>}
                        </td>
                        <td>
                          {blocked
                            ? <span className="chip chip-new">Needs countersign</span>
                            : <span className="chip chip-opd">Ready</span>}
                        </td>
                        <td>
                          <button className="primary-btn ipd" disabled={blocked} onClick={() => setActive(r)}>
                            {blocked ? "Awaiting countersign" : "Complete Registration →"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {!isLoading && (referrals || []).length === 0 && (
                    <tr><td colSpan={6} className="fine" style={{ padding: "16px 14px" }}>No admissions are waiting on registration right now.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 14 }}>
            <div className="panel-head">
              <h2>Awaiting bed</h2>
              <span className="chip chip-shared">{awaitingBed?.length ?? 0}</span>
            </div>
            <div className="section" style={{ overflowX: "auto" }}>
              <table className="wtable">
                <thead>
                  <tr>
                    <th>Patient</th>
                    <th>Admission #</th>
                    <th>Department</th>
                    <th>Admitted</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(awaitingBed || []).map((a) => (
                    <tr key={a.id}>
                      <td style={{ fontWeight: 700 }}>{a.patient_name}</td>
                      <td className="iw-mono">{a.admission_number}</td>
                      <td>{a.department_name} <span className="chip chip-shared">{a.admission_type}</span></td>
                      <td className="fine">{timeAgo(a.created_at)}</td>
                      <td><button className="primary-btn ipd" onClick={() => setAssigningFor(a)}>Assign Bed →</button></td>
                    </tr>
                  ))}
                  {(awaitingBed || []).length === 0 && (
                    <tr><td colSpan={5} className="fine" style={{ padding: "16px 14px" }}>No admissions are waiting on a bed right now.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
      </div>

      {active && (
        <CompleteAdmissionModal
          referral={active}
          branchId={branchId}
          onClose={() => setActive(null)}
          onDone={(admission) => { setActive(null); navigate(ROUTES.FRONT_DESK.ADMISSION_DETAIL(admission.id)); }}
        />
      )}

      {assigningFor && (
        <AssignBedModal
          admission={assigningFor}
          branchId={branchId}
          onClose={() => setAssigningFor(null)}
          onDone={() => navigate(ROUTES.FRONT_DESK.ADMISSION_DETAIL(assigningFor.id))}
        />
      )}

      {loggingExternal && (
        <LogExternalReferralModal
          onClose={() => setLoggingExternal(false)}
          onDone={() => refetch()}
        />
      )}
    </>
  );
}

export default function AdmissionsPage() {
  return <AdmissionsPageContent />;
}
