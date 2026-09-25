/**
 * pages/platform-admin/DocClassifierPage.jsx
 * ------------------------------------------
 * Platform admin (internal): the My Reports document classifier.
 *
 *   Keyword rules    — the rule-based classifier's vocabulary, one row per
 *                      rule: document type, pipe-separated keywords, and how
 *                      many hits count as 100%. Saved rules apply to the next
 *                      upload — no code change, no restart.
 *   Agreement report — pipeline status counts and how often the rules and
 *                      the LLM agree with what people confirmed.
 *
 * Backend: apps/platform_admin/doc_classification_views.py
 */

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient from "../../services/api.client";
import { useToast } from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";

const TYPE_LABEL = {
  prescription: "Prescription", lab_report: "Lab report", scan: "Imaging",
  discharge_summary: "Discharge summary", not_medical: "Not medical", other: "Other",
};
const inputStyle = {
  width: "100%", boxSizing: "border-box", border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "8px 10px", fontSize: 13.5, background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 12.5, fontWeight: 600, marginBottom: 5 };
const pctText = (r) => (r == null ? "—" : `${Math.round(r * 100)}%`);

export default function DocClassifierPage() {
  const [tab, setTab] = useState("rules");
  return (
    <AppShell>
      <PageShell title="Document Classifier">
        <LLMServerCard />
        <div style={{ display: "inline-flex", border: "1px solid var(--color-border)", borderRadius: 9, overflow: "hidden", marginBottom: 16 }}>
          {[["rules", "Keyword rules"], ["report", "Agreement report"]].map(([id, l]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              padding: "7px 14px", fontSize: 13, border: "none", cursor: "pointer",
              background: tab === id ? "var(--color-primary)" : "transparent",
              color: tab === id ? "#fff" : "var(--color-text-secondary)", fontWeight: tab === id ? 600 : 400,
            }}>{l}</button>
          ))}
        </div>
        {tab === "rules" ? <RulesTab /> : <ReportTab />}
      </PageShell>
    </AppShell>
  );
}

/* ───────────────────────────────────────────────────────── LLM server */
// Which LLM this install uses (LLM_MODE in .env: local | production) and
// whether it's answering. Documents wait in the AI queue while it's down.
function LLMServerCard() {
  const [s, setS] = useState(null);
  const load = useCallback(async () => {
    try { const { data } = await apiClient.get(API_ENDPOINTS.PLATFORM.LLM_STATUS); setS(data?.data || data); }
    catch { setS({ error: true }); }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);
  if (!s) return null;
  if (s.error) return <div className="card" style={{ padding: 14, marginBottom: 16, fontSize: 13 }}>Couldn't read the LLM status.</div>;
  const q = s.queue || {};
  const prod = s.mode === "production";
  return (
    <div className="card" style={{ padding: "14px 16px", marginBottom: 16, display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 240 }}>
        <span style={{ width: 10, height: 10, borderRadius: "50%", background: s.online ? "#16A34A" : "#DC2626", boxShadow: s.online ? "0 0 0 4px rgba(22,163,74,.15)" : "0 0 0 4px rgba(220,38,38,.15)" }} />
        <div>
          <div style={{ fontWeight: 700, fontSize: 14 }}>
            LLM: {prod ? "Production GPU server" : "Local"} · {s.online ? "online" : "offline"}
          </div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>
            {s.url || "not configured"}{!prod && s.detail?.model ? ` · ${s.detail.model}` : ""} · switch with <code>LLM_MODE</code> in .env
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 16, fontSize: 13, color: "var(--color-text-secondary)", marginLeft: "auto", flexWrap: "wrap" }}>
        <span>AI queue: <b>{q.queued || 0}</b> waiting</span>
        <span><b>{q.running || 0}</b> running</span>
        <span><b>{q.done || 0}</b> done</span>
        {q.failed ? <span style={{ color: "#B91C1C" }}><b>{q.failed}</b> failed</span> : null}
      </div>
      {!s.online && (q.queued || 0) > 0 && (
        <div style={{ width: "100%", fontSize: 12, color: "var(--color-warning)" }}>
          The LLM server isn't answering — {q.queued} document{q.queued !== 1 ? "s" : ""} will be sent one by one as soon as it's back. Uploads keep working meanwhile.
        </div>
      )}
    </div>
  );
}

