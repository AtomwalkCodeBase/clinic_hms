/** pages/patient/EmergencyQRPage.jsx */
import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useToast }  from "../../hooks/useToast";
import apiClient      from "../../services/api.client";
import API_ENDPOINTS  from "../../config/api.config";
import { usePatientContext } from "../../context/PatientContext";
import { QrCode, RefreshCw, Copy, ShieldAlert, Clock, Check } from "lucide-react";

function useCountdown(expiresAt) {
  const [secondsLeft, setSecondsLeft] = useState(null);

  useEffect(() => {
    if (!expiresAt) { setSecondsLeft(null); return; }
    const tick = () => {
      const left = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
      setSecondsLeft(left);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  return secondsLeft;
}

export default function EmergencyQRPage() {
  const { familyMembers } = usePatientContext();
  const { toastApiError, toastSuccess } = useToast();

  // Independent of PatientContext.selectedPatient on purpose — see file
  const [targetAwpid, setTargetAwpid] = useState("");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState(null); // { token, view_url, qr_image, expires_at, ttl_minutes }

  const secondsLeft = useCountdown(result?.expires_at);
  const expired = result && secondsLeft === 0;

  const targetLabel = targetAwpid
    ? (familyMembers.find(m => m.awpid === targetAwpid)?.full_name || "this family member")
    : "yourself";

  const requestToken = useCallback(async () => {
    setGenerating(true);
    try {
      const { data: res } = await apiClient.post(API_ENDPOINTS.PORTAL.EMERGENCY_TOKEN, {
        patient_awpid: targetAwpid || undefined,
      });
      setResult(res.data);
    } catch (err) {
      toastApiError(err, "Could not generate an emergency QR code.");
    } finally {
      setGenerating(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetAwpid]);

  const startGenerate = requestToken;

  // Switching who the QR is for invalidates whatever was on screen — don't
  useEffect(() => { setResult(null); }, [targetAwpid]);

  function copyLink() {
    if (!result?.view_url) return;
    navigator.clipboard?.writeText(result.view_url)
      .then(() => toastSuccess("Link copied."))
      .catch(() => {});
  }

  const mm = String(Math.floor((secondsLeft || 0) / 60)).padStart(2, "0");
  const ss = String((secondsLeft || 0) % 60).padStart(2, "0");

  return (
    <AppShell>
      <PageShell title="Emergency QR">
        <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginBottom: 20, marginTop: -8, display: "flex", alignItems: "flex-start", gap: 6, maxWidth: 560 }}>
          <ShieldAlert size={14} style={{ marginTop: 1, flexShrink: 0 }} />
          <span>
            For emergencies at a hospital outside our network. Generate a code, show it on this
            screen, and let the treating doctor scan it — no login or app needed on their end. Each
            code expires in 20 minutes.
          </span>
        </div>

        <div className="card" style={{ padding: 20, maxWidth: 480 }}>
          <label style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, display: "block" }}>
            Who is this for?
          </label>
          <select
            className="form-input"
            style={{ appearance: "auto", marginBottom: 16 }}
            value={targetAwpid}
            onChange={e => setTargetAwpid(e.target.value)}
          >
            <option value="">Myself</option>
            {familyMembers.map(m => (
              <option key={m.awpid} value={m.awpid}>{m.full_name}</option>
            ))}
          </select>

          {!result || expired ? (
            <button
              className="btn-primary"
              onClick={startGenerate}
              disabled={generating}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, padding: "9px 20px" }}
            >
              <QrCode size={15} />
              {generating ? "Generating…" : expired ? "Generate a new code" : `Generate QR for ${targetLabel}`}
            </button>
          ) : (
            <div style={{ display: "grid", justifyItems: "center", gap: 12 }}>
              <div style={{ padding: 12, background: "#fff", borderRadius: 12, border: "1px solid var(--color-border)" }}>
                <img src={result.qr_image} alt="Emergency QR code" width={220} height={220} style={{ display: "block" }} />
              </div>

              <div style={{ fontSize: 13, fontWeight: 600 }}>
                For {targetLabel}
              </div>

              <div style={{
                display: "flex", alignItems: "center", gap: 6, fontSize: 12.5,
                color: secondsLeft <= 60 ? "var(--color-danger, #b91c1c)" : "var(--color-text-muted)",
                fontWeight: secondsLeft <= 60 ? 700 : 400,
              }}>
                <Clock size={13} /> Expires in {mm}:{ss}
              </div>

              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="btn-secondary"
                  onClick={startGenerate}
                  disabled={generating}
                  style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, padding: "7px 14px" }}
                >
                  <RefreshCw size={13} /> New code
                </button>
                <button
                  className="btn-secondary"
                  onClick={copyLink}
                  style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, padding: "7px 14px" }}
                >
                  <Copy size={13} /> Copy link
                </button>
              </div>
            </div>
          )}

          {expired && (
            <div style={{ marginTop: 12, fontSize: 12, color: "var(--color-danger, #b91c1c)" }}>
              This code has expired. Generate a new one to show it again.
            </div>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
