/**
 * pages/front-desk/AdmissionDetailPage.jsx
 * -------------------------------------------
 * Single-admission workspace — everything front desk needs to do with an
 * admission AFTER intake + initial bed allotment are done, closing the gap
 * flagged from the Admissions page ("anything else i wanna edit or add,
 * no place to click and update it? like discharge date or handle payments
 * and the rest"):
 *   - edit the registration fields captured at intake (attendant, payer,
 *     insurance, expected discharge date) — PATCH ipd/admissions/{id}/
 *   - move/assign/release the bed — reuses ASSIGN_BED / RELEASE_BED
 *   - record advance deposits — POST ipd/admissions/{id}/deposit/
 *   - discharge the patient once Active — POST .../discharge/
 *   - generate the IPD stay invoice (room charges × nights + deposits
 *     folded in as payments) and record further payments against it —
 *     POST .../generate-invoice/, then billing.PAYMENTS same as BillingPage
 *
 * Invoices generated here are NOT linked to the admission by a foreign key
 * (billing.Invoice only ever links to a patient) — GenerateInvoiceView
 * stamps a recognizable note instead ("IPD stay — {admission_number}"), so
 * this page finds "its" invoice(s) by filtering the patient's invoice list
 * for that exact note rather than a real relation. Good enough for a
 * front-desk workspace; not a general-purpose invoice lookup.
 */
import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useAuth }   from "../../hooks/useAuth";
import { useToast }  from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES }     from "../../config/routes.config";

const inputStyle = {
  width: "100%", boxSizing: "border-box", padding: "8px 12px", borderRadius: 8,
  fontSize: 13.5, border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
  color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "var(--color-text-muted)" };

const STATUS_BADGE = {
  requested:            "badge--neutral",
  admitted:              "badge--warning",
  active:                "badge--success",
  discharge_initiated:  "badge--warning",
  discharged:            "badge--neutral",
  cancelled:             "badge--error",
};

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString();
}
function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

