/**
 * pages/hospital-admin/VaccinationSchedulePage.jsx
 * --------------------------------------------------
 * Hospital admin: configure the vaccination roadmap this hospital's staff
 * and patient portal build against (apps.registry.vaccine_schedule.build_roadmap()).
 *
 * Backend (apps/org/vaccination_schedule_views.py):
 *   GET  /org/vaccination-schedules/        -> { own_schedules: [...], templates: [...], active_schedule_id }
 *   POST /org/vaccination-schedules/        -> clone {template_id, name?} into an owned schedule, auto-activates it
 *   GET  /org/vaccination-schedules/<id>/   -> schedule + rules[]
 *   PATCH /org/vaccination-schedules/<id>/  -> { name?, description?, active?, rules?: [{id?, vaccine_name,
 *                                                scheduled_label, min_age_days, max_age_days?, dose_number?,
 *                                                mandatory?, sort_order?, _delete?}] }
 *   POST /org/vaccination-schedules/<id>/activate/ -> set this tenant's active schedule
 *
 * A hospital only ever has an "active_schedule_id" pointing either at a system
 * template (until it clones one) or at exactly one schedule it owns after
 * cloning — there's no notion of multiple simultaneously-active owned
 * schedules, so the switcher only needs to show up when the hospital has more
 * than one owned schedule to pick between (rare, but the activate endpoint
 * supports it, so we handle it).
 */

import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient      from "../../services/api.client";
import { useToast }   from "../../hooks/useToast";
import API_ENDPOINTS  from "../../config/api.config";
import { VaccinationRuleRow as RuleRow } from "../../components/schedules/VaccinationRuleRow";
import { emptyVaccinationRule as emptyRule } from "../../components/schedules/ruleDefaults";
import { ScheduleBadge as Badge } from "../../components/schedules/ScheduleBadge";
import { labelStyle, adminInputStyle as inputStyle } from "../../styles/formStyles";










function ScheduleEditor({ schedule, isActive, onSaved, canActivate, onActivate, activating }) {
  const api = apiClient;
  const { toastSuccess, toastError, toastApiError } = useToast();
  const [name, setName] = useState(schedule.name);
  const [description, setDescription] = useState(schedule.description || "");
  const [rules, setRules] = useState(
    (schedule.rules || []).map(r => ({ ...r, _key: `existing-${r.id}` }))
  );
  const [removedIds, setRemovedIds] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setName(schedule.name);
    setDescription(schedule.description || "");
    setRules((schedule.rules || []).map(r => ({ ...r, _key: `existing-${r.id}` })));
    setRemovedIds([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-seed only when a different schedule is opened
  }, [schedule.id]);

  function addRule() {
    const nextSort = rules.length ? Math.max(...rules.map(r => r.sort_order ?? 0)) + 1 : 0;
    setRules(rs => [...rs, emptyRule(nextSort)]);
  }

  function updateRule(key, next) {
    setRules(rs => rs.map(r => (r._key === key ? next : r)));
  }

  function removeRule(key) {
    setRules(rs => {
      const target = rs.find(r => r._key === key);
      if (target?.id) setRemovedIds(ids => [...ids, target.id]);
      return rs.filter(r => r._key !== key);
    });
  }

  function moveRule(index, dir) {
    setRules(rs => {
      const next = [...rs];
      const swapWith = index + dir;
      if (swapWith < 0 || swapWith >= next.length) return rs;
      [next[index], next[swapWith]] = [next[swapWith], next[index]];
      return next.map((r, i) => ({ ...r, sort_order: i }));
    });
  }

  async function handleSave() {
    for (const r of rules) {
      if (!r.vaccine_name?.trim() || !r.scheduled_label?.trim() || r.min_age_days === "" || r.min_age_days === null || r.min_age_days === undefined) {
        toastError("Every rule needs a vaccine name, scheduled label, and min age.");
        return;
      }
    }
    setSaving(true);
    try {
      const rulePayload = [
        ...rules.map(r => ({
          ...(r.id ? { id: r.id } : {}),
          vaccine_name: r.vaccine_name.trim(),
          scheduled_label: r.scheduled_label.trim(),
          min_age_days: r.min_age_days,
          max_age_days: r.max_age_days === "" ? null : r.max_age_days,
          dose_number: r.dose_number || 1,
          mandatory: !!r.mandatory,
          sort_order: r.sort_order ?? 0,
        })),
        ...removedIds.map(id => ({ id, _delete: true })),
      ];
      const { data: res } = await api.patch(API_ENDPOINTS.ORG.VACCINATION_SCHEDULE(schedule.id), {
        name, description, rules: rulePayload,
      });
      toastSuccess(res.message || "Schedule updated.");
      onSaved(res.data);
    } catch (err) {
      toastApiError(err, "Failed to save schedule.");
    } finally {
      setSaving(false);
    }
  }

  const sortedRules = [...rules].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        {isActive ? <Badge tone="primary">ACTIVE FOR THIS HOSPITAL</Badge> : <Badge tone="muted">NOT ACTIVE</Badge>}
        {!isActive && canActivate && (
          <button type="button" onClick={() => onActivate(schedule.id)} disabled={activating}
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

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: 0.4 }}>
          Rules ({sortedRules.length})
        </div>
        <button type="button" onClick={addRule}
          style={{ fontSize: 12.5, padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-primary)", background: "none", color: "var(--color-primary)", cursor: "pointer", fontWeight: 600 }}>
          + Add Rule
        </button>
      </div>

      {sortedRules.length === 0 ? (
        <div style={{ textAlign: "center", padding: 30, color: "var(--color-text-muted)", fontSize: 13.5 }}>
          No rules yet. Add the first vaccine milestone.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
          {sortedRules.map((rule, idx) => (
            <RuleRow
              key={rule._key}
              rule={rule}
              onChange={(next) => updateRule(rule._key, next)}
              onRemove={() => removeRule(rule._key)}
              onMove={(dir) => moveRule(idx, dir)}
              isFirst={idx === 0}
              isLast={idx === sortedRules.length - 1}
            />
          ))}
        </div>
      )}

      <button type="button" className="btn-primary" onClick={handleSave} disabled={saving}>
        {saving ? "Saving…" : "Save Schedule"}
      </button>
    </div>
  );
}

