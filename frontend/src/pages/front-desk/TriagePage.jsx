/**
 * pages/front-desk/TriagePage.jsx
 * -----------------------------------
 * Front desk's entry point for a walk-in with no prior appointment — step 1
 * of the approved intake mockup (Triage -> OPD Booking -> Emergency
 * Registration -> Referral Queue -> Complete Admission + Bed). Markup and
 * styling here follow that mockup exactly (see intake-workspace.css) rather
 * than the app's default page look — this is the shared step-wizard
 * workspace, so it stays visually consistent with the other 4 steps.
 *
 * Checks real per-department doctor availability (org.DepartmentAvailabilityView,
 * see docs/PENDING_IMPROVEMENTS.md item 1) and routes the decision from
 * there: a free doctor today sends the patient into normal OPD booking;
 * nobody free doesn't block registration — it routes to Emergency instead,
 * since identity/registration never waits on OPD capacity.
 *
 * Exports both a standalone routed page (default export, used directly at
 * ROUTES.FRONT_DESK.TRIAGE — kept working for backward compatibility/deep
 * links) and a bare content component (`TriagePageContent`) that the
 * Patient Intake hub (PatientIntakePage.jsx) embeds as one of its internal
 * tabs — same component, same API calls, no duplicated implementation.
 * `embedded` just suppresses this page's own PageShell, since the hub
 * already supplies an equivalent page title and tab bar.
 */
import { useNavigate } from "react-router-dom";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import { useApi } from "../../hooks/useApi";
import { useAuth } from "../../hooks/useAuth";
import API_ENDPOINTS from "../../config/api.config";
import { ROUTES } from "../../config/routes.config";

const TODAY = new Date().toISOString().split("T")[0];

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
                      onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_OPD, { state: { departmentHint: d.department_name } })}
                    >
                      Book OPD →
                    </button>
                  ) : (
                    <button className="secondary-btn" disabled>Book OPD →</button>
                  )}
                  <button
                    className={d.is_available_today ? "secondary-btn" : "critical-btn"}
                    onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_EMERGENCY, { state: { departmentHint: d.department_name } })}
                  >
                    {d.is_available_today ? "Route to Emergency" : "Route to Emergency →"}
                  </button>
                </div>
              </div>
            ))}

            {!isLoading && list.length === 0 && (
              <div className="fine">No departments configured for this branch yet.</div>
            )}

            <div className="avail-row none">
              <div>
                <div className="avail-dept">Unconscious, unidentified, or a clear emergency</div>
                <div className="avail-meta">Skip department selection — identity and registration never wait on which department the patient turns out to need.</div>
              </div>
              <div className="avail-actions">
                <button className="critical-btn" onClick={() => navigate(ROUTES.FRONT_DESK.INTAKE_EMERGENCY)}>
                  Register Emergency Patient →
                </button>
              </div>
            </div>
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
