/**
 * pages/patient/MyProfilePage.jsx
 * ---------------------------------
 * Patient portal's own account page. Cards: identity (AWPID/email,
 * read-only — these are the keys the cross-hospital HIE matching relies
 * on), editable basics, health summary, emergency contact, family members,
 * linked hospitals, and change-password.
 *
 * Everything shown is real data already tracked elsewhere in the system —
 * blood group comes from PatientIdentity, allergies/diagnoses from the same
 * shared HIE tables doctors see, linked hospitals from actual booking
 * history. Nothing here is fabricated (no invented "primary doctor",
 * "chronic conditions" classifier, login-device list, or notification
 * toggles — none of that is tracked anywhere in the backend yet).
 *
 * Styled with the same premium hero-card / icon-chip language used on
 * DashboardPage and DoctorProfilePage, rather than flat white cards with
 * plain label/value stacks — this is the patient's identity page, it
 * should read as such.
 */
import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  ShieldCheck, CalendarPlus, Building2, Droplet, CalendarClock, AlertTriangle,
  Smartphone, User, Cake, Fingerprint, Mail, Phone, HeartPulse, Stethoscope,
} from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import ProfilePhotoUpload from "../../components/common/ProfilePhotoUpload";
import { useToast }  from "../../hooks/useToast";
import { usePatientContext } from "../../context/PatientContext";
import { useAuth }   from "../../hooks/useAuth";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";
import { calcAge }   from "../../utils/age";

const inputStyle = {
  width: "100%", boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "9px 12px", fontSize: 14,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };
const readOnlyStyle = {
  ...inputStyle,
  background: "var(--color-surface-secondary, #f6f4ee)",
  color: "var(--color-text-muted)",
};
const cardStyle = { padding: 0, marginTop: 16, overflow: "hidden" };

const EMPTY_PW = { current_password: "", new_password: "", confirm_password: "" };
const EMPTY_MEMBER = { full_name: "", date_of_birth: "", gender: "", relationship: "child" };
const REL_LABELS = { child: "Child", parent: "Parent", spouse: "Spouse", sibling: "Sibling", ward: "Ward", other: "Other" };
const REL_ICONS  = { child: "🧒", parent: "🧑", spouse: "💍", sibling: "🧑‍🤝‍🧑", ward: "🧑‍🦱", other: "👤" };

// Plain, light section header — small text label + thin bottom border.
// Kept deliberately quiet (no color banner) so a page full of cards reads
// as calm data, not a stack of billboards.
function SectionHeader({ title, action }) {
  return (
    <div style={{
      padding: "14px 20px",
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
      borderBottom: "1px solid var(--color-border)",
    }}>
      <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 14, color: "var(--color-text)" }}>
        {title}
      </div>
      {action}
    </div>
  );
}

// Field row with a colored icon chip — replaces bare label/value stacks so
// a glance at the card reads as data, not empty space.
function InfoField({ icon: Icon, chip = "green", label, value, empty = "Not set" }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
      <div className={`icon-chip icon-chip--${chip}`} style={{ width: 30, height: 30, flexShrink: 0 }}>
        <Icon size={14} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="stat-label">{label}</div>
        <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2, color: value ? "var(--color-text)" : "var(--color-text-muted)" }}>
          {value || empty}
        </div>
      </div>
    </div>
  );
}

// Compact stat tile for the Health Summary strip.
function StatTile({ icon: Icon, chip, label, value, sub, valueColor }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10, padding: "12px 14px", borderRadius: 12,
      background: "var(--color-surface-secondary, #f6f4ee)", flex: 1, minWidth: 150,
    }}>
      <div className={`icon-chip icon-chip--${chip}`} style={{ width: 32, height: 32, flexShrink: 0 }}>
        <Icon size={15} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="stat-label">{label}</div>
        <div style={{ fontSize: 15, fontWeight: 700, marginTop: 2, color: valueColor || "var(--color-text)", lineHeight: 1.3 }}>
          {value}
        </div>
        {sub && <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 1 }}>{sub}</div>}
      </div>
    </div>
  );
}

