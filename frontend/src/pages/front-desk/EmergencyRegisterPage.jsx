/**
 * pages/front-desk/EmergencyRegisterPage.jsx
 * -----------------------------------------------
 * Minimal/provisional patient registration for a patient who arrives with
 * no identity, no consent, sometimes no name — step 3 ("Emergency Reg.")
 * of the approved intake mockup. Markup/styling here follow that mockup
 * (see intake-workspace.css) — the mockup's step 3 shows a read-only field
 * summary, but this has to actually collect the data, so the same
 * `.field`/`.val`-shaped boxes are real inputs instead.
 *
 * Deliberately a SEPARATE page from RegisterPatientPage / QuickRegisterModal:
 * this is the only registration path that requires neither a mobile number
 * nor a guardian (see apps/patients/serializers.py::PatientEmergencyRegisterSerializer
 * and docs/PENDING_IMPROVEMENTS.md item 1).
 *
 * Consent is NOT collected here — it's explicitly deferred, with a reason
 * recorded, on the emergency-treatment legal basis already used elsewhere
 * in this codebase (see apps/ipd/models.py AdmissionDeposit docstring).
 *
 * A doctor's referral is still required for actual IPD admission — front
 * desk cannot originate one (see AdmissionsPage.jsx) — so after
 * registering, this page only offers two next steps: close the visit as
 * an emergency OPD encounter, or hand off and wait for a doctor.
 *
 * Exports both a standalone routed page (default export, used directly at
 * ROUTES.FRONT_DESK.REGISTER_EMERGENCY — kept working for backward
 * compatibility/deep links) and a bare content component
 * (`EmergencyRegisterPageContent`) that the Patient Intake hub
 * (PatientIntakePage.jsx) embeds as one of its internal tabs — same
 * component, same API calls, no duplicated implementation. `embedded`
 * just suppresses this page's own PageShell, since the hub already
 * supplies an equivalent page title and tab bar.
 */
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useAuth } from "../../hooks/useAuth";
import { useApi } from "../../hooks/useApi";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES } from "../../config/routes.config";
import { sanitizeMobileInput, isValidMobile } from "../../utils/validation";

const ARRIVAL_CHANNELS = [
  { value: "ambulance", label: "Ambulance" },
  { value: "brought_in", label: "Brought in" },
  { value: "police_case", label: "Police case" },
  { value: "walk_in_unresponsive", label: "Walk-in, unresponsive" },
  { value: "other", label: "Other" },
];

function CheckIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <path d="M4 12l5 5L20 6" />
    </svg>
  );
}

