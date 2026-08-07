/**
 * pages/front-desk/RegisterPatientPage.jsx
 * ------------------------------------------
 * Patient registration form — matches the Atomwalk HMS field specification.
 *
 * Sections (per atomwalk_registration_fields.html):
 *   1. Personal Information (name, DOB, gender, blood group, etc.)
 *   2. Contact Information (mobile, email, address, emergency contact)
 *   3. Registration Branch (branch, referring doctor)
 *   4. Insurance & Payment (payer type, insurer, policy)
 *   5. Consent (DPDP consent)
 */

import { useState, useEffect, useRef } from "react";
import { useNavigate }   from "react-router-dom";
import { AppShell }      from "../../components/layout/AppShell";
import { PageShell }     from "../../components/common/PageShell";
import { useToast }      from "../../hooks/useToast";
import { useApi }        from "../../hooks/useApi";
import apiClient         from "../../services/api.client";
import API_ENDPOINTS     from "../../config/api.config";
import { calcAge }       from "../../utils/age";

// ── Field helpers ─────────────────────────────────────────────────────────────
function FieldGroup({ label, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{
        display: "block", fontSize: 12, fontWeight: 600,
        color: "var(--color-text-secondary)", marginBottom: 5,
      }}>{label}</label>
      {children}
    </div>
  );
}

function Input({ error, ...props }) {
  return (
    <>
      <input className={`form-input${error ? " error" : ""}`} {...props} />
      {error && <div className="field-error">{error}</div>}
    </>
  );
}

function FSelect({ error, children, ...props }) {
  return (
    <>
      <select className={`form-input${error ? " error" : ""}`}
        style={{ appearance: "auto" }} {...props}>
        {children}
      </select>
      {error && <div className="field-error">{error}</div>}
    </>
  );
}

function SectionCard({ title, subtitle, color = "#5B52EE", bgColor = "#EDE9FF", emoji, children }) {
  return (
    <div className="card" style={{ padding: 0, marginBottom: 20, overflow: "hidden" }}>
      <div style={{
        background: bgColor, padding: "12px 20px",
        borderBottom: "1px solid var(--color-border)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {emoji && <span style={{ fontSize: 18 }}>{emoji}</span>}
          <span style={{ fontWeight: 700, fontSize: 14, color }}>{title}</span>
        </div>
        {subtitle && (
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3, marginLeft: emoji ? 28 : 0 }}>
            {subtitle}
          </div>
        )}
      </div>
      <div style={{ padding: 20 }}>{children}</div>
    </div>
  );
}

// Two-node progress indicator — registration is really two phases: find the
// patient, then (if new) fill in their details. Kept to what's actually
// built rather than a longer wizard that doesn't exist yet.
function Stepper({ step }) {
  const nodeStyle = (active) => ({
    display: "flex", alignItems: "center", gap: 7, fontSize: 12, fontWeight: 700,
    color: active ? "#1D4ED8" : "var(--color-text-muted)",
  });
  const dotStyle = (active) => ({
    width: 9, height: 9, borderRadius: "50%",
    background: active ? "#1D4ED8" : "var(--color-border)",
  });
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
      <div style={nodeStyle(step >= 1)}><span style={dotStyle(step >= 1)} />Find Patient</div>
      <div style={{ width: 32, height: 1, background: "var(--color-border)" }} />
      <div style={nodeStyle(step >= 2)}><span style={dotStyle(step >= 2)} />Patient Details</div>
    </div>
  );
}

function TwoCol({ children }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      {children}
    </div>
  );
}