export default function MyProfilePage() {
  const { toastSuccess, toastApiError } = useToast();
  const { refreshUser } = useAuth();
  const navigate = useNavigate();
  const { selectPatient } = usePatientContext();

  const [profile, setProfile] = useState(null);
  const [form, setForm] = useState({ full_name: "", mobile: "", gender: "", date_of_birth: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const snapshotRef = useRef(null);

  const [pw, setPw] = useState(EMPTY_PW);
  const [pwSaving, setPwSaving] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);

  const [family, setFamily] = useState(null); // null = loading
  const [familyOpen, setFamilyOpen] = useState(false);
  const [memberForm, setMemberForm] = useState(EMPTY_MEMBER);
  const [memberSaving, setMemberSaving] = useState(false);

  const [emergency, setEmergency] = useState({ emergency_contact_name: "", emergency_contact_phone: "", emergency_contact_relation: "" });
  const [emergencyEditing, setEmergencyEditing] = useState(false);
  const [emergencySaving, setEmergencySaving] = useState(false);
  const emergencySnapshotRef = useRef(null);

  const [health, setHealth] = useState(null); // null = loading

  function loadFamily() {
    apiClient.get(API_ENDPOINTS.PORTAL.FAMILY)
      .then(({ data: res }) => setFamily(res?.data?.results || []))
      .catch(() => setFamily([]));
  }

  function loadHealth() {
    apiClient.get(API_ENDPOINTS.PORTAL.HEALTH_SUMMARY)
      .then(({ data: res }) => setHealth(res?.data || null))
      .catch(() => setHealth(null));
  }

  useEffect(() => {
    apiClient.get(API_ENDPOINTS.PORTAL.PROFILE)
      .then(({ data: res }) => {
        const d = res?.data;
        if (d) {
          setProfile(d);
          setForm({
            full_name: d.full_name || "",
            mobile: d.mobile || "",
            gender: d.gender || "",
            date_of_birth: d.date_of_birth || "",
          });
          setEmergency({
            emergency_contact_name:     d.emergency_contact_name || "",
            emergency_contact_phone:    d.emergency_contact_phone || "",
            emergency_contact_relation: d.emergency_contact_relation || "",
          });
        }
      })
      .catch(err => toastApiError(err, "Could not load your profile."))
      .finally(() => setLoading(false));
    loadFamily();
    loadHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleAddMember(e) {
    e.preventDefault();
    if (!memberForm.full_name.trim() || !memberForm.date_of_birth) {
      toastApiError({ message: "Name and date of birth are required." }, "Name and date of birth are required.");
      return;
    }
    setMemberSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.FAMILY, memberForm);
      toastSuccess("Family member added.");
      setMemberForm(EMPTY_MEMBER);
      setFamilyOpen(false);
      loadFamily();
    } catch (err) {
      toastApiError(err, "Failed to add family member.");
    } finally {
      setMemberSaving(false);
    }
  }

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  function startEditing() {
    snapshotRef.current = form;
    setEditing(true);
  }
  function cancelEditing() {
    if (snapshotRef.current) setForm(snapshotRef.current);
    setEditing(false);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const { data: res } = await apiClient.patch(API_ENDPOINTS.PORTAL.PROFILE, form);
      if (res?.data) {
        setProfile(p => ({ ...p, ...res.data }));
        setForm(f => ({ ...f, ...res.data }));
      }
      setEditing(false);
      toastSuccess("Profile updated.");
    } catch (err) {
      toastApiError(err, "Failed to update profile.");
    } finally {
      setSaving(false);
    }
  }

  function startEmergencyEditing() {
    emergencySnapshotRef.current = emergency;
    setEmergencyEditing(true);
  }
  function cancelEmergencyEditing() {
    if (emergencySnapshotRef.current) setEmergency(emergencySnapshotRef.current);
    setEmergencyEditing(false);
  }
  async function handleEmergencySubmit(e) {
    e.preventDefault();
    setEmergencySaving(true);
    try {
      const { data: res } = await apiClient.patch(API_ENDPOINTS.PORTAL.PROFILE, emergency);
      if (res?.data) {
        setProfile(p => ({ ...p, ...res.data }));
        setEmergency(f => ({ ...f, ...res.data }));
      }
      setEmergencyEditing(false);
      toastSuccess("Emergency contact updated.");
    } catch (err) {
      toastApiError(err, "Failed to update emergency contact.");
    } finally {
      setEmergencySaving(false);
    }
  }

  async function handlePasswordSubmit(e) {
    e.preventDefault();
    if (!pw.new_password || pw.new_password !== pw.confirm_password) {
      toastApiError({ message: "New password and confirmation don't match." }, "Passwords don't match.");
      return;
    }
    setPwSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.CHANGE_PASSWORD, {
        current_password: pw.current_password,
        new_password: pw.new_password,
      });
      toastSuccess("Password changed.");
      setPw(EMPTY_PW);
      setPwOpen(false);
    } catch (err) {
      toastApiError(err, "Failed to change password.");
    } finally {
      setPwSaving(false);
    }
  }

  const name = profile?.full_name || "";
  const initials = name.split(" ").map(p => p.charAt(0)).join("").slice(0, 2).toUpperCase() || "?";

  // Focus styling for edit mode inputs
  const editInputStyle = {
    ...inputStyle,
    borderLeft: "3px solid var(--color-primary)",
  };

  if (loading) {
    return (
      <AppShell>
        <PageShell title="My Profile">
          <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        </PageShell>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageShell title="My Profile">
        <style>{`
          .profile-edit-input:focus {
            border-color: var(--color-primary) !important;
            border-left-width: 3px !important;
            box-shadow: 0 0 0 3px var(--color-primary-light);
            outline: none;
          }
        `}</style>

        {/* Hero header — dark gradient with avatar in gold ring */}
        <div className="hero-card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            {/* Gold ring lives on the avatar circle itself (not a wrapper around
                the whole upload control) — wrapping the avatar+button row in a
                border-radius:50% box clipped/overlapped the "Change photo"
                button against the photo. */}
            <ProfilePhotoUpload
              photo={profile?.photo} initials={initials} size={62} variant="dark"
              avatarBorderColor="rgba(201,162,75,0.7)"
              endpoint={API_ENDPOINTS.PORTAL.PROFILE}
              onUploaded={(newPhoto) => { setProfile(p => ({ ...p, photo: newPhoto })); refreshUser(); }}
            />
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 600, color: "#fff" }}>{name || "—"}</div>
                <span style={{
                  display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 700,
                  padding: "3px 10px", borderRadius: 20, background: "rgba(126, 224, 168, 0.16)", color: "#7EE0A8",
                  border: "1px solid rgba(126, 224, 168, 0.35)",
                }}>
                  <ShieldCheck size={12} /> Verified Patient
                </span>
              </div>
              <div className="stat-label" style={{ color: "var(--color-hero-muted)", marginTop: 5, letterSpacing: "0.08em" }}>
                {profile?.awpid}
              </div>
              {profile?.email && (
                <div style={{ fontSize: 12, color: "var(--color-hero-muted)", marginTop: 2 }}>
                  {profile.email}
                </div>
              )}
            </div>
          </div>
          <button
            className="btn-gold" style={{ display: "flex", alignItems: "center", gap: 6, padding: "10px 20px", whiteSpace: "nowrap" }}
            onClick={() => navigate(ROUTES.PATIENT.HOSPITALS)}
          >
            <CalendarPlus size={15} /> Book Appointment
          </button>
        </div>

        {/* Personal details — editable basics + read-only identity keys in one place */}
        <div className="card" style={{ ...cardStyle, marginTop: 16 }}>
          <SectionHeader
            title="Personal Details"
            action={!editing && (
              <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "4px 12px" }} onClick={startEditing}>
                Edit
              </button>
            )}
          />
          <div style={{ padding: "16px 20px" }}>
            {editing ? (
              <form onSubmit={handleSubmit}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                  <div><label style={labelStyle}>Full Name</label>
                    <input className="profile-edit-input" style={inputStyle} value={form.full_name} onChange={set("full_name")} required />
                  </div>
                  <div><label style={labelStyle}>Mobile</label>
                    <input className="profile-edit-input" style={inputStyle} value={form.mobile} onChange={set("mobile")} placeholder="9876543210" />
                  </div>
                  <div><label style={labelStyle}>Gender</label>
                    <select className="profile-edit-input" style={inputStyle} value={form.gender} onChange={set("gender")}>
                      <option value="">—</option>
                      <option value="M">Male</option>
                      <option value="F">Female</option>
                      <option value="O">Other</option>
                    </select>
                  </div>
                  <div><label style={labelStyle}>Date of Birth</label>
                    <input type="date" className="profile-edit-input" style={inputStyle} value={form.date_of_birth || ""} onChange={set("date_of_birth")} />
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 20, maxWidth: 360 }}>
                  <button type="button" className="btn-outline" style={{ flex: 1, padding: "10px 0" }} onClick={cancelEditing} disabled={saving}>
                    Cancel
                  </button>
                  <button type="submit" className="btn-primary" disabled={saving} style={{ flex: 2, padding: "10px 0", fontSize: 13, fontWeight: 700 }}>
                    {saving ? "Saving…" : "Save Profile"}
                  </button>
                </div>
              </form>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <InfoField icon={Smartphone} chip="green" label="Mobile" value={form.mobile} />
                <InfoField icon={User} chip="green" label="Gender" value={{ M: "Male", F: "Female", O: "Other" }[form.gender]} />
                <InfoField
                  icon={Cake} chip="green" label="Date of Birth"
                  value={form.date_of_birth ? `${form.date_of_birth}${calcAge(form.date_of_birth) != null ? ` · ${calcAge(form.date_of_birth)}y` : ""}` : ""}
                />
              </div>
            )}

            <div style={{ borderTop: "1px solid var(--color-border)", marginTop: 18, paddingTop: 16 }}>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 12 }}>
                Your AWPID and email are your permanent health identity — they can't be changed here; contact support if either needs updating.
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <InfoField icon={Fingerprint} chip="gold" label="AWPID" value={profile?.awpid} />
                <InfoField icon={Mail} chip="blue" label="Email" value={profile?.email} />
              </div>
            </div>
          </div>
        </div>

        {/* Health summary — real data from shared HIE tables + booking history */}
        <div className="card" style={cardStyle}>
          <SectionHeader title="Health Summary" />
          <div style={{ padding: "16px 20px" }}>
            {health === null ? (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Loading…</div>
            ) : (
              <>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 14 }}>
                  <StatTile
                    icon={Droplet} chip="rose" label="Blood Group"
                    value={health.blood_group || "Not recorded"}
                    valueColor={health.blood_group ? "var(--color-error)" : undefined}
                  />
                  <StatTile
                    icon={CalendarClock} chip="blue" label="Last Visit"
                    value={health.last_visit
                      ? new Date(health.last_visit).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })
                      : "No visits yet"}
                    sub={health.last_hospital}
                  />
                  <StatTile
                    icon={AlertTriangle} chip="gold" label="Allergies"
                    value={health.active_allergies?.length > 0 ? health.active_allergies.map(a => a.substance).join(", ") : "None recorded"}
                  />
                </div>
                {health.active_diagnoses?.length > 0 && (
                  <div style={{ marginBottom: 14 }}>
                    <div className="stat-label" style={{ marginBottom: 6 }}>Active diagnoses</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {health.active_diagnoses.map((d, i) => (
                        <span key={i} className="tag-pill" style={{ background: "var(--color-info-light)", color: "var(--color-info)" }}>
                          {d.description}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <button className="btn-outline" style={{ fontSize: 12, padding: "6px 16px" }} onClick={() => navigate(ROUTES.PATIENT.RECORDS)}>
                  View Complete Medical History
                </button>
              </>
            )}
          </div>
        </div>

        {/* Emergency contact */}
        <div className="card" style={cardStyle}>
          <SectionHeader
            title="Emergency Contact"
            action={!emergencyEditing && (
              <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "4px 12px", whiteSpace: "nowrap" }}
                onClick={startEmergencyEditing}>
                {emergency.emergency_contact_name ? "Edit" : "+ Add"}
              </button>
            )}
          />
          <div style={{ padding: "14px 20px" }}>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 12 }}>
              Who hospital staff should reach if you can't be — shown to staff during any visit, at any hospital.
            </div>

            {emergencyEditing ? (
              <form onSubmit={handleEmergencySubmit} style={{ maxWidth: 420 }}>
                <div style={{ display: "grid", gap: 14 }}>
                  <div><label style={labelStyle}>Contact Name</label>
                    <input className="profile-edit-input" style={inputStyle} value={emergency.emergency_contact_name}
                      onChange={e => setEmergency(f => ({ ...f, emergency_contact_name: e.target.value }))} />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                    <div><label style={labelStyle}>Relationship</label>
                      <input className="profile-edit-input" style={inputStyle} value={emergency.emergency_contact_relation} placeholder="e.g. Spouse"
                        onChange={e => setEmergency(f => ({ ...f, emergency_contact_relation: e.target.value }))} />
                    </div>
                    <div><label style={labelStyle}>Phone</label>
                      <input className="profile-edit-input" style={inputStyle} value={emergency.emergency_contact_phone} placeholder="9876543210"
                        onChange={e => setEmergency(f => ({ ...f, emergency_contact_phone: e.target.value }))} />
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                  <button type="button" className="btn-outline" style={{ flex: 1, padding: "9px 0" }} onClick={cancelEmergencyEditing} disabled={emergencySaving}>
                    Cancel
                  </button>
                  <button type="submit" className="btn-primary" disabled={emergencySaving} style={{ flex: 2, padding: "9px 0", fontSize: 13, fontWeight: 700 }}>
                    {emergencySaving ? "Saving…" : "Save"}
                  </button>
                </div>
              </form>
            ) : emergency.emergency_contact_name ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                <StatTile icon={HeartPulse} chip="rose" label="Contact" value={emergency.emergency_contact_name} />
                <StatTile icon={Stethoscope} chip="green" label="Relationship" value={emergency.emergency_contact_relation || "—"} />
                <StatTile icon={Phone} chip="blue" label="Phone" value={emergency.emergency_contact_phone || "—"} />
              </div>
            ) : (
              <div style={{
                fontSize: 13, color: "var(--color-warning)", background: "var(--color-warning-light)",
                padding: "10px 14px", borderRadius: 8, borderLeft: "3px solid var(--color-warning)",
              }}>
                No emergency contact on file yet — add one so staff know who to call if needed.
              </div>
            )}
          </div>
        </div>

        {/* Family members — book for a child or anyone without their own login */}
        <div className="card" style={cardStyle}>
          <SectionHeader
            title="Family Members"
            action={
              <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "4px 12px", whiteSpace: "nowrap" }}
                onClick={() => setFamilyOpen(o => !o)}>
                {familyOpen ? "Cancel" : "+ Add Family Member"}
              </button>
            }
          />
          <div style={{ padding: "14px 20px" }}>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 12 }}>
              Add a child or dependent to book appointments for them — they don't need their own login.
            </div>

            {family === null ? (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Loading…</div>
            ) : family.length > 0 ? (
              <div style={{ display: "grid", gap: 10, marginBottom: familyOpen ? 16 : 0 }}>
                {family.map(m => (
                  <div key={m.awpid} className="card--interactive" style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12,
                    background: "var(--color-surface)", border: "1px solid var(--color-border)",
                    borderRadius: 12, padding: "12px 16px",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <div style={{
                        width: 40, height: 40, borderRadius: "50%", flexShrink: 0, fontSize: 18,
                        background: "var(--color-accent-light)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        {REL_ICONS[m.relationship] || "👤"}
                      </div>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 14 }}>{m.full_name}</div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3, flexWrap: "wrap" }}>
                          <span className="tag-pill">{REL_LABELS[m.relationship] || m.relationship}</span>
                          <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                            {m.date_of_birth ? `DOB ${m.date_of_birth}${calcAge(m.date_of_birth) != null ? ` · ${calcAge(m.date_of_birth)}y` : ""}` : ""}
                          </span>
                        </div>
                        <div style={{ fontSize: 10, color: "var(--color-text-muted)", marginTop: 2, fontFamily: "monospace" }}>
                          {m.awpid}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button className="btn-outline" style={{ fontSize: 11, padding: "6px 14px" }}
                        onClick={() => navigate(ROUTES.PATIENT.HOSPITALS)}>
                        Book Appointment
                      </button>
                      <button className="btn-outline" style={{ fontSize: 11, padding: "6px 14px" }}
                        onClick={() => { selectPatient(m.awpid, m.full_name); navigate(ROUTES.PATIENT.RECORDS); }}>
                        View Records
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            {familyOpen && (
              <form onSubmit={handleAddMember} style={{ maxWidth: 420 }}>
                <div style={{ display: "grid", gap: 14 }}>
                  <div><label style={labelStyle}>Full Name</label>
                    <input className="profile-edit-input" style={inputStyle} value={memberForm.full_name}
                      onChange={e => setMemberForm(f => ({ ...f, full_name: e.target.value }))} required />
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                    <div><label style={labelStyle}>Date of Birth</label>
                      <input type="date" className="profile-edit-input" style={inputStyle} value={memberForm.date_of_birth}
                        onChange={e => setMemberForm(f => ({ ...f, date_of_birth: e.target.value }))} required />
                    </div>
                    <div><label style={labelStyle}>Gender</label>
                      <select className="profile-edit-input" style={inputStyle} value={memberForm.gender}
                        onChange={e => setMemberForm(f => ({ ...f, gender: e.target.value }))}>
                        <option value="">—</option>
                        <option value="M">Male</option>
                        <option value="F">Female</option>
                        <option value="O">Other</option>
                      </select>
                    </div>
                  </div>
                  <div><label style={labelStyle}>Relationship to You</label>
                    <select className="profile-edit-input" style={inputStyle} value={memberForm.relationship}
                      onChange={e => setMemberForm(f => ({ ...f, relationship: e.target.value }))}>
                      {Object.entries(REL_LABELS).map(([v, l]) => <option key={v} value={v}>{REL_ICONS[v]} {l}</option>)}
                    </select>
                  </div>
                </div>
                <button type="submit" className="btn-primary" disabled={memberSaving} style={{ width: "100%", padding: "10px 0", marginTop: 18, fontSize: 13, fontWeight: 700 }}>
                  {memberSaving ? "Adding…" : "Add Family Member"}
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Linked hospitals — every hospital with a booking record for this account */}
        <div className="card" style={cardStyle}>
          <SectionHeader title="Linked Healthcare Providers" />
          <div style={{ padding: "14px 20px" }}>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
              Hospitals you've booked with — your shared history is visible to their doctors once you've booked there.
            </div>
            {health === null ? (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Loading…</div>
            ) : health.linked_hospitals?.length > 0 ? (
              <div style={{ display: "grid", gap: 8 }}>
                {health.linked_hospitals.map(h => (
                  <div key={h.tenant_id} style={{
                    display: "flex", alignItems: "center", gap: 12,
                    background: "var(--color-surface-secondary, #f6f4ee)", borderRadius: 10, padding: "10px 14px",
                  }}>
                    <div className="icon-chip icon-chip--green" style={{ width: 32, height: 32, flexShrink: 0 }}>
                      <Building2 size={15} />
                    </div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 13 }}>{h.hospital_name}</div>
                      <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                        Last visit: {new Date(h.last_visit).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                No hospitals yet — once you book your first appointment, it'll show up here.
              </div>
            )}
          </div>
        </div>

        {/* Change password */}
        <div className="card" style={cardStyle}>
          <SectionHeader
            title="Password"
            action={
              <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "4px 12px" }}
                onClick={() => setPwOpen(o => !o)}>
                {pwOpen ? "Cancel" : "Change Password"}
              </button>
            }
          />
          {pwOpen && (
            <div style={{ padding: "14px 20px" }}>
              <form onSubmit={handlePasswordSubmit} style={{ maxWidth: 360 }}>
                <div style={{ display: "grid", gap: 14 }}>
                  <div><label style={labelStyle}>Current Password</label>
                    <input type="password" className="profile-edit-input" style={inputStyle} value={pw.current_password}
                      onChange={e => setPw(p => ({ ...p, current_password: e.target.value }))} required />
                  </div>
                  <div><label style={labelStyle}>New Password</label>
                    <input type="password" className="profile-edit-input" style={inputStyle} value={pw.new_password} minLength={8}
                      onChange={e => setPw(p => ({ ...p, new_password: e.target.value }))} required />
                  </div>
                  <div><label style={labelStyle}>Confirm New Password</label>
                    <input type="password" className="profile-edit-input" style={inputStyle} value={pw.confirm_password} minLength={8}
                      onChange={e => setPw(p => ({ ...p, confirm_password: e.target.value }))} required />
                  </div>
                </div>
                <button type="submit" className="btn-primary" disabled={pwSaving} style={{ width: "100%", padding: "10px 0", marginTop: 18, fontSize: 13, fontWeight: 700 }}>
                  {pwSaving ? "Changing…" : "Change Password"}
                </button>
              </form>
            </div>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
