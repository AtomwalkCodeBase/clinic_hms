/**
 * pages/front-desk/BedBoardPage.jsx
 * -----------------------------------
 * Live Floor -> Room -> Bed grid, backed by org.BedBoardView (one call
 * instead of stitching Floor/Room/Bed lists together). Click any bed to act
 * on it:
 *   - available -> Reserve it for a patient still on the Awaiting Bed
 *     worklist (see AdmissionsPage.jsx), or take it out of rotation
 *     (maintenance — hospital-admin only on the backend).
 *   - reserved  -> confirm ("patient is actually in the bed now" — the same
 *     action as AssignBedView) or cancel the hold.
 *   - occupied  -> see who's in it, jump to their admission, or transfer
 *     them straight into a different bed (one atomic call — see
 *     apps.ipd.views.TransferBedView).
 *   - cleaning  -> mark it clean and available again (the turnover step a
 *     discharge/transfer now routes through instead of freeing a bed
 *     straight back to available).
 *   - blocked / out_of_service -> return it to available.
 *
 * Maintenance actions are shown regardless of role — hospital_admin already
 * has route access to this page "for oversight" (see AppShell.jsx), and a
 * front-desk user attempting an admin-only action just gets the ordinary
 * 403 toast, the same pattern every other cross-role button in this app
 * already follows (no in-page role branching elsewhere in front-desk pages).
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import { useToast } from "../../hooks/useToast";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES } from "../../config/routes.config";
import "../../styles/intake-workspace.css"; // reuses .bed/.bedgrid/.bed-legend styles from AdmissionsPage

const STATUS_META = {
  available:      { cls: "free",     label: "Available" },
  reserved:       { cls: "reserved", label: "Reserved" },
  occupied:       { cls: "occupied", label: "Occupied" },
  cleaning:       { cls: "cleaning", label: "Cleaning" },
  blocked:        { cls: "blocked",  label: "Blocked" },
  out_of_service: { cls: "blocked",  label: "Out of Service" },
};
function statusMeta(status) {
  return STATUS_META[status] || { cls: "taken", label: status || "Unknown" };
}
const BADGE_META = {
  available: "badge--success", reserved: "badge--warning", occupied: "badge--error",
  cleaning: "badge--warning", blocked: "badge--neutral", out_of_service: "badge--neutral",
};

function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

const selectStyle = {
  width: "100%", padding: "8px 10px", borderRadius: 8,
  border: "1.5px solid var(--color-border)", background: "var(--color-surface)",
  color: "var(--color-text)", fontSize: 13.5,
};
const fieldLabelStyle = { display: "block", fontSize: 12, fontWeight: 600, marginBottom: 4, color: "var(--color-text-muted)" };

// One modal, contents vary by the clicked bed's current status.
function BedActionModal({ bed, awaitingBed, availableBeds, onClose, onDone }) {
  const { toastSuccess, toastApiError } = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [reserveFor, setReserveFor] = useState("");
  const [transferTo, setTransferTo] = useState("");

  async function run(fn, okMsg) {
    setBusy(true);
    try {
      await fn();
      toastSuccess(okMsg);
      onDone();
    } catch (err) {
      toastApiError(err, "Could not complete that action.");
    } finally {
      setBusy(false);
    }
  }

  const reserve = () => reserveFor && run(
    () => apiClient.post(API_ENDPOINTS.IPD.ADMISSION_RESERVE_BED(reserveFor), { bed_id: bed.id }),
    "Bed reserved.",
  );
  const confirmAssign = () => run(
    () => apiClient.post(API_ENDPOINTS.IPD.ADMISSION_ASSIGN_BED(bed.reservation.admission_id), { bed_id: bed.id }),
    "Bed assignment confirmed.",
  );
  const cancelReservation = () => run(
    () => apiClient.post(API_ENDPOINTS.IPD.ADMISSION_CANCEL_BED_RESERVATION(bed.reservation.admission_id)),
    "Reservation cancelled.",
  );
  const transfer = () => transferTo && run(
    () => apiClient.post(API_ENDPOINTS.IPD.ADMISSION_TRANSFER_BED(bed.current_admission.admission_id), { to_bed_id: Number(transferTo) }),
    "Patient transferred.",
  );
  const markClean = () => run(
    () => apiClient.post(API_ENDPOINTS.ORG.BED_MARK_CLEAN(bed.id)),
    "Bed marked available.",
  );
  const maintenance = (action) => run(
    () => apiClient.post(API_ENDPOINTS.ORG.BED_MAINTENANCE(bed.id), { action }),
    "Bed updated.",
  );

  const m = statusMeta(bed.status);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: "var(--color-surface)", borderRadius: 16, width: "100%", maxWidth: 440, padding: 28, boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 17 }}>{bed.room_name} — Bed {bed.bed_number}</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <span className={`badge ${BADGE_META[bed.status] || "badge--neutral"}`}>{m.label}</span>

        <div style={{ marginTop: 18, display: "grid", gap: 12 }}>
          {bed.status === "available" && (
            <>
              <div className="fine">Hold this bed for a patient still on the Awaiting Bed worklist, before they're physically moved in.</div>
              <div>
                <label style={fieldLabelStyle}>Reserve for</label>
                <select style={selectStyle} value={reserveFor} onChange={(e) => setReserveFor(e.target.value)}>
                  <option value="">Select an admission…</option>
                  {(awaitingBed || []).map((a) => (
                    <option key={a.id} value={a.id}>{a.patient_name} · {a.admission_number}</option>
                  ))}
                </select>
                {(awaitingBed || []).length === 0 && (
                  <div className="fine" style={{ marginTop: 6 }}>No admissions are waiting on a bed right now.</div>
                )}
              </div>
              <button className="btn-primary" disabled={busy || !reserveFor} onClick={reserve}>
                {busy ? "Reserving…" : "Reserve Bed"}
              </button>
              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <button className="btn-outline" disabled={busy} onClick={() => maintenance("block")} style={{ flex: 1, fontSize: 12.5 }}>Block</button>
                <button className="btn-outline" disabled={busy} onClick={() => maintenance("out_of_service")} style={{ flex: 1, fontSize: 12.5 }}>Out of Service</button>
              </div>
            </>
          )}

          {bed.status === "reserved" && bed.reservation && (
            <>
              <div className="fine">
                Held for <b>{bed.reservation.patient_name}</b> ({bed.reservation.admission_number}) — not yet physically occupied.
              </div>
              <button className="btn-primary" disabled={busy} onClick={confirmAssign}>
                {busy ? "Confirming…" : "Confirm — Patient Is In Bed"}
              </button>
              <button className="btn-outline" disabled={busy} onClick={cancelReservation}>
                {busy ? "Cancelling…" : "Cancel Reservation"}
              </button>
            </>
          )}

          {bed.status === "occupied" && bed.current_admission && (
            <>
              <div className="fine">
                <b>{bed.current_admission.patient_name}</b> · UHID {bed.current_admission.patient_uhid}
                <br />Since {formatDateTime(bed.current_admission.admitted_at)}
              </div>
              <button className="btn-outline" onClick={() => navigate(ROUTES.FRONT_DESK.ADMISSION_DETAIL(bed.current_admission.admission_id))}>
                View Admission →
              </button>
              <div>
                <label style={fieldLabelStyle}>Transfer to</label>
                <select style={selectStyle} value={transferTo} onChange={(e) => setTransferTo(e.target.value)}>
                  <option value="">Select an available bed…</option>
                  {(availableBeds || []).map((b) => (
                    <option key={b.id} value={b.id}>{b.room_name} — Bed {b.bed_number}</option>
                  ))}
                </select>
              </div>
              <button className="btn-primary" disabled={busy || !transferTo} onClick={transfer}>
                {busy ? "Transferring…" : "Transfer Patient"}
              </button>
            </>
          )}

          {bed.status === "cleaning" && (
            <>
              <div className="fine">Awaiting housekeeping confirmation before its next occupant.</div>
              <button className="btn-primary" disabled={busy} onClick={markClean}>
                {busy ? "Updating…" : "Mark Clean & Available"}
              </button>
            </>
          )}

          {(bed.status === "blocked" || bed.status === "out_of_service") && (
            <>
              <div className="fine">Out of rotation for maintenance.</div>
              <button className="btn-primary" disabled={busy} onClick={() => maintenance("unblock")}>
                {busy ? "Updating…" : "Return to Available"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BedBoardPage() {
  const { user } = useAuth();
  const branchId = user?.branch_id;
  const [selected, setSelected] = useState(null);

  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.ORG.BED_BOARD, {
    params: { branch_id: branchId }, skip: !branchId, pollMs: 20000,
  });
  const { data: awaitingBed, refetch: refetchAwaiting } = useApi(API_ENDPOINTS.IPD.ADMISSION_AWAITING_BED);

  const floors = data?.floors || [];
  const allBeds = floors.flatMap((f) => f.rooms.flatMap((r) => r.beds.map((b) => ({ ...b, room_name: r.room_name }))));
  const availableBeds = allBeds.filter((b) => b.status === "available");
  const counts = allBeds.reduce((acc, b) => { acc[b.status] = (acc[b.status] || 0) + 1; return acc; }, {});

  function refreshAll() {
    refetch();
    refetchAwaiting();
    setSelected(null);
  }

  return (
    <AppShell>
      <PageShell title="Bed Board">
        <div className="fine" style={{ marginBottom: 16 }}>
          Live status of every ward bed for your branch — click a bed to reserve, confirm, transfer, or turn it over.
        </div>

        <div className="intake-workspace">
          <div className="bed-legend" style={{ marginBottom: 18 }}>
            {Object.entries(STATUS_META).map(([key, m]) => (
              <span key={key} className={"dot " + m.cls}>{m.label} ({counts[key] || 0})</span>
            ))}
          </div>

          {isLoading && <div className="fine">Loading bed board…</div>}
          {!isLoading && floors.length === 0 && (
            <div className="fine">No bed-based rooms configured for this branch yet — set them up under Rooms &amp; Floors.</div>
          )}

          {floors.map((floor) => (
            <div key={floor.floor_id ?? "unassigned"} style={{ marginBottom: 26 }}>
              <div className="ward-group-label" style={{ fontSize: 13 }}>{floor.floor_name}</div>
              {floor.rooms.map((room) => (
                <div key={room.room_id} style={{ marginBottom: 14 }}>
                  <div className="fine" style={{ fontWeight: 700, marginBottom: 6 }}>
                    {room.room_name}{room.department_name ? ` · ${room.department_name}` : ""}
                    {room.capacity != null && <span style={{ marginLeft: 6 }}>({room.beds.length}/{room.capacity})</span>}
                  </div>
                  <div className="bedgrid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(64px, 1fr))" }}>
                    {room.beds.map((bed) => (
                      <div
                        key={bed.id}
                        className={"bed " + statusMeta(bed.status).cls}
                        style={{ aspectRatio: "auto", height: 56 }}
                        title={`Bed ${bed.bed_number} — ${statusMeta(bed.status).label}`}
                        onClick={() => setSelected({ ...bed, room_name: room.room_name })}
                      >
                        {bed.bed_number}
                      </div>
                    ))}
                    {room.beds.length === 0 && <div className="fine">No beds set up in this room.</div>}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>

        {selected && (
          <BedActionModal
            bed={selected}
            awaitingBed={awaitingBed}
            availableBeds={availableBeds.filter((b) => b.id !== selected.id)}
            onClose={() => setSelected(null)}
            onDone={refreshAll}
          />
        )}
      </PageShell>
    </AppShell>
  );
}
