/**
 * components/front-desk/QuickRegisterModal.jsx
 * -----------------------------------------------
 * Minimal-field registration for two situations where front desk can't
 * (or shouldn't have to) collect a full registration form up front:
 *
 *   1. Emergency / walk-in — name + mobile + age only. Everything else
 *      (address, insurance, emergency contact, etc.) can be filled in
 *      later from the patient's record; what matters right now is getting
 *      them a UHID and in front of a doctor.
 *   2. Registering a family member found via the family-tree lookup who
 *      isn't registered at this hospital yet — same minimal shape, but
 *      tied to the guardian's AWPID as a dependent (see
 *      PatientService.resolve_dependent_identity).
 *
 * Age is converted to an approximate date_of_birth (Jan 1 of the birth
 * year) since Patient has no separate "age" field — good enough to get
 * someone booked; the real DOB can be corrected later from the full
 * registration/edit form.
 */
import { useState } from "react";
import { X, Siren, UserPlus } from "lucide-react";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { sanitizeMobileInput, isValidMobile } from "../../utils/validation";

function approximateDobFromAge(age) {
  const n = Number(age);
  if (!n || n <= 0) return null;
  const year = new Date().getFullYear() - n;
  return `${year}-01-01`;
}

// Inverse of the above, for prefilling from a known date_of_birth (e.g. a
// family-tree entry) — just whole years, same precision the age field
// itself works in.
function ageFromDob(dob) {
  if (!dob) return "";
  const year = Number(String(dob).slice(0, 4));
  if (!year) return "";
  const age = new Date().getFullYear() - year;
  return age > 0 ? String(age) : "";
}

const RELATIONS = [
  { value: "child",   label: "Child" },
  { value: "parent",  label: "Parent" },
  { value: "spouse",  label: "Spouse" },
  { value: "sibling", label: "Sibling" },
  { value: "ward",    label: "Ward" },
  { value: "other",   label: "Other" },
];

/**
 * @param {boolean} open
 * @param {() => void} onClose
 * @param {(patient: object) => void} onRegistered - called with the
 *   PatientDetailSerializer response after a successful registration.
 * @param {number|string} branchId - branch to register under.
 * @param {{awpid: string, full_name: string, relation?: string} | null} guardian
 *   when set, registers a dependent under this guardian instead of a new
 *   independent adult patient.
 * @param {{full_name?: string, date_of_birth?: string, gender?: string} | null} prefill
 *   known details about the PERSON BEING REGISTERED (not the guardian) —
 *   e.g. from a family-tree lookup that already knows this relative's name/
 *   DOB/gender even though they have no local record at this hospital yet.
 *   Pre-fills those fields instead of asking front desk to re-type
 *   something the system already has on file.
 */
