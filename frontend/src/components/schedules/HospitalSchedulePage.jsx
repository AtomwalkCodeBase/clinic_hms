/** Hospital admin: configure the vaccination or milestone roadmap this hospital's staff and patient portal build against. */
import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../layout/AppShell";
import { PageShell } from "../common/PageShell";
import apiClient      from "../../services/api.client";
import { useToast }   from "../../hooks/useToast";
import { TemplateBadge as Badge } from "./TemplateBadge";
import { RulesEditor, useRules } from "./RulesEditor";
import { labelStyle, adminInputStyle as inputStyle } from "../../styles/formStyles";

function ScheduleEditor({ kind, schedule, isActive, onSaved, canActivate, onActivate, activating }) {
  const { toastSuccess, toastError, toastApiError } = useToast();
  const [name, setName] = useState(schedule.name);
  const [description, setDescription] = useState(schedule.description || "");
  const [saving, setSaving] = useState(false);
  const list = useRules(kind, schedule.rules, schedule.immunization_schedule_id);

  useEffect(() => {
    setName(schedule.name);
    setDescription(schedule.description || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-seed only when a different schedule is opened
  }, [schedule.immunization_schedule_id]);

  async function handleSave() {
    const problem = list.error();
    if (problem) { toastError(problem); return; }
    setSaving(true);
    try {
      const { data: res } = await apiClient.patch(kind.endpoints.schedule(schedule.immunization_schedule_id), { name, description, rules: list.payload() });
      toastSuccess(res.message || "Schedule updated.");
      onSaved(res.data);
    } catch (err) {
      toastApiError(err, "Failed to save schedule.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        {isActive ? <Badge tone="primary">ACTIVE FOR THIS HOSPITAL</Badge> : <Badge tone="muted">NOT ACTIVE</Badge>}
        {!isActive && canActivate && (
          <button type="button" onClick={() => onActivate(schedule.immunization_schedule_id)} disabled={activating}
            style={{ padding: "5px 12px", borderRadius: 8, border: "1.5px solid var(--color-primary)", background: "none", color: "var(--color-primary)", cursor: "pointer", fontSize: 12.5, fontWeight: 600 }}>
            {activating ? "Activating…" : "Activate this schedule"}
          </button>
        )}
      </div>

      <div style={{ display: "grid", gap: 14, marginBottom: 20 }}>
        <div>
          <label style={labelStyle}>Schedule Name *</label>
          <input style={inputStyle} value={name} onChange={e => setName(e.target.value)} required />
        </div>
        <div>
          <label style={labelStyle}>Description</label>
          <textarea style={{ ...inputStyle, minHeight: 60, resize: "vertical" }} value={description}
            onChange={e => setDescription(e.target.value)} placeholder="Optional description for staff" />
        </div>
      </div>

      <RulesEditor kind={kind} list={list} />

      <button type="button" className="btn-primary" onClick={handleSave} disabled={saving}>
        {saving ? "Saving…" : "Save Schedule"}
      </button>
    </div>
  );
}

function TemplateCard({ kind, template, onClone, cloning }) {
  return (
    <div className="card" style={{ padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{template.name}</div>
        <Badge tone="muted">{template.rule_count} {kind.text.rule}{template.rule_count === 1 ? "" : "s"}</Badge>
      </div>
      {template.description && (
        <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 12 }}>{template.description}</div>
      )}
      <button type="button" className="btn-primary" onClick={() => onClone(template)} disabled={cloning}>
        {cloning ? "Cloning…" : "Clone & Customize"}
      </button>
    </div>
  );
}

export default function HospitalSchedulePage({ kind }) {
  const api = apiClient;
  const { toastSuccess, toastApiError } = useToast();

  const [loading, setLoading] = useState(true);
  const [ownSchedules, setOwnSchedules] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [activeScheduleId, setActiveScheduleId] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedSchedule, setSelectedSchedule] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cloningId, setCloningId] = useState(null);
  const [activatingId, setActivatingId] = useState(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await api.get(kind.endpoints.schedules);
      const own = res.data?.own_schedules || [];
      const activeId = res.data?.active_schedule_id ?? null;
      setOwnSchedules(own);
      setTemplates(res.data?.templates || []);
      setActiveScheduleId(activeId);
      setSelectedId(own.length > 0 ? (own.find(s => s.immunization_schedule_id === activeId)?.immunization_schedule_id || own[0].immunization_schedule_id) : null);
    } catch (err) {
      toastApiError(err, kind.text.loadSchedules);
      setOwnSchedules([]); setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [api, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchList(); }, [fetchList]);

  const fetchDetail = useCallback(async (id) => {
    if (!id) { setSelectedSchedule(null); return; }
    setDetailLoading(true);
    try {
      const { data: res } = await api.get(kind.endpoints.schedule(id));
      setSelectedSchedule(res.data);
    } catch (err) {
      toastApiError(err, "Failed to load schedule detail.");
      setSelectedSchedule(null);
    } finally {
      setDetailLoading(false);
    }
  }, [api, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchDetail(selectedId); }, [selectedId, fetchDetail]);

  async function handleClone(template) {
    setCloningId(template.immunization_schedule_id);
    try {
      const { data: res } = await api.post(kind.endpoints.schedules, { template_id: template.immunization_schedule_id });
      toastSuccess(res.message || `Cloned '${template.name}'.`);
      await fetchList();
      setSelectedId(res.data?.immunization_schedule_id || null);
    } catch (err) {
      toastApiError(err, "Failed to clone template.");
    } finally {
      setCloningId(null);
    }
  }

  async function handleActivate(id) {
    setActivatingId(id);
    try {
      const { data: res } = await api.post(kind.endpoints.activate(id));
      toastSuccess(res.message || "Schedule activated.");
      await fetchList();
      setSelectedId(id);
    } catch (err) {
      toastApiError(err, "Failed to activate schedule.");
    } finally {
      setActivatingId(null);
    }
  }

  function handleSaved(updated) {
    setSelectedSchedule(updated);
    fetchList();
  }

  const loadingBox = <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>;

  return (
    <AppShell>
      <PageShell title={kind.text.scheduleTitle}>
        {loading ? loadingBox : ownSchedules.length === 0 ? (
          <>
            <div style={{
              display: "flex", alignItems: "center", gap: 10, padding: "14px 18px", borderRadius: 12,
              background: "var(--color-warning-light)", color: "var(--color-warning)", marginBottom: 24, fontSize: 13.5, fontWeight: 600,
            }}>
              {kind.text.useDefault}
            </div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 10 }}>
              Available Templates
            </div>
            {templates.length === 0 ? (
              <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--color-text-muted)" }}>
                No system templates available yet.
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
                {templates.map(t => (
                  <TemplateCard key={t.immunization_schedule_id} kind={kind} template={t} onClone={handleClone} cloning={cloningId === t.immunization_schedule_id} />
                ))}
              </div>
            )}
          </>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: ownSchedules.length > 1 ? "220px 1fr" : "1fr", gap: 20 }}>
            {ownSchedules.length > 1 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {ownSchedules.map(s => (
                  <div key={s.immunization_schedule_id} className="card"
                    onClick={() => setSelectedId(s.immunization_schedule_id)}
                    style={{
                      padding: "12px 14px", cursor: "pointer",
                      border: s.immunization_schedule_id === selectedId ? "1.5px solid var(--color-primary)" : "1.5px solid var(--color-border)",
                    }}>
                    <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 4 }}>{s.name}</div>
                    {s.immunization_schedule_id === activeScheduleId ? <Badge tone="primary">ACTIVE</Badge> : <Badge tone="muted">INACTIVE</Badge>}
                  </div>
                ))}
              </div>
            )}
            <div>
              {detailLoading || !selectedSchedule ? loadingBox : (
                <ScheduleEditor
                  kind={kind}
                  schedule={selectedSchedule}
                  isActive={selectedSchedule.immunization_schedule_id === activeScheduleId}
                  onSaved={handleSaved}
                  canActivate={ownSchedules.length > 1}
                  onActivate={handleActivate}
                  activating={activatingId === selectedSchedule.immunization_schedule_id}
                />
              )}
            </div>
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
