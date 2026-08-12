/**
 * pages/platform-admin/VaccinationTemplatesPage.jsx
 * ----------------------------------------------------
 * Platform admin: manage system-level vaccination schedule templates
 * (VaccinationSchedule rows with owner_tenant_id=None, is_template=True)
 * that every hospital admin sees as "available templates" to clone from
 * (see pages/hospital-admin/VaccinationSchedulePage.jsx).
 *
 * Backend (apps/platform_admin/vaccination_template_views.py):
 *   GET    /platform/vaccination-templates/        -> [ {id, name, description,
 *                                                        active, rule_count,
 *                                                        tenants_using, ...} ]
 *   POST   /platform/vaccination-templates/        -> create {name, description?, active?, rules?}
 *   GET    /platform/vaccination-templates/<id>/   -> template + rules[]
 *   PATCH  /platform/vaccination-templates/<id>/   -> {name?, description?, active?,
 *                                                       rules?: [{id?, vaccine_name,
 *                                                       scheduled_label, min_age_days,
 *                                                       max_age_days?, dose_number?,
 *                                                       mandatory?, sort_order?, _delete?}]}
 *   DELETE /platform/vaccination-templates/<id>/   -> refused (400) if any tenant's
 *                                                       active_vaccination_schedule_id
 *                                                       points at it
 *
 * Rule-editing UI note: this intentionally duplicates the add/edit/remove/
 * reorder rule-row markup from pages/hospital-admin/VaccinationSchedulePage.jsx
 * rather than extracting a shared component. The two editors are *almost*
 * identical but diverge just enough (this one has an "active" template
 * toggle + delete + tenants-in-use badge; the hospital-admin one has an
 * "activate for this hospital" flow) that a shared component would need a
 * handful of conditional props threaded through, and the hospital-admin page
 * is already working in production. Duplicating ~150 lines here is a much
 * lower-risk way to ship this than editing that file. If a third
 * schedule-editing surface shows up later, that's the trigger to extract
 * ScheduleRuleEditor for real.
 */

import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient      from "../../services/api.client";
import { useToast }   from "../../hooks/useToast";
import API_ENDPOINTS  from "../../config/api.config";

const inputStyle = {
  width: "100%", boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "8px 10px", fontSize: 13.5,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 5 };

function Badge({ children, tone = "primary" }) {
  const tones = {
    primary: { background: "var(--color-primary-light, var(--color-bg))", color: "var(--color-primary)", border: "1px solid var(--color-primary)" },
    muted:   { background: "var(--color-bg)", color: "var(--color-text-muted)", border: "1px solid var(--color-border)" },
    warning: { background: "var(--color-warning-light, var(--color-bg))", color: "var(--color-warning)", border: "1px solid var(--color-warning)" },
  };
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 20,
      letterSpacing: 0.3, whiteSpace: "nowrap", ...tones[tone],
    }}>{children}</span>
  );
}

