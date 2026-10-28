/** components/front-desk/QuickRegisterModal.jsx */
import { useState } from "react";
import { X, Siren, UserPlus } from "lucide-react";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { sanitizeMobileInput, isValidMobile } from "../../utils/validation";
import { formatAgeYM } from "../../utils/age";

function approximateDobFromAge(age) {
  const n = Number(age);
  if (!n || n <= 0) return null;
  const year = new Date().getFullYear() - n;
  return `${year}-01-01`;
}

// prefill.gender arrives as the single normalized character the backend
const GENDER_CODE_TO_OPTION = { M: "male", F: "female", O: "other" };
function normalizeGenderPrefill(g) {
  if (!g) return "";
  const s = String(g).trim();
  if (s.length === 1) return GENDER_CODE_TO_OPTION[s.toUpperCase()] || "";
  const lower = s.toLowerCase();
  return ["male", "female", "other"].includes(lower) ? lower : "";
}

function joinWithAnd(items) {
  if (items.length === 0) return "";
  if (items.length === 1) return items[0];
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

const RELATIONS = [
  { value: "child",   label: "Child" },
  { value: "parent",  label: "Parent" },
  { value: "spouse",  label: "Spouse" },
  { value: "sibling", label: "Sibling" },
  { value: "ward",    label: "Ward" },
  { value: "other",   label: "Other" },
];

/** @param {boolean} open */
export default function QuickRegisterModal({ open, onClose, onRegistered, branchId, guardian = null, prefill = null }) {
  const { toastSuccess, toastApiError } = useToast();
  const [fullName, setFullName] = useState(prefill?.full_name || guardian?.suggestedName || "");
  const [mobile, setMobile] = useState("");
  // A known exact DOB (from a family-tree record) is kept as-is and sent
  const knownDob = prefill?.date_of_birth || null;
  const [age, setAge] = useState("");
  const [gender, setGender] = useState(() => normalizeGenderPrefill(prefill?.gender));
  const [relationship, setRelationship] = useState(guardian?.relation || "child");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const knownFields = [
    prefill?.full_name && "name",
    knownDob && "age",
    prefill?.gender && "gender",
  ].filter(Boolean);
  const hasPrefill = knownFields.length > 0;

  // "Who is the patient?" — only asked in true emergency mode (no guardian
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

    const dob = knownDob || approximateDobFromAge(age);
    if (isDependent && !dob) { setError("Age is required to register a dependent."); return; }

    const payload = {
      full_name: fullName.trim(),
      branch_id: branchId,
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
            {`${joinWithAnd(knownFields).replace(/^./, c => c.toUpperCase())} below ${knownFields.length > 1 ? "are" : "is"} already known from this family's record — just confirm and register.`}
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
              {knownDob ? (
                <div className="form-input" style={{
                  display: "flex", alignItems: "center", background: "var(--color-bg-secondary, #f1f5f9)",
                  color: "var(--color-text-secondary)",
                }}>
                  {formatAgeYM(knownDob) || "—"}
                </div>
              ) : (
                <input className="form-input" type="number" min="0" max="120" value={age}
                  onChange={e => setAge(e.target.value)} placeholder="Years" />
              )}
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
