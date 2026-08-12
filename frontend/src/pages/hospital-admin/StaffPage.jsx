/**
 * pages/hospital-admin/StaffPage.jsx
 * ------------------------------------
 * Hospital admin: invite and manage staff members.
 * Uses the invite → setup-password flow (no admin-set passwords).
 */

import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import { useAuth }   from "../../hooks/useAuth";
import { usePermissions } from "../../hooks/usePermissions";
import API_ENDPOINTS from "../../config/api.config";
import { Mail, Users } from "lucide-react";
import { calcAge }   from "../../utils/age";
import { sanitizeMobileInput, isValidMobile, mobileError } from "../../utils/validation";

const ROLE_LABELS = {
  hospital_admin: { label: "Hospital Admin", color: "#7c3aed" },
  doctor:         { label: "Doctor",         color: "#0ea5e9" },
  nurse:          { label: "Nurse",          color: "#16a34a" },
  front_desk:     { label: "Front Desk",     color: "#B07C24" },
  lab_tech:       { label: "Lab Tech",       color: "#0891b2" },
  pharmacist:     { label: "Pharmacist",     color: "#dc2626" },
};

const ROLES = Object.keys(ROLE_LABELS);

// Which "basics" fields to collect at invite time, per role — mirrors the
// registration-fields reference: nurse/pharmacist have a legally-mandated
// council registration, lab tech's is optional-but-common, front desk/admin
// have none. Doctor is handled separately (has its own specialisation field).
const ROLE_BASICS = {
  nurse:          { license: true,  licenseLabel: "Nursing Council Registration No." },
  pharmacist:     { license: true,  licenseLabel: "Pharmacy Council Registration No." },
  lab_tech:       { license: true,  licenseLabel: "Professional Registration No. (if applicable)" },
  front_desk:     { license: false },
  hospital_admin: { license: false },
};