function emptyRule(sortOrder) {
  return {
    _key: `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    vaccine_name: "",
    dose_number: 1,
    scheduled_label: "",
    min_age_days: 0,
    max_age_days: "",
    mandatory: true,
    sort_order: sortOrder,
  };
}

function RuleRow({ rule, onChange, onRemove, onMove, isFirst, isLast }) {
  const set = (k) => (v) => onChange({ ...rule, [k]: v });
  return (
    <div className="card" style={{ padding: "14px 16px", display: "grid", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
        <div>
          <label style={labelStyle}>Vaccine Name *</label>
          <input style={inputStyle} value={rule.vaccine_name}
            onChange={e => set("vaccine_name")(e.target.value)} placeholder="e.g. BCG" required />
        </div>
        <div>
          <label style={labelStyle}>Dose #</label>
          <input type="number" min={1} style={inputStyle} value={rule.dose_number}
            onChange={e => set("dose_number")(Number(e.target.value))} />
        </div>
      </div>

      <div>
        <label style={labelStyle}>Scheduled Label (milestone) *</label>
        <input style={inputStyle} value={rule.scheduled_label}
          onChange={e => set("scheduled_label")(e.target.value)} placeholder="e.g. Birth, 6 weeks, 9 months" required />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <div>
          <label style={labelStyle}>Min Age (days) *</label>
          <input type="number" min={0} style={inputStyle} value={rule.min_age_days}
            onChange={e => set("min_age_days")(Number(e.target.value))} required />
        </div>
        <div>
          <label style={labelStyle}>Max Age (days)</label>
          <input type="number" min={0} style={inputStyle} value={rule.max_age_days ?? ""}
            onChange={e => set("max_age_days")(e.target.value === "" ? "" : Number(e.target.value))}
            placeholder="optional" />
        </div>
        <div>
          <label style={labelStyle}>Sort Order</label>
          <input type="number" style={inputStyle} value={rule.sort_order}
            onChange={e => set("sort_order")(Number(e.target.value))} />
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 2 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
          <input type="checkbox" checked={!!rule.mandatory} onChange={e => set("mandatory")(e.target.checked)} />
          Mandatory
        </label>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" onClick={onMove ? () => onMove(-1) : undefined} disabled={isFirst}
            title="Move up"
            style={{ padding: "5px 10px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: isFirst ? "not-allowed" : "pointer", fontSize: 13, opacity: isFirst ? 0.4 : 1 }}>
            ↑
          </button>
          <button type="button" onClick={onMove ? () => onMove(1) : undefined} disabled={isLast}
            title="Move down"
            style={{ padding: "5px 10px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: isLast ? "not-allowed" : "pointer", fontSize: 13, opacity: isLast ? 0.4 : 1 }}>
            ↓
          </button>
          <button type="button" onClick={onRemove}
            style={{ padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-error)", background: "none", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "var(--color-error)" }}>
            Remove
          </button>
        </div>
      </div>
    </div>
  );
}

function TemplateEditor({ template, onSaved, onDeleted, onBack }) {
  const api = apiClient;
  const { toastSuccess, toastError, toastApiError } = useToast();
  const [name, setName] = useState(template.name);
  const [description, setDescription] = useState(template.description || "");
  const [active, setActive] = useState(!!template.active);
  const [rules, setRules] = useState(
    (template.rules || []).map(r => ({ ...r, _key: `existing-${r.id}` }))
  );
  const [removedIds, setRemovedIds] = useState([]);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setName(template.name);
    setDescription(template.description || "");
    setActive(!!template.active);
    setRules((template.rules || []).map(r => ({ ...r, _key: `existing-${r.id}` })));
    setRemovedIds([]);
  }, [template.id]); // eslint-disable-line react-hooks/exhaustive-deps

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
      const { data: res } = await api.patch(API_ENDPOINTS.PLATFORM.VACCINATION_TEMPLATE(template.id), {
        name, description, active, rules: rulePayload,
      });
      toastSuccess(res.message || "Template updated.");
      onSaved(res.data);
    } catch (err) {
      toastApiError(err, "Failed to save template.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete template "${template.name}"? This can't be undone.`)) return;
    setDeleting(true);
    try {
      const { data: res } = await api.delete(API_ENDPOINTS.PLATFORM.VACCINATION_TEMPLATE(template.id));
      toastSuccess(res.message || "Template deleted.");
      onDeleted(template.id);
    } catch (err) {
      // Backend returns a 400 with a specific "N hospital(s) currently have
      // this template..." message when it's still in use — surface that
      // exact message rather than a generic failure toast.
      toastApiError(err, "Failed to delete template.");
    } finally {
      setDeleting(false);
    }
  }

  const sortedRules = [...rules].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <button type="button" onClick={onBack}
          style={{ padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 12.5, fontWeight: 600, color: "var(--color-text-muted)" }}>
          ← All templates
        </button>
        {active ? <Badge tone="primary">ACTIVE</Badge> : <Badge tone="muted">INACTIVE</Badge>}
        {typeof template.tenants_using === "number" && template.tenants_using > 0 && (
          <Badge tone="warning">{template.tenants_using} hospital{template.tenants_using === 1 ? "" : "s"} using this</Badge>
        )}
        <div style={{ flex: 1 }} />
        <button type="button" onClick={handleDelete} disabled={deleting}
          style={{ padding: "5px 12px", borderRadius: 7, border: "1.5px solid var(--color-error)", background: "none", cursor: "pointer", fontSize: 12.5, fontWeight: 600, color: "var(--color-error)" }}>
          {deleting ? "Deleting…" : "Delete Template"}
        </button>
      </div>

      <div style={{ display: "grid", gap: 14, marginBottom: 20 }}>
        <div>
          <label style={labelStyle}>Template Name *</label>
          <input style={inputStyle} value={name} onChange={e => setName(e.target.value)} required />
        </div>
        <div>
          <label style={labelStyle}>Description</label>
          <textarea style={{ ...inputStyle, minHeight: 60, resize: "vertical" }} value={description}
            onChange={e => setDescription(e.target.value)} placeholder="Optional description for hospital admins" />
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
          <input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />
          Active (visible to hospital admins as an available template)
        </label>
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
        {saving ? "Saving…" : "Save Template"}
      </button>
    </div>
  );
}

