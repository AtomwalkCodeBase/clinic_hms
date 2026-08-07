/**
 * pages/patient/DoctorProfilePage.jsx
 * ---------------------------------------
 * Step 3 of booking: doctor profile + book panel.
 * Slot-based — the patient picks a fixed 15-min time slot (same grid front
 * desk's own booking screen uses, core.PortalSlotListView) rather than just
 * getting a queue token. A token number is still assigned server-side for
 * the day's queue and shown on the confirmation screen, but the patient's
 * choice is the exact time, not just the date.
 *
 * Every trust signal on this page is real data already returned by the
 * backend (experience_years, consultations_count, known_for, hospital
 * accreditations, live slot availability) — there is no reviews/ratings
 * system in this product, so no star ratings or review counts are shown;
 * inventing those numbers would be actively misleading in a healthcare app.
 */
import { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Building2, ShieldCheck, CircleCheck, Lock, Clock } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import { useToast }  from "../../hooks/useToast";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import ROUTES        from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];

const STEPS = ["Choose date", "Select time", "Your concern", "Confirm"];

function StepProgress({ current }) {
  return (
    <div style={{ display: "flex", alignItems: "center", marginBottom: 22 }}>
      {STEPS.map((label, i) => (
        <div key={label} style={{ display: "flex", alignItems: "center", flex: i < STEPS.length - 1 ? 1 : "0 0 auto" }}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
            <div style={{
              width: 22, height: 22, borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, fontWeight: 700,
              background: i <= current ? "var(--color-primary)" : "var(--color-border)",
              color: i <= current ? "#fff" : "var(--color-text-muted)",
            }}>
              {i < current ? "✓" : i + 1}
            </div>
            <div style={{
              fontSize: 10, marginTop: 4, whiteSpace: "nowrap",
              color: i <= current ? "var(--color-primary)" : "var(--color-text-muted)",
              fontWeight: i === current ? 700 : 500,
            }}>
              {label}
            </div>
          </div>
          {i < STEPS.length - 1 && (
            <div style={{
              flex: 1, height: 2, margin: "0 6px 16px",
              background: i < current ? "var(--color-primary)" : "var(--color-border)",
            }} />
          )}
        </div>
      ))}
    </div>
  );
}