function RoleBadge({ role }) {
  const r = ROLE_LABELS[role] || { label: role, color: "#64748b" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 10px", borderRadius: 20,
      fontSize: 11, fontWeight: 600,
      background: r.color + "22", color: r.color,
    }}>{r.label}</span>
  );
}

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function InviteModal({ branches, onClose, onInvited, atCapacity, permissions }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [form, setForm] = useState({
    email: "", first_name: "", last_name: "", role: "doctor",
    phone: "", branch_id: "", department_id: "",
    registration_no: "", specialisation: "", qualification: "", experience_years: "",
    council_name: "", registration_expiry: "",
    consultation_fee: "",
  });

  // Working-hours state: array of 7 day objects
  const [schedule, setSchedule] = useState(
    DAYS.map((_, i) => ({
      day_of_week:  i,
      is_available: i < 5,          // Mon–Fri on by default
      start_time:   "09:00",
      end_time:     "17:00",
    }))
  );
  const [slotDuration, setSlotDuration] = useState(15);

  // Per-invite fee toggle: true = admin sets fee now, false = doctor sets it themselves.
  // Defaults to whatever the tenant's global setting is, but admin can flip it per invite.
  const [adminSetsFee, setAdminSetsFee] = useState(false);
  useEffect(() => {
    api.get("/org/settings/")
      .then(r => {
        const fo = (r.data?.data ?? r.data)?.fee_ownership;
        setAdminSetsFee(fo === "hospital");
      })
      .catch(() => setAdminSetsFee(false));
  }, [api]);

  // Doctor-only: which branches beyond the single dropdown above they also
  // work at. Everyone else stays single-branch (see docs/onboarding_auth_
  // rbac_architecture.md 4.4 — doctors are the only role that realistically
  // needs more than one).
  const [extraBranchIds, setExtraBranchIds] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null);

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));
  function toggleExtraBranch(id) {
    setExtraBranchIds(ids => ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]);
  }

  const doctorsCapped = atCapacity?.("doctors");
  const staffCapped = atCapacity?.("staff");
  const selectedRoleCapped = form.role === "doctor" ? doctorsCapped : staffCapped;

  // Load departments when branch changes
  useEffect(() => {
    if (!form.branch_id) { setDepartments([]); return; }
    api.get(`${API_ENDPOINTS.ORG.DEPARTMENTS}?branch_id=${form.branch_id}`)
      .then(r => setDepartments(r.data?.data || []))
      .catch(() => setDepartments([]));
  }, [form.branch_id, api]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!isValidMobile(form.phone)) {
      toastApiError(null, "Enter a valid 10-digit mobile number.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        branch_id:           form.branch_id        ? parseInt(form.branch_id)        : null,
        department_id:       form.department_id    ? parseInt(form.department_id)    : null,
        experience_years:    form.experience_years ? parseInt(form.experience_years) : null,
        registration_expiry: form.registration_expiry || null,
      };
      // Doctor's extra branches, if any were checked — the primary branch
      // dropdown's value is folded in automatically as the primary on the
      // backend (see StaffInviteSerializer.branch_ids / branch_utils).
      if (form.role === "doctor" && extraBranchIds.length > 0) {
        payload.branch_ids = [
          ...(payload.branch_id ? [payload.branch_id] : []),
          ...extraBranchIds.filter(id => id !== payload.branch_id),
        ];
      }
      // specialisation only applies to doctors; council_name/registration_expiry
      // only apply to non-doctor roles with a professional license.
      if (form.role === "doctor") {
        delete payload.council_name; delete payload.registration_expiry;
        // Consultation fee — only include when admin chose to set it now
        if (adminSetsFee && form.consultation_fee) {
          payload.consultation_fee = parseFloat(form.consultation_fee);
        } else {
          delete payload.consultation_fee;
        }
        // Working-hours schedule
        const activeDays = schedule.filter(d => d.is_available);
        if (activeDays.length > 0) {
          payload.schedule = {
            slot_duration_minutes: slotDuration,
            days: schedule,
          };
        }
      } else {
        delete payload.specialisation;
        delete payload.consultation_fee;
      }
      const { data: res } = await api.post(API_ENDPOINTS.ORG.STAFF + "invite/", payload);
      setResult(res.data);
      toastSuccess(`${form.first_name} invited successfully.`);
      onInvited();
    } catch (err) {
      toastApiError(err, "Failed to invite staff.");
    } finally { setSaving(false); }
  }

  const inputStyle = {
    width: "100%", boxSizing: "border-box",
    border: "1.5px solid var(--color-border)", borderRadius: 8,
    padding: "9px 12px", fontSize: 14,
    background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
  };
  const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        background: "var(--color-surface)", borderRadius: 16,
        width: "100%", maxWidth: 540, maxHeight: "90vh", overflowY: "auto",
        padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
      }}>
        {result ? (
          <div>
            <div style={{ textAlign: "center", marginBottom: 20 }}>
              <Mail size={40} style={{ color: "var(--color-text-muted)", marginBottom: 12 }} />
              <h2 style={{ margin: 0 }}>Invite Sent!</h2>
              <p style={{ color: "var(--color-text-muted)", fontSize: 14, marginTop: 6 }}>
                Share the setup link with the staff member.
              </p>
            </div>
            <div style={{
              background: "var(--color-bg)", borderRadius: 10, padding: 20,
              fontSize: 13, lineHeight: "1.8", border: "1px solid var(--color-border)",
            }}>
              <div><strong>Name:</strong> {result.first_name} {result.last_name}</div>
              <div><strong>Mobile:</strong> {result.phone}</div>
              {result.employee_id && <div><strong>Employee ID:</strong> {result.employee_id}</div>}
              <div><strong>Role:</strong> {ROLE_LABELS[result.role]?.label || result.role}</div>
              <div style={{ marginTop: 10, borderTop: "1px solid var(--color-border)", paddingTop: 10 }}>
                <strong>Temporary Password:</strong>
                <div style={{
                  marginTop: 6, padding: "8px 12px",
                  background: "var(--color-surface)", border: "1.5px solid var(--color-border)",
                  borderRadius: 8, fontFamily: "monospace", fontSize: 15,
                  letterSpacing: 1, userSelect: "all",
                }}>
                  {result.temp_password}
                </div>
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: "var(--color-text-muted)" }}>
                {result.note}
              </div>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button onClick={() => {
                navigator.clipboard.writeText(result.temp_password);
                toastSuccess("Password copied!");
              }}
                style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-primary)", background: "none", color: "var(--color-primary)", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
                Copy Password
              </button>
              <button className="btn-primary" onClick={onClose} style={{ flex: 1 }}>Done</button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
              <h2 style={{ margin: 0, fontSize: 18 }}>Invite Staff Member</h2>
              <button type="button" onClick={onClose}
                style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "var(--color-text-muted)" }}>✕</button>
            </div>

            <div style={{ display: "grid", gap: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <label style={labelStyle}>First Name *</label>
                  <input style={inputStyle} value={form.first_name} onChange={set("first_name")} placeholder="Priya" required />
                </div>
                <div>
                  <label style={labelStyle}>Last Name</label>
                  <input style={inputStyle} value={form.last_name} onChange={set("last_name")} placeholder="Sharma" />
                </div>
              </div>

              <div>
                <label style={labelStyle}>Mobile Number *</label>
                <input style={inputStyle} type="tel" value={form.phone}
                  onChange={e => setForm(f => ({ ...f, phone: sanitizeMobileInput(e.target.value) }))}
                  placeholder="98xxxxxxxx" maxLength={10} inputMode="numeric" required />
              </div>

              <div>
                <label style={labelStyle}>Email (optional)</label>
                <input style={inputStyle} type="email" value={form.email} onChange={set("email")} placeholder="priya@hospital.com" />
              </div>

              <div>
                <label style={labelStyle}>Role *</label>
                <select style={inputStyle} value={form.role} onChange={set("role")} required>
                  {ROLES.map(r => {
                    const capped = r === "doctor" ? doctorsCapped : staffCapped;
                    return (
                      <option key={r} value={r} disabled={capped}>
                        {ROLE_LABELS[r].label}{capped ? " — limit reached" : ""}
                      </option>
                    );
                  })}
                </select>
              </div>

              {selectedRoleCapped && (
                <div style={{
                  fontSize: 12.5, color: "var(--color-warning)", background: "var(--color-warning-light)",
                  padding: "8px 12px", borderRadius: 8,
                }}>
                  {form.role === "doctor"
                    ? `Doctor limit reached (${permissions?.max_doctors} on your current plan).`
                    : `Staff limit reached (${permissions?.max_staff} on your current plan).`} Upgrade your plan to add more, or choose a different role.
                </div>
              )}

              <div>
                <label style={labelStyle}>{form.role === "doctor" ? "Primary Branch" : "Branch"}</label>
                <select style={inputStyle} value={form.branch_id} onChange={set("branch_id")}>
                  <option value="">— No branch assigned —</option>
                  {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </div>

              {form.role === "doctor" && branches.length > 1 && (
                <div>
                  <label style={labelStyle}>Also works at (optional)</label>
                  <div style={{
                    display: "flex", flexDirection: "column", gap: 6,
                    border: "1.5px solid var(--color-border)", borderRadius: 8, padding: "10px 12px",
                    maxHeight: 140, overflowY: "auto",
                  }}>
                    {branches.filter(b => String(b.id) !== String(form.branch_id)).map(b => (
                      <label key={b.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                        <input type="checkbox" checked={extraBranchIds.includes(b.id)}
                          onChange={() => toggleExtraBranch(b.id)} />
                        {b.name}
                      </label>
                    ))}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                    For a doctor who consults at more than one branch. The primary branch above is used by default; they can switch branches from their own dashboard.
                  </div>
                </div>
              )}

              {departments.length > 0 && (
                <div>
                  <label style={labelStyle}>Department</label>
                  <select style={inputStyle} value={form.department_id} onChange={set("department_id")}>
                    <option value="">— No department —</option>
                    {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                </div>
              )}

              {form.role === "doctor" && (
                <div style={{
                  borderTop: "1px solid var(--color-border)", paddingTop: 14, marginTop: 2,
                  display: "grid", gap: 14,
                }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4 }}>
                    Doctor basics — shown to patients right away
                  </div>
                  <div><label style={labelStyle}>Specialisation</label>
                    <input style={inputStyle} value={form.specialisation} onChange={set("specialisation")} placeholder="e.g. Cardiology, General Physician, Gynaecology" />
                  </div>
                  <div><label style={labelStyle}>Qualification</label>
                    <input style={inputStyle} value={form.qualification} onChange={set("qualification")} placeholder="MBBS, MD (Cardiology)" />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <div><label style={labelStyle}>MCI/NMC Registration No.</label>
                      <input style={inputStyle} value={form.registration_no} onChange={set("registration_no")} placeholder="MH-12345" />
                    </div>
                    <div><label style={labelStyle}>Experience (years)</label>
                      <input style={inputStyle} type="number" min="0" value={form.experience_years} onChange={set("experience_years")} placeholder="10" />
                    </div>
                  </div>
                  {/* Consultation fee toggle */}
                  <div style={{
                    borderRadius: 10, border: "1px solid var(--color-border)",
                    overflow: "hidden",
                  }}>
                    {/* Toggle row */}
                    <div style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: "11px 14px",
                      background: adminSetsFee ? "var(--color-primary-light)" : "var(--color-bg)",
                    }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text)" }}>
                          Consultation Fee
                        </div>
                        <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 1 }}>
                          {adminSetsFee ? "Set by hospital admin" : "Doctor configures after first login"}
                        </div>
                      </div>
                      {/* Toggle switch */}
                      <button
                        type="button"
                        onClick={() => { setAdminSetsFee(v => !v); setForm(f => ({ ...f, consultation_fee: "" })); }}
                        style={{
                          width: 44, height: 24, borderRadius: 12, border: "none", flexShrink: 0,
                          background: adminSetsFee ? "var(--color-primary)" : "var(--color-border)",
                          cursor: "pointer", position: "relative", transition: "background 0.2s",
                        }}
                      >
                        <span style={{
                          position: "absolute", top: 3,
                          left: adminSetsFee ? 23 : 3,
                          width: 18, height: 18, borderRadius: "50%",
                          background: "#fff", boxShadow: "0 1px 4px rgba(0,0,0,0.2)",
                          transition: "left 0.2s",
                        }} />
                      </button>
                    </div>
                    {/* Fee input — only when admin sets it */}
                    {adminSetsFee && (
                      <div style={{ padding: "12px 14px", borderTop: "1px solid var(--color-border)", background: "var(--color-surface)" }}>
                        <label style={{ ...labelStyle, marginBottom: 4 }}>Amount (₹)</label>
                        <input
                          style={inputStyle} type="number" min="0" step="0.01"
                          value={form.consultation_fee}
                          onChange={set("consultation_fee")}
                          placeholder="e.g. 500"
                          autoFocus
                        />
                      </div>
                    )}
                  </div>

                  {/* Working hours */}
                  <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: 14, marginTop: 2 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 12 }}>
                      Working Hours
                    </div>

                    {/* Slot duration */}
                    <div style={{ marginBottom: 14 }}>
                      <label style={labelStyle}>Appointment Slot Duration</label>
                      <select
                        style={inputStyle}
                        value={slotDuration}
                        onChange={e => setSlotDuration(parseInt(e.target.value))}
                      >
                        {[10, 15, 20, 30, 45, 60].map(m => (
                          <option key={m} value={m}>{m} minutes</option>
                        ))}
                      </select>
                    </div>

                    {/* Per-day rows */}
                    <div style={{ display: "grid", gap: 8 }}>
                      {schedule.map((day, i) => (
                        <div key={i} style={{
                          display: "grid",
                          gridTemplateColumns: "110px 36px 1fr auto auto",
                          alignItems: "center", gap: 10,
                          padding: "8px 12px", borderRadius: 10,
                          background: day.is_available ? "var(--color-primary-light)" : "var(--color-bg)",
                          border: `1px solid ${day.is_available ? "var(--color-border)" : "var(--color-border)"}`,
                          opacity: day.is_available ? 1 : 0.55,
                        }}>
                          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)" }}>
                            {DAYS[i]}
                          </span>
                          {/* Toggle available */}
                          <button
                            type="button"
                            onClick={() => setSchedule(s => s.map((d, j) => j === i ? { ...d, is_available: !d.is_available } : d))}
                            style={{
                              width: 32, height: 18, borderRadius: 9, border: "none",
                              background: day.is_available ? "var(--color-primary)" : "var(--color-border)",
                              cursor: "pointer", position: "relative", flexShrink: 0,
                            }}
                          >
                            <span style={{
                              position: "absolute", top: 2,
                              left: day.is_available ? 16 : 2,
                              width: 14, height: 14, borderRadius: "50%",
                              background: "#fff", transition: "left 0.15s",
                            }} />
                          </button>
                          <input
                            type="time" disabled={!day.is_available}
                            value={day.start_time}
                            onChange={e => setSchedule(s => s.map((d, j) => j === i ? { ...d, start_time: e.target.value } : d))}
                            style={{ ...inputStyle, padding: "5px 8px", fontSize: 13, opacity: day.is_available ? 1 : 0.4 }}
                          />
                          <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>to</span>
                          <input
                            type="time" disabled={!day.is_available}
                            value={day.end_time}
                            onChange={e => setSchedule(s => s.map((d, j) => j === i ? { ...d, end_time: e.target.value } : d))}
                            style={{ ...inputStyle, padding: "5px 8px", fontSize: 13, opacity: day.is_available ? 1 : 0.4 }}
                          />
                        </div>
                      ))}
                    </div>
                  </div>

                  <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                    Bio, photo, and e-signature are filled in by the doctor after their first login.
                  </div>
                </div>
              )}

              {form.role !== "doctor" && ROLE_BASICS[form.role] && (
                <div style={{
                  borderTop: "1px solid var(--color-border)", paddingTop: 14, marginTop: 2,
                  display: "grid", gap: 14,
                }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4 }}>
                    Professional basics
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <div><label style={labelStyle}>Qualification</label>
                      <input style={inputStyle} value={form.qualification} onChange={set("qualification")} placeholder="e.g. BSc Nursing" />
                    </div>
                    <div><label style={labelStyle}>Experience (years)</label>
                      <input style={inputStyle} type="number" min="0" value={form.experience_years} onChange={set("experience_years")} placeholder="5" />
                    </div>
                  </div>

                  {ROLE_BASICS[form.role].license && (
                    <>
                      <div><label style={labelStyle}>{ROLE_BASICS[form.role].licenseLabel}</label>
                        <input style={inputStyle} value={form.registration_no} onChange={set("registration_no")} placeholder="e.g. KSNC-45678" />
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                        <div><label style={labelStyle}>Issuing Council / Body</label>
                          <input style={inputStyle} value={form.council_name} onChange={set("council_name")} placeholder="e.g. Karnataka State Nursing Council" />
                        </div>
                        <div><label style={labelStyle}>Registration Expiry</label>
                          <input style={inputStyle} type="date" value={form.registration_expiry} onChange={set("registration_expiry")} />
                        </div>
                      </div>
                    </>
                  )}

                  <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                    Gender, bio, languages, and photo are filled in by {ROLE_LABELS[form.role]?.label.toLowerCase() || "the staff member"} themselves after their first login.
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button type="button" onClick={onClose}
                style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
                Cancel
              </button>
              <button type="submit" disabled={saving || selectedRoleCapped} className="btn-primary" style={{ flex: 2 }}>
                {saving ? "Inviting…" : "Send Invite"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function DoctorProfileModal({ staff, onClose, onSaved }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [form, setForm] = useState({
    registration_no: "", specialisation: "", qualification: "",
    gender: "", experience_years: "", consultation_fee: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get(`${API_ENDPOINTS.ORG.STAFF_MEMBER(staff.id)}doctor-profile/`)
      .then(r => { if (r.data?.data) setForm(r.data.data); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [api, staff.id]);

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    const payload = { ...form, experience_years: form.experience_years ? parseInt(form.experience_years) : null };
    try {
      await api.patch(`${API_ENDPOINTS.ORG.STAFF_MEMBER(staff.id)}doctor-profile/`, payload)
        .catch(() => api.post(`${API_ENDPOINTS.ORG.STAFF_MEMBER(staff.id)}doctor-profile/`, payload));
      toastSuccess("Doctor profile saved.");
      onSaved();
      onClose();
    } catch (err) { toastApiError(err, "Failed to save profile."); }
    finally { setSaving(false); }
  }

  const inputStyle = { width: "100%", boxSizing: "border-box", border: "1.5px solid var(--color-border)", borderRadius: 8, padding: "9px 12px", fontSize: 14, background: "var(--color-surface)", color: "var(--color-text)", outline: "none" };
  const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 500, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Doctor Profile — {staff.first_name} {staff.last_name}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        {loading ? <div style={{ textAlign: "center", padding: 40 }}>Loading…</div> : (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gap: 14 }}>
              <div><label style={labelStyle}>MCI/NMC Registration No.</label><input style={inputStyle} value={form.registration_no} onChange={set("registration_no")} placeholder="MH-12345" /></div>
              <div><label style={labelStyle}>Specialisation</label><input style={inputStyle} value={form.specialisation} onChange={set("specialisation")} placeholder="Cardiology" /></div>
              <div><label style={labelStyle}>Qualification</label><input style={inputStyle} value={form.qualification} onChange={set("qualification")} placeholder="MBBS, MD (Cardiology)" /></div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div><label style={labelStyle}>Gender</label>
                  <select style={inputStyle} value={form.gender} onChange={set("gender")}>
                    <option value="">—</option>
                    <option value="M">Male</option>
                    <option value="F">Female</option>
                    <option value="O">Other</option>
                  </select>
                </div>
                <div><label style={labelStyle}>Experience (years)</label><input style={inputStyle} type="number" min="0" value={form.experience_years} onChange={set("experience_years")} placeholder="10" /></div>
              </div>
              <div><label style={labelStyle}>Consultation Fee (₹)</label><input style={inputStyle} type="number" step="0.01" value={form.consultation_fee} onChange={set("consultation_fee")} placeholder="500.00" /></div>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button type="button" onClick={onClose} style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>Cancel</button>
              <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2 }}>{saving ? "Saving…" : "Save Profile"}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function StaffProfileModal({ staff, onClose, onSaved }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const basics = ROLE_BASICS[staff.role] || { license: false };
  const [form, setForm] = useState({
    registration_no: "", council_name: "", registration_expiry: "",
    qualification: "", experience_years: "",
    gender: "", bio: "", languages: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get(`${API_ENDPOINTS.ORG.STAFF_MEMBER(staff.id)}profile/`)
      .then(r => { if (r.data?.data) setForm(f => ({ ...f, ...r.data.data })); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [api, staff.id]);

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    const payload = {
      ...form,
      experience_years: form.experience_years ? parseInt(form.experience_years) : null,
      registration_expiry: form.registration_expiry || null,
    };
    try {
      await api.patch(`${API_ENDPOINTS.ORG.STAFF_MEMBER(staff.id)}profile/`, payload)
        .catch(() => api.post(`${API_ENDPOINTS.ORG.STAFF_MEMBER(staff.id)}profile/`, payload));
      toastSuccess("Profile saved.");
      onSaved();
      onClose();
    } catch (err) { toastApiError(err, "Failed to save profile."); }
    finally { setSaving(false); }
  }

  const inputStyle = { width: "100%", boxSizing: "border-box", border: "1.5px solid var(--color-border)", borderRadius: 8, padding: "9px 12px", fontSize: 14, background: "var(--color-surface)", color: "var(--color-text)", outline: "none" };
  const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 500, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>
            Profile — {staff.first_name} {staff.last_name}
            <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 400, color: "var(--color-text-muted)" }}>
              ({ROLE_LABELS[staff.role]?.label || staff.role})
            </span>
          </h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        {loading ? <div style={{ textAlign: "center", padding: 40 }}>Loading…</div> : (
          <form onSubmit={handleSubmit}>
            <div style={{ display: "grid", gap: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div><label style={labelStyle}>Qualification</label><input style={inputStyle} value={form.qualification} onChange={set("qualification")} placeholder="e.g. BSc Nursing" /></div>
                <div><label style={labelStyle}>Experience (years)</label><input style={inputStyle} type="number" min="0" value={form.experience_years} onChange={set("experience_years")} placeholder="5" /></div>
              </div>

              {basics.license && (
                <>
                  <div><label style={labelStyle}>{basics.licenseLabel}</label>
                    <input style={inputStyle} value={form.registration_no} onChange={set("registration_no")} placeholder="e.g. KSNC-45678" />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <div><label style={labelStyle}>Issuing Council / Body</label>
                      <input style={inputStyle} value={form.council_name} onChange={set("council_name")} placeholder="e.g. Karnataka State Nursing Council" />
                    </div>
                    <div><label style={labelStyle}>Registration Expiry</label>
                      <input style={inputStyle} type="date" value={form.registration_expiry || ""} onChange={set("registration_expiry")} />
                    </div>
                  </div>
                </>
              )}

              <div><label style={labelStyle}>Gender</label>
                <select style={inputStyle} value={form.gender} onChange={set("gender")}>
                  <option value="">—</option>
                  <option value="M">Male</option>
                  <option value="F">Female</option>
                  <option value="O">Other</option>
                </select>
              </div>
              <div><label style={labelStyle}>Languages Spoken</label>
                <input style={inputStyle} value={form.languages} onChange={set("languages")} placeholder="English, Hindi, Kannada" />
              </div>
              <div><label style={labelStyle}>Short Bio</label>
                <textarea style={{ ...inputStyle, minHeight: 70, resize: "vertical" }} value={form.bio} onChange={set("bio")} placeholder="A line or two about them." />
              </div>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                Gender, languages, and bio can also be filled in by {staff.first_name || "the staff member"} themselves via My Profile.
              </div>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button type="button" onClick={onClose} style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>Cancel</button>
              <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2 }}>{saving ? "Saving…" : "Save Profile"}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function EditStaffModal({ staff, branches, onClose, onSaved }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();
  const [form, setForm] = useState({
    first_name:  staff.first_name  || "",
    last_name:   staff.last_name   || "",
    phone:       staff.phone       || "",
    date_of_birth: staff.date_of_birth || "",
    branch_id:   staff.branch_id   || staff.branch?.id || "",
  });
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const isDoctor = staff.role === "doctor";
  const [extraBranchIds, setExtraBranchIds] = useState([]);
  function toggleExtraBranch(id) {
    setExtraBranchIds(ids => ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]);
  }
  // Seed from staff.branches (already returned on the list/serializer) if
  // present, else fall back to fetching — covers callers that pass a lean
  // staff object.
  useEffect(() => {
    if (!isDoctor) return;
    if (Array.isArray(staff.branches)) {
      setExtraBranchIds(staff.branches.filter(b => !b.is_primary).map(b => b.id));
      return;
    }
    api.get(API_ENDPOINTS.ORG.STAFF_BRANCHES(staff.id))
      .then(r => setExtraBranchIds((r.data?.data || []).filter(b => !b.is_primary).map(b => b.id)))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDoctor, staff.id]);

  const inputStyle = {
    width: "100%", boxSizing: "border-box",
    border: "1.5px solid var(--color-border)", borderRadius: 8,
    padding: "9px 12px", fontSize: 14,
    background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
  };
  const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

  async function handleSubmit(e) {
    e.preventDefault();
    if (form.phone && !isValidMobile(form.phone)) {
      toastApiError(null, "Enter a valid 10-digit mobile number.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        branch_id: form.branch_id ? parseInt(form.branch_id) : null,
        date_of_birth: form.date_of_birth || null,
      };
      await api.patch(API_ENDPOINTS.ORG.STAFF_MEMBER(staff.id), payload);
      // Doctor's full branch set — primary is whatever's selected in the
      // dropdown above, extras are the checked boxes. A separate call since
      // it's a separate resource (StaffBranchMapping), not a plain field.
      if (isDoctor) {
        const branchIds = [
          ...(payload.branch_id ? [payload.branch_id] : []),
          ...extraBranchIds.filter(id => id !== payload.branch_id),
        ];
        await api.put(API_ENDPOINTS.ORG.STAFF_BRANCHES(staff.id), {
          branch_ids: branchIds,
          primary_branch_id: payload.branch_id || null,
        });
      }
      toastSuccess("Staff updated.");
      onSaved();
      onClose();
    } catch (err) { toastApiError(err, "Failed to update."); }
    finally { setSaving(false); }
  }

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
    }}>
      <div style={{
        background: "var(--color-surface)", borderRadius: 16,
        width: "100%", maxWidth: 480,
        padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>
            Edit — {staff.first_name} {staff.last_name}
            <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 400, color: "var(--color-text-muted)" }}>
              ({ROLE_LABELS[staff.role]?.label || staff.role})
            </span>
          </h2>
          <button type="button" onClick={onClose}
            style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: "var(--color-text-muted)" }}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div>
                <label style={labelStyle}>First Name *</label>
                <input style={inputStyle} value={form.first_name} onChange={set("first_name")} required />
              </div>
              <div>
                <label style={labelStyle}>Last Name</label>
                <input style={inputStyle} value={form.last_name} onChange={set("last_name")} />
              </div>
            </div>
            <div>
              <label style={labelStyle}>Phone</label>
              <input style={inputStyle} value={form.phone}
                onChange={e => setForm(f => ({ ...f, phone: sanitizeMobileInput(e.target.value) }))}
                placeholder="98xxxxxxxx" maxLength={10} inputMode="numeric" />
            </div>
            {staff.employee_id && (
              <div>
                <label style={labelStyle}>Employee ID</label>
                <div style={{ ...inputStyle, background: "var(--color-bg)", color: "var(--color-text-muted)" }}>
                  {staff.employee_id}
                </div>
              </div>
            )}
            <div>
              <label style={labelStyle}>Date of Birth</label>
              <input type="date" style={inputStyle} value={form.date_of_birth} onChange={set("date_of_birth")} />
            </div>
            <div>
              <label style={labelStyle}>{isDoctor ? "Primary Branch" : "Branch"}</label>
              <select style={inputStyle} value={form.branch_id} onChange={set("branch_id")}>
                <option value="">— No branch assigned —</option>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>

            {isDoctor && branches.length > 1 && (
              <div>
                <label style={labelStyle}>Also works at (optional)</label>
                <div style={{
                  display: "flex", flexDirection: "column", gap: 6,
                  border: "1.5px solid var(--color-border)", borderRadius: 8, padding: "10px 12px",
                  maxHeight: 140, overflowY: "auto",
                }}>
                  {branches.filter(b => String(b.id) !== String(form.branch_id)).map(b => (
                    <label key={b.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                      <input type="checkbox" checked={extraBranchIds.includes(b.id)}
                        onChange={() => toggleExtraBranch(b.id)} />
                      {b.name}
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
            <button type="button" onClick={onClose}
              style={{ flex: 1, padding: "9px 0", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 14, fontWeight: 600 }}>
              Cancel
            </button>
            <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2 }}>
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function StaffPage() {
  const api = apiClient;
  const { user } = useAuth();
  const { toastSuccess, toastApiError } = useToast();
  const { permissions, atCapacity, refresh: refreshPermissions } = usePermissions();
  const [staff,    setStaff]    = useState([]);
  const [branches, setBranches] = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [modal,    setModal]    = useState(null);
  const [doctorModal, setDoctorModal] = useState(null);
  const [profileModal, setProfileModal] = useState(null);
  const [editModal,   setEditModal]   = useState(null);
  const [roleFilter, setRoleFilter]   = useState("all");
  const [search,     setSearch]       = useState("");
  const [page,       setPage]         = useState(1);
  const [pagination, setPagination]   = useState(null);

  const fetchData = useCallback(async (targetPage = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(targetPage), page_size: "20" });
      if (roleFilter !== "all") params.set("role", roleFilter);
      if (search) params.set("search", search);
      const [staffRes, branchRes] = await Promise.all([
        api.get(`${API_ENDPOINTS.ORG.STAFF}?${params.toString()}`),
        api.get(API_ENDPOINTS.ORG.BRANCHES),
      ]);
      setStaff(staffRes.data?.data?.results || []);
      setPagination(staffRes.data?.data?.pagination || null);
      setBranches(branchRes.data?.data || []);
    } catch { setStaff([]); setPagination(null); }
    finally { setLoading(false); }
  }, [api, roleFilter, search]);

  // Reset to page 1 whenever filters change (debounced for the free-text search).
  useEffect(() => {
    const t = setTimeout(() => { setPage(1); fetchData(1); }, 300);
    return () => clearTimeout(t);
  }, [search, roleFilter, fetchData]);

  useEffect(() => {
    if (page !== 1) fetchData(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const refetchCurrentPage = useCallback(() => fetchData(page), [fetchData, page]);

  async function deactivate(s) {
    if (!confirm(`Deactivate ${s.first_name} ${s.last_name}?`)) return;
    try {
      await api.delete(API_ENDPOINTS.ORG.STAFF_MEMBER(s.id));
      toastSuccess("Staff deactivated.");
      refetchCurrentPage(); refreshPermissions();
    } catch (err) { toastApiError(err, "Failed."); }
  }

  async function resendInvite(s) {
    try {
      const { data: res } = await api.post(`${API_ENDPOINTS.ORG.STAFF_MEMBER(s.id)}resend-invite/`);
      const tempPassword = res.data?.temp_password || "";
      navigator.clipboard.writeText(tempPassword);
      toastSuccess("New temp password copied to clipboard.");
    } catch (err) { toastApiError(err, "Failed."); }
  }

  // Filtering and pagination now happen server-side (see fetchData above),
  // so the fetched page is rendered as-is.
  const filtered = staff;

  const doctorsCapped = atCapacity("doctors");
  const staffCapped = atCapacity("staff");
  const allRolesCapped = doctorsCapped && staffCapped;

  return (
    <AppShell>
      <PageShell title="Staff">
        {(permissions?.max_doctors > 0 || permissions?.max_staff > 0) && (
          <div style={{ display: "flex", gap: 16, marginBottom: 14, fontSize: 13, color: "var(--color-text-muted)", flexWrap: "wrap" }}>
            {permissions?.max_doctors > 0 && (
              <span>
                {permissions.usage?.doctors ?? "—"} of {permissions.max_doctors} doctors used
                {doctorsCapped && <span style={{ color: "var(--color-error)", fontWeight: 600 }}> — limit reached</span>}
              </span>
            )}
            {permissions?.max_staff > 0 && (
              <span>
                {permissions.usage?.staff ?? "—"} of {permissions.max_staff} other staff used
                {staffCapped && <span style={{ color: "var(--color-error)", fontWeight: 600 }}> — limit reached</span>}
              </span>
            )}
          </div>
        )}

        {/* Filters + actions */}
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search by name or mobile…"
            style={{ flex: 1, minWidth: 200, padding: "9px 14px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", fontSize: 14, outline: "none" }} />
          <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)}
            style={{ padding: "9px 12px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "var(--color-surface)", fontSize: 14, outline: "none" }}>
            <option value="all">All roles</option>
            {Object.entries(ROLE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
          <button className="btn-primary" onClick={() => setModal("invite")} disabled={allRolesCapped}
            title={allRolesCapped ? "Every role is at your plan's limit. Upgrade to invite more staff." : undefined}
            style={allRolesCapped ? { opacity: 0.5, cursor: "not-allowed" } : undefined}>
            + Invite Staff
          </button>
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="card" style={{ textAlign: "center", padding: 60 }}>
            <Users size={40} style={{ color: "var(--color-text-muted)", marginBottom: 12 }} />
            <div style={{ fontWeight: 600, marginBottom: 8 }}>
              {(!search && roleFilter === "all") ? "No staff yet" : "No results"}
            </div>
            <div style={{ color: "var(--color-text-muted)", marginBottom: 20 }}>
              {(!search && roleFilter === "all") ? "Invite your first staff member to get started." : "Try a different filter."}
            </div>
            {(!search && roleFilter === "all") && (
              <button className="btn-primary" onClick={() => setModal("invite")} disabled={allRolesCapped}
                style={allRolesCapped ? { opacity: 0.5, cursor: "not-allowed" } : undefined}>
                Invite First Staff Member
              </button>
            )}
          </div>
        ) : (
          <>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {filtered.map(s => (
              <div key={s.id} className="card" style={{ padding: "14px 20px", display: "flex", alignItems: "center", gap: 14 }}>
                {/* Avatar */}
                <div style={{
                  width: 44, height: 44, borderRadius: "50%", flexShrink: 0,
                  background: ROLE_LABELS[s.role]?.color + "22",
                  color: ROLE_LABELS[s.role]?.color,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontWeight: 700, fontSize: 16,
                }}>
                  {(s.first_name?.[0] || s.phone?.[0] || "?").toUpperCase()}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 700 }}>{s.first_name} {s.last_name}</span>
                    <RoleBadge role={s.role} />
                    {s.must_change_password && (
                      <span style={{ padding: "2px 8px", borderRadius: 20, fontSize: 11, background: "#F9F0DC", color: "#92400e", fontWeight: 600 }}>
                        Temp Password
                      </span>
                    )}
                    {!s.is_active && (
                      <span style={{ padding: "2px 8px", borderRadius: 20, fontSize: 11, background: "#fee2e2", color: "#991b1b", fontWeight: 600 }}>
                        Inactive
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 3 }}>
                    {s.phone}
                    {Array.isArray(s.branches) && s.branches.length > 1
                      ? ` · ${s.branches.map(b => b.name).join(", ")}`
                      : (s.branch_name && ` · ${s.branch_name}`)}
                    {s.department_name && ` / ${s.department_name}`}
                    {calcAge(s.date_of_birth) != null && ` · ${calcAge(s.date_of_birth)}y`}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                  <button onClick={() => setEditModal(s)}
                    style={{ padding: "6px 12px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
                    Edit
                  </button>
                  <button onClick={() => s.role === "doctor" ? setDoctorModal(s) : setProfileModal(s)}
                    style={{ padding: "6px 12px", borderRadius: 8, border: "1.5px solid var(--color-primary)", background: "none", color: "var(--color-primary)", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
                    Profile
                  </button>
                  {s.password === "!" && (
                    <button onClick={() => resendInvite(s)}
                      style={{ padding: "6px 12px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
                      Resend
                    </button>
                  )}
                  {s.is_active && s.id !== user?.user_id && (
                    <button onClick={() => deactivate(s)}
                      style={{ padding: "6px 12px", borderRadius: 8, border: "1.5px solid var(--color-error)", background: "none", color: "var(--color-error)", cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
                      Remove
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {pagination && pagination.total_pages > 1 && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 24 }}>
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={!pagination.has_previous}
                style={{
                  padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                  border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
                  color: "var(--color-text)", cursor: pagination.has_previous ? "pointer" : "not-allowed",
                  opacity: pagination.has_previous ? 1 : 0.5,
                }}>
                ← Previous
              </button>
              <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Page {pagination.page} of {pagination.total_pages} · {pagination.total_count} staff
              </span>
              <button
                onClick={() => setPage(p => Math.min(pagination.total_pages, p + 1))}
                disabled={!pagination.has_next}
                style={{
                  padding: "7px 16px", borderRadius: 8, fontSize: 13, fontWeight: 600,
                  border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
                  color: "var(--color-text)", cursor: pagination.has_next ? "pointer" : "not-allowed",
                  opacity: pagination.has_next ? 1 : 0.5,
                }}>
                Next →
              </button>
            </div>
          )}
          </>
        )}

        {modal === "invite" && (
          <InviteModal
            branches={branches}
            onClose={() => setModal(null)}
            onInvited={() => { refetchCurrentPage(); refreshPermissions(); }}
            atCapacity={atCapacity}
            permissions={permissions}
          />
        )}

        {doctorModal && (
          <DoctorProfileModal
            staff={doctorModal}
            onClose={() => setDoctorModal(null)}
            onSaved={refetchCurrentPage}
          />
        )}

        {profileModal && (
          <StaffProfileModal
            staff={profileModal}
            onClose={() => setProfileModal(null)}
            onSaved={refetchCurrentPage}
          />
        )}

        {editModal && (
          <EditStaffModal
            staff={editModal}
            branches={branches}
            onClose={() => setEditModal(null)}
            onSaved={refetchCurrentPage}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
