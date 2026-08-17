/**
 * pages/patient/NotificationsPage.jsx
 * -------------------------------------
 * In-app reminders (HMS-10g) — appointment reminders, follow-up reminders
 * (both pre-generated server-side, see apps/notifications/services.py), and
 * vaccination-due items (computed live from the vaccination roadmap, so
 * always current). No real SMS/email/push exists in this build yet — this
 * IS the notification, not a copy of one sent elsewhere.
 */
import { useState } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi }    from "../../hooks/useApi";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { Calendar, Stethoscope, Syringe, Building2, CircleCheck } from "lucide-react";

const TYPE_META = {
  appointment_reminder: { label: "Appointment", icon: Calendar,    color: "var(--color-primary)", bg: "var(--color-primary-light)" },
  followup_reminder:    { label: "Follow-up",    icon: Stethoscope, color: "var(--color-info)",     bg: "var(--color-info-light)" },
  vaccination_due:      { label: "Vaccination",  icon: Syringe,     color: "var(--color-warning)",  bg: "#FFF8E1" },
};

function relativeDate(dateStr) {
  const today = new Date().toISOString().split("T")[0];
  const yesterday = new Date(Date.now() - 86400000).toISOString().split("T")[0];
  if (dateStr === today) return "Today";
  if (dateStr === yesterday) return "Yesterday";
  try {
    return new Date(dateStr + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return dateStr;
  }
}

export default function NotificationsPage() {
  const { data, isLoading, refetch } = useApi(API_ENDPOINTS.PORTAL.NOTIFICATIONS);
  const [markingId, setMarkingId] = useState(null);
  const notifications = data?.results || [];
  const unreadCount = data?.unread_count ?? 0;

  async function markRead(n) {
    // Only real NotificationLog rows ("<tenant_db>:<log_id>") can be marked
    // read — vaccination-due items are computed live with no backing row.
    const sepIndex = n.id.indexOf(":");
    if (sepIndex === -1 || n.type === "vaccination_due") return;
    const tenantDb = n.id.slice(0, sepIndex);
    const logId = n.id.slice(sepIndex + 1);
    setMarkingId(n.id);
    try {
      await apiClient.post(API_ENDPOINTS.PORTAL.NOTIFICATION_READ(tenantDb, logId));
      refetch();
    } catch {
      // Best-effort — leaving it unread just means it stays highlighted, not harmful.
    } finally {
      setMarkingId(null);
    }
  }

  return (
    <AppShell>
      <PageShell title="Notifications">
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: "1px solid var(--color-border)" }}>
            <span className="dot-label dot-label--green">
              {unreadCount > 0 ? `${unreadCount} unread` : "All caught up"} ({notifications.length})
            </span>
            <button className="btn-outline" style={{ fontSize: 12, padding: "5px 14px" }} onClick={refetch}>Refresh</button>
          </div>

          {isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
          ) : notifications.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center" }}>
              <div style={{ fontFamily: "var(--font-display)", fontSize: 18, fontWeight: 600, marginBottom: 6 }}>
                Nothing here yet
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
                Appointment reminders, follow-up nudges, and vaccination-due alerts will show up here.
              </div>
            </div>
          ) : (
            <div>
              {notifications.map(n => {
                const meta = TYPE_META[n.type] || TYPE_META.appointment_reminder;
                const Icon = meta.icon;
                const clickable = n.type !== "vaccination_due" && !n.read;
                return (
                  <div key={n.id}
                    onClick={() => clickable && markRead(n)}
                    style={{
                      display: "flex", gap: 12, padding: "14px 20px",
                      borderBottom: "1px solid var(--color-border)",
                      background: n.read ? "transparent" : "var(--color-surface-secondary, #FAFAF6)",
                      cursor: clickable ? "pointer" : "default",
                      opacity: markingId === n.id ? 0.6 : 1,
                    }}>
                    <span style={{
                      width: 34, height: 34, borderRadius: "50%", flexShrink: 0,
                      background: meta.bg, color: meta.color,
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                      <Icon size={16} />
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: meta.color, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                          {meta.label}
                        </span>
                        {!n.read && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-accent)" }} />}
                      </div>
                      <div style={{ fontSize: 13.5, color: "var(--color-text)", lineHeight: 1.5 }}>{n.body}</div>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4, fontSize: 11.5, color: "var(--color-text-muted)" }}>
                        <span>{relativeDate(n.date)}</span>
                        {n.hospital && (
                          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                            <Building2 size={11} /> {n.hospital}
                          </span>
                        )}
                        {n.read && (
                          <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                            <CircleCheck size={11} /> Read
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </PageShell>
    </AppShell>
  );
}
