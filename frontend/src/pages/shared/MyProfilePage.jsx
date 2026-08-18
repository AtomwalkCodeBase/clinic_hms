/**
 * pages/shared/MyProfilePage.jsx
 * ----------------------------------
 * Generic self-service profile page for any staff role that isn't a
 * doctor (nurse, front desk, lab tech, pharmacist, hospital admin).
 * Photo upload (StaffUser.photo, shared with the doctor page) plus a
 * qualification/license card — admin-set basics shown read-only, gender/
 * bio/languages filled in by the person themselves. Mirrors the doctor
 * profile page's view/edit pattern so every login works the same way.
 */
import { useState, useEffect, useRef } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ProfilePhotoUpload from "../../components/common/ProfilePhotoUpload";
import ChangePasswordCard from "../../components/common/ChangePasswordCard";
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

export default function MyProfilePage() {
  const { user, refreshUser } = useAuth();
  const { toastSuccess, toastApiError } = useToast();
  const [photo, setPhoto] = useState("");
  const [dob, setDob] = useState("");
  const [form, setForm] = useState({
    registration_no: "", council_name: "", registration_expiry: "",
    qualification: "", experience_years: "",
    gender: "", bio: "", languages: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(false);
  const snapshotRef = useRef(null);

  useEffect(() => {
    Promise.all([
      apiClient.get(API_ENDPOINTS.ORG.MY_PROFILE),
      apiClient.get(API_ENDPOINTS.ORG.MY_STAFF_PROFILE),
    ])
      .then(([meRes, profileRes]) => {
        if (meRes.data?.data?.photo) setPhoto(meRes.data.data.photo);
        if (meRes.data?.data?.date_of_birth) setDob(meRes.data.data.date_of_birth);
        if (profileRes.data?.data) {
          const d = profileRes.data.data;
          setForm(f => ({ ...f, ...d }));
          if (!(d.bio || d.languages || d.gender)) setEditing(true);
        }
      })
      .catch(err => toastApiError(err, "Could not load your profile."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      const payload = { gender: form.gender, bio: form.bio, languages: form.languages };
      const [{ data: res }] = await Promise.all([
        apiClient.patch(API_ENDPOINTS.ORG.MY_STAFF_PROFILE, payload),
        apiClient.patch(API_ENDPOINTS.ORG.MY_PROFILE, { date_of_birth: dob || null }),
      ]);
      if (res?.data) setForm(f => ({ ...f, ...res.data }));
      setEditing(false);
      toastSuccess("Profile updated.");
    } catch (err) {
      toastApiError(err, "Failed to update profile.");
    } finally {
      setSaving(false);
    }
  }

  const name = user?.full_name || user?.email?.split("@")[0] || "";
  const initials = name.split(" ").map(p => p.charAt(0)).join("").slice(0, 2).toUpperCase() || "?";
  const hasLicense = form.registration_no || form.council_name;
  const hasBasics = form.qualification || form.experience_years != null || hasLicense;

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

        <div className="card" style={{ padding: 24, marginBottom: 20 }}>
          <div className="dot-label dot-label--green" style={{ marginBottom: 14 }}>Profile photo</div>
          <ProfilePhotoUpload photo={photo} onUploaded={(p) => { setPhoto(p); refreshUser(); }} initials={initials} />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>

          {/* Read-only: set by the hospital admin at onboarding */}
          <div className="card" style={{ padding: 24 }}>
            <div className="dot-label dot-label--gold" style={{ marginBottom: 16 }}>
              Set by your hospital admin
            </div>
            {!hasBasics && (
              <div style={{
                fontSize: 12, color: "var(--color-warning)", marginBottom: 14,
                background: "var(--color-warning-light)", padding: "8px 12px", borderRadius: 8,
              }}>
                Your qualification hasn't been entered yet — ask your hospital admin to add it from Staff → Profile.
              </div>
            )}
            <div style={{ display: "grid", gap: 14 }}>
              <div><label style={labelStyle}>Qualification</label>
                <input style={readOnlyStyle} value={form.qualification || "Not set"} readOnly />
              </div>
              <div><label style={labelStyle}>Experience (years)</label>
                <input style={readOnlyStyle} value={form.experience_years ?? "Not set"} readOnly />
              </div>
              {hasLicense && (
                <>
                  <div><label style={labelStyle}>Registration / License No.</label>
                    <input style={readOnlyStyle} value={form.registration_no || "Not set"} readOnly />
                  </div>
                  <div><label style={labelStyle}>Issuing Council / Body</label>
                    <input style={readOnlyStyle} value={form.council_name || "Not set"} readOnly />
                  </div>
                  <div><label style={labelStyle}>Registration Expiry</label>
                    <input style={readOnlyStyle} value={form.registration_expiry || "Not set"} readOnly />
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Self-service: gender / bio / languages */}
          <div className="card" style={{ padding: 24 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <div className="dot-label dot-label--green">Fill in yourself</div>
              {!editing && (
                <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={startEditing}>
                  Edit
                </button>
              )}
            </div>

            {editing ? (
              <form onSubmit={handleSubmit}>
                <div style={{ display: "grid", gap: 14 }}>
                  <div><label style={labelStyle}>Gender</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      {[["M", "Male"], ["F", "Female"], ["O", "Other"]].map(([val, label]) => (
                        <button key={val} type="button"
                          className={form.gender === val ? "btn-primary" : "btn-outline"}
                          style={{ flex: 1, fontSize: 12.5, padding: "8px 0" }}
                          onClick={() => setForm(f => ({ ...f, gender: f.gender === val ? "" : val }))}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div><label style={labelStyle}>Date of Birth</label>
                    <input type="date" style={inputStyle} value={dob} onChange={e => setDob(e.target.value)} />
                  </div>
                  <div><label style={labelStyle}>Languages Spoken</label>
                    <input style={inputStyle} value={form.languages} onChange={set("languages")} placeholder="English, Hindi, Kannada" />
                  </div>
                  <div><label style={labelStyle}>Short Bio</label>
                    <textarea style={{ ...inputStyle, minHeight: 80, resize: "vertical" }} value={form.bio} onChange={set("bio")} placeholder="A line or two about you." />
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
                  <button type="button" className="btn-outline" style={{ flex: 1, padding: "10px 0" }} onClick={cancelEditing} disabled={saving}>
                    Cancel
                  </button>
                  <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2, padding: "10px 0" }}>
                    {saving ? "Saving…" : "Save Profile"}
                  </button>
                </div>
              </form>
            ) : (
              <div style={{ display: "grid", gap: 16 }}>
                <div>
                  <label style={labelStyle}>Gender</label>
                  <div style={{ fontSize: 14 }}>
                    {{ M: "Male", F: "Female", O: "Other" }[form.gender] || <span style={{ color: "var(--color-text-muted)" }}>Not set</span>}
                  </div>
                </div>
                <div>
                  <label style={labelStyle}>Date of Birth</label>
                  <div style={{ fontSize: 14 }}>
                    {dob
                      ? `${dob}${calcAge(dob) != null ? ` · ${calcAge(dob)}y` : ""}`
                      : <span style={{ color: "var(--color-text-muted)" }}>Not set</span>}
                  </div>
                </div>
                <div>
                  <label style={labelStyle}>Languages Spoken</label>
                  <div style={{ fontSize: 14 }}>
                    {form.languages || <span style={{ color: "var(--color-text-muted)" }}>Not set</span>}
                  </div>
                </div>
                <div>
                  <label style={labelStyle}>Short Bio</label>
                  <div style={{ fontSize: 14, lineHeight: 1.6, color: form.bio ? "var(--color-text)" : "var(--color-text-muted)" }}>
                    {form.bio || "Not set"}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <ChangePasswordCard />
      </PageShell>
    </AppShell>
  );
}
