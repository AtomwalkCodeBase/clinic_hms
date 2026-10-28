/** pages/front-desk/RegisterPatientPage.jsx */

import { useState, useEffect, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { AppShell }      from "../../components/layout/AppShell";
import { PageShell }     from "../../components/common/PageShell";
import QuickRegisterModal from "../../components/front-desk/QuickRegisterModal";
import { useToast }      from "../../hooks/useToast";
import { useApi }        from "../../hooks/useApi";
import { useAuth }       from "../../hooks/useAuth";
import apiClient         from "../../services/api.client";
import API_ENDPOINTS     from "../../config/api.config";
import PaginationControls from "../../components/common/PaginationControls";
import { formatAgeYM } from "../../utils/age";
import { sanitizeMobileInput, isValidMobile } from "../../utils/validation";
import { ROUTES } from "../../config/routes.config";
import {
  Search, Contact, Phone, Building2, Shield, Smartphone,
  AlertTriangle, User, Siren, Baby,
} from "lucide-react";

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

function SectionCard({ title, subtitle, color = "#5B52EE", bgColor = "#EDE9FF", icon: Icon, children }) {
  return (
    <div className="fdc-panel" style={{ padding: 0, marginBottom: 20, overflow: "hidden" }}>
      <div style={{
        background: bgColor, padding: "12px 20px",
        borderBottom: "1px solid var(--color-border)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {Icon && <Icon size={18} style={{ color }} />}
          <span style={{ fontWeight: 700, fontSize: 14, color }}>{title}</span>
        </div>
        {subtitle && (
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3, marginLeft: Icon ? 28 : 0 }}>
            {subtitle}
          </div>
        )}
      </div>
      <div style={{ padding: 20 }}>{children}</div>
    </div>
  );
}

// Two-node progress indicator — registration is really two phases: find the
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
export function RegisterPatientPageContent({ embedded = false } = {}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { toastSuccess, toastApiError } = useToast();
  const { user } = useAuth();
  const { data: branches } = useApi(API_ENDPOINTS.ORG.BRANCHES);
  const branchList = branches || [];
  const defaultBranchId = user?.branch_id || branchList?.[0]?.branch_id || "";

  const [loading, setLoading] = useState(false);
  const [errors,  setErrors]  = useState({});

  // A family member the mobile lookup already knows everything about (name/
  const [quickRegisterMember, setQuickRegisterMember] = useState(null);

  function handleQuickRegistered(created) {
    // QuickRegisterModal already toasts the "registered" confirmation —
    setQuickRegisterMember(null);
    navigate(ROUTES.FRONT_DESK.APPOINTMENTS, { state: { patient: created, justRegistered: true } });
  }

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



    // Dependent / guardian — set when registering a family member (child,
    is_dependent:    false,
    guardian_awpid:  "",
    guardian_name:   "",
    guardian_mobile: "",
    relationship:    "child",
  });

  // Pediatric-only — Birth History, captured here (registration) OR later by
  const [birthHistory, setBirthHistory] = useState({
    gestational_age_weeks: "", birth_weight_kg: "", delivery_mode: "",
    nicu_admission: false, nicu_days: "", birth_complications: "",
  });
  function setBh(key) {
    return (e) => {
      const val = e.target.type === "checkbox" ? e.target.checked : e.target.value;
      setBirthHistory(f => ({ ...f, [key]: val }));
    };
  }
  // Shown only while registering a dependent whose DOB marks them a minor —
  function isMinorDob(dob) {
    if (!dob) return false;
    const born = new Date(dob);
    if (Number.isNaN(born.getTime())) return false;
    const now = new Date();
    let age = now.getFullYear() - born.getFullYear();
    const m = now.getMonth() - born.getMonth();
    if (m < 0 || (m === 0 && now.getDate() < born.getDate())) age--;
    return age < 18;
  }
  const showBirthHistory = form.is_dependent && isMinorDob(form.date_of_birth);

  // ── Step 1: mobile-number check, gates the rest of the form ──────────────
  const [mobileInput, setMobileInput] = useState(location.state?.mobile || "");
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
        .then(({ data: res }) => setLookup(res?.data || null))
        .catch(() => setLookup(null))
        .finally(() => setLookupLoading(false));
    }, 400);
    return () => clearTimeout(lookupDebounce.current);
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
  const [searchTab, setSearchTab] = useState("mobile"); // "mobile" | "name"
  const [nameQuery, setNameQuery] = useState("");
  const [nameResults, setNameResults] = useState(null); // null = not loaded yet
  const [nameIsBrowse, setNameIsBrowse] = useState(true);
  const [nameSearchLoading, setNameSearchLoading] = useState(false);
  const [namePagination, setNamePagination] = useState(null);
  const [namePage, setNamePage] = useState(1);
  const [namePageSize, setNamePageSize] = useState(10);
  const nameDebounce = useRef(null);

  function runNameSearch(q, page = namePage, pageSize = namePageSize) {
    setNameSearchLoading(true);
    apiClient.get(API_ENDPOINTS.PATIENTS.SEARCH, { params: { ...(q ? { q } : {}), page, page_size: pageSize } })
      .then(({ data: res }) => {
        setNameResults(res?.data?.results || []);
        setNameIsBrowse(!!res?.data?.is_browse);
        setNamePagination(res?.data?.pagination || null);
      })
      .catch(() => { setNameResults([]); setNamePagination(null); })
      .finally(() => setNameSearchLoading(false));
  }

  // Loads the default "recently registered" browse list on mount (empty
  useEffect(() => {
    clearTimeout(nameDebounce.current);
    const q = nameQuery.trim();
    if (q && q.length < 2) return; // too short to search, but not empty — wait for more input
    nameDebounce.current = setTimeout(() => runNameSearch(q, namePage, namePageSize), q ? 300 : 0);
    return () => clearTimeout(nameDebounce.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nameQuery, namePage, namePageSize]);

  // Fields that must be a plain 10-digit mobile number — sanitized on every
  const MOBILE_FIELDS = new Set(["mobile", "alternate_mobile", "emergency_phone"]);

  function set(key) {
    return (e) => {
      let val = e.target.type === "checkbox" ? e.target.checked : e.target.value;
      if (MOBILE_FIELDS.has(key)) val = sanitizeMobileInput(val);
      setForm(f => ({ ...f, [key]: val }));
      if (errors[key]) setErrors(er => ({ ...er, [key]: undefined }));
    };
  }

  function validate() {
    const e = {};
    if (!form.full_name.trim())      e.full_name      = "Full name is required.";
    if (!form.date_of_birth)         e.date_of_birth  = "Date of birth is required.";
    if (!form.gender)                e.gender         = "Gender is required.";
    if (!form.is_dependent && !form.mobile.trim()) {
      e.mobile = "Mobile number is required.";
    } else if (form.mobile && !isValidMobile(form.mobile)) {
      e.mobile = "Enter a valid 10-digit mobile number.";
    }
    if (form.alternate_mobile && !isValidMobile(form.alternate_mobile))
                                      e.alternate_mobile = "Enter a valid 10-digit mobile number.";
    if (form.emergency_phone && !isValidMobile(form.emergency_phone))
                                      e.emergency_phone  = "Enter a valid 10-digit mobile number.";
    if (!form.branch_id)             e.branch_id      = "Branch is required.";
    return e;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length > 0) { setErrors(errs); return; }

    setLoading(true);
    try {
      const { data: envelope } = await apiClient.post(API_ENDPOINTS.PATIENTS.REGISTER, form);
      const patient = envelope?.data;

      // Optional Birth History — only when there's actually something to
      if (showBirthHistory && patient?.patient_id) {
        const bhBody = {};
        Object.entries(birthHistory).forEach(([k, v]) => {
          if (v === "" || v === null || v === undefined) return;
          bhBody[k] = v;
        });
        if (Object.keys(bhBody).length > 0) {
          bhBody.nicu_admission = !!birthHistory.nicu_admission;
          try {
            await apiClient.post(API_ENDPOINTS.PATIENTS.BIRTH_HISTORY(patient.patient_id), bhBody);
          } catch {
            // Non-fatal — registration already succeeded; birth history can
          }
        }
      }

      toastSuccess("Patient registered successfully.");
      // Straight to booking, not the queue — a freshly registered patient
      navigate(ROUTES.FRONT_DESK.APPOINTMENTS, { state: { patient, justRegistered: true } });
    } catch (err) {
      if (err?.errors) setErrors(err.errors);
      toastApiError(err, "Registration failed.");
    } finally {
      setLoading(false);
    }
  }

  const content = (
    <>
        <QuickRegisterModal
          key={quickRegisterMember?.awpid || "closed"}
          open={!!quickRegisterMember}
          onClose={() => setQuickRegisterMember(null)}
          onRegistered={handleQuickRegistered}
          branchId={defaultBranchId}
          guardian={quickRegisterMember ? {
            awpid: lookup?.awpid, full_name: lookup?.full_name, relation: quickRegisterMember.relationship,
          } : null}
          prefill={quickRegisterMember ? {
            full_name: quickRegisterMember.full_name,
            date_of_birth: quickRegisterMember.date_of_birth,
            gender: quickRegisterMember.gender,
          } : null}
        />

        <Stepper step={proceeded ? 2 : 1} />

        {/* ── Step 1: find the patient before anything else ── */}
        <SectionCard title="Find Patient" subtitle="Search first to avoid creating a duplicate record — then create a new one only if nothing matches."
          icon={Search} bgColor="#EFF6FF" color="#1D4ED8">

          {/* Segmented tabs — mobile is the fast path (dedup-checked across */}
          <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
            {[["mobile", Smartphone, "Mobile Number"], ["name", Contact, "Name / UHID"]].map(([key, TabIcon, label]) => (
              <button key={key} type="button"
                onClick={() => setSearchTab(key)}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 6,
                  fontSize: 12, fontWeight: 700, padding: "6px 14px", borderRadius: 20,
                  border: `1.5px solid ${searchTab === key ? "var(--color-primary)" : "var(--color-border)"}`,
                  background: searchTab === key ? "var(--color-primary-light)" : "#fff",
                  color: searchTab === key ? "var(--color-primary)" : "var(--color-text-muted)",
                  cursor: "pointer",
                }}>
                <TabIcon size={13} />
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
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 700, color: "#B91C1C", marginBottom: 8 }}>
                    <AlertTriangle size={13} /> Possible duplicate — patient already registered here
                  </div>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 12, background: "#fff",
                    borderRadius: 8, padding: "10px 14px", marginBottom: 10,
                  }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: "50%", background: "#FEE2E2", color: "#B91C1C",
                      display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                    }}><User size={16} /></div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{lookup.full_name}</div>
                      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                        UHID: {lookup.existing_uhid}{lookup.existing_branch_name ? ` · ${lookup.existing_branch_name}` : ""}
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: "#7f1d1d", lineHeight: 1.6, marginBottom: 10 }}>
                    Use their existing record instead of creating a new one — book their appointment directly.
                  </div>
                  <button type="button" className="btn-primary" style={{ fontSize: 12, padding: "6px 14px" }}
                    onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS, {
                      state: { prefillQuery: lookup.existing_uhid || lookup.full_name },
                    })}>
                    Book Appointment →
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
                      display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                    }}><User size={16} /></div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{lookup.full_name}</div>
                      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
                        {lookup.date_of_birth
                          ? `Born ${lookup.date_of_birth}${formatAgeYM(lookup.date_of_birth) ? ` · ${formatAgeYM(lookup.date_of_birth)}` : ""}`
                          : "Registered at another Atomwalk hospital"}
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: "#075985", lineHeight: 1.6, marginBottom: 10 }}>
                    Not registered at this hospital yet. If this is the same person, use their details — avoids a disconnected duplicate.
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

              {/* Family members — a patient record shouldn't depend on having */}
              {!proceeded && mobileChecked && lookup.exists_in_network && (
                <div style={{
                  background: "#FAF5FF", border: "1px solid #E9D5FF", borderRadius: 8,
                  padding: "14px 16px", marginTop: 10,
                }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#6B21A8", marginBottom: 2 }}>
                    Family Members
                  </div>
                  {(lookup.family_members || []).length > 0 && (
                    <div style={{ fontSize: 11.5, color: "#7E22CE", marginBottom: 8 }}>
                      Already known from {lookup.full_name}'s record — no need to re-type their details.
                    </div>
                  )}
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
                              {m.relationship}{m.date_of_birth ? ` · DOB ${m.date_of_birth}${formatAgeYM(m.date_of_birth) ? ` (${formatAgeYM(m.date_of_birth)})` : ""}` : ""}
                            </div>
                          </div>
                          {m.already_registered_here ? (
                            <button type="button" className="btn-outline" style={{ fontSize: 11, padding: "5px 12px" }}
                              onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS, {
                                state: { prefillQuery: m.full_name },
                              })}>
                              Already here — Book Appointment
                            </button>
                          ) : (
                            <button type="button" className="btn-primary" style={{ fontSize: 11, padding: "5px 12px" }}
                              onClick={() => setQuickRegisterMember(m)}>
                              Add at this hospital →
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
                  <User size={28} style={{ marginBottom: 8 }} />
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
            <FieldGroup label="Patient Name, UHID, AWPID, or Mobile">
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ flex: 1, position: "relative" }}>
                  <Input value={nameQuery}
                    onChange={e => { setNameQuery(e.target.value); setNamePage(1); }}
                    onKeyDown={e => e.key === "Enter" && (e.preventDefault(), setNamePage(1), runNameSearch(nameQuery.trim(), 1, namePageSize))}
                    placeholder="Start typing a name, UHID, AWPID, or mobile…" autoFocus />
                  {nameSearchLoading && (
                    <span style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", fontSize: 11, color: "var(--color-text-muted)" }}>
                      Searching…
                    </span>
                  )}
                </div>
                <button type="button" className="btn-primary" style={{ padding: "0 20px" }}
                  onClick={() => { setNamePage(1); runNameSearch(nameQuery.trim(), 1, namePageSize); }}
                  disabled={nameQuery.trim().length === 1 || nameSearchLoading}>
                  Search
                </button>
              </div>
            </FieldGroup>
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
          <SectionCard title="Personal Information" icon={Contact} bgColor="#F0FDF4" color="#15803D">
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

          {/* ── Birth History (pediatric-only) ── shown only for a dependent */}
          {showBirthHistory && (
            <SectionCard title="Birth History" subtitle="Optional — fill in if you have the details on hand. The pediatrician can also add this at consultation."
              icon={Baby} bgColor="#FFF7ED" color="#C2410C">
              <TwoCol>
                <FieldGroup label="Gestational Age (weeks)">
                  <Input type="number" value={birthHistory.gestational_age_weeks} onChange={setBh("gestational_age_weeks")} placeholder="e.g. 39" />
                </FieldGroup>
                <FieldGroup label="Birth Weight (kg)">
                  <Input type="number" step="0.01" value={birthHistory.birth_weight_kg} onChange={setBh("birth_weight_kg")} placeholder="e.g. 3.2" />
                </FieldGroup>
              </TwoCol>
              <TwoCol>
                <FieldGroup label="Delivery Mode">
                  <FSelect value={birthHistory.delivery_mode} onChange={setBh("delivery_mode")}>
                    <option value="">Select</option>
                    <option value="normal">Normal Vaginal Delivery</option>
                    <option value="c_section">C-Section</option>
                    <option value="assisted">Assisted (Forceps/Vacuum)</option>
                    <option value="unknown">Unknown</option>
                  </FSelect>
                </FieldGroup>
                <FieldGroup label="NICU Admission">
                  <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, marginTop: 6 }}>
                    <input type="checkbox" checked={birthHistory.nicu_admission} onChange={setBh("nicu_admission")} />
                    Was admitted to NICU
                  </label>
                  {birthHistory.nicu_admission && (
                    <Input type="number" style={{ marginTop: 6 }} value={birthHistory.nicu_days}
                      onChange={setBh("nicu_days")} placeholder="Days in NICU" />
                  )}
                </FieldGroup>
              </TwoCol>
              <FieldGroup label="Birth Complications">
                <textarea className="form-input" rows={2} value={birthHistory.birth_complications}
                  onChange={setBh("birth_complications")} placeholder="e.g. jaundice, birth asphyxia (optional)"
                  style={{ resize: "vertical" }} />
              </FieldGroup>
            </SectionCard>
          )}

          {/* ── 2. Contact Information ── */}
          <SectionCard title="Contact Information" icon={Phone} bgColor="#F0FDF4" color="#15803D">
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
                <Input type="tel" inputMode="numeric" maxLength={10} value={form.mobile} onChange={set("mobile")}
                  placeholder={form.is_dependent ? "Only if they have their own phone" : "98xxxxxxxx"}
                  error={errors.mobile} required={!form.is_dependent} />
              </FieldGroup>
              <FieldGroup label="Alternate Mobile">
                <Input type="tel" inputMode="numeric" maxLength={10} value={form.alternate_mobile} onChange={set("alternate_mobile")}
                  placeholder="Optional" error={errors.alternate_mobile} />
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
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 700, color: "#92400E", marginBottom: 14 }}>
                <Siren size={14} /> Emergency Contact <span style={{ fontWeight: 400, color: "#b45309" }}>(optional)</span>
              </div>
              <ThreeCol>
                <FieldGroup label="Name">
                  <Input value={form.emergency_name} onChange={set("emergency_name")}
                    placeholder="Contact name" error={errors.emergency_name} />
                </FieldGroup>
                <FieldGroup label="Phone">
                  <Input type="tel" inputMode="numeric" maxLength={10} value={form.emergency_phone} onChange={set("emergency_phone")}
                    placeholder="98xxxxxxxx" error={errors.emergency_phone} />
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
          <SectionCard title="Registration Branch" icon={Building2} bgColor="#EDE9FF" color="#5B52EE">
            <TwoCol>
              <FieldGroup label="Register at Branch *">
                <FSelect value={form.branch_id} onChange={set("branch_id")}
                  error={errors.branch_id} required>
                  <option value="">Select branch</option>
                  {branchList.map(b => (
                    <option key={b.branch_id} value={b.branch_id}>{b.name}</option>
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

        {/* Shared browse/search results list — visible under BOTH tabs, so */}
        {nameResults != null && (
          <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px dashed var(--color-border)" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.04em", margin: "4px 0 8px" }}>
              {nameIsBrowse
                ? `Recently registered at this hospital${namePagination ? ` (${namePagination.total_count})` : ""}`
                : `${namePagination ? namePagination.total_count : nameResults.length} match${(namePagination ? namePagination.total_count : nameResults.length) === 1 ? "" : "es"} for "${nameQuery}"`}
            </div>

            {nameResults.length === 0 ? (
              <div style={{
                textAlign: "center", padding: "28px 16px", color: "var(--color-text-muted)",
                background: "#F8FAFC", border: "1px dashed var(--color-border)", borderRadius: 10,
              }}>
                <Search size={24} style={{ marginBottom: 6 }} />
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>
                  {nameIsBrowse ? "No patients registered here yet" : `No patients matched "${nameQuery}"`}
                </div>
                <div style={{ fontSize: 12 }}>
                  {nameIsBrowse ? "New registrations will show up here." : "Try Mobile Number, or create a new record below."}
                </div>
              </div>
            ) : (
              <div className="fdc-panel" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ display: "grid", gap: 8, padding: 10, maxHeight: 420, overflowY: "auto" }}>
                  {nameResults.map(p => {
                    const age = formatAgeYM(p.date_of_birth) || null;
                    const initials = (p.full_name || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();
                    return (
                      <div key={p.patient_id} style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
                        background: "#fff", border: "1px solid var(--color-border)", borderRadius: 10,
                        padding: "12px 16px", transition: "box-shadow 0.15s, border-color 0.15s",
                      }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--color-primary)"; e.currentTarget.style.boxShadow = "0 2px 10px rgba(0,0,0,0.06)"; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--color-border)"; e.currentTarget.style.boxShadow = "none"; }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                          <div style={{
                            width: 38, height: 38, borderRadius: "50%", flexShrink: 0,
                            background: "#EDE9FF", color: "#5B52EE",
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 13, fontWeight: 700,
                          }}>{initials}</div>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                              <span style={{ fontWeight: 700, fontSize: 13.5 }}>{p.full_name}</span>
                              {p.is_dependent && (
                                <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 10, background: "#F1E9FA", color: "#6B3FA0" }}>
                                  Dependent{p.guardian_relation ? ` · ${p.guardian_relation}` : ""}
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 2, display: "flex", gap: 8, flexWrap: "wrap" }}>
                              <span>UHID {p.uhid}</span>
                              {p.mobile && <span>· {p.mobile}</span>}
                              {(age != null || p.gender) && <span>· {[age, p.gender].filter(Boolean).join(" ")}</span>}
                              {p.branch_name && <span>· {p.branch_name}</span>}
                            </div>
                          </div>
                        </div>
                        <button type="button" className="btn-outline" style={{ fontSize: 12, padding: "6px 14px", flexShrink: 0 }}
                          onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS, { state: { patient: p } })}>
                          Book Appointment →
                        </button>
                      </div>
                    );
                  })}
                </div>
                <PaginationControls
                  pagination={namePagination}
                  page={namePage} pageSize={namePageSize}
                  onPageChange={setNamePage} onPageSizeChange={setNamePageSize}
                />
              </div>
            )}
          </div>
        )}
    </>
  );

  if (embedded) return content;
  return <PageShell title="Register New Patient">{content}</PageShell>;
}

export default function RegisterPatientPage() {
  return (
    <AppShell>
      <RegisterPatientPageContent />
    </AppShell>
  );
}
