// Which hospitals hold a patient's record, and whether each may see their history from other hospitals. The patient can withdraw or grant it at any time.
import { useEffect, useState } from "react";
import apiClient from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";

export default function HospitalSharingCard({ awpid, name }) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");
  const params = awpid ? { patient_awpid: awpid } : {};

  useEffect(() => {
    let live = true;
    apiClient.get(API_ENDPOINTS.PORTAL.HOSPITAL_SHARING, { params })
      .then(({ data }) => { if (live) setRows((data?.data || data).results || []); })
      .catch(() => { if (live) setRows([]); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [awpid]);

  async function change(row, share) {
    setBusy(row.hospital_id); setError("");
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.HOSPITAL_SHARING, { hospital_id: row.hospital_id, share, ...params });
      setRows((rs) => rs.map((r) => (r.hospital_id === row.hospital_id ? { ...r, share } : r)));
    } catch {
      setError("Could not save that change. Please try again.");
    } finally {
      setBusy(null);
    }
  }

  if (!rows || rows.length === 0) return null;
  return (
    <section className="card" style={{ padding: 20, marginBottom: 16 }}>
      <h3 style={{ margin: 0, fontSize: 17 }}>Hospitals that can see {name ? `${name}'s` : "your"} history</h3>
      <p style={{ fontSize: 13, color: "var(--color-text-muted)", margin: "6px 0 14px" }}>
        When this is on, a hospital's doctors can see the history from other hospitals. When it is off, they see only what that hospital records itself.
        You can change it at any time; the change applies to the next time a doctor opens the record.
      </p>
      <div style={{ display: "grid", gap: 10 }}>
        {rows.map((r) => (
          <div key={r.hospital_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "10px 14px", border: "1px solid var(--color-border)", borderRadius: 10 }}>
            <div>
              <div style={{ fontWeight: 600 }}>{r.hospital}</div>
              <div style={{ fontSize: 12, color: r.share ? "var(--color-success, #1a7f4b)" : "var(--color-text-muted)" }}>
                {r.share ? "Sharing is on" : "Sharing is off: only this hospital's own records are seen"}
              </div>
            </div>
            <button className={r.share ? "btn-outline" : "btn-primary"} disabled={busy === r.hospital_id} onClick={() => change(r, !r.share)}>
              {r.share ? "Stop sharing" : "Allow sharing"}
            </button>
          </div>
        ))}
      </div>
      {error && <p role="alert" style={{ color: "var(--color-error, #b91c1c)", fontSize: 12.5, marginTop: 10 }}>{error}</p>}
    </section>
  );
}
