/** pages/front-desk/TriagePage.jsx */
import { useNavigate } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES } from "../../config/routes.config";
import { todayLocal } from "../../utils/dates";

const TODAY = todayLocal();

export function TriagePageContent({ embedded = false } = {}) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const branchId = user?.branch_id;

  const { data: departments, isLoading } = useApi(API_ENDPOINTS.ORG.DEPARTMENTS_AVAILABILITY, {
    params: { branch_id: branchId, date: TODAY },
    skip: !branchId,
    pollMs: 30000,
  });

  const list = departments || [];

  const content = (
    <div className="intake-workspace">
      <div className="panel" style={{ marginTop: embedded ? 0 : 14 }}>
        <div className="panel-head">
          <h2>Walk-in triage — who's available right now</h2>
          <span className="chip chip-new">new</span>
        </div>

        <div className="section">
          {isLoading && <div className="fine">Checking today's availability…</div>}

          <div className="avail-list">
            {list.map((d) => (
              <div key={d.department_id} className={"avail-row" + (d.is_available_today ? "" : " none")}>
                <div>
                  <div className="avail-dept">{d.department_name}</div>
                  <div className="avail-meta">
                    {d.doctors_free_today > 0
                      ? `${d.doctors_free_today} doctor${d.doctors_free_today > 1 ? "s" : ""} free · next slot today`
                      : d.next_available_date
                      ? `No doctor free until ${new Date(d.next_available_date).toLocaleDateString()}${d.next_available_time ? `, ${d.next_available_time}` : ""}`
                      : "No upcoming availability found"}
                  </div>
                </div>
                <div className="avail-actions">
                  {d.is_available_today ? (
                    <button
                      className="primary-btn"
                      onClick={() => navigate(ROUTES.FRONT_DESK.APPOINTMENTS, { state: { departmentHint: d.department_name } })}
                    >
                      Book OPD →
                    </button>
                  ) : (
                    <button className="secondary-btn" disabled>Book OPD →</button>
                  )}
                </div>
              </div>
            ))}

            {!isLoading && list.length === 0 && (
              <div className="fine">No departments configured for this branch yet.</div>
            )}
          </div>
        </div>

        <div className="btnbar" style={{ background: "transparent" }}>
          <div className="fine">
            OPD registration was never mandatory — when no doctor is free, front desk can send the
            walk-in straight to Emergency instead of queueing them for a slot that doesn't exist yet.
          </div>
        </div>
      </div>
    </div>
  );

  if (embedded) return content;
  return <PageShell title="Triage">{content}</PageShell>;
}

export default function TriagePage() {
  return (
    <AppShell>
      <TriagePageContent />
    </AppShell>
  );
}