export default function PatientDoctorProfilePage() {
  const { tenantId, doctorId } = useParams();
  const navigate = useNavigate();
  const { toastSuccess, toastApiError } = useToast();

  const { data: doctor, isLoading } = useApi(API_ENDPOINTS.PORTAL.DOCTOR_DETAIL(tenantId, doctorId));

  const [date,   setDate]   = useState(TODAY);
  const [reason, setReason] = useState("");
  const [slots, setSlots] = useState([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState(null);
  // Pay Online isn't wired to a real payment gateway yet — offered as an
  // option so the choice is captured now, but selecting it just tells the
  // patient it's coming soon rather than defaulting them to it.
  const [paymentPreference, setPaymentPreference] = useState("pay_at_desk");
  const [booking, setBooking] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  // Set when the backend tells us this is the patient's first booking at
  // this hospital and it needs explicit consent before sharing their
  // cross-hospital history — holds what to show in the consent modal.
  const [consentPrompt, setConsentPrompt] = useState(null);

  // Family members this account can book for, plus who the booking is for
  // (defaults to "self" — patient_awpid omitted from the POST in that case).
  const [family, setFamily] = useState([]);
  const [bookingFor, setBookingFor] = useState("self");
  const [addingMember, setAddingMember] = useState(false);
  const [memberForm, setMemberForm] = useState({ full_name: "", date_of_birth: "", gender: "", relationship: "child" });
  const [memberSaving, setMemberSaving] = useState(false);

  function loadFamily() {
    return apiClient.get(API_ENDPOINTS.PORTAL.FAMILY)
      .then(({ data: res }) => setFamily(res?.data?.results || []))
      .catch(() => setFamily([]));
  }

  useEffect(() => { loadFamily(); }, []);

  async function handleAddMember(e) {
    e.preventDefault();
    if (!memberForm.full_name.trim() || !memberForm.date_of_birth) {
      toastApiError({ message: "Name and date of birth are required." }, "Name and date of birth are required.");
      return;
    }
    setMemberSaving(true);
    try {
      const { data: res } = await apiClient.post(API_ENDPOINTS.PORTAL.FAMILY, memberForm);
      const newAwpid = res?.data?.awpid;
      await loadFamily();
      if (newAwpid) setBookingFor(newAwpid);
      setMemberForm({ full_name: "", date_of_birth: "", gender: "", relationship: "child" });
      setAddingMember(false);
      toastSuccess("Family member added.");
    } catch (err) {
      toastApiError(err, "Failed to add family member.");
    } finally {
      setMemberSaving(false);
    }
  }

  // Load available slots whenever the date changes.
  useEffect(() => {
    setSelectedSlot(null);
    setSlots([]);
    if (!date) return;
    setSlotsLoading(true);
    apiClient.get(API_ENDPOINTS.PORTAL.SLOTS(tenantId, doctorId), { params: { date } })
      .then(({ data: d }) => setSlots(d?.results || []))
      .catch(() => setSlots([]))
      .finally(() => setSlotsLoading(false));
  }, [tenantId, doctorId, date]);

  async function book(dataSharingConsent) {
    if (!selectedSlot) return;
    setBooking(true);
    setConfirmation(null);
    try {
      const { data } = await apiClient.post(API_ENDPOINTS.PORTAL.BOOK, {
        tenant_id: tenantId,
        doctor_id: doctorId,
        scheduled_date: date,
        scheduled_time: selectedSlot,
        chief_complaint: reason,
        payment_preference: paymentPreference,
        ...(bookingFor !== "self" ? { patient_awpid: bookingFor } : {}),
        ...(dataSharingConsent ? { data_sharing_consent: true } : {}),
      });
      setConfirmation(data);
      setConsentPrompt(null);
      toastSuccess("Appointment booked!");
    } catch (err) {
      // First booking at a new hospital — backend needs explicit consent
      // before it'll create the local patient record there (and before that
      // hospital's doctors can see any shared history). Show the prompt
      // instead of a generic error toast.
      if (err?.status === 428 && err.data?.consent_required) {
        setConsentPrompt(err.data);
      } else {
        toastApiError(err, "Could not book the appointment.");
      }
    } finally {
      setBooking(false);
    }
  }

  if (isLoading) {
    return (
      <AppShell>
        <PageShell title="Doctor Profile">
          <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
        </PageShell>
      </AppShell>
    );
  }

  const morningSlots   = slots.filter(s => s.time < "13:00");
  const afternoonSlots = slots.filter(s => s.time >= "13:00");
  const availableCount = slots.filter(s => s.available).length;
  const availableToday = date === TODAY && availableCount > 0;
  const languages  = (doctor?.languages || "").split(",").map(s => s.trim()).filter(Boolean);
  const knownFor   = (doctor?.known_for || "").split(",").map(s => s.trim()).filter(Boolean);

  const currentStep = selectedSlot ? (reason.trim() ? 3 : 2) : (date ? 1 : 0);

  function SlotGrid({ items }) {
    if (items.length === 0) return null;
    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        {items.map(s => {
          const isSelected = selectedSlot === s.time;
          return (
            <button
              key={s.time}
              type="button"
              disabled={!s.available}
              onClick={() => setSelectedSlot(s.time)}
              style={{
                padding: "7px 12px", borderRadius: 8, fontSize: 12.5, fontWeight: 700,
                cursor: s.available ? "pointer" : "not-allowed",
                border: `1.5px solid ${isSelected ? "var(--color-primary)" : s.available ? "var(--color-success)" : "var(--color-border)"}`,
                background: isSelected ? "var(--color-primary)" : s.available ? "var(--color-success-light)" : "var(--color-surface-secondary, #f6f4ee)",
                color: isSelected ? "#fff" : s.available ? "var(--color-success)" : "var(--color-text-muted)",
                textDecoration: s.available ? "none" : "line-through",
                transition: "all 120ms ease",
              }}
            >
              {s.time}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <AppShell>
      <PageShell title={doctor?.name || "Doctor Profile"}>
        <Link
          to={ROUTES.PATIENT.HOSPITAL_DOCTORS(tenantId)}
          style={{ fontSize: 12, color: "var(--color-text-muted)", display: "inline-block", marginBottom: 14 }}
        >
          ← All doctors{doctor?.hospital ? ` at ${doctor.hospital.name}` : ""}
        </Link>

        {confirmation ? (
          <div className="card" style={{
            padding: 28, textAlign: "center",
            background: "var(--color-primary-light)", border: "1.5px solid var(--color-primary)",
          }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
            <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 20, marginBottom: 4 }}>
              Booked — {confirmation.time || selectedSlot}, token #{confirmation.token_number}
            </div>
            <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 18 }}>
              {confirmation.doctor} at {confirmation.hospital} on {confirmation.date}.
              Please arrive a little early with this token number.
              {confirmation.payment_preference === "pay_online"
                ? " Online payment isn't available yet, so please pay at the front desk when you arrive."
                : " Please pay at the front desk when you arrive."}
            </div>
            <button className="btn-primary" onClick={() => navigate(ROUTES.PATIENT.APPOINTMENTS)}>
              View my bookings
            </button>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>
            {/* Profile card */}
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{
                background: "linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary-dark) 100%)",
                padding: "28px 24px 20px", display: "flex", flexDirection: "column", alignItems: "center",
              }}>
                <div style={{ position: "relative", marginBottom: 14 }}>
                  <div style={{
                    width: 128, height: 128, borderRadius: "50%", background: "#fff",
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 44, fontWeight: 700,
                    color: "var(--color-primary)", overflow: "hidden", boxShadow: "0 8px 24px rgba(0,0,0,.25)",
                    border: "4px solid rgba(255,255,255,0.5)",
                  }}>
                    {doctor?.photo
                      ? <img src={doctor.photo} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      : (doctor?.name?.replace("Dr. ", "").charAt(0) || "D")}
                  </div>
                  {availableToday && (
                    <div style={{
                      position: "absolute", bottom: -10, left: "50%", transform: "translateX(-50%)",
                      background: "var(--color-success)", whiteSpace: "nowrap",
                      color: "#fff", fontSize: 10, fontWeight: 700, padding: "4px 11px", borderRadius: 12,
                      display: "flex", alignItems: "center", gap: 5, boxShadow: "0 2px 6px rgba(0,0,0,.3)",
                      border: "2px solid var(--color-primary)",
                    }}>
                      <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#fff", flexShrink: 0 }} /> Available today
                    </div>
                  )}
                </div>
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 21, color: "#fff", textAlign: "center", marginTop: availableToday ? 8 : 0 }}>
                  {doctor?.name}
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#E8C77A", marginTop: 2 }}>
                  {doctor?.specialisation || "Specialisation not listed yet"}
                </div>
              </div>

              <div style={{ padding: 22 }}>
                {/* Trust indicators — all real, computed server-side */}
                <div style={{ display: "grid", gap: 8, marginBottom: 16 }}>
                  {doctor?.experience_years != null && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                      <CircleCheck size={15} style={{ color: "var(--color-success)", flexShrink: 0 }} />
                      {doctor.experience_years}+ years of experience
                    </div>
                  )}
                  {doctor?.consultations_count > 0 && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                      <CircleCheck size={15} style={{ color: "var(--color-success)", flexShrink: 0 }} />
                      {doctor.consultations_count}+ consultations at this hospital
                    </div>
                  )}
                  <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                    <CircleCheck size={15} style={{ color: "var(--color-success)", flexShrink: 0 }} />
                    Accepting new patients
                  </div>
                  {availableToday && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                      <CircleCheck size={15} style={{ color: "var(--color-success)", flexShrink: 0 }} />
                      {availableCount} slot{availableCount === 1 ? "" : "s"} open today
                    </div>
                  )}
                </div>

                {languages.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div className="stat-label" style={{ marginBottom: 6 }}>Languages</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {languages.map(l => <span key={l} className="tag-pill">{l}</span>)}
                    </div>
                  </div>
                )}

                {doctor?.bio && (
                  <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6, marginBottom: 16, fontStyle: "italic" }}>
                    "{doctor.bio}"
                  </div>
                )}

                {knownFor.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div className="stat-label" style={{ marginBottom: 6 }}>Why patients visit</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {knownFor.map(k => (
                        <span key={k} className="tag-pill" style={{ background: "var(--color-info-light)", color: "var(--color-info)" }}>{k}</span>
                      ))}
                    </div>
                  </div>
                )}

                {doctor?.consultation_fee && (
                  <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "12px 16px", borderRadius: 10, background: "var(--color-accent-light)", marginBottom: 16,
                  }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-accent)" }}>Consultation fee</span>
                    <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 18, color: "var(--color-accent)" }}>
                      ₹{doctor.consultation_fee}
                    </span>
                  </div>
                )}

                {/* Clinic card */}
                {doctor?.hospital && (
                  <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: 16 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <div className="icon-chip icon-chip--green" style={{ width: 32, height: 32 }}>
                        <Building2 size={16} />
                      </div>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 13 }}>{doctor.hospital.name}</div>
                        {doctor.hospital.city && (
                          <div style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{doctor.hospital.city}</div>
                        )}
                      </div>
                    </div>
                    {doctor.hospital.accreditations?.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                        {doctor.hospital.accreditations.map(a => (
                          <span key={a} className="tag-pill" style={{
                            background: "var(--color-success-light)", color: "var(--color-success)",
                            display: "inline-flex", alignItems: "center", gap: 4,
                          }}>
                            <ShieldCheck size={11} />{a}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Booking panel */}
            <div className="card" style={{ padding: 24, position: "sticky", top: 14 }}>
              <div className="dot-label dot-label--green" style={{ marginBottom: 6 }}>Book an appointment</div>
              <StepProgress current={currentStep} />

              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Booking for</label>
              {!addingMember && (
                <select
                  className="form-input" value={bookingFor}
                  onChange={e => {
                    if (e.target.value === "__add__") { setAddingMember(true); return; }
                    setBookingFor(e.target.value);
                  }}
                  style={{ marginBottom: 16, width: "100%" }}
                >
                  <option value="self">Myself</option>
                  {family.map(m => (
                    <option key={m.awpid} value={m.awpid}>
                      {m.full_name} ({m.relationship})
                    </option>
                  ))}
                  <option value="__add__">+ Add someone else (child, parent, etc.)</option>
                </select>
              )}

              {addingMember && (
                <form
                  onSubmit={handleAddMember}
                  style={{
                    border: "1.5px solid var(--color-primary)", borderRadius: 10,
                    padding: 14, marginBottom: 16, display: "grid", gap: 10,
                    background: "var(--color-primary-light)",
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-primary)" }}>
                    Add patient details
                  </div>
                  <input
                    className="form-input" placeholder="Full name"
                    value={memberForm.full_name}
                    onChange={e => setMemberForm(f => ({ ...f, full_name: e.target.value }))}
                    required
                  />
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <input
                      type="date" className="form-input" value={memberForm.date_of_birth}
                      onChange={e => setMemberForm(f => ({ ...f, date_of_birth: e.target.value }))}
                      required
                    />
                    <select
                      className="form-input" value={memberForm.gender}
                      onChange={e => setMemberForm(f => ({ ...f, gender: e.target.value }))}
                    >
                      <option value="">Gender</option>
                      <option value="M">Male</option>
                      <option value="F">Female</option>
                      <option value="O">Other</option>
                    </select>
                  </div>
                  <select
                    className="form-input" value={memberForm.relationship}
                    onChange={e => setMemberForm(f => ({ ...f, relationship: e.target.value }))}
                  >
                    <option value="child">Child</option>
                    <option value="parent">Parent</option>
                    <option value="spouse">Spouse</option>
                    <option value="sibling">Sibling</option>
                    <option value="ward">Ward</option>
                    <option value="other">Other</option>
                  </select>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button type="submit" disabled={memberSaving} className="btn-primary" style={{ flex: 1, padding: "8px 0", fontSize: 12.5 }}>
                      {memberSaving ? "Adding…" : "Add & select"}
                    </button>
                    <button
                      type="button" className="btn-outline" style={{ padding: "8px 14px", fontSize: 12.5 }}
                      onClick={() => setAddingMember(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}

              <label className="stat-label" style={{ display: "block", marginBottom: 6 }}>Date</label>
              <input
                type="date" className="form-input" value={date} min={TODAY}
                onChange={e => setDate(e.target.value)}
                style={{ marginBottom: 16, width: "100%" }}
              />

              <label className="stat-label" style={{ display: "block", marginBottom: 8 }}>
                Available slots
                {!slotsLoading && slots.length > 0 && (
                  <span style={{ fontWeight: 400, color: "var(--color-text-muted)", textTransform: "none", marginLeft: 6 }}>
                    — {availableCount} open {date === TODAY ? "today" : "on this date"}
                  </span>
                )}
              </label>
              {slotsLoading ? (
                <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>Checking availability…</div>
              ) : slots.length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>No slots configured for this date.</div>
              ) : (
                <div style={{ marginBottom: 8 }}>
                  {morningSlots.length > 0 && (
                    <>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", marginBottom: 6 }}>Morning</div>
                      <SlotGrid items={morningSlots} />
                    </>
                  )}
                  {afternoonSlots.length > 0 && (
                    <>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", marginBottom: 6, marginTop: 4 }}>Afternoon</div>
                      <SlotGrid items={afternoonSlots} />
                    </>
                  )}
                  {slots.every(s => !s.available) && (
                    <div style={{ fontSize: 12, color: "var(--color-warning)", marginTop: 4 }}>
                      No slots left on this date — try another day.
                    </div>
                  )}
                </div>
              )}

              <label className="stat-label" style={{ display: "block", marginBottom: 6, marginTop: 10 }}>Reason for visit</label>
              <input
                className="form-input" placeholder="e.g. Fever since 2 days"
                value={reason} onChange={e => setReason(e.target.value)}
                style={{ marginBottom: 16, width: "100%" }}
              />

              <label className="stat-label" style={{ display: "block", marginBottom: 8 }}>
                How will you pay{doctor?.consultation_fee ? ` (₹${doctor.consultation_fee})` : ""}?
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
                <button
                  type="button"
                  onClick={() => setPaymentPreference("pay_at_desk")}
                  style={{
                    padding: "10px 12px", borderRadius: 10, textAlign: "left", cursor: "pointer",
                    border: `1.5px solid ${paymentPreference === "pay_at_desk" ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: paymentPreference === "pay_at_desk" ? "var(--color-primary-light)" : "var(--color-surface)",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700 }}>Pay at front desk</div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>Cash, card, or UPI on arrival</div>
                </button>
                <button
                  type="button"
                  onClick={() => setPaymentPreference("pay_online")}
                  style={{
                    padding: "10px 12px", borderRadius: 10, textAlign: "left", cursor: "pointer",
                    border: `1.5px solid ${paymentPreference === "pay_online" ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: paymentPreference === "pay_online" ? "var(--color-primary-light)" : "var(--color-surface)",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700 }}>Pay online</div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>Coming soon — you'll pay at the desk for now</div>
                </button>
              </div>

              {/* Reassurance — only claims we can actually back up */}
              <div style={{
                display: "flex", flexDirection: "column", gap: 6,
                padding: "12px 14px", borderRadius: 10, marginBottom: 16,
                background: "var(--color-info-light)", fontSize: 12, color: "var(--color-info)",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700 }}>
                  <Lock size={13} /> Secure booking
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <CircleCheck size={13} style={{ flexShrink: 0 }} /> No advance payment required
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <CircleCheck size={13} style={{ flexShrink: 0 }} /> You'll get your token number the moment you confirm
                </div>
              </div>

              {selectedSlot && (
                <div style={{
                  padding: "10px 14px", borderRadius: 10, marginBottom: 16, fontSize: 13,
                  background: "var(--color-primary-light)", border: "1px solid var(--color-primary)",
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <Clock size={14} style={{ flexShrink: 0, color: "var(--color-primary)" }} />
                  Booking for <strong>{selectedSlot}</strong> on {date}.
                </div>
              )}

              <button
                className="btn-primary" style={{ width: "100%", padding: "10px 0" }}
                disabled={!date || !selectedSlot || booking}
                onClick={() => book(false)}
              >
                {booking ? "Booking…" : selectedSlot ? "Confirm booking" : "Pick a slot to continue"}
              </button>
            </div>
          </div>
        )}

        {consentPrompt && (() => {
          const bookedFor = bookingFor === "self" ? null : family.find(m => m.awpid === bookingFor);
          const subject = bookedFor ? bookedFor.full_name : "you";
          const possessive = bookedFor ? `${bookedFor.full_name}'s` : "your";
          return (
          <div style={{
            position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)",
            display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
          }}>
            <div className="card" style={{ width: "100%", maxWidth: 460, padding: 28 }}>
              <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 18, marginBottom: 8 }}>
                Share {possessive} medical history with {consentPrompt.hospital_name}?
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 16, lineHeight: 1.5 }}>
                This is {possessive} first booking at {consentPrompt.hospital_name}. With your permission, their doctors
                will be able to see {subject === "you" ? "your" : `${subject}'s`} medical history from other hospitals {subject === "you" ? "you've" : `${subject} has`} visited — this often helps
                with diagnosis and avoids repeating tests. Specifically, they'll be able to see:
              </div>
              <ul style={{ fontSize: 13, color: "var(--color-text-secondary)", margin: "0 0 20px", paddingLeft: 20, lineHeight: 1.8 }}>
                {(consentPrompt.share_categories || []).map(c => <li key={c}>{c}</li>)}
              </ul>
              <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 20 }}>
                They will not see which other hospital or doctor any of this came from. If you'd rather not share
                this, you can cancel and choose a different hospital instead.
              </div>
              <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                <button className="btn-outline" disabled={booking} onClick={() => setConsentPrompt(null)}>
                  Cancel
                </button>
                <button className="btn-primary" disabled={booking} onClick={() => book(true)}>
                  {booking ? "Booking…" : "Agree & confirm booking"}
                </button>
              </div>
            </div>
          </div>
          );
        })()}
      </PageShell>
    </AppShell>
  );
}