function NewTemplateForm({ onCreated, onCancel }) {
  const api = apiClient;
  const { toastSuccess, toastError, toastApiError } = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  async function handleCreate() {
    if (!name.trim()) {
      toastError("Name is required.");
      return;
    }
    setCreating(true);
    try {
      const { data: res } = await api.post(API_ENDPOINTS.PLATFORM.VACCINATION_TEMPLATES, {
        name: name.trim(), description: description.trim(),
      });
      toastSuccess(res.message || "Template created.");
      onCreated(res.data);
    } catch (err) {
      toastApiError(err, "Failed to create template.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="card" style={{ padding: 20, marginBottom: 20 }}>
      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 14 }}>New Vaccination Template</div>
      <div style={{ display: "grid", gap: 14, marginBottom: 16 }}>
        <div>
          <label style={labelStyle}>Template Name *</label>
          <input style={inputStyle} value={name} onChange={e => setName(e.target.value)}
            placeholder="e.g. National Immunization Schedule" autoFocus />
        </div>
        <div>
          <label style={labelStyle}>Description</label>
          <textarea style={{ ...inputStyle, minHeight: 60, resize: "vertical" }} value={description}
            onChange={e => setDescription(e.target.value)} placeholder="Optional description" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn-primary" onClick={handleCreate} disabled={creating}>
          {creating ? "Creating…" : "Create & Add Rules"}
        </button>
        <button type="button" onClick={onCancel}
          style={{ padding: "8px 16px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 13.5, fontWeight: 600 }}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function TemplateCard({ template, onSelect }) {
  return (
    <div className="card card--interactive" style={{ padding: "16px 20px", cursor: "pointer" }} onClick={() => onSelect(template.id)}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{template.name}</div>
        {template.active ? <Badge tone="primary">ACTIVE</Badge> : <Badge tone="muted">INACTIVE</Badge>}
      </div>
      {template.description && (
        <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 12 }}>{template.description}</div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Badge tone="muted">{template.rule_count} rule{template.rule_count === 1 ? "" : "s"}</Badge>
        {typeof template.tenants_using === "number" && (
          <Badge tone={template.tenants_using > 0 ? "warning" : "muted"}>
            {template.tenants_using} hospital{template.tenants_using === 1 ? "" : "s"} using
          </Badge>
        )}
      </div>
    </div>
  );
}

export default function VaccinationTemplatesPage() {
  const api = apiClient;
  const { toastApiError } = useToast();

  const [loading, setLoading] = useState(true);
  const [templates, setTemplates] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [creating, setCreating] = useState(false);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await api.get(API_ENDPOINTS.PLATFORM.VACCINATION_TEMPLATES);
      setTemplates(res.data || []);
    } catch (err) {
      toastApiError(err, "Failed to load vaccination templates.");
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [api]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchList(); }, [fetchList]);

  const fetchDetail = useCallback(async (id) => {
    if (!id) { setSelectedTemplate(null); return; }
    setDetailLoading(true);
    try {
      const { data: res } = await api.get(API_ENDPOINTS.PLATFORM.VACCINATION_TEMPLATE(id));
      setSelectedTemplate(res.data);
    } catch (err) {
      toastApiError(err, "Failed to load template detail.");
      setSelectedTemplate(null);
      setSelectedId(null);
    } finally {
      setDetailLoading(false);
    }
  }, [api]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchDetail(selectedId); }, [selectedId, fetchDetail]);

  function handleSelect(id) {
    setCreating(false);
    setSelectedId(id);
  }

  function handleBack() {
    setSelectedId(null);
    setSelectedTemplate(null);
    setCreating(false);
    fetchList();
  }

  function handleCreated(newTemplate) {
    setCreating(false);
    fetchList();
    setSelectedId(newTemplate.id);
  }

  function handleSaved(updated) {
    setSelectedTemplate(updated);
    fetchList();
  }

  function handleDeleted() {
    handleBack();
  }

  const showDetail = selectedId !== null;

  return (
    <AppShell>
      <PageShell
        title="Vaccination Templates"
        action={!showDetail && !creating ? (
          <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
            + New Template
          </button>
        ) : null}
      >
        {loading && !showDetail ? (
          <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
        ) : showDetail ? (
          detailLoading || !selectedTemplate ? (
            <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>
          ) : (
            <TemplateEditor
              template={selectedTemplate}
              onSaved={handleSaved}
              onDeleted={handleDeleted}
              onBack={handleBack}
            />
          )
        ) : (
          <>
            {creating && (
              <NewTemplateForm onCreated={handleCreated} onCancel={() => setCreating(false)} />
            )}
            {templates.length === 0 ? (
              <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--color-text-muted)" }}>
                No system vaccination templates yet. Create one to give hospitals a starting roadmap.
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
                {templates.map(t => (
                  <TemplateCard key={t.id} template={t} onSelect={handleSelect} />
                ))}
              </div>
            )}
          </>
        )}
      </PageShell>
    </AppShell>
  );
}