function TemplateCard({ template, onClone, cloning }) {
  return (
    <div className="card" style={{ padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{template.name}</div>
        <Badge tone="muted">{template.rule_count} rule{template.rule_count === 1 ? "" : "s"}</Badge>
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

export default function VaccinationSchedulePage() {
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
      const { data: res } = await api.get(API_ENDPOINTS.ORG.VACCINATION_SCHEDULES);
      const own = res.data?.own_schedules || [];
      const tmpl = res.data?.templates || [];
      const activeId = res.data?.active_schedule_id ?? null;
      setOwnSchedules(own);
      setTemplates(tmpl);
      setActiveScheduleId(activeId);
      if (own.length > 0) {
        setSelectedId(own.find(s => s.id === activeId)?.id || own[0].id);
      } else {
        setSelectedId(null);
      }
    } catch (err) {
      toastApiError(err, "Failed to load vaccination schedules.");
      setOwnSchedules([]); setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [api]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchList(); }, [fetchList]);

  const fetchDetail = useCallback(async (id) => {
    if (!id) { setSelectedSchedule(null); return; }
    setDetailLoading(true);
    try {
      const { data: res } = await api.get(API_ENDPOINTS.ORG.VACCINATION_SCHEDULE(id));
      setSelectedSchedule(res.data);
    } catch (err) {
      toastApiError(err, "Failed to load schedule detail.");
      setSelectedSchedule(null);
    } finally {
      setDetailLoading(false);
    }
  }, [api]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchDetail(selectedId); }, [selectedId, fetchDetail]);

  async function handleClone(template) {
    setCloningId(template.id);
    try {
      const { data: res } = await api.post(API_ENDPOINTS.ORG.VACCINATION_SCHEDULES, { template_id: template.id });
      toastSuccess(res.message || `Cloned '${template.name}'.`);
      await fetchList();
      setSelectedId(res.data?.id || null);
    } catch (err) {
      toastApiError(err, "Failed to clone template.");
    } finally {
      setCloningId(null);
    }
  }

  async function handleActivate(id) {
    setActivatingId(id);
    try {
      const { data: res } = await api.post(API_ENDPOINTS.ORG.VACCINATION_SCHEDULE_ACTIVATE(id));
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

  const hasOwn = ownSchedules.length > 0;

  return (
    <AppShell>
      <PageShell title="Vaccination Schedule">
        {loading ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
        ) : !hasOwn ? (
          <>
            <div style={{
              display: "flex", alignItems: "center", gap: 10, padding: "14px 18px", borderRadius: 12,
              background: "var(--color-warning-light)", color: "var(--color-warning)", marginBottom: 24, fontSize: 13.5, fontWeight: 600,
            }}>
              You're currently using the system Default Schedule for every patient. Clone it — or a different
              template below — to start customizing vaccine milestones for your hospital.
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
                  <TemplateCard key={t.id} template={t} onClone={handleClone} cloning={cloningId === t.id} />
                ))}
              </div>
            )}
          </>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: ownSchedules.length > 1 ? "220px 1fr" : "1fr", gap: 20 }}>
            {ownSchedules.length > 1 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {ownSchedules.map(s => (
                  <div key={s.id} className="card"
                    onClick={() => setSelectedId(s.id)}
                    style={{
                      padding: "12px 14px", cursor: "pointer",
                      border: s.id === selectedId ? "1.5px solid var(--color-primary)" : "1.5px solid var(--color-border)",
                    }}>
                    <div style={{ fontWeight: 700, fontSize: 13.5, marginBottom: 4 }}>{s.name}</div>
                    {s.id === activeScheduleId ? <Badge tone="primary">ACTIVE</Badge> : <Badge tone="muted">INACTIVE</Badge>}
                  </div>
                ))}
              </div>
            )}
            <div>
              {detailLoading || !selectedSchedule ? (
                <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
              ) : (
                <ScheduleEditor
                  schedule={selectedSchedule}
                  isActive={selectedSchedule.id === activeScheduleId}
                  onSaved={handleSaved}
                  canActivate={ownSchedules.length > 1}
                  onActivate={handleActivate}
                  activating={activatingId === selectedSchedule.id}
                />
              )}
            </div>
          </div>
        )}
      </PageShell>
    </AppShell>
  );
}