// ── Registration details — inline-editable, same display/edit-swap pattern
// as platform-admin/HospitalDetailPage.jsx's OverviewTab. ───────────────────
function RegistrationCard({ admission, onSaved }) {
  const { toastSuccess, toastApiError } = useToast();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    attendant_name: admission.attendant_name || "",
    attendant_phone: admission.attendant_phone || "",
    payer_type: admission.payer_type || "self",
    insurance_provider: admission.insurance_provider || "",
    expected_discharge_date: admission.expected_discharge_date || "",
  });
  const [saving, setSaving] = useState(false);
  const locked = admission.status === "discharged" || admission.status === "cancelled";

  function set(field, value) { setForm(f => ({ ...f, [field]: value })); }
  function resetForm() {
    setForm({
      attendant_name: admission.attendant_name || "",
      attendant_phone: admission.attendant_phone || "",
      payer_type: admission.payer_type || "self",
      insurance_provider: admission.insurance_provider || "",
      expected_discharge_date: admission.expected_discharge_date || "",
    });
  }

  async function save() {
    setSaving(true);
    try {
      await apiClient.patch(API_ENDPOINTS.IPD.ADMISSION(admission.id), {
        ...form,
        expected_discharge_date: form.expected_discharge_date || null,
      });
      toastSuccess("Admission updated.");
      setEditing(false);
      onSaved();
    } catch (err) {
      toastApiError(err, "Could not update admission.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: editing ? 16 : 10 }}>
        <div className="dot-label">Registration details</div>
        {!editing && !locked && (
          <button onClick={() => setEditing(true)} className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label style={labelStyle}>Attendant / next of kin — name</label>
              <input style={inputStyle} value={form.attendant_name} onChange={e => set("attendant_name", e.target.value)} placeholder="e.g. Sunita Kumar (spouse)" />
            </div>
            <div>
              <label style={labelStyle}>Attendant phone</label>
              <input style={inputStyle} value={form.attendant_phone} onChange={e => set("attendant_phone", e.target.value)} placeholder="+91 9xxxxxxxxx" />
            </div>
            <div>
              <label style={labelStyle}>Payer type</label>
              <select style={inputStyle} value={form.payer_type} onChange={e => set("payer_type", e.target.value)}>
                <option value="self">Self Pay</option>
                <option value="insurance">Insurance</option>
                <option value="corporate">Corporate</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>Insurance provider</label>
              <input style={inputStyle} value={form.insurance_provider} onChange={e => set("insurance_provider", e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>Expected discharge date</label>
              <input style={inputStyle} type="date" value={form.expected_discharge_date || ""} onChange={e => set("expected_discharge_date", e.target.value)} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={save} disabled={saving} className="btn-primary" style={{ fontSize: 13, padding: "8px 18px" }}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button onClick={() => { setEditing(false); resetForm(); }}
              style={{ fontSize: 13, padding: "8px 18px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer" }}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, fontSize: 13.5 }}>
          <div><div className="stat-label">Attendant</div><div style={{ marginTop: 2 }}>{admission.attendant_name || "—"}</div></div>
          <div><div className="stat-label">Attendant phone</div><div style={{ marginTop: 2 }}>{admission.attendant_phone || "—"}</div></div>
          <div><div className="stat-label">Payer type</div><div style={{ marginTop: 2, textTransform: "capitalize" }}>{admission.payer_type || "—"}</div></div>
          <div><div className="stat-label">Insurance provider</div><div style={{ marginTop: 2 }}>{admission.insurance_provider || "—"}</div></div>
          <div><div className="stat-label">Expected discharge date</div><div style={{ marginTop: 2 }}>{formatDate(admission.expected_discharge_date)}</div></div>
          <div><div className="stat-label">Actual discharge</div><div style={{ marginTop: 2 }}>{formatDateTime(admission.discharged_at)}</div></div>
        </div>
      )}
      {locked && (
        <div className="fine" style={{ marginTop: 12 }}>
          Admission is {admission.status_display} — registration details can no longer be edited.
        </div>
      )}
    </div>
  );
}

// ── Bed & ward — current assignment plus assign/release/transfer/discharge. ─
function BedCard({ admission, branchId, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [releasing, setReleasing] = useState(false);
  const [discharging, setDischarging] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);

  async function releaseBed() {
    setReleasing(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_RELEASE_BED(admission.id));
      toastSuccess("Bed released.");
      onChanged();
    } catch (err) {
      toastApiError(err, "Could not release bed.");
    } finally {
      setReleasing(false);
    }
  }

  async function dischargePatient() {
    if (!window.confirm(`Discharge ${admission.patient_name}? This frees the bed and marks the stay complete.`)) return;
    setDischarging(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_DISCHARGE(admission.id));
      toastSuccess("Patient discharged.");
      onChanged();
    } catch (err) {
      toastApiError(err, "Could not discharge patient.");
    } finally {
      setDischarging(false);
    }
  }

  const canAssign = admission.status === "requested" || admission.status === "admitted";
  const canRelease = !!admission.bed && (admission.status === "active" || admission.status === "admitted");
  // Transfer only makes sense once a stay is genuinely under way (ACTIVE,
  // bed allocated) — Release above already covers "never really occupied,
  // undo the assignment" for the ADMITTED case.
  const canTransfer = !!admission.bed && admission.status === "active";
  const canDischarge = admission.status === "active";
  const terminal = admission.status === "discharged" || admission.status === "cancelled";

  return (
    <div className="card" style={{ padding: 20 }}>
      <div className="dot-label" style={{ marginBottom: 10 }}>Bed &amp; ward</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, fontSize: 13.5, marginBottom: 16 }}>
        <div><div className="stat-label">Room</div><div style={{ marginTop: 2 }}>{admission.room_name || "—"}</div></div>
        <div><div className="stat-label">Bed</div><div style={{ marginTop: 2 }}>{admission.bed_number || "Not assigned"}</div></div>
        <div><div className="stat-label">Bed assigned</div><div style={{ marginTop: 2 }}>{formatDateTime(admission.bed_assigned_at)}</div></div>
      </div>

      {!terminal && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {canAssign && (
            <button onClick={() => setPickerOpen(true)} className="btn-primary" style={{ fontSize: 13, padding: "8px 16px" }}>
              {admission.bed ? "Change Bed" : "Assign Bed"}
            </button>
          )}
          {canTransfer && (
            <button onClick={() => setTransferOpen(true)} className="btn-outline" style={{ fontSize: 13, padding: "8px 16px" }}>
              Transfer Bed
            </button>
          )}
          {canRelease && (
            <button onClick={releaseBed} disabled={releasing} className="btn-outline" style={{ fontSize: 13, padding: "8px 16px" }}>
              {releasing ? "Releasing…" : "Release Bed"}
            </button>
          )}
          {canDischarge && (
            <button onClick={dischargePatient} disabled={discharging}
              style={{ fontSize: 13, padding: "8px 16px", borderRadius: 8, cursor: "pointer",
                border: "1.5px solid var(--color-error)", background: "none", color: "var(--color-error)", fontWeight: 600 }}>
              {discharging ? "Discharging…" : "Discharge Patient"}
            </button>
          )}
        </div>
      )}
      {!canDischarge && !terminal && (
        <div className="fine" style={{ marginTop: 10 }}>
          {admission.bed ? "" : "A bed must be assigned before this admission can be discharged."}
        </div>
      )}

      {pickerOpen && (
        <BedPickerModal
          admission={admission}
          branchId={branchId}
          onClose={() => setPickerOpen(false)}
          onDone={() => { setPickerOpen(false); onChanged(); }}
        />
      )}

      {transferOpen && (
        <TransferBedModal
          admission={admission}
          branchId={branchId}
          onClose={() => setTransferOpen(false)}
          onDone={() => { setTransferOpen(false); onChanged(); }}
        />
      )}
    </div>
  );
}