/* ───────────────────────────────────────────────────────── rules */
function RulesTab() {
  const { toastSuccess, toastApiError } = useToast();
  const [rules, setRules] = useState([]);
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);   // rule object or {} for new

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get(API_ENDPOINTS.PLATFORM.DOC_RULES);
      const d = data?.data || data;
      setRules(d.rules || []);
      setTypes(d.doc_types || []);
    } catch (err) { toastApiError(err, "Could not load rules."); } finally { setLoading(false); }
  }, [toastApiError]);
  useEffect(() => { load(); }, [load]);

  async function toggle(rule) {
    try {
      await apiClient.patch(API_ENDPOINTS.PLATFORM.DOC_RULE(rule.id), { is_active: !rule.is_active });
      load();
    } catch (err) { toastApiError(err, "Could not update."); }
  }
  async function remove(rule) {
    if (!window.confirm(`Delete the rule “${rule.name}”?`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.PLATFORM.DOC_RULE(rule.id));
      toastSuccess("Rule deleted.");
      load();
    } catch (err) { toastApiError(err, "Could not delete."); }
  }

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <p style={{ margin: 0, fontSize: 13, color: "var(--color-text-muted)", flex: 1, minWidth: 260 }}>
          A document scores <b>hits ÷ required hits</b> for each type (4 of 5 = 80%). “Not medical” rules are the
          negative patterns. Changes apply to the next upload.
        </p>
        <button className="btn-primary" onClick={() => setEditing({})}>+ New rule</button>
      </div>

      {editing && (
        <RuleEditor rule={editing} types={types} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }} />
      )}

      {loading ? (
        <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>
      ) : (
        <div className="card" style={{ padding: 0, overflowX: "auto", marginBottom: 18 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 12 }}>
                <th style={th}>Type</th><th style={th}>Rule</th><th style={th}>Keywords</th>
                <th style={th}>100% at</th><th style={th}>Active</th><th style={th} />
              </tr>
            </thead>
            <tbody>
              {rules.map(r => (
                <tr key={r.id} style={{ borderTop: "1px solid var(--color-border)", opacity: r.is_active ? 1 : 0.55 }}>
                  <td style={td}><b>{TYPE_LABEL[r.doc_type] || r.doc_type}</b></td>
                  <td style={td}>{r.name}</td>
                  <td style={{ ...td, maxWidth: 420 }}>
                    <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>
                      {r.keywords.slice(0, 8).join(" | ")}{r.keyword_count > 8 ? ` … +${r.keyword_count - 8}` : ""}
                    </span>
                  </td>
                  <td style={td}>{r.required_hits} hits</td>
                  <td style={td}><input type="checkbox" checked={r.is_active} onChange={() => toggle(r)} /></td>
                  <td style={{ ...td, whiteSpace: "nowrap" }}>
                    <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => setEditing(r)}>Edit</button>{" "}
                    <button className="btn-outline" style={{ fontSize: 12, padding: "4px 10px", color: "var(--color-danger)" }} onClick={() => remove(r)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <TestBox />
    </>
  );
}

function RuleEditor({ rule, types, onClose, onSaved }) {
  const { toastSuccess, toastApiError } = useToast();
  const isNew = !rule.id;
  const [form, setForm] = useState({
    doc_type: rule.doc_type || (types[0]?.value ?? "prescription"),
    name: rule.name || "",
    keywords: (rule.keywords || []).join("\n"),
    required_hits: rule.required_hits || 5,
    is_active: rule.is_active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function save() {
    setBusy(true);
    const body = { ...form, keywords: form.keywords.split(/\n|\|/).map(s => s.trim()).filter(Boolean), required_hits: Number(form.required_hits) };
    try {
      if (isNew) await apiClient.post(API_ENDPOINTS.PLATFORM.DOC_RULES, body);
      else await apiClient.patch(API_ENDPOINTS.PLATFORM.DOC_RULE(rule.id), body);
      toastSuccess(isNew ? "Rule created." : "Rule saved.");
      onSaved();
    } catch (err) { toastApiError(err, "Could not save."); } finally { setBusy(false); }
  }

  const nKw = form.keywords.split(/\n|\|/).filter(s => s.trim()).length;
  return (
    <div className="card" style={{ padding: 16, marginBottom: 16, display: "grid", gap: 12 }}>
      <div style={{ fontWeight: 700 }}>{isNew ? "New rule" : `Edit “${rule.name}”`}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
        <label><span style={labelStyle}>Document type</span>
          <select style={inputStyle} value={form.doc_type} onChange={set("doc_type")}>
            {types.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
        <label><span style={labelStyle}>Rule name</span>
          <input style={inputStyle} value={form.name} onChange={set("name")} placeholder="e.g. Lab report — Indian labs" />
        </label>
        <label><span style={labelStyle}>Hits for 100%</span>
          <input style={inputStyle} type="number" min={1} max={50} value={form.required_hits} onChange={set("required_hits")} />
        </label>
      </div>
      <label><span style={labelStyle}>Keywords — one per line (or separated by |) · {nKw}</span>
        <textarea style={{ ...inputStyle, minHeight: 150, fontFamily: "monospace", fontSize: 12.5 }}
          value={form.keywords} onChange={set("keywords")} placeholder={"reference range\nmg/dl\nhaemoglobin"} />
      </label>
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
        <input type="checkbox" checked={form.is_active} onChange={set("is_active")} /> Active
      </label>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button className="btn-outline" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || !form.name.trim() || !nKw} onClick={save}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </div>
  );
}

function TestBox() {
  const { toastApiError } = useToast();
  const [text, setText] = useState("");
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const { data } = await apiClient.post(API_ENDPOINTS.PLATFORM.DOC_RULES_TEST, { text });
      setOut(data?.data || data);
    } catch (err) { toastApiError(err, "Could not run the test."); } finally { setBusy(false); }
  }

  const scores = out ? Object.entries(out.scores || {}).sort((a, b) => b[1].score - a[1].score) : [];
  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>Try the rules</div>
      <textarea style={{ ...inputStyle, minHeight: 110, fontSize: 12.5 }} value={text} onChange={e => setText(e.target.value)}
        placeholder="Paste the text of a document to see how the current rules classify it" />
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
        <button className="btn-primary" disabled={busy || text.trim().length < 10} onClick={run}>{busy ? "Checking…" : "Classify"}</button>
      </div>
      {out && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13.5, marginBottom: 10 }}>
            Verdict: <b>{TYPE_LABEL[out.kind] || out.kind}</b> · confidence {pctText(out.confidence)}
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {scores.map(([t, s]) => (
              <div key={t} style={{ display: "grid", gridTemplateColumns: "140px 1fr 70px", gap: 10, alignItems: "center", fontSize: 12.5 }}>
                <span>{TYPE_LABEL[t] || t}</span>
                <div style={{ height: 6, borderRadius: 6, background: "var(--color-border)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.round(s.score * 100)}%`, background: "var(--color-primary)" }} />
                </div>
                <span style={{ fontFamily: "monospace", color: "var(--color-text-muted)" }}>{s.hits}/{s.required} · {pctText(s.score)}</span>
                {s.matched?.length > 0 && (
                  <span style={{ gridColumn: "2 / 4", fontSize: 11, color: "var(--color-text-muted)", marginTop: -4 }}>{s.matched.join(" · ")}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ───────────────────────────────────────────────────────── report */
function ReportTab() {
  const { toastApiError } = useToast();
  const [r, setR] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data } = await apiClient.get(API_ENDPOINTS.PLATFORM.DOC_CLASSIFICATION_REPORT);
      setR(data?.data || data);
    } catch (err) { toastApiError(err, "Could not load the report."); }
  }, [toastApiError]);
  useEffect(() => { load(); }, [load]);

  if (!r) return <div className="card" style={{ padding: 30, textAlign: "center", color: "var(--color-text-muted)" }}>Loading…</div>;

  const Stat = ({ label, value, sub }) => (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, fontFamily: "var(--font-display)", fontVariantNumeric: "tabular-nums" }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>{sub}</div>}
    </div>
  );
  const pair = (p) => p.compared ? `${p.agree} agree · ${p.disagree} differ (of ${p.compared})` : "No overlap yet";
  const humanTypes = Object.keys(r.confusion || {});
  const predTypes = [...new Set(humanTypes.flatMap(h => Object.keys(r.confusion[h])))];

  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
        <button className="btn-outline" style={{ fontSize: 12.5 }} onClick={load}>Refresh</button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, marginBottom: 16 }}>
        <Stat label="Patient uploads" value={r.totals.documents} sub={`${r.totals.human_labelled} confirmed by a person · LLM ran on ${r.totals.llm_ran}`} />
        <Stat label="Rules vs person" value={pctText(r.rule_vs_human.rate)} sub={pair(r.rule_vs_human)} />
        <Stat label="LLM vs person" value={pctText(r.llm_vs_human.rate)} sub={pair(r.llm_vs_human)} />
        <Stat label="Rules vs LLM" value={pctText(r.rule_vs_llm.rate)} sub={pair(r.rule_vs_llm)} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12, marginBottom: 16 }}>
        <CountCard title="Processing status" counts={r.processing_status}
          order={["queued", "extracting", "classifying", "done", "failed"]} />
        <CountCard title="Classification status" counts={r.classification_status}
          order={["pending", "partial", "closed"]}
          labels={{ pending: "Pending", partial: "Partial — awaiting person", closed: "Closed" }} />
        <CountCard title="Person's verdict" counts={r.human_actions}
          order={["accepted", "changed", "rejected"]} labels={{ accepted: "Thumbs up", changed: "Changed", rejected: "Rejected" }} />
      </div>

      {humanTypes.length > 0 && (
        <div className="card" style={{ padding: 16, marginBottom: 16, overflowX: "auto" }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Rules vs person, by type</div>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 10 }}>Rows: what the person said. Columns: what the rules said.</div>
          <table style={{ borderCollapse: "collapse", fontSize: 12.5 }}>
            <thead>
              <tr><th style={th} />{predTypes.map(p => <th key={p} style={th}>{TYPE_LABEL[p] || p}</th>)}</tr>
            </thead>
            <tbody>
              {humanTypes.map(h => (
                <tr key={h} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <td style={{ ...td, fontWeight: 600 }}>{TYPE_LABEL[h] || h}</td>
                  {predTypes.map(p => (
                    <td key={p} style={{ ...td, textAlign: "center", fontVariantNumeric: "tabular-nums",
                      fontWeight: p === h ? 700 : 400, color: p === h ? "var(--color-success, #1F8F6E)" : (r.confusion[h][p] ? "var(--color-error)" : "var(--color-text-muted)") }}>
                      {r.confusion[h][p] || "·"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card" style={{ padding: 16, overflowX: "auto" }}>
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Recent disagreements</div>
        {r.recent_disagreements.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>None yet.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
            <thead><tr style={{ textAlign: "left", color: "var(--color-text-muted)" }}>
              <th style={th}>Doc</th><th style={th}>Rules</th><th style={th}>LLM</th><th style={th}>Person</th><th style={th}>When</th>
            </tr></thead>
            <tbody>
              {r.recent_disagreements.map(x => (
                <tr key={x.id} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <td style={td}>#{x.id} {x.title}</td>
                  <td style={td}>{x.rule_doc_type ? `${TYPE_LABEL[x.rule_doc_type] || x.rule_doc_type} ${pctText(x.rule_confidence)}` : "—"}</td>
                  <td style={td}>{x.llm_doc_type ? `${TYPE_LABEL[x.llm_doc_type] || x.llm_doc_type} ${pctText(x.llm_confidence)}` : "—"}</td>
                  <td style={{ ...td, fontWeight: 600 }}>{TYPE_LABEL[x.human_doc_type] || x.human_doc_type}</td>
                  <td style={td}>{x.human_at ? new Date(x.human_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function CountCard({ title, counts = {}, order, labels = {} }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>{title}</div>
      {order.map(k => (
        <div key={k} style={{ display: "grid", gridTemplateColumns: "1fr 100px 36px", gap: 10, alignItems: "center", fontSize: 12.5, marginBottom: 6 }}>
          <span style={{ textTransform: labels[k] ? "none" : "capitalize" }}>{labels[k] || k}</span>
          <div style={{ height: 6, borderRadius: 6, background: "var(--color-border)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: total ? `${((counts[k] || 0) / total) * 100}%` : 0, background: "var(--color-primary)" }} />
          </div>
          <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{counts[k] || 0}</span>
        </div>
      ))}
    </div>
  );
}

const th = { padding: "9px 12px", fontWeight: 600 };
const td = { padding: "9px 12px", verticalAlign: "top" };