export function EmergencyRegisterPageContent({ embedded = false } = {}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const { toastSuccess, toastApiError } = useToast();
  const departmentHint = location.state?.departmentHint || "";

  const { data: branchList } = useApi(API_ENDPOINTS.ORG.BRANCHES);
  const branchId = user?.branch_id || branchList?.[0]?.id || "";

  const [identityKnown, setIdentityKnown] = useState(false);
  const [fullName, setFullName] = useState("");
  const [placeholderLabel, setPlaceholderLabel] = useState("");
  const [gender, setGender] = useState("");
  const [dob, setDob] = useState("");
  const [isMlc, setIsMlc] = useState(false);
  const [arrivalChannel, setArrivalChannel] = useState("");
  const [mobile, setMobile] = useState("");
  const [guardianName, setGuardianName] = useState("");
  const [guardianMobile, setGuardianMobile] = useState("");
  const [consentReason, setConsentReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [registered, setRegistered] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (identityKnown && !fullName.trim()) {
      setError("Enter the patient's name, or switch to “identity not known.”");
      return;
    }
    if (!identityKnown && !placeholderLabel.trim()) {
      setError('Enter a placeholder label (e.g. "Unknown Male, approx. 30yrs").');
      return;
    }
    if (mobile && !isValidMobile(mobile)) {
      setError("Mobile number must be a valid 10-digit number, or left blank.");
      return;
    }
    if (guardianMobile && !isValidMobile(guardianMobile)) {
      setError("Guardian/attendant mobile must be a valid 10-digit number, or left blank.");
      return;
    }

    const payload = {
      branch_id: branchId,
      ...(identityKnown ? { full_name: fullName.trim() } : { placeholder_label: placeholderLabel.trim() }),
      gender: gender || undefined,
      date_of_birth: dob || undefined,
      is_mlc: isMlc,
      arrival_channel: arrivalChannel || undefined,
      mobile: mobile ? sanitizeMobileInput(mobile) : undefined,
      guardian_name: guardianName.trim() || undefined,
      guardian_mobile: guardianMobile ? sanitizeMobileInput(guardianMobile) : undefined,
      consent_deferred_reason: consentReason.trim() || undefined,
    };

    setSaving(true);
    try {
      const { data: res } = await apiClient.post(API_ENDPOINTS.PATIENTS.REGISTER_EMERGENCY, payload);
      const patient = res?.data || res;
      toastSuccess(`${patient.full_name} registered — UHID ${patient.uhid} (provisional).`);
      setRegistered(patient);
    } catch (err) {
      toastApiError(err, "Could not register patient.");
      setError(err?.message || "Could not register patient.");
    } finally {
      setSaving(false);
    }
  }

  if (registered) {
    const content = (
      <div className="intake-workspace">
        <div className="intake-grid" style={{ marginTop: embedded ? 0 : 14 }}>
          <div className="panel">
            <div className="panel-head">
              <h2>{registered.full_name}</h2>
              <span className="chip chip-shared">registered — provisional identity</span>
            </div>
            <div className="section">
              <div className="fine">
                Consent deferred, not skipped — reason on file. A doctor's referral is still required
                for admission — front desk can't originate one. If this turns out not to need
                admission, close it out as an emergency OPD encounter instead.
              </div>
            </div>
            <div className="btnbar">
              <button
                className="secondary-btn"
                onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_OPD, {
                  state: {
                    patient: { uuid: registered.id, awpid: registered.awpid, full_name: registered.full_name },
                    justRegistered: true,
                    appointmentType: "emergency",
                  },
                })}
              >
                Close as emergency OPD encounter
              </button>
              <button className="primary-btn ipd" onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_REFERRALS)}>
                Done — awaiting doctor referral →
              </button>
              <button className="secondary-btn" onClick={() => setRegistered(null)}>
                Register another patient
              </button>
            </div>
          </div>
          <aside className="side-card">
            <h3>Quick facts</h3>
            <div className="idline"><span>UHID</span><span className="iw-mono">{registered.uhid}</span></div>
            {registered.awpid && <div className="idline"><span>AWPID</span><span className="iw-mono">{registered.awpid}</span></div>}
          </aside>
        </div>
      </div>
    );
    if (embedded) return content;
    return <PageShell title="Emergency Registration">{content}</PageShell>;
  }

  const content = (
    <div className="intake-workspace">
      <form onSubmit={submit} className="panel" style={{ marginTop: embedded ? 0 : 14 }}>
        <div className="panel-head">
          <h2>Emergency registration — provisional identity</h2>
          {isMlc ? <span className="chip chip-critical">MLC</span> : <span className="chip chip-new">new</span>}
        </div>

        {!identityKnown && (
          <div className="id-banner">
            Identity unknown or unconfirmed — minimum fields only, the rest fills in once identified.
          </div>
        )}

        <div className="section">
          {departmentHint && (
            <div className="fine">Routed from Triage — {departmentHint} had no doctor free today.</div>
          )}
          <div className="choice-row">
            <div className={"choice-card" + (identityKnown ? " picked" : "")} onClick={() => setIdentityKnown(true)}>
              <b>Yes — I have a name</b>
              <span>Identity known and can be entered now</span>
            </div>
            <div className={"choice-card" + (!identityKnown ? " picked" : "")} onClick={() => setIdentityKnown(false)}>
              <b>No — unidentified</b>
              <span>Register with a placeholder label instead</span>
            </div>
          </div>
        </div>

        <div className="section">
          <div className="fgrid">
            {identityKnown ? (
              <div className="field" style={{ gridColumn: "span 2" }}>
                <label>Full name *</label>
                <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus />
              </div>
            ) : (
              <div className="field" style={{ gridColumn: "span 2" }}>
                <label>Placeholder label *</label>
                <input value={placeholderLabel} onChange={(e) => setPlaceholderLabel(e.target.value)}
                  placeholder='e.g. "Unknown Male, approx. 30yrs"' autoFocus />
              </div>
            )}
            <div className="field">
              <label>Gender</label>
              <select value={gender} onChange={(e) => setGender(e.target.value)}>
                <option value="">—</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
                <option value="prefer_not_to_say">Prefer not to say</option>
              </select>
            </div>
            <div className="field">
              <label>Date of birth (if known)</label>
              <input type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
            </div>
            <div className="field">
              <label>Arrival channel</label>
              <select value={arrivalChannel} onChange={(e) => setArrivalChannel(e.target.value)}>
                <option value="">—</option>
                {ARRIVAL_CHANNELS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Mobile (if known)</label>
              <input value={mobile} maxLength={10} onChange={(e) => setMobile(sanitizeMobileInput(e.target.value))}
                placeholder="10-digit mobile" />
            </div>
            <div className="field">
              <label>Guardian / attendant name</label>
              <input value={guardianName} onChange={(e) => setGuardianName(e.target.value)} />
            </div>
            <div className="field">
              <label>Guardian / attendant mobile</label>
              <input value={guardianMobile} maxLength={10} onChange={(e) => setGuardianMobile(sanitizeMobileInput(e.target.value))}
                placeholder="10-digit mobile" />
            </div>
          </div>
        </div>

        <div className="section">
          <label className="toggle-row">
            <span className={"fakecheck" + (isMlc ? " on crit" : "")} onClick={(e) => { e.preventDefault(); setIsMlc((v) => !v); }}>
              {isMlc && <CheckIcon />}
            </span>
            <input type="checkbox" checked={isMlc} onChange={(e) => setIsMlc(e.target.checked)} style={{ display: "none" }} />
            Is MLC (medico-legal case)
          </label>
          <div className="toggle-row" style={{ cursor: "default" }}>
            <span className="fakecheck on"><CheckIcon /></span>
            Consent deferred — logged under emergency-treatment doctrine, not skipped silently
          </div>
          <div className="field" style={{ maxWidth: 420 }}>
            <label>Consent deferral reason (optional)</label>
            <input value={consentReason} onChange={(e) => setConsentReason(e.target.value)}
              placeholder="Defaults to the standard emergency-treatment legal basis if left blank" />
          </div>
        </div>

        {error && (
          <div className="section" style={{ paddingTop: 0, paddingBottom: 0 }}>
            <div className="fine" style={{ color: "var(--iw-critical)" }}>{error}</div>
          </div>
        )}

        <div className="btnbar">
          <button className="primary-btn ipd" disabled={saving} type="submit">
            {saving ? "Registering…" : "Register Emergency Patient →"}
          </button>
        </div>
      </form>
    </div>
  );

  if (embedded) return content;
  return <PageShell title="Emergency Registration">{content}</PageShell>;
}

export default function EmergencyRegisterPage() {
  return (
    <AppShell>
      <EmergencyRegisterPageContent />
    </AppShell>
  );
}
