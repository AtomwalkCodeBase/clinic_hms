/**
 * Modal shown when the doctor clicks "Handwrite (QR)" on the SOAP card.
 * Shows the patient's QR for this consultation's handwriting session — scan
 * it, write across the Prescription and Internal Note tabs (it autosaves and
 * survives closing the tab), then back here press "Load handwritten note".
 */
export function ConsultPadQRModal({ data, patientName, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 16,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--color-surface, #fff)", borderRadius: 12, padding: 20,
          maxWidth: 360, width: "100%", textAlign: "center", boxShadow: "0 12px 40px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <strong style={{ fontSize: 14 }}>Handwrite on phone</strong>
          <button onClick={onClose} style={{ border: "none", background: "none", cursor: "pointer", fontSize: 18, lineHeight: 1 }}>×</button>
        </div>
        <p style={{ fontSize: 12, color: "var(--color-text-secondary)", margin: "0 0 12px" }}>
          Scan to write for <b>{patientName || "this patient"}</b> — two tabs, <b>Prescription</b> and
          <b> Internal Note</b>. It autosaves as you write. Back here, press <b>Load handwritten note</b>
          to pull it in; you can load again after writing more.
        </p>
        <img
          src={data.qr_image}
          alt="Handwriting pad QR"
          style={{ width: 220, height: 220, border: "1px solid var(--color-border)", borderRadius: 8 }}
        />
        <div style={{ fontSize: 10, color: "var(--color-text-secondary)", wordBreak: "break-all", margin: "8px 0 12px" }}>
          {data.pad_url}
        </div>
        <button className="btn-primary" style={{ width: "100%" }} onClick={onClose}>Done</button>
        <p style={{ fontSize: 10, color: "var(--color-text-secondary)", margin: "10px 0 0" }}>
          The session stays open until you sign this encounter.
        </p>
      </div>
    </div>
  );
}