function ThreeCol({ children }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
      {children}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function RegisterPatientPage() {
  const navigate = useNavigate();
  const { toastSuccess, toastApiError } = useToast();
  const { data: branches } = useApi(API_ENDPOINTS.ORG.BRANCHES);
  const branchList = branches || [];

  const [loading, setLoading] = useState(false);
  const [errors,  setErrors]  = useState({});

  const [form, setForm] = useState({
    // Personal
    full_name:       "",
    date_of_birth:   "",
    gender:          "",
    blood_group:     "",
    marital_status:  "",
    nationality:     "Indian",
    occupation:      "",

    // Contact
    mobile:           "",
    alternate_mobile: "",
    email:            "",
    address_line1:    "",
    city:             "",
    state:            "",
    pincode:          "",

    // Emergency
    emergency_name:    "",
    emergency_phone:   "",
    emergency_relation:"",

    // Hospital identity
    branch_id:         "",
    referring_doctor:  "",

    // Insurance
    payer_type:        "self",
    insurance_provider:"",
    policy_number:     "",
    tpa_name:          "",

    // Consent
    dpdp_consent: false,
    hie_consent:  false,

    // Dependent / guardian — set when registering a family member (child,
    // or anyone with no mobile of their own) via an existing guardian
    // record instead of their own mobile number.
    is_dependent:    false,
    guardian_awpid:  "",
    guardian_name:   "",
    guardian_mobile: "",
    relationship:    "child",
  });

  // ── Step 1: mobile-number check, gates the rest of the form ──────────────
  // Front desk shouldn't have to type a patient's full name/DOB/gender before
  // finding out they're already in the system — check the mobile number
  // first, and only reveal the registration fields once we know this is
  // genuinely a new patient (or the front desk explicitly chooses to
  // continue anyway).
  const [mobileInput, setMobileInput] = useState("");
  const [lookup, setLookup] = useState(null);       // API result once mobile is long enough
  const [lookupLoading, setLookupLoading] = useState(false);
  const [proceeded, setProceeded] = useState(false); // form unlocked
  const lookupDebounce = useRef(null);

  useEffect(() => {
    clearTimeout(lookupDebounce.current);
    const digits = mobileInput.replace(/\D/g, "");
    if (digits.length < 10) {
      setLookup(null);
      setLookupLoading(false);
      return;
    }
    setLookupLoading(true);
    lookupDebounce.current = setTimeout(() => {
      apiClient.get(API_ENDPOINTS.PATIENTS.LOOKUP, { params: { mobile: mobileInput } })
        // Backend wraps the payload as {success, message, data: {...}} —
        // the actual lookup fields are under .data.data, not .data.
        .then(({ data: res }) => setLookup(res?.data || null))
        .catch(() => setLookup(null))
        .finally(() => setLookupLoading(false));
    }, 400);
    return () => clearTimeout(lookupDebounce.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mobileInput]);

  const mobileDigits = mobileInput.replace(/\D/g, "");
  const mobileChecked = mobileDigits.length >= 10 && !lookupLoading && lookup != null;
  const isBlocked = mobileChecked && lookup.already_registered_here;
  const isNetworkMatch = mobileChecked && lookup.exists_in_network && !lookup.already_registered_here;
  const isNewPatient = mobileChecked && !lookup.exists_in_network && !lookup.already_registered_here;

  function continueWithDetails(useExisting) {
    setForm(f => ({
      ...f,
      mobile: mobileInput,
      is_dependent: false, guardian_awpid: "", guardian_name: "", guardian_mobile: "",
      ...(useExisting && lookup ? {
        full_name:     lookup.full_name || f.full_name,
        date_of_birth: lookup.date_of_birth || f.date_of_birth,
        gender:        (lookup.gender || "").toLowerCase() || f.gender,
      } : {}),
    }));
    setProceeded(true);
  }

  // A patient record shouldn't depend on the person having their own
  // mobile/login — a dependent (child, elderly parent with no phone, etc.)
  // is registered against a guardian's existing identity instead. Picking
  // an existing family member reuses their AWPID (cross-hospital dedup, the
  // same way mobile matching does for adults); "add new" starts a blank
  // dependent record under the same guardian.
  function continueAsDependent(member) {
    setForm(f => ({
      ...f,
      mobile: "",
      is_dependent: true,
      guardian_awpid: lookup.awpid,
      guardian_name: lookup.full_name,
      guardian_mobile: mobileInput,
      relationship: member?.relationship || "child",
      full_name:     member?.full_name || "",
      date_of_birth: member?.date_of_birth || "",
      gender:        (member?.gender || "").toLowerCase(),
    }));
    setProceeded(true);
  }

  function changeMobileNumber() {
    setProceeded(false);
    setForm(f => ({ ...f, is_dependent: false, guardian_awpid: "", guardian_name: "", guardian_mobile: "" }));
  }

  function searchNow() {
    clearTimeout(lookupDebounce.current);
    if (mobileDigits.length < 10) return;
    setLookupLoading(true);
    apiClient.get(API_ENDPOINTS.PATIENTS.LOOKUP, { params: { mobile: mobileInput } })
      .then(({ data: res }) => setLookup(res?.data || null))
      .catch(() => setLookup(null))
      .finally(() => setLookupLoading(false));
  }

  // ── Name / UHID search — a second way to find an existing patient without
  // knowing their mobile number. Reuses the same search endpoint the doctor
  // and nurse patient-search screens use (name/UHID/AWPID/mobile prefix).
  const [searchTab, setSearchTab] = useState("mobile"); // "mobile" | "name"
  const [nameQuery, setNameQuery] = useState("");
  const [nameResults, setNameResults] = useState(null); // null = not searched yet
  const [nameSearchLoading, setNameSearchLoading] = useState(false);

  function runNameSearch() {
    const q = nameQuery.trim();
    if (q.length < 2) return;
    setNameSearchLoading(true);
    apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, { params: { q } })
      .then(({ data: res }) => setNameResults(res?.data?.results || []))
      .catch(() => setNameResults([]))
      .finally(() => setNameSearchLoading(false));
  }

  function set(key) {
    return (e) => {
      const val = e.target.type === "checkbox" ? e.target.checked : e.target.value;
      setForm(f => ({ ...f, [key]: val }));
      if (errors[key]) setErrors(er => ({ ...er, [key]: undefined }));
    };
  }

  function validate() {
    const e = {};
    if (!form.full_name.trim())      e.full_name      = "Full name is required.";
    if (!form.date_of_birth)         e.date_of_birth  = "Date of birth is required.";
    if (!form.gender)                e.gender         = "Gender is required.";
    if (!form.is_dependent && !form.mobile.trim())
                                      e.mobile         = "Mobile number is required.";
    if (!form.branch_id)             e.branch_id      = "Branch is required.";
    if (!form.payer_type)            e.payer_type     = "Payer type is required.";
    if (!form.dpdp_consent)          e.dpdp_consent   = "DPDP consent is mandatory.";
    return e;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length > 0) { setErrors(errs); return; }

    setLoading(true);
    try {
      await apiClient.post("/api/v1/patients/register/", form);
      toastSuccess("Patient registered successfully.");
      navigate("/front-desk/queue");
    } catch (err) {
      if (err?.errors) setErrors(err.errors);
      toastApiError(err, "Registration failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell>
      <PageShell title="Register New Patient">

        <Stepper step={proceeded ? 2 : 1} />

        {/* ── Step 1: find the patient before anything else ── */}
        <SectionCard title="Find Patient" subtitle="Search first to avoid creating a duplicate record — then create a new one only if nothing matches."
          emoji="🔍" bgColor="#EFF6FF" color="#1D4ED8">

          {/* Segmented tabs — mobile is the fast path (dedup-checked across
              every hospital); name/UHID only searches this hospital's own
              records, for when front desk doesn't have the mobile handy. */}
          <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
            {[["mobile", "📱 Mobile Number"], ["name", "🪪 Name / UHID"]].map(([key, label]) => (
              <button key={key} type="button"
                onClick={() => setSearchTab(key)}
                style={{
                  fontSize: 12, fontWeight: 700, padding: "6px 14px", borderRadius: 20,
                  border: `1.5px solid ${searchTab === key ? "var(--color-primary)" : "var(--color-border)"}`,
                  background: searchTab === key ? "var(--color-primary-light)" : "#fff",
                  color: searchTab === key ? "var(--color-primary)" : "var(--color-text-muted)",
                  cursor: "pointer",
                }}>
                {label}
              </button>
            ))}
          </div>

          {searchTab === "mobile" ? (
            <>
              <FieldGroup label="Mobile Number *">
                <div style={{ display: "flex", gap: 8 }}>
                  <div style={{ flex: 1 }}>
                    <Input type="tel" value={mobileInput}
                      onChange={e => { setMobileInput(e.target.value); setProceeded(false); }}
                      onKeyDown={e => e.key === "Enter" && (e.preventDefault(), searchNow())}
                      placeholder="+91 XXXXX XXXXX" autoFocus />
                  </div>
                  <button type="button" className="btn-primary" style={{ padding: "0 20px" }}
                    onClick={searchNow} disabled={mobileDigits.length < 10 || lookupLoading}>
                    {lookupLoading ? "Searching…" : "Search"}
                  </button>
                </div>
              </FieldGroup>

              {mobileDigits.length > 0 && mobileDigits.length < 10 && (
                <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                  Enter at least 10 digits, then press Search (or wait — it checks automatically too).
                </div>
              )}

              {!proceeded && isBlocked && (
                <div style={{ background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 8, padding: "14px 16px" }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#B91C1C", marginBottom: 8 }}>
                    ⚠ Possible duplicate — patient already registered here
                  </div>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 12, background: "#fff",
                    borderRadius: 8, padding: "10px 14px", marginBottom: 10,
                  }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: "50%", background: "#FEE2E2", color: "#B91C1C",
                      display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0,
                    }}>👤</div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{lookup.full_name}</div>
                      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                        UHID: {lookup.existing_uhid}{lookup.existing_branch_name ? ` · ${lookup.existing_branch_name}` : ""}
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: "#7f1d1d", lineHeight: 1.6, marginBottom: 10 }}>
                    Use their existing record instead of creating a new one — find them in Appointments or
                    Queue by UHID or name.
                  </div>
                  <button type="button" className="btn-primary" style={{ fontSize: 12, padding: "6px 14px" }}
                    onClick={() => navigate("/front-desk/queue")}>
                    Go to Queue →
                  </button>
                </div>
              )}

              {!proceeded && isNetworkMatch && (
                <div style={{ background: "#F0F9FF", border: "1px solid #BAE6FD", borderRadius: 8, padding: "14px 16px" }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#0369a1", marginBottom: 8 }}>
                    Patient Found ✓ — already in our network
                  </div>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 12, background: "#fff",
                    borderRadius: 8, padding: "10px 14px", marginBottom: 10,
                  }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: "50%", background: "#DBEAFE", color: "#1E40AF",
                      display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0,
                    }}>👤</div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{lookup.full_name}</div>
                      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                        {lookup.date_of_birth
                          ? `Born ${lookup.date_of_birth}${calcAge(lookup.date_of_birth) != null ? ` · ${calcAge(lookup.date_of_birth)}y` : ""}`
                          : "Registered at another Atomwalk hospital"}
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: "#075985", lineHeight: 1.6, marginBottom: 10 }}>
                    Not registered at this hospital yet. If this is the same person, use their details and ask
                    their consent to share history with this hospital too — avoids a disconnected duplicate.
                  </div>
                  <div style={{ display: "flex", gap: 10 }}>
                    <button type="button" className="btn-primary" style={{ fontSize: 12, padding: "6px 14px" }}
                      onClick={() => continueWithDetails(true)}>
                      Use these details & Continue
                    </button>
                    <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}
                      onClick={() => continueWithDetails(false)}>
                      Not the same person — continue as new
                    </button>
                  </div>
                </div>
              )}

              {/* Family members — a patient record shouldn't depend on having
                  their own mobile, so dependents registered under this
                  guardian anywhere in the network show up here to reuse,
                  instead of front desk re-typing (and re-guessing) details
                  that create a disconnected duplicate. */}
              {!proceeded && mobileChecked && lookup.exists_in_network && (
                <div style={{
                  background: "#FAF5FF", border: "1px solid #E9D5FF", borderRadius: 8,
                  padding: "14px 16px", marginTop: 10,
                }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#6B21A8", marginBottom: 8 }}>
                    Family Members
                  </div>
                  {(lookup.family_members || []).length === 0 ? (
                    <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 10 }}>
                      No family members linked to {lookup.full_name} yet.
                    </div>
                  ) : (
                    <div style={{ display: "grid", gap: 8, marginBottom: 10 }}>
                      {lookup.family_members.map(m => (
                        <div key={m.awpid} style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          background: "#fff", borderRadius: 8, padding: "8px 12px",
                        }}>
                          <div>
                            <div style={{ fontWeight: 700, fontSize: 13 }}>{m.full_name}</div>
                            <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "capitalize" }}>
                              {m.relationship}{m.date_of_birth ? ` · DOB ${m.date_of_birth}${calcAge(m.date_of_birth) != null ? ` (${calcAge(m.date_of_birth)}y)` : ""}` : ""}
                            </div>
                          </div>
                          {m.already_registered_here ? (
                            <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "5px 12px" }}
                              onClick={() => navigate("/front-desk/queue")}>
                              Already here — Go to Queue
                            </button>
                          ) : (
                            <button type="button" className="btn-primary" style={{ fontSize: 11, padding: "5px 12px" }}
                              onClick={() => continueAsDependent(m)}>
                              Register here →
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}
                    onClick={() => continueAsDependent(null)}>
                    + Add a new family member
                  </button>
                </div>
              )}

              {!proceeded && isNewPatient && (
                <div style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 8, padding: "14px 16px" }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#166534", marginBottom: 4 }}>
                    No patient found
                  </div>
                  <div style={{ fontSize: 12, color: "#166534", lineHeight: 1.6, marginBottom: 10 }}>
                    Create a new patient record for this mobile number?
                  </div>
                  <button type="button" className="btn-primary" style={{ fontSize: 12, padding: "6px 14px" }}
                    onClick={() => continueWithDetails(false)}>
                    Create New Patient →
                  </button>
                </div>
              )}

              {proceeded && (
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  background: "#F0FDF4", border: "1px solid #BBF7D0", borderRadius: 8, padding: "10px 16px",
                }}>
                  <div style={{ fontSize: 12, color: "#166534" }}>
                    {form.is_dependent
                      ? <>✓ Registering a family member under <strong>{form.guardian_name}</strong> — continuing below.</>
                      : <>✓ Checked <strong>{mobileInput}</strong> — continuing registration below.</>}
                  </div>
                  <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "5px 12px" }}
                    onClick={changeMobileNumber}>
                    Change number
                  </button>
                </div>
              )}

              {/* Empty state — nothing entered yet */}
              {mobileDigits.length === 0 && !proceeded && (
                <div style={{
                  textAlign: "center", padding: "28px 20px", marginTop: 4,
                  border: "1.5px dashed var(--color-border)", borderRadius: 10,
                }}>
                  <div style={{ fontSize: 28, marginBottom: 8 }}>👤</div>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4 }}>Register a new patient</div>
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>
                    Search existing records first to avoid duplicate profiles.
                  </div>
                  <div style={{ display: "flex", justifyContent: "center", gap: 18, fontSize: 12, color: "#166534", flexWrap: "wrap" }}>
                    <span>✓ Instant UHID generation</span>
                    <span>✓ Previous history linked</span>
                    <span>✓ Appointment ready</span>
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <FieldGroup label="Patient Name or UHID">
                <div style={{ display: "flex", gap: 8 }}>
                  <div style={{ flex: 1 }}>
                    <Input value={nameQuery}
                      onChange={e => setNameQuery(e.target.value)}
                      onKeyDown={e => e.key === "Enter" && (e.preventDefault(), runNameSearch())}
                      placeholder="e.g. Meera Krishnan or LKV-000013" autoFocus />
                  </div>
                  <button type="button" className="btn-primary" style={{ padding: "0 20px" }}
                    onClick={runNameSearch} disabled={nameQuery.trim().length < 2 || nameSearchLoading}>
                    {nameSearchLoading ? "Searching…" : "Search"}
                  </button>
                </div>
              </FieldGroup>

              {nameResults != null && (
                nameResults.length === 0 ? (
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)", padding: "10px 0" }}>
                    No patients matched "{nameQuery}" at this hospital. Try Mobile Number, or create a new record.
                  </div>
                ) : (
                  <div style={{ display: "grid", gap: 8 }}>
                    {nameResults.map(p => (
                      <div key={p.id} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        background: "#F8FAFC", border: "1px solid var(--color-border)", borderRadius: 8,
                        padding: "10px 14px",
                      }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                          <div style={{
                            width: 34, height: 34, borderRadius: "50%", background: "#EDE9FF", color: "#5B52EE",
                            display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15,
                          }}>👤</div>
                          <div>
                            <div style={{ fontWeight: 700, fontSize: 13 }}>{p.full_name}</div>
                            <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
                              UHID: {p.uhid} {p.mobile ? `· ${p.mobile}` : ""}
                            </div>
                          </div>
                        </div>
                        <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "5px 12px" }}
                          onClick={() => navigate("/front-desk/appointments")}>
                          Book Appointment →
                        </button>
                      </div>
                    ))}
                  </div>
                )
              )}
            </>
          )}
        </SectionCard>

        {!proceeded ? null : (
        <form onSubmit={handleSubmit}>

          {/* Info banner */}
          <div style={{
            background: "#F0F9FF", border: "1px solid #BAE6FD", borderRadius: 8,
            padding: "10px 16px", marginBottom: 20, fontSize: 12, color: "#0369a1", lineHeight: 1.6,
          }}>
            Fields marked <strong style={{ color: "#dc2626" }}>*</strong> are mandatory.
            UHID and AWPID are auto-generated after registration.
          </div>

          {/* ── 1. Personal Information ── */}
          <SectionCard title="Personal Information" emoji="🪪" bgColor="#F0FDF4" color="#15803D">
            <TwoCol>
              <FieldGroup label="Full Name *">
                <Input value={form.full_name} onChange={set("full_name")}
                  placeholder="As per government ID" error={errors.full_name} required />
              </FieldGroup>
              <FieldGroup label="Date of Birth *">
                <Input type="date" value={form.date_of_birth} onChange={set("date_of_birth")}
                  error={errors.date_of_birth} required />
              </FieldGroup>
            </TwoCol>
            <TwoCol>
              <FieldGroup label="Gender *">
                <FSelect value={form.gender} onChange={set("gender")} error={errors.gender} required>
                  <option value="">Select gender</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="other">Other</option>
                  <option value="prefer_not_to_say">Prefer not to say</option>
                </FSelect>
              </FieldGroup>
              <FieldGroup label="Blood Group">
                <FSelect value={form.blood_group} onChange={set("blood_group")}>
                  <option value="">Unknown</option>
                  {["A+","A-","B+","B-","AB+","AB-","O+","O-"].map(g => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </FSelect>
              </FieldGroup>
            </TwoCol>
            <ThreeCol>
              <FieldGroup label="Marital Status">
                <FSelect value={form.marital_status} onChange={set("marital_status")}>
                  <option value="">Select</option>
                  <option value="single">Single</option>
                  <option value="married">Married</option>
                  <option value="widowed">Widowed</option>
                  <option value="divorced">Divorced</option>
                </FSelect>
              </FieldGroup>
              <FieldGroup label="Nationality">
                <Input value={form.nationality} onChange={set("nationality")} placeholder="Indian" />
              </FieldGroup>
              <FieldGroup label="Occupation">
                <Input value={form.occupation} onChange={set("occupation")} placeholder="Optional" />
              </FieldGroup>
            </ThreeCol>
          </SectionCard>

          {/* ── 2. Contact Information ── */}
          <SectionCard title="Contact Information" emoji="📞" bgColor="#F0FDF4" color="#15803D">
            {form.is_dependent && (
              <div style={{
                background: "#FAF5FF", border: "1px solid #E9D5FF", borderRadius: 8,
                padding: "12px 16px", marginBottom: 16,
              }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#6B21A8", marginBottom: 8 }}>
                  Registering as a dependent — no login/mobile of their own needed
                </div>
                <TwoCol>
                  <FieldGroup label="Guardian">
                    <Input value={form.guardian_name} readOnly style={{ background: "var(--color-surface-secondary, #f6f4ee)" }} />
                  </FieldGroup>
                  <FieldGroup label="Guardian Mobile">
                    <Input value={form.guardian_mobile} readOnly style={{ background: "var(--color-surface-secondary, #f6f4ee)" }} />
                  </FieldGroup>
                </TwoCol>
                <FieldGroup label="Relationship to Guardian">
                  <FSelect value={form.relationship} onChange={set("relationship")}>
                    <option value="child">Child</option>
                    <option value="parent">Parent</option>
                    <option value="spouse">Spouse</option>
                    <option value="sibling">Sibling</option>
                    <option value="ward">Ward</option>
                    <option value="other">Other</option>
                  </FSelect>
                </FieldGroup>
              </div>
            )}
            <TwoCol>
              <FieldGroup label={form.is_dependent ? "Mobile Number (optional)" : "Mobile Number *"}>
                <Input type="tel" value={form.mobile} onChange={set("mobile")}
                  placeholder={form.is_dependent ? "Only if they have their own phone" : "+91 XXXXX XXXXX"}
                  error={errors.mobile} required={!form.is_dependent} />
              </FieldGroup>
              <FieldGroup label="Alternate Mobile">
                <Input type="tel" value={form.alternate_mobile} onChange={set("alternate_mobile")}
                  placeholder="Optional" />
              </FieldGroup>
            </TwoCol>

            <FieldGroup label="Email Address">
              <Input type="email" value={form.email} onChange={set("email")}
                placeholder="patient@example.com (optional)" />
            </FieldGroup>
            <FieldGroup label="Address Line 1">
              <Input value={form.address_line1} onChange={set("address_line1")}
                placeholder="House / Flat, Street, Area" />
            </FieldGroup>
            <ThreeCol>
              <FieldGroup label="City">
                <Input value={form.city} onChange={set("city")} placeholder="City" />
              </FieldGroup>
              <FieldGroup label="State">
                <Input value={form.state} onChange={set("state")} placeholder="State" />
              </FieldGroup>
              <FieldGroup label="Pincode">
                <Input value={form.pincode} onChange={set("pincode")}
                  placeholder="6-digit pincode" maxLength={6} />
              </FieldGroup>
            </ThreeCol>

            {/* Emergency Contact subsection */}
            <div style={{
              background: "#FFFBEB", border: "1px solid #FDE68A",
              borderRadius: 8, padding: "14px 16px", marginTop: 8,
            }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#92400E", marginBottom: 14 }}>
                🚨 Emergency Contact <span style={{ fontWeight: 400, color: "#b45309" }}>(optional)</span>
              </div>
              <ThreeCol>
                <FieldGroup label="Name">
                  <Input value={form.emergency_name} onChange={set("emergency_name")}
                    placeholder="Contact name" error={errors.emergency_name} />
                </FieldGroup>
                <FieldGroup label="Phone">
                  <Input type="tel" value={form.emergency_phone} onChange={set("emergency_phone")}
                    placeholder="+91 XXXXX XXXXX" error={errors.emergency_phone} />
                </FieldGroup>
                <FieldGroup label="Relationship">
                  <FSelect value={form.emergency_relation} onChange={set("emergency_relation")}>
                    <option value="">Select</option>
                    <option value="spouse">Spouse</option>
                    <option value="parent">Parent</option>
                    <option value="child">Child</option>
                    <option value="sibling">Sibling</option>
                    <option value="friend">Friend</option>
                    <option value="other">Other</option>
                  </FSelect>
                </FieldGroup>
              </ThreeCol>
            </div>
          </SectionCard>

          {/* ── 3. Registration Branch ── */}
          <SectionCard title="Registration Branch" emoji="🏥" bgColor="#EDE9FF" color="#5B52EE">
            <TwoCol>
              <FieldGroup label="Register at Branch *">
                <FSelect value={form.branch_id} onChange={set("branch_id")}
                  error={errors.branch_id} required>
                  <option value="">Select branch</option>
                  {branchList.map(b => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </FSelect>
              </FieldGroup>
              <FieldGroup label="Referring Doctor / Source">
                <Input value={form.referring_doctor} onChange={set("referring_doctor")}
                  placeholder="Optional" />
              </FieldGroup>
            </TwoCol>
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
              gap: 16, background: "var(--color-bg)", borderRadius: 8, padding: "12px 16px",
            }}>
              {[
                ["UHID", "Auto-generated"],
                ["AWPID (Global ID)", "Auto-generated"],
                ["Registration Date", "Today"],
                ["Registered By", "Current staff"],
              ].map(([label, note]) => (
                <div key={label}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 2 }}>
                    {label}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--color-text-disabled)", fontStyle: "italic" }}>
                    {note}
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>

          {/* ── 4. Insurance & Payment ── */}
          <SectionCard title="Insurance & Payment" emoji="🛡️" bgColor="#F5F3FF" color="#5B52EE">
            <FieldGroup label="Payer Type *">
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {[
                  { value: "self",      label: "Self Pay" },
                  { value: "insurance", label: "Insurance" },
                  { value: "corporate", label: "Corporate / Cashless" },
                ].map(({ value, label }) => (
                  <label key={value} style={{
                    display: "flex", alignItems: "center", gap: 7,
                    fontSize: 13, cursor: "pointer",
                    padding: "8px 16px", borderRadius: 8,
                    border: `1.5px solid ${form.payer_type === value ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: form.payer_type === value ? "var(--color-primary-light)" : "#fff",
                    color: form.payer_type === value ? "var(--color-primary)" : "var(--color-text)",
                    fontWeight: form.payer_type === value ? 600 : 400,
                    transition: "all 120ms ease", userSelect: "none",
                  }}>
                    <input type="radio" name="payer_type" value={value}
                      checked={form.payer_type === value} onChange={set("payer_type")}
                      style={{ accentColor: "var(--color-primary)" }} />
                    {label}
                  </label>
                ))}
              </div>
              {errors.payer_type && <div className="field-error" style={{ marginTop: 6 }}>{errors.payer_type}</div>}
            </FieldGroup>

            {form.payer_type === "insurance" && (
              <ThreeCol>
                <FieldGroup label="Insurance Provider">
                  <Input value={form.insurance_provider} onChange={set("insurance_provider")}
                    placeholder="e.g. Star Health" />
                </FieldGroup>
                <FieldGroup label="Policy Number">
                  <Input value={form.policy_number} onChange={set("policy_number")}
                    placeholder="Policy / Member ID" />
                </FieldGroup>
                <FieldGroup label="TPA Name">
                  <Input value={form.tpa_name} onChange={set("tpa_name")}
                    placeholder="TPA company name" />
                </FieldGroup>
              </ThreeCol>
            )}
            {form.payer_type === "corporate" && (
              <FieldGroup label="Corporate / Employer Name">
                <Input value={form.insurance_provider} onChange={set("insurance_provider")}
                  placeholder="Employer / company name for cashless" />
              </FieldGroup>
            )}
          </SectionCard>

          {/* ── 5. DPDP Consent ── */}
          <SectionCard title="Privacy Consent (DPDP Act 2023)" emoji="🔑" bgColor="#FEF2F2" color="#B91C1C">
            <div style={{
              background: "#FFF7ED", border: "1px solid #FED7AA",
              borderRadius: 8, padding: "10px 16px", marginBottom: 16,
              fontSize: 12, color: "#92400E", lineHeight: 1.7,
            }}>
              Under the <strong>Digital Personal Data Protection (DPDP) Act 2023</strong>, explicit
              consent must be obtained before collecting and processing this patient's personal and
              health data. This is legally mandatory.
            </div>
            <label style={{
              display: "flex", alignItems: "flex-start", gap: 12,
              padding: "14px 16px", borderRadius: 8, cursor: "pointer",
              border: `2px solid ${form.dpdp_consent ? "#16a34a" : errors.dpdp_consent ? "#ef4444" : "var(--color-border)"}`,
              background: form.dpdp_consent ? "#f0fdf4" : "#fff",
              transition: "all 150ms ease",
            }}>
              <input type="checkbox" checked={form.dpdp_consent} onChange={set("dpdp_consent")}
                style={{ marginTop: 2, accentColor: "#16a34a", width: 16, height: 16, minWidth: 16, cursor: "pointer" }} />
              <span style={{ fontSize: 13, lineHeight: 1.6, color: "var(--color-text)" }}>
                <strong>I confirm</strong> that the patient has been informed about how their personal and
                medical data will be collected, used, and stored by this hospital, and has given their
                explicit verbal / written consent as required under the DPDP Act 2023.
              </span>
            </label>
            {errors.dpdp_consent && (
              <div className="field-error" style={{ marginTop: 6 }}>{errors.dpdp_consent}</div>
            )}

            <div style={{
              background: "#F0F9FF", border: "1px solid #BAE6FD",
              borderRadius: 8, padding: "10px 16px", margin: "16px 0",
              fontSize: 12, color: "#0369a1", lineHeight: 1.7,
            }}>
              Separate from the above — this specifically governs whether <strong>this hospital's</strong> doctors
              can see records the patient shared at <strong>other</strong> hospitals on Atomwalk (diagnoses,
              allergies, prescriptions, lab results). Optional — declining just means this hospital only
              sees what it records itself.
            </div>
            <label style={{
              display: "flex", alignItems: "flex-start", gap: 12,
              padding: "14px 16px", borderRadius: 8, cursor: "pointer",
              border: `2px solid ${form.hie_consent ? "#16a34a" : "var(--color-border)"}`,
              background: form.hie_consent ? "#f0fdf4" : "#fff",
              transition: "all 150ms ease",
            }}>
              <input type="checkbox" checked={form.hie_consent} onChange={set("hie_consent")}
                style={{ marginTop: 2, accentColor: "#16a34a", width: 16, height: 16, minWidth: 16, cursor: "pointer" }} />
              <span style={{ fontSize: 13, lineHeight: 1.6, color: "var(--color-text)" }}>
                <strong>I confirm</strong> the patient agrees to share their medical history from other
                Atomwalk hospitals with this hospital's doctors.
              </span>
            </label>
          </SectionCard>

          {/* Submit row */}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, paddingBottom: 32 }}>
            <button type="button" className="btn-outline"
              onClick={() => navigate(-1)} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={loading}
              style={{ minWidth: 180 }}>
              {loading ? "Registering…" : "Register Patient →"}
            </button>
          </div>
        </form>
        )}
      </PageShell>
    </AppShell>
  );
}