// Move an ACTIVE admission's patient from their current bed straight into a
// different available one — one atomic call (IPD.ADMISSION_TRANSFER_BED),
// unlike Release-then-Assign. The vacated bed goes to `cleaning`, not
// `available` — see apps.ipd.views.TransferBedView.
function TransferBedModal({ admission, branchId, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [rooms, setRooms] = useState([]);
  const [roomTypes, setRoomTypes] = useState([]);
  const [roomId, setRoomId] = useState("");
  const [beds, setBeds] = useState([]);
  const [bedId, setBedId] = useState("");
  const [loadingBeds, setLoadingBeds] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!branchId) return;
    Promise.all([
      apiClient.get(API_ENDPOINTS.ORG.ROOMS, { params: { branch_id: branchId } }),
      apiClient.get(API_ENDPOINTS.BILLING.ROOM_TYPES),
    ]).then(([roomsRes, typesRes]) => {
      const types = typesRes.data?.data || typesRes.data || [];
      setRoomTypes(types);
      const allRooms = roomsRes.data?.data || roomsRes.data || [];
      setRooms(allRooms.filter(r => types.find(t => t.value === r.room_type)?.is_bed_based));
    }).catch(() => {});
  }, [branchId]);

  useEffect(() => {
    if (!roomId) { setBeds([]); return; }
    setLoadingBeds(true);
    apiClient.get(API_ENDPOINTS.ORG.BEDS, { params: { branch_id: branchId, room_id: roomId } })
      .then(r => setBeds((r.data?.data || r.data || []).filter(b => b.status === "available")))
      .catch(() => setBeds([]))
      .finally(() => setLoadingBeds(false));
  }, [roomId, branchId]);

  const roomTypeLabel = (value) => roomTypes.find(t => t.value === value)?.label || value || "—";

  async function submit() {
    if (!bedId) return;
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_TRANSFER_BED(admission.id), { to_bed_id: Number(bedId) });
      toastSuccess("Patient transferred.");
      onDone();
    } catch (err) {
      toastApiError(err, "Could not transfer patient.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 420, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Transfer bed</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div className="fine" style={{ marginBottom: 14 }}>
          Moving from {admission.room_name} — Bed {admission.bed_number}. That bed will need cleaning before its next occupant.
        </div>
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <label style={labelStyle}>Room</label>
            <select style={inputStyle} value={roomId} onChange={e => { setRoomId(e.target.value); setBedId(""); }}>
              <option value="">Select a room…</option>
              {rooms.map(r => <option key={r.id} value={r.id}>{r.name} ({roomTypeLabel(r.room_type)})</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Bed</label>
            <select style={inputStyle} value={bedId} onChange={e => setBedId(e.target.value)} disabled={!roomId || loadingBeds}>
              <option value="">{loadingBeds ? "Loading beds…" : "Select a bed…"}</option>
              {beds.map(b => <option key={b.id} value={b.id}>Bed {b.bed_number}</option>)}
            </select>
            {roomId && !loadingBeds && beds.length === 0 && (
              <div className="fine" style={{ marginTop: 6 }}>No available beds in this room.</div>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
          <button onClick={onClose} className="btn-outline" style={{ flex: 1, padding: "9px 0" }}>Cancel</button>
          <button onClick={submit} disabled={saving || !bedId} className="btn-primary" style={{ flex: 2, padding: "9px 0" }}>
            {saving ? "Transferring…" : "Transfer Patient"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Movement history — read-only timeline of every bed change so far. ──────
const MOVEMENT_LABEL = {
  initial_assignment: "Bed assigned",
  transfer: "Transferred",
  release: "Bed released",
  discharge: "Discharged",
};
function MovementHistoryCard({ admissionId, version }) {
  const [movements, setMovements] = useState(null); // null = loading

  useEffect(() => {
    let cancelled = false;
    apiClient.get(API_ENDPOINTS.IPD.ADMISSION_MOVEMENTS(admissionId))
      .then(r => { if (!cancelled) setMovements(r.data?.data || []); })
      .catch(() => { if (!cancelled) setMovements([]); });
    return () => { cancelled = true; };
  }, [admissionId, version]);

  return (
    <div className="card" style={{ padding: 20 }}>
      <div className="dot-label" style={{ marginBottom: 10 }}>Bed history</div>
      {movements === null && <div className="fine">Loading…</div>}
      {movements && movements.length === 0 && <div className="fine">No bed movements recorded yet.</div>}
      {movements && movements.length > 0 && (
        <div style={{ display: "grid", gap: 8 }}>
          {movements.map(m => (
            <div key={m.id} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13, padding: "6px 0", borderBottom: "1px solid var(--color-border)" }}>
              <span>
                <b>{MOVEMENT_LABEL[m.movement_type] || m.movement_type_display}</b>
                {m.from_room_name && <span> · from {m.from_room_name} / Bed {m.from_bed_number}</span>}
                {m.to_room_name && <span> {m.from_room_name ? "→" : "to"} {m.to_room_name} / Bed {m.to_bed_number}</span>}
                {m.moved_by_name && <div className="fine">by {m.moved_by_name}</div>}
              </span>
              <span className="fine" style={{ whiteSpace: "nowrap" }}>{formatDateTime(m.moved_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Lightweight room -> bed picker (plain selects, not the visual bedgrid
// AdmissionsPage.jsx uses for first-time assignment — that grid isn't
// exported from that file, and a second bed-picking screen on the detail
// page doesn't need the full visual treatment, just a reliable one).
function BedPickerModal({ admission, branchId, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const [rooms, setRooms] = useState([]);
  const [roomTypes, setRoomTypes] = useState([]);
  const [roomId, setRoomId] = useState("");
  const [beds, setBeds] = useState([]);
  const [bedId, setBedId] = useState("");
  const [loadingBeds, setLoadingBeds] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!branchId) return;
    Promise.all([
      apiClient.get(API_ENDPOINTS.ORG.ROOMS, { params: { branch_id: branchId } }),
      apiClient.get(API_ENDPOINTS.BILLING.ROOM_TYPES),
    ]).then(([roomsRes, typesRes]) => {
      const types = typesRes.data?.data || typesRes.data || [];
      setRoomTypes(types);
      const allRooms = roomsRes.data?.data || roomsRes.data || [];
      setRooms(allRooms.filter(r => types.find(t => t.value === r.room_type)?.is_bed_based));
    }).catch(() => {});
  }, [branchId]);

  useEffect(() => {
    if (!roomId) { setBeds([]); return; }
    setLoadingBeds(true);
    apiClient.get(API_ENDPOINTS.ORG.BEDS, { params: { branch_id: branchId, room_id: roomId } })
      .then(r => setBeds((r.data?.data || r.data || []).filter(b => b.status === "available")))
      .catch(() => setBeds([]))
      .finally(() => setLoadingBeds(false));
  }, [roomId, branchId]);

  const roomTypeLabel = (value) => roomTypes.find(t => t.value === value)?.label || value || "—";

  async function submit() {
    if (!bedId) return;
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_ASSIGN_BED(admission.id), { bed_id: Number(bedId) });
      toastSuccess("Bed assigned.");
      onDone();
    } catch (err) {
      toastApiError(err, "Could not assign bed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 420, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Assign bed</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <label style={labelStyle}>Room</label>
            <select style={inputStyle} value={roomId} onChange={e => { setRoomId(e.target.value); setBedId(""); }}>
              <option value="">Select a room…</option>
              {rooms.map(r => <option key={r.id} value={r.id}>{r.name} ({roomTypeLabel(r.room_type)})</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Bed</label>
            <select style={inputStyle} value={bedId} onChange={e => setBedId(e.target.value)} disabled={!roomId || loadingBeds}>
              <option value="">{loadingBeds ? "Loading beds…" : "Select a bed…"}</option>
              {beds.map(b => <option key={b.id} value={b.id}>Bed {b.bed_number}</option>)}
            </select>
            {roomId && !loadingBeds && beds.length === 0 && (
              <div className="fine" style={{ marginTop: 6 }}>No available beds in this room.</div>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
          <button onClick={onClose} className="btn-outline" style={{ flex: 1, padding: "9px 0" }}>Cancel</button>
          <button onClick={submit} disabled={saving || !bedId} className="btn-primary" style={{ flex: 2, padding: "9px 0" }}>
            {saving ? "Assigning…" : "Assign Bed"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Deposits ─────────────────────────────────────────────────────────────
function DepositModal({ admission, onClose, onRecorded }) {
  const { toastSuccess, toastApiError } = useToast();
  const [amount, setAmount] = useState("");
  const [modes, setModes] = useState([]);
  const [mode, setMode] = useState("");
  const [ref, setRef] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiClient.get(API_ENDPOINTS.BILLING.PAYMENT_MODES)
      .then(r => {
        const list = r.data?.data || [];
        setModes(list);
        if (list.length) setMode(list[0].name);
      })
      .catch(() => {});
  }, []);

  async function submit(e) {
    e.preventDefault();
    if (!Number(amount) || Number(amount) <= 0) {
      toastApiError({ message: "Enter an amount greater than zero." });
      return;
    }
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_DEPOSIT(admission.id), {
        amount: Number(amount), payment_mode: mode, transaction_ref: ref,
      });
      toastSuccess("Deposit recorded.");
      onRecorded();
      onClose();
    } catch (err) {
      toastApiError(err, "Could not record deposit.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 420, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Record deposit — {admission.patient_name}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <form onSubmit={submit}>
          <div style={{ display: "grid", gap: 14 }}>
            <div><label style={labelStyle}>Amount (₹)</label>
              <input style={inputStyle} type="number" min="0" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} required />
            </div>
            <div><label style={labelStyle}>Payment mode</label>
              <select style={inputStyle} value={mode} onChange={e => setMode(e.target.value)}>
                {modes.map(m => <option key={m.id} value={m.name}>{m.name}</option>)}
              </select>
            </div>
            <div><label style={labelStyle}>Transaction ref (optional)</label>
              <input style={inputStyle} value={ref} onChange={e => setRef(e.target.value)} placeholder="UPI/txn ID" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
            <button type="button" onClick={onClose} className="btn-outline" style={{ flex: 1, padding: "9px 0" }}>Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2, padding: "9px 0" }}>
              {saving ? "Recording…" : "Record Deposit"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DepositsCard({ admission, deposits, onChanged }) {
  const [modalOpen, setModalOpen] = useState(false);
  const total = deposits.reduce((s, d) => s + (Number(d.amount) || 0), 0);
  const terminal = admission.status === "discharged" || admission.status === "cancelled";

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <div className="dot-label">Deposits {total > 0 && <span style={{ fontWeight: 400 }}>· ₹{total.toLocaleString("en-IN")} collected</span>}</div>
        {!terminal && (
          <button onClick={() => setModalOpen(true)} className="btn-outline" style={{ fontSize: 12, padding: "6px 14px" }}>
            + Record Deposit
          </button>
        )}
      </div>

      {deposits.length === 0 ? (
        <div className="fine">No deposits recorded yet.</div>
      ) : (
        <div style={{ display: "grid", gap: 6 }}>
          {deposits.map(d => (
            <div key={d.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0", borderBottom: "1px solid var(--color-border)" }}>
              <span>
                {d.payment_mode}{d.transaction_ref && ` · ${d.transaction_ref}`}
                <span className="fine" style={{ marginLeft: 6 }}>{formatDateTime(d.collected_at)}</span>
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                ₹{Number(d.amount).toLocaleString("en-IN")}
                {d.reconciled_invoice
                  ? <span className="badge badge--success" style={{ fontSize: 10 }}>Applied to invoice</span>
                  : <span className="badge badge--neutral" style={{ fontSize: 10 }}>Not yet applied</span>}
              </span>
            </div>
          ))}
        </div>
      )}

      {modalOpen && (
        <DepositModal admission={admission} onClose={() => setModalOpen(false)} onRecorded={onChanged} />
      )}
    </div>
  );
}

// ── Billing — generate the IPD stay invoice, view it, record payments. ─────
function PaymentModal({ invoice, onClose, onRecorded }) {
  const { toastSuccess, toastApiError } = useToast();
  const outstanding = Number(invoice.total_amount) - Number(invoice.paid_amount);
  const [amount, setAmount] = useState(outstanding > 0 ? outstanding.toFixed(2) : "0");
  const [modes, setModes] = useState([]);
  const [mode, setMode] = useState("");
  const [ref, setRef] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiClient.get(API_ENDPOINTS.BILLING.PAYMENT_MODES)
      .then(r => {
        const list = r.data?.data || [];
        setModes(list);
        if (list.length) setMode(list[0].name);
      })
      .catch(() => {});
  }, []);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await apiClient.post(API_ENDPOINTS.BILLING.PAYMENTS, {
        invoice: invoice.id, amount: Number(amount), payment_mode: mode, transaction_ref: ref,
      });
      toastSuccess("Payment recorded.");
      onRecorded();
      onClose();
    } catch (err) {
      toastApiError(err, "Could not record payment.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 420, padding: 32, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Record Payment</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 18 }}>
          {invoice.invoice_number} · Outstanding: ₹{outstanding.toFixed(2)}
        </div>
        <form onSubmit={submit}>
          <div style={{ display: "grid", gap: 14 }}>
            <div><label style={labelStyle}>Amount (₹)</label>
              <input style={inputStyle} type="number" min="0" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} required />
            </div>
            <div><label style={labelStyle}>Payment mode</label>
              <select style={inputStyle} value={mode} onChange={e => setMode(e.target.value)}>
                {modes.map(m => <option key={m.id} value={m.name}>{m.name}</option>)}
              </select>
            </div>
            <div><label style={labelStyle}>Transaction ref (optional)</label>
              <input style={inputStyle} value={ref} onChange={e => setRef(e.target.value)} placeholder="UPI/txn ID" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
            <button type="button" onClick={onClose} className="btn-outline" style={{ flex: 1, padding: "9px 0" }}>Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary" style={{ flex: 2, padding: "9px 0" }}>
              {saving ? "Recording…" : "Record Payment"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const INVOICE_BADGE = {
  draft:          "badge--neutral",
  issued:         "badge--primary",
  paid:           "badge--success",
  partially_paid: "badge--warning",
  cancelled:      "badge--error",
};

function InvoiceView({ invoice, onChanged }) {
  const [payModal, setPayModal] = useState(false);
  const outstanding = Number(invoice.total_amount) - Number(invoice.paid_amount);

  return (
    <div style={{ border: "1px solid var(--color-border)", borderRadius: 10, padding: 16, marginTop: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 13.5 }}>{invoice.invoice_number}</div>
        <span className={`badge ${INVOICE_BADGE[invoice.status] || "badge--neutral"}`}>{invoice.status?.replace("_", " ")}</span>
      </div>

      <div style={{ display: "grid", gap: 5, fontSize: 13, marginBottom: 6 }}>
        {(invoice.items || []).map(it => (
          <div key={it.id} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--color-border)" }}>
            <span>{it.description}</span>
            <span>₹{it.total}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gap: 3, fontSize: 12.5, marginTop: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}><span>Subtotal</span><span>₹{invoice.subtotal}</span></div>
        <div style={{ display: "flex", justifyContent: "space-between" }}><span>Tax</span><span>₹{invoice.tax_amount}</span></div>
        <div style={{ display: "flex", justifyContent: "space-between" }}><span>Discount</span><span>₹{invoice.discount_amount}</span></div>
        <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 13.5, borderTop: "1.5px solid var(--color-border)", paddingTop: 5, marginTop: 3 }}>
          <span>Total</span><span>₹{invoice.total_amount}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", color: "var(--color-text-muted)" }}>
          <span>Paid</span><span>₹{invoice.paid_amount}</span>
        </div>
      </div>

      {(invoice.payments || []).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="fine" style={{ fontWeight: 700, marginBottom: 4 }}>PAYMENTS</div>
          <div style={{ display: "grid", gap: 3 }}>
            {invoice.payments.map(p => (
              <div key={p.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                <span>{p.payment_mode}{p.transaction_ref && ` · ${p.transaction_ref}`}</span>
                <span>₹{p.amount}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {outstanding > 0.001 && (
        <div style={{ marginTop: 12 }}>
          <button onClick={() => setPayModal(true)} className="btn-primary" style={{ fontSize: 12, padding: "6px 14px" }}>
            Record Payment
          </button>
        </div>
      )}

      {payModal && (
        <PaymentModal invoice={invoice} onClose={() => setPayModal(false)} onRecorded={onChanged} />
      )}
    </div>
  );
}

function BillingCard({ admission, invoices, onChanged }) {
  const { toastSuccess, toastApiError } = useToast();
  const [generating, setGenerating] = useState(false);

  async function generate() {
    setGenerating(true);
    try {
      await apiClient.post(API_ENDPOINTS.IPD.ADMISSION_GENERATE_INVOICE(admission.id));
      toastSuccess("Invoice generated.");
      onChanged();
    } catch (err) {
      toastApiError(err, "Could not generate invoice.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div className="dot-label">Billing</div>
        <button onClick={generate} disabled={generating || !admission.bed} className="btn-primary" style={{ fontSize: 12, padding: "6px 14px" }}>
          {generating ? "Generating…" : invoices.length ? "Generate New Invoice" : "Generate Invoice"}
        </button>
      </div>
      <div className="fine">
        Bills room charges for nights stayed (up to discharge, or up to now if still admitted) and folds in
        any deposit not yet applied to an invoice.
      </div>
      {!admission.bed && <div className="fine" style={{ marginTop: 6 }}>Assign a bed first — room charges need a bed to price from.</div>}

      {invoices.length === 0 ? (
        <div className="fine" style={{ marginTop: 14 }}>No invoice generated for this stay yet.</div>
      ) : (
        invoices.map(inv => <InvoiceView key={inv.id} invoice={inv} onChanged={onChanged} />)
      )}
    </div>
  );
}

export default function AdmissionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const branchId = user?.branch_id;
  const [admission, setAdmission] = useState(null); // null = loading, false = not found
  const [deposits, setDeposits] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [movementsVersion, setMovementsVersion] = useState(0); // bump to force MovementHistoryCard to refetch

  const fetchAdmission = useCallback(async () => {
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.IPD.ADMISSION(id));
      const d = res.data;
      setAdmission(d);
      setDeposits(d.deposits || []);
    } catch {
      setAdmission(false);
    }
  }, [id]);

  const fetchInvoices = useCallback(async (patientId, admissionNumber) => {
    if (!patientId || !admissionNumber) return;
    try {
      const { data: res } = await apiClient.get(API_ENDPOINTS.BILLING.INVOICES, { params: { patient_id: patientId, page_size: 50 } });
      const all = res.data?.results || [];
      setInvoices(all.filter(inv => inv.notes === `IPD stay — ${admissionNumber}`));
    } catch {
      setInvoices([]);
    }
  }, []);

  useEffect(() => { fetchAdmission(); }, [fetchAdmission]);
  useEffect(() => {
    if (admission) fetchInvoices(admission.patient, admission.admission_number);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [admission?.patient, admission?.admission_number, fetchInvoices]);

  function refreshAll() {
    fetchAdmission();
    setMovementsVersion((v) => v + 1);
  }

  if (admission === false) {
    return (
      <AppShell>
        <PageShell title="Admission not found">
          <button onClick={() => navigate(ROUTES.FRONT_DESK.ADMISSIONS)} className="btn-outline">← Back to Admissions</button>
        </PageShell>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageShell title="">
        <button onClick={() => navigate(ROUTES.FRONT_DESK.ADMISSIONS)}
          style={{ display: "flex", alignItems: "center", gap: 6, background: "none", border: "none", cursor: "pointer", color: "var(--color-text-muted)", fontSize: 13, marginBottom: 14, padding: 0 }}>
          <ArrowLeft size={14} /> Back to Admissions
        </button>

        {admission === null ? (
          <div style={{ color: "var(--color-text-muted)", fontSize: 13.5 }}>Loading…</div>
        ) : (
          <>
            <div className="hero-card" style={{ marginBottom: 22 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
                <div>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 600 }}>{admission.patient_name}</div>
                  <div className="hero-sub">
                    UHID {admission.patient_uhid} · {admission.admission_number} · {admission.department_name}
                  </div>
                </div>
                <span className={`badge ${STATUS_BADGE[admission.status] || "badge--neutral"}`} style={{ fontSize: 12.5 }}>
                  {admission.status_display}
                </span>
              </div>
              <div style={{ display: "flex", gap: 18, marginTop: 16, flexWrap: "wrap", fontSize: 12.5 }} className="hero-sub">
                <span>Ordering doctor: {admission.ordering_doctor_name || "—"}</span>
                <span>Admitted: {formatDateTime(admission.created_at)}</span>
                <span>{admission.reason_for_admission}</span>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>
              <div style={{ display: "grid", gap: 20 }}>
                <RegistrationCard admission={admission} onSaved={refreshAll} />
                <BedCard admission={admission} branchId={branchId} onChanged={refreshAll} />
                <MovementHistoryCard admissionId={admission.id} version={movementsVersion} />
              </div>
              <div style={{ display: "grid", gap: 20 }}>
                <DepositsCard admission={admission} deposits={deposits} onChanged={refreshAll} />
                <BillingCard admission={admission} invoices={invoices} onChanged={() => fetchInvoices(admission.patient, admission.admission_number)} />
              </div>
            </div>
          </>
        )}
      </PageShell>
    </AppShell>
  );
}
