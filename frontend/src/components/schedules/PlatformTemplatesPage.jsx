/**
 * Platform admin: manage the system-level schedule templates every hospital admin can clone from. One page for both kinds
 * (scheduleKinds.js); the API is apps/patients/pediatrics/schedule_views.py:
 *   GET    endpoints.templates       -> [ {id, name, description, active, rule_count, tenants_using, ...} ]
 *   POST   endpoints.templates       -> create {name, description?, active?, rules?}
 *   GET    endpoints.template(id)    -> template + rules[]
 *   PATCH  endpoints.template(id)    -> {name?, description?, active?, rules?: [{id?, ..., _delete?}]}
 *   DELETE endpoints.template(id)    -> refused (400) while any hospital has it as its active schedule
 */
import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../layout/AppShell";
import { PageShell } from "../common/PageShell";
import apiClient      from "../../services/api.client";
import { useToast }   from "../../hooks/useToast";
import { TemplateBadge as Badge } from "./TemplateBadge";
import { RulesEditor, useRules } from "./RulesEditor";
import { labelStyle, adminInputStyle as inputStyle } from "../../styles/formStyles";

const outlineButton = { padding: "5px 12px", borderRadius: 7, background: "none", cursor: "pointer", fontSize: 12.5, fontWeight: 600 };

function TemplateEditor({ kind, template, onSaved, onDeleted, onBack }) {
  const { toastSuccess, toastError, toastApiError } = useToast();
  const [name, setName] = useState(template.name);
  const [description, setDescription] = useState(template.description || "");
  const [active, setActive] = useState(!!template.active);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const list = useRules(kind, template.rules, template.id);

  useEffect(() => {
    setName(template.name);
    setDescription(template.description || "");
    setActive(!!template.active);
  }, [template.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSave() {
    const problem = list.error();
    if (problem) { toastError(problem); return; }
    setSaving(true);
    try {
      const { data: res } = await apiClient.patch(kind.endpoints.template(template.id), { name, description, active, rules: list.payload() });
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
      const { data: res } = await apiClient.delete(kind.endpoints.template(template.id));
      toastSuccess(res.message || "Template deleted.");
      onDeleted(template.id);
    } catch (err) {
      // a 400 carries "N hospital(s) currently have this template…" when it is still in use; show that message as it is
      toastApiError(err, "Failed to delete template.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="card" style={{ padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <button type="button" onClick={onBack}
          style={{ ...outlineButton, border: "1.5px solid var(--color-border)", color: "var(--color-text-muted)" }}>
          ← All templates
        </button>
        {active ? <Badge tone="primary">ACTIVE</Badge> : <Badge tone="muted">INACTIVE</Badge>}
        {typeof template.tenants_using === "number" && template.tenants_using > 0 && (
          <Badge tone="warning">{template.tenants_using} hospital{template.tenants_using === 1 ? "" : "s"} using this</Badge>
        )}
        <div style={{ flex: 1 }} />
        <button type="button" onClick={handleDelete} disabled={deleting}
          style={{ ...outlineButton, border: "1.5px solid var(--color-error)", color: "var(--color-error)" }}>
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

      <RulesEditor kind={kind} list={list} />

      <button type="button" className="btn-primary" onClick={handleSave} disabled={saving}>
        {saving ? "Saving…" : "Save Template"}
      </button>
    </div>
  );
}

function NewTemplateForm({ kind, onCreated, onCancel }) {
  const { toastSuccess, toastError, toastApiError } = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  async function handleCreate() {
    if (!name.trim()) { toastError("Name is required."); return; }
    setCreating(true);
    try {
      const { data: res } = await apiClient.post(kind.endpoints.templates, { name: name.trim(), description: description.trim() });
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
      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 14 }}>{kind.text.newTemplate}</div>
      <div style={{ display: "grid", gap: 14, marginBottom: 16 }}>
        <div>
          <label style={labelStyle}>Template Name *</label>
          <input style={inputStyle} value={name} onChange={e => setName(e.target.value)}
            placeholder={kind.text.templateExample} autoFocus />
        </div>
        <div>
          <label style={labelStyle}>Description</label>
          <textarea style={{ ...inputStyle, minHeight: 60, resize: "vertical" }} value={description}
            onChange={e => setDescription(e.target.value)} placeholder="Optional description" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn-primary" onClick={handleCreate} disabled={creating}>
          {creating ? "Creating…" : kind.text.createTemplate}
        </button>
        <button type="button" onClick={onCancel}
          style={{ padding: "8px 16px", borderRadius: 8, border: "1.5px solid var(--color-border)", background: "none", cursor: "pointer", fontSize: 13.5, fontWeight: 600 }}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function TemplateCard({ kind, template, onSelect }) {
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
        <Badge tone="muted">{template.rule_count} {kind.text.rule}{template.rule_count === 1 ? "" : "s"}</Badge>
        {typeof template.tenants_using === "number" && (
          <Badge tone={template.tenants_using > 0 ? "warning" : "muted"}>
            {template.tenants_using} hospital{template.tenants_using === 1 ? "" : "s"} using
          </Badge>
        )}
      </div>
    </div>
  );
}

export default function PlatformTemplatesPage({ kind }) {
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
      const { data: res } = await api.get(kind.endpoints.templates);
      setTemplates(res.data || []);
    } catch (err) {
      toastApiError(err, kind.text.loadTemplates);
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [api, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchList(); }, [fetchList]);

  const fetchDetail = useCallback(async (id) => {
    if (!id) { setSelectedTemplate(null); return; }
    setDetailLoading(true);
    try {
      const { data: res } = await api.get(kind.endpoints.template(id));
      setSelectedTemplate(res.data);
    } catch (err) {
      toastApiError(err, "Failed to load template detail.");
      setSelectedTemplate(null);
      setSelectedId(null);
    } finally {
      setDetailLoading(false);
    }
  }, [api, kind]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchDetail(selectedId); }, [selectedId, fetchDetail]);

  function handleBack() {
    setSelectedId(null);
    setSelectedTemplate(null);
    setCreating(false);
    fetchList();
  }

  const showDetail = selectedId !== null;
  const loadingBox = <div style={{ textAlign: "center", padding: 60, color: "var(--color-text-muted)" }}>Loading…</div>;

  return (
    <AppShell>
      <PageShell
        title={kind.text.templatesTitle}
        action={!showDetail && !creating ? (
          <button type="button" className="btn-primary" onClick={() => setCreating(true)}>+ New Template</button>
        ) : null}
      >
        {loading && !showDetail ? loadingBox : showDetail ? (
          detailLoading || !selectedTemplate ? loadingBox : (
            <TemplateEditor
              kind={kind}
              template={selectedTemplate}
              onSaved={(updated) => { setSelectedTemplate(updated); fetchList(); }}
              onDeleted={handleBack}
              onBack={handleBack}
            />
          )
        ) : (
          <>
            {creating && (
              <NewTemplateForm
                kind={kind}
                onCreated={(created) => { setCreating(false); fetchList(); setSelectedId(created.id); }}
                onCancel={() => setCreating(false)}
              />
            )}
            {templates.length === 0 ? (
              <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--color-text-muted)" }}>
                {kind.text.noTemplates}
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
                {templates.map(t => (
                  <TemplateCard key={t.id} kind={kind} template={t} onSelect={(id) => { setCreating(false); setSelectedId(id); }} />
                ))}
              </div>
            )}
          </>
        )}
      </PageShell>
    </AppShell>
  );
}
