/**
 * pages/doctor/MyProfilePage.jsx
 * ---------------------------------
 * Doctor self-service profile. Admin-set basics (registration no.,
 * specialisation, qualification, experience) are shown read-only — they
 * were entered by the hospital admin when the account was created. The
 * doctor fills in everything else here: bio, photo, languages spoken, and
 * an e-signature (used on prescriptions), both uploaded as images.
 *
 * Consultation fee is intentionally on hold — likely belongs to front desk
 * (billing owns pricing), not the doctor's own login. Shown read-only with
 * a note until that's decided; not editable from here.
 */
import { useState, useEffect, useRef } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useToast }  from "../../hooks/useToast";
import { useAuth }   from "../../hooks/useAuth";
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

// Same downscale approach as ProfilePhotoUpload — signatures don't need to
// be huge either, and this keeps it well under the request body cap.
function resizeToDataUrl(file, maxDim = 480, quality = 0.85) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.onload = () => {
      img.onerror = () => reject(new Error("Not a valid image."));
      img.onload = () => {
        let { width, height } = img;
        if (width > height && width > maxDim) { height = Math.round(height * (maxDim / width)); width = maxDim; }
        else if (height > maxDim) { width = Math.round(width * (maxDim / height)); height = maxDim; }
        const canvas = document.createElement("canvas");
        canvas.width = width; canvas.height = height;
        canvas.getContext("2d").drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL("image/png", quality));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

export default function DoctorMyProfilePage() {
  const { toastSuccess, toastApiError } = useToast();
  const { refreshUser } = useAuth();
  const [form, setForm] = useState({
    registration_no: "", specialisation: "", qualification: "", gender: "",
    experience_years: "", consultation_fee: "", digital_signature: "",
    bio: "", languages: "",
  });
  const [photo, setPhoto] = useState("");
  const [dob, setDob] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sigUploading, setSigUploading] = useState(false);
  const [feeEditable, setFeeEditable] = useState(false); // true when fee_ownership=doctor
  // View mode by default once there's something to show; edit mode opens
  // the form. Cancel reverts to whatever was last saved (snapshot below).
  const [editing, setEditing] = useState(false);
  const snapshotRef = useRef(null);
  const sigInputRef = useRef(null);

  useEffect(() => {
    Promise.all([
      apiClient.get(API_ENDPOINTS.ORG.MY_DOCTOR_PROFILE),
      apiClient.get(API_ENDPOINTS.ORG.MY_PROFILE),
      apiClient.get("/org/settings/").catch(() => ({ data: { data: { fee_ownership: "doctor" } } })),
    ])
      .then(([profileRes, meRes, settingsRes]) => {
        if (profileRes.data?.data) {
          setForm(f => ({ ...f, ...profileRes.data.data }));
          const d = profileRes.data.data;
          if (!(d.bio || d.languages || d.digital_signature || d.gender)) {
            setEditing(true);
          }
        }
        if (meRes.data?.data?.photo) setPhoto(meRes.data.data.photo);
        if (meRes.data?.data?.date_of_birth) setDob(meRes.data.data.date_of_birth);
        const fo = (settingsRes?.data?.data ?? settingsRes?.data)?.fee_ownership;
        setFeeEditable(fo === "doctor");
      })
      .catch(err => toastApiError(err, "Could not load your profile."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startEditing() {
    snapshotRef.current = form; // remember pre-edit values in case of Cancel
    setEditing(true);
  }

  function cancelEditing() {
    if (snapshotRef.current) setForm(snapshotRef.current);
    setEditing(false);
  }

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  async function handleSignatureFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toastApiError({ message: "Please choose an image file." }, "Invalid file.");
      return;
    }
    setSigUploading(true);
    try {
      const dataUrl = await resizeToDataUrl(file);
      setForm(f => ({ ...f, digital_signature: dataUrl }));
      toastSuccess("Signature ready — click Save Profile to keep it.");
    } catch (err) {
      toastApiError(err, "Could not read that image.");
    } finally {
      setSigUploading(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        gender: form.gender,
        digital_signature: form.digital_signature,
        bio: form.bio,
        languages: form.languages,
        // Only send consultation_fee when the hospital delegates it to the doctor
        ...(feeEditable && form.consultation_fee !== "" && {
          consultation_fee: form.consultation_fee || null,
        }),
      };
      const [{ data: res }] = await Promise.all([
        apiClient.patch(API_ENDPOINTS.ORG.MY_DOCTOR_PROFILE, payload),
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

  if (loading) {
    return (
      <AppShell>
        <PageShell title="My Profile">
          <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        </PageShell>
      </AppShell>
    );
  }

  const hasBasics = form.specialisation || form.qualification || form.registration_no;
  const initials = (form.specialisation ? "Dr" : "Dr");

  return (
    <AppShell>
      <PageShell title="My Profile">

        {/* Photo — shared across every staff role, shows up on the dashboard greeting */}
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
                Your specialisation and qualification haven't been entered yet — ask your hospital admin to add them from Staff → Edit.
              </div>
            )}
            <div style={{ display: "grid", gap: 14 }}>
              <div><label style={labelStyle}>Specialisation</label>
                <input style={readOnlyStyle} value={form.specialisation || "Not set"} readOnly />
              </div>
              <div><label style={labelStyle}>Qualification</label>
                <input style={readOnlyStyle} value={form.qualification || "Not set"} readOnly />
              </div>
              <div><label style={labelStyle}>MCI/NMC Registration No.</label>
                <input style={readOnlyStyle} value={form.registration_no || "Not set"} readOnly />
              </div>
              <div><label style={labelStyle}>Experience (years)</label>
                <input style={readOnlyStyle} value={form.experience_years ?? "Not set"} readOnly />
              </div>
              <div>
                <label style={labelStyle}>Consultation Fee (₹)</label>
                <input
                  style={feeEditable && editing ? inputStyle : readOnlyStyle}
                  type={feeEditable && editing ? "number" : "text"}
                  value={feeEditable && editing
                    ? form.consultation_fee
                    : form.consultation_fee ? `₹${form.consultation_fee}` : "Not set"}
                  onChange={e => feeEditable && setForm(f => ({ ...f, consultation_fee: e.target.value }))}
                  readOnly={!feeEditable || !editing}
                />
                {!feeEditable && (
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                    Set by your hospital admin.
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Self-service: the doctor's own details */}
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
                    <select style={inputStyle} value={form.gender} onChange={set("gender")}>
                      <option value="">—</option>
                      <option value="M">Male</option>
                      <option value="F">Female</option>
                      <option value="O">Other</option>
                    </select>
                  </div>
                  <div><label style={labelStyle}>Date of Birth</label>
                    <input type="date" style={inputStyle} value={dob} onChange={e => setDob(e.target.value)} />
                  </div>
                  <div><label style={labelStyle}>Languages Spoken</label>
                    <input style={inputStyle} value={form.languages} onChange={set("languages")} placeholder="English, Hindi, Kannada" />
                  </div>
                  <div><label style={labelStyle}>Short Bio</label>
                    <textarea style={{ ...inputStyle, minHeight: 80, resize: "vertical" }} value={form.bio} onChange={set("bio")} placeholder="A line or two patients will see on your profile." />
                  </div>

                  <div>
                    <label style={labelStyle}>Digital Signature</label>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <div style={{
                        width: 120, height: 56, borderRadius: 8, border: "1.5px solid var(--color-border)",
                        background: "var(--color-surface)", display: "flex", alignItems: "center", justifyContent: "center",
                        overflow: "hidden", flexShrink: 0,
                      }}>
                        {form.digital_signature
                          ? <img src={form.digital_signature} alt="Signature" style={{ maxWidth: "100%", maxHeight: "100%" }} />
                          : <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>No signature</span>}
                      </div>
                      <button
                        type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}
                        disabled={sigUploading} onClick={() => sigInputRef.current?.click()}
                      >
                        {sigUploading ? "Reading…" : form.digital_signature ? "Change" : "Upload"}
                      </button>
                      <input ref={sigInputRef} type="file" accept="image/*" hidden onChange={handleSignatureFile} />
                    </div>
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                      Used on prescriptions. Upload, then Save Profile to keep it.
                    </div>
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
                <div>
                  <label style={labelStyle}>Digital Signature</label>
                  <div style={{
                    width: 140, height: 60, borderRadius: 8, border: "1.5px solid var(--color-border)",
                    background: "var(--color-surface)", display: "flex", alignItems: "center", justifyContent: "center",
                    overflow: "hidden",
                  }}>
                    {form.digital_signature
                      ? <img src={form.digital_signature} alt="Signature" style={{ maxWidth: "100%", maxHeight: "100%" }} />
                      : <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>Not set</span>}
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