export default function QuickRegisterModal({ open, onClose, onRegistered, branchId, guardian = null, prefill = null }) {
  const { toastSuccess, toastApiError } = useToast();
  const [fullName, setFullName] = useState(prefill?.full_name || guardian?.suggestedName || "");
  const [mobile, setMobile] = useState("");
  const [age, setAge] = useState(() => ageFromDob(prefill?.date_of_birth));
  const [gender, setGender] = useState(prefill?.gender || "");
  const [relationship, setRelationship] = useState(guardian?.relation || "child");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const hasPrefill = !!(prefill?.full_name || prefill?.date_of_birth || prefill?.gender);

  // "Who is the patient?" — only asked in true emergency mode (no guardian
  // already found via family-tree lookup). The caller who phones in isn't
  // always the patient — could be calling about their kid, parent, etc.
  // "self": the caller IS the patient — mobile/name/age are theirs directly.
  // "relative": the caller is reporting on someone else — we still only
  // need the caller's mobile (as contact/guardian) plus the patient's own
  // name + age; the relationship tells us how the patient relates to caller.
  const [patientIs, setPatientIs] = useState("self");
  const [callerName, setCallerName] = useState("");

  if (!open) return null;

  const isDependent = !!guardian || patientIs === "relative";
  const isEmergencyRelative = !guardian && patientIs === "relative";

  function resetForm() {
    setFullName(""); setMobile(""); setAge(""); setGender("");
    setRelationship("child"); setPatientIs("self"); setCallerName("");
  }

  async function submit(e) {
    e.preventDefault();
    setError("");

    if (!fullName.trim()) { setError("Patient's name is required."); return; }
    if (!isDependent && !isValidMobile(mobile)) { setError("Enter a valid 10-digit mobile number."); return; }
    if (isEmergencyRelative && !isValidMobile(mobile)) { setError("Enter a valid 10-digit mobile number for the caller."); return; }

    const dob = approximateDobFromAge(age);
    if (isDependent && !dob) { setError("Age is required to register a dependent."); return; }

    const payload = {
      full_name: fullName.trim(),
      branch_id: branchId,
      dpdp_consent: false,
      gender: gender || undefined,
      date_of_birth: dob || undefined,
      ...(guardian
        ? {
            is_dependent: true,
            guardian_awpid: guardian.awpid,
            guardian_name: guardian.full_name,
            relationship,
          }
        : isEmergencyRelative
        ? {
            // No existing guardian record yet — backend resolves/creates
            // the caller's network identity from their mobile number.
            is_dependent: true,
            guardian_mobile: sanitizeMobileInput(mobile),
            guardian_name: callerName.trim() || undefined,
            relationship,
          }
        : { mobile: sanitizeMobileInput(mobile) }),
    };

    setSaving(true);
    try {
      const { data: res } = await apiClient.post(API_ENDPOINTS.PATIENTS.REGISTER, payload);
      const created = res?.data || res;
      toastSuccess(`${created.full_name} registered — UHID ${created.uhid}.`);
      onRegistered(created);
      resetForm();
    } catch (err) {
      const msg = err?.data?.message || err?.data?.errors
        ? (err.data.message || Object.values(err.data.errors || {}).flat().join(" "))
        : "Could not register patient.";
      setError(msg);
      toastApiError(err, "Could not register patient.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 200,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
    }} onClick={onClose}>
      <div className="card" style={{ width: "100%", maxWidth: 420, padding: 24 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {isDependent ? <UserPlus size={18} style={{ color: "var(--color-primary)" }} />
                         : <Siren size={18} style={{ color: "var(--color-error)" }} />}
            <h2 style={{ margin: 0, fontSize: 16 }}>
              {isDependent ? `Register ${guardian.full_name}'s family member` : "Emergency quick registration"}
            </h2>
          </div>
          <button type="button" onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 18 }}>
            <X size={18} />
          </button>
        </div>
        <p style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: hasPrefill ? 10 : 18 }}>
          {guardian
            ? "Just enough to book an appointment now — the rest of their record can be filled in later."
            : "Only the essentials — enough to get a UHID and get them booked in. Everything else can be completed later from their record."}
        </p>

        {hasPrefill && (
          <div style={{
            fontSize: 11.5, color: "var(--color-primary)", background: "var(--color-primary-light)",
            borderRadius: 8, padding: "8px 12px", marginBottom: 16, fontWeight: 600,
          }}>
            Name, age, and gender below are already known from this family's record — just confirm and register.
          </div>
        )}

        <form onSubmit={submit}>
          {!guardian && (
            <div style={{ marginBottom: 16 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Who is the patient?</label>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button"
                  onClick={() => setPatientIs("self")}
                  style={{
                    flex: 1, padding: "9px 10px", borderRadius: 8, fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                    border: `1.5px solid ${patientIs === "self" ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: patientIs === "self" ? "var(--color-primary-light)" : "transparent",
                    color: patientIs === "self" ? "var(--color-primary)" : "var(--color-text-secondary)",
                  }}
                >
                  The caller themself
                </button>
                <button type="button"
                  onClick={() => setPatientIs("relative")}
                  style={{
                    flex: 1, padding: "9px 10px", borderRadius: 8, fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                    border: `1.5px solid ${patientIs === "relative" ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: patientIs === "relative" ? "var(--color-primary-light)" : "transparent",
                    color: patientIs === "relative" ? "var(--color-primary)" : "var(--color-text-secondary)",
                  }}
                >
                  A relative (mom, dad, kid…)
                </button>
              </div>
            </div>
          )}

          {isEmergencyRelative && (
            <div style={{ marginBottom: 14 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Caller's mobile number *</label>
              <input className="form-input" value={mobile} maxLength={10}
                onChange={e => setMobile(sanitizeMobileInput(e.target.value))} placeholder="10-digit mobile" />
            </div>
          )}
          {isEmergencyRelative && (
            <div style={{ marginBottom: 14 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Caller's name (optional)</label>
              <input className="form-input" value={callerName} onChange={e => setCallerName(e.target.value)} placeholder="Who's calling in" />
            </div>
          )}

          <div style={{ marginBottom: 14 }}>
            <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>
              {isEmergencyRelative ? "Patient's full name *" : "Full name *"}
            </label>
            <input className="form-input" value={fullName} onChange={e => setFullName(e.target.value)} autoFocus />
          </div>

          {!isDependent && (
            <div style={{ marginBottom: 14 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Mobile number *</label>
              <input className="form-input" value={mobile} maxLength={10}
                onChange={e => setMobile(sanitizeMobileInput(e.target.value))} placeholder="10-digit mobile" />
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>
                {isEmergencyRelative ? "Patient's age *" : `Age ${isDependent ? "*" : ""}`}
              </label>
              <input className="form-input" type="number" min="0" max="120" value={age}
                onChange={e => setAge(e.target.value)} placeholder="Years" />
            </div>
            <div>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Gender</label>
              <select className="form-input" style={{ appearance: "auto" }} value={gender} onChange={e => setGender(e.target.value)}>
                <option value="">—</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>

          {guardian && (
            <div style={{ marginBottom: 14 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Relationship to {guardian.full_name}</label>
              <select className="form-input" style={{ appearance: "auto" }} value={relationship} onChange={e => setRelationship(e.target.value)}>
                {RELATIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
          )}

          {isEmergencyRelative && (
            <div style={{ marginBottom: 14 }}>
              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Patient is the caller's…</label>
              <select className="form-input" style={{ appearance: "auto" }} value={relationship} onChange={e => setRelationship(e.target.value)}>
                {RELATIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
          )}

          {error && (
            <div style={{ fontSize: 12.5, color: "var(--color-error)", marginBottom: 12 }}>{error}</div>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 6 }}>
            <button type="button" className="btn-outline" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? "Registering…" : "Register & continue"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
