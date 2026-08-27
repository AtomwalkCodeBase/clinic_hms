/**
 * pages/hospital-admin/BillingSetupPage.jsx
 * ------------------------------------------
 * Hospital admin: everything about billing that used to be hardcoded.
 *   - Registration fee (on/off + amount) and default tax rate — tenant-wide.
 *   - Service catalog (price list) — full CRUD, was previously DB-only.
 *   - Three configurable dropdown lists (service categories, payment modes,
 *     invoice statuses) that replace what used to be fixed choices= lists
 *     on the backend models. Seeded "system" values can be relabelled but
 *     not removed (the backend's own logic depends on a few of them); a
 *     hospital can add its own custom entries alongside them.
 */
import { useState, useEffect, useCallback } from "react";
import { AppShell }  from "../../components/layout/AppShell";
import { PageShell } from "../../components/common/PageShell";
import apiClient     from "../../services/api.client";
import { useToast }  from "../../hooks/useToast";
import API_ENDPOINTS from "../../config/api.config";
import { Receipt, Tag, ListChecks, Lock } from "lucide-react";

const inputStyle = {
  boxSizing: "border-box",
  border: "1.5px solid var(--color-border)", borderRadius: 8,
  padding: "8px 12px", fontSize: 13,
  background: "var(--color-surface)", color: "var(--color-text)", outline: "none",
};
const labelStyle = { display: "block", fontSize: 12, fontWeight: 600, marginBottom: 5, color: "var(--color-text-muted)" };

function SectionCard({ icon: Icon, title, subtitle, children }) {
  return (
    <div className="card" style={{ padding: 20, marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        {Icon && <Icon size={17} style={{ color: "var(--color-primary)" }} />}
        <h3 style={{ margin: 0, fontSize: 15 }}>{title}</h3>
      </div>
      {subtitle && <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 14 }}>{subtitle}</div>}
      {children}
    </div>
  );
}

// ── Tenant-wide billing settings (registration fee, default tax rate) ──────
// Both amount fields used to be uncontrolled (defaultValue + onBlur) — that
// meant a failed save (e.g. clearing the field to blank, or a stray value
// outside 0-100 for tax) left the input showing whatever the admin typed
// with no way to tell it hadn't actually been saved, and a successful save
// never visibly reflected the server's normalized value either, since a
// defaultValue prop is only ever read once at mount. Rewritten as fully
// controlled: local text state tracks what's on screen, client-side range
// validation runs before the request goes out, and on any failure — client
// or server-side — the field snaps back to the last known-good saved value
// instead of sitting there silently wrong.
function TenantBillingSettings() {
  const { toastSuccess, toastApiError, toastError } = useToast();
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [regFeeInput, setRegFeeInput] = useState("");
  const [taxRateInput, setTaxRateInput] = useState("");

  const load = useCallback(() => {
    apiClient.get("/org/settings/")
      .then(r => {
        const s = r.data?.data || r.data;
        setSettings(s);
        setRegFeeInput(String(s.registration_fee_amount ?? ""));
        setTaxRateInput(String(s.default_tax_rate ?? ""));
      })
      .catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save(patch) {
    setSaving(true);
    try {
      const { data: res } = await apiClient.patch("/org/settings/", patch);
      const updated = res.data || {};
      setSettings(s => ({ ...s, ...updated }));
      // Re-sync the specific field(s) just saved to the server's own
      // (normalized/rounded) value, so the field always shows exactly
      // what's actually stored rather than the raw text the admin typed.
      if ("registration_fee_amount" in updated) setRegFeeInput(String(updated.registration_fee_amount));
      if ("default_tax_rate" in updated) setTaxRateInput(String(updated.default_tax_rate));
      toastSuccess("Billing settings saved.");
    } catch (err) {
      toastApiError(err, "Could not save settings.");
      // Revert the visible field to the last known-good value — otherwise
      // a rejected save (e.g. an out-of-range or non-numeric value) leaves
      // the input showing something that was never actually saved.
      if ("registration_fee_amount" in patch) setRegFeeInput(String(settings?.registration_fee_amount ?? ""));
      if ("default_tax_rate" in patch) setTaxRateInput(String(settings?.default_tax_rate ?? ""));
    } finally {
      setSaving(false);
    }
  }

  function saveRegFee() {
    const trimmed = regFeeInput.trim();
    const num = Number(trimmed);
    if (trimmed === "" || Number.isNaN(num) || num < 0) {
      toastError("Registration fee must be a number of 0 or more.");
      setRegFeeInput(String(settings.registration_fee_amount ?? ""));
      return;
    }
    if (String(num) === String(settings.registration_fee_amount)) return; // unchanged, skip the round-trip
    save({ registration_fee_amount: num });
  }

  function saveTaxRate() {
    const trimmed = taxRateInput.trim();
    const num = Number(trimmed);
    if (trimmed === "" || Number.isNaN(num) || num < 0 || num > 100) {
      toastError("Default tax rate must be a number between 0 and 100.");
      setTaxRateInput(String(settings.default_tax_rate ?? ""));
      return;
    }
    if (String(num) === String(settings.default_tax_rate)) return;
    save({ default_tax_rate: num });
  }

  if (!settings) return <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Loading…</div>;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <label style={{ fontSize: 13, fontWeight: 600 }}>Charge a registration fee</label>
          <button
            type="button"
            onClick={() => save({ registration_fee_enabled: !(settings.registration_fee_enabled === true || settings.registration_fee_enabled === "true") })}
            disabled={saving}
            style={{
              width: 40, height: 22, borderRadius: 11, border: "none", cursor: "pointer", position: "relative", flexShrink: 0,
              background: (settings.registration_fee_enabled === true || settings.registration_fee_enabled === "true") ? "var(--color-primary)" : "var(--color-border)",
            }}>
            <span style={{
              position: "absolute", top: 2,
              left: (settings.registration_fee_enabled === true || settings.registration_fee_enabled === "true") ? 20 : 2,
              width: 18, height: 18, borderRadius: "50%", background: "#fff", transition: "left 0.15s",
            }} />
          </button>
        </div>
        <label style={labelStyle}>Amount (₹) — charged once, when a patient is registered at the desk</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            style={{ ...inputStyle, width: 140 }} type="number" min="0" step="0.01"
            value={regFeeInput} disabled={saving}
            onChange={e => setRegFeeInput(e.target.value)}
            onBlur={saveRegFee}
            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
          />
        </div>
      </div>

      <div>
        <label style={labelStyle}>Default tax rate (%) — used whenever a billed item doesn't set its own tax rate (auto-generated consultation &amp; registration invoices, and any custom line item added without a tax %)</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            style={{ ...inputStyle, width: 100 }} type="number" min="0" max="100" step="0.01"
            value={taxRateInput} disabled={saving}
            onChange={e => setTaxRateInput(e.target.value)}
            onBlur={saveTaxRate}
            onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
          />
          <span style={{ fontSize: 13, color: "var(--color-text-muted)" }}>%</span>
        </div>
      </div>
    </div>
  );
}

// Small pill toggle, reused for per-item "accepted" switches below —
// same visual language as the bigger toggles in TenantBillingSettings above.
function MiniToggle({ checked, onChange, disabled }) {
  return (
    <button
      type="button" onClick={onChange} disabled={disabled}
      title={checked ? "Accepted — click to turn off" : "Not accepted — click to turn on"}
      style={{
        width: 30, height: 17, borderRadius: 9, border: "none", flexShrink: 0,
        background: checked ? "var(--color-primary)" : "var(--color-border)",
        cursor: disabled ? "default" : "pointer", position: "relative", transition: "background 0.15s",
      }}>
      <span style={{
        position: "absolute", top: 2, left: checked ? 15 : 2,
        width: 13, height: 13, borderRadius: "50%", background: "#fff", transition: "left 0.15s",
      }} />
    </button>
  );
}

// ── Generic configurable dropdown list (service categories / payment modes
//    / invoice statuses) — one small CRUD block, reused three times below.
//    toggleable=true (Payment Modes) additionally fetches inactive entries
//    and shows an is_active switch per item — this is what the hospital
//    actually accepts, reflected to patients at booking time. ──
function DropdownListEditor({ title, listEndpoint, itemEndpoint, identityField, extraFields, toggleable, helpText }) {
  const { toastSuccess, toastApiError } = useToast();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(() => {
    const f = { [identityField]: "" };
    (extraFields || []).forEach(ef => { f[ef.name] = ef.default ?? ""; });
    return f;
  });
  const [saving, setSaving] = useState(false);
  const [togglingId, setTogglingId] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    apiClient.get(toggleable ? `${listEndpoint}?all=1` : listEndpoint)
      .then(r => setItems(r.data?.data || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [listEndpoint, toggleable]);
  useEffect(() => { load(); }, [load]);

  async function toggleActive(item) {
    setTogglingId(item.id);
    try {
      await apiClient.patch(itemEndpoint(item.id), { is_active: !item.is_active });
      setItems(its => its.map(i => i.id === item.id ? { ...i, is_active: !i.is_active } : i));
    } catch (err) {
      toastApiError(err, "Could not update.");
    } finally {
      setTogglingId(null);
    }
  }

  async function addItem(e) {
    e.preventDefault();
    if (!String(form[identityField] || "").trim()) return;
    setSaving(true);
    try {
      await apiClient.post(listEndpoint, form);
      toastSuccess("Added.");
      setForm(f => ({ ...f, [identityField]: "" }));
      load();
    } catch (err) {
      toastApiError(err, "Could not add.");
    } finally {
      setSaving(false);
    }
  }

  async function removeItem(item) {
    if (item.is_system) return;
    if (!confirm(`Remove "${item[identityField]}"?`)) return;
    try {
      await apiClient.delete(itemEndpoint(item.id));
      toastSuccess("Removed.");
      load();
    } catch (err) {
      toastApiError(err, "Could not remove.");
    }
  }

  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 2 }}>{title}</div>
      {helpText && <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginBottom: 10 }}>{helpText}</div>}
      {loading ? (
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
          {items.map(item => (
            <span key={item.id} style={{
              display: "inline-flex", alignItems: "center", gap: 7,
              fontSize: 12, fontWeight: 600, padding: "4px 8px 4px 10px", borderRadius: 999,
              background: "var(--color-bg)", border: "1px solid var(--color-border)",
              opacity: toggleable && !item.is_active ? 0.55 : 1,
            }}>
              {item.is_system && <Lock size={10} style={{ color: "var(--color-text-muted)" }} />}
              {item.label || item[identityField]}
              {toggleable && (
                <MiniToggle checked={item.is_active} disabled={togglingId === item.id}
                  onChange={() => toggleActive(item)} />
              )}
              {!item.is_system && (
                <button type="button" onClick={() => removeItem(item)}
                  style={{ background: "none", border: "none", cursor: "pointer", padding: 0, lineHeight: 1, color: "var(--color-text-muted)" }}>
                  ✕
                </button>
              )}
            </span>
          ))}
          {items.length === 0 && <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontStyle: "italic" }}>Nothing configured yet.</span>}
        </div>
      )}
      <form onSubmit={addItem} style={{ display: "flex", gap: 8 }}>
        <input
          style={{ ...inputStyle, flex: 1 }}
          placeholder={`Add a custom ${title.toLowerCase().replace(/s$/, "")}…`}
          value={form[identityField]}
          onChange={e => setForm(f => ({ ...f, [identityField]: e.target.value }))}
        />
        {identityField === "value" && (
          <input
            style={{ ...inputStyle, width: 140 }}
            placeholder="Label"
            value={form.label || ""}
            onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
          />
        )}
        <button type="submit" disabled={saving} className="btn-outline" style={{ fontSize: 12, padding: "8px 16px" }}>
          {saving ? "…" : "+ Add"}
        </button>
      </form>
    </div>
  );
}

const EMPTY_SERVICE = { name: "", code: "", category: "", unit_price: "", tax_rate: "" };

// ── Service (price) catalog — full CRUD ─────────────────────────────────────
function ServiceCatalog() {
  const { toastSuccess, toastApiError } = useToast();
  const [services, setServices] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(EMPTY_SERVICE);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      apiClient.get(API_ENDPOINTS.BILLING.SERVICES),
      apiClient.get(API_ENDPOINTS.BILLING.SERVICE_CATEGORIES),
    ])
      .then(([svcRes, catRes]) => {
        setServices(svcRes.data?.data || []);
        setCategories(catRes.data?.data || []);
      })
      .catch(() => { setServices([]); setCategories([]); })
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  function startEdit(svc) {
    setEditingId(svc.id);
    setForm({ name: svc.name, code: svc.code || "", category: svc.category, unit_price: svc.unit_price, tax_rate: svc.tax_rate });
  }
  function cancelEdit() {
    setEditingId(null);
    setForm(EMPTY_SERVICE);
  }

  async function submit(e) {
    e.preventDefault();
    if (!form.name || !form.unit_price) return;
    setSaving(true);
    const payload = {
      name: form.name, code: form.code, category: form.category || (categories[0]?.name || "Other"),
      unit_price: Number(form.unit_price), tax_rate: form.tax_rate === "" ? 0 : Number(form.tax_rate),
    };
    try {
      if (editingId) {
        await apiClient.patch(API_ENDPOINTS.BILLING.SERVICE(editingId), payload);
        toastSuccess("Service updated.");
      } else {
        await apiClient.post(API_ENDPOINTS.BILLING.SERVICES, payload);
        toastSuccess("Service added.");
      }
      cancelEdit();
      load();
    } catch (err) {
      toastApiError(err, "Could not save service.");
    } finally {
      setSaving(false);
    }
  }

  async function deactivate(svc) {
    if (!confirm(`Remove "${svc.name}" from the price catalog?`)) return;
    try {
      await apiClient.delete(API_ENDPOINTS.BILLING.SERVICE(svc.id));
      toastSuccess("Service removed.");
      load();
    } catch (err) {
      toastApiError(err, "Could not remove.");
    }
  }

  return (
    <div>
      <form onSubmit={submit} style={{
        display: "grid", gridTemplateColumns: "1.4fr 0.8fr 1fr 0.7fr 0.6fr auto auto", gap: 8,
        alignItems: "end", marginBottom: 16, padding: 12, borderRadius: 10, background: "var(--color-bg)",
      }}>
        <div>
          <label style={labelStyle}>Name</label>
          <input style={inputStyle} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. General Consultation" required />
        </div>
        <div>
          <label style={labelStyle}>Code</label>
          <input style={inputStyle} value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} placeholder="optional" />
        </div>
        <div>
          <label style={labelStyle}>Category</label>
          <select style={inputStyle} value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}>
            <option value="">Select…</option>
            {categories.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Price (₹)</label>
          <input style={inputStyle} type="number" min="0" step="0.01" value={form.unit_price} onChange={e => setForm(f => ({ ...f, unit_price: e.target.value }))} required />
        </div>
        <div>
          <label style={labelStyle}>Tax %</label>
          <input style={inputStyle} type="number" min="0" max="100" step="0.01" value={form.tax_rate} onChange={e => setForm(f => ({ ...f, tax_rate: e.target.value }))} placeholder="0" />
        </div>
        <button type="submit" disabled={saving} className="btn-primary" style={{ fontSize: 12, padding: "8px 14px" }}>
          {saving ? "…" : editingId ? "Update" : "+ Add"}
        </button>
        {editingId && (
          <button type="button" onClick={cancelEdit} className="btn-outline" style={{ fontSize: 12, padding: "8px 14px" }}>
            Cancel
          </button>
        )}
      </form>

      {loading ? (
        <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>Loading…</div>
      ) : services.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--color-text-muted)", fontStyle: "italic" }}>No services in the price catalog yet — add one above.</div>
      ) : (
        <div style={{ display: "grid", gap: 6 }}>
          {services.map(svc => (
            <div key={svc.id} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "8px 12px", borderRadius: 8, background: "var(--color-surface)", border: "1px solid var(--color-border)",
            }}>
              <div style={{ fontSize: 13 }}>
                <strong>{svc.name}</strong>
                <span style={{ color: "var(--color-text-muted)" }}> · {svc.category} · ₹{svc.unit_price}{Number(svc.tax_rate) > 0 && ` +${svc.tax_rate}% tax`}</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => startEdit(svc)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, fontWeight: 600, color: "var(--color-primary)" }}>Edit</button>
                <button onClick={() => deactivate(svc)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, fontWeight: 600, color: "var(--color-error)" }}>Remove</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function BillingSetupPage() {
  return (
    <AppShell>
      <PageShell title="Billing Setup">
        <SectionCard icon={Receipt} title="Registration Fee & Tax"
          subtitle="Off/zero by default — nothing changes for a hospital that doesn't touch this.">
          <TenantBillingSettings />
        </SectionCard>

        <SectionCard icon={Tag} title="Service Price Catalog"
          subtitle="What front desk picks from when billing a patient (Billing → Bill).">
          <ServiceCatalog />
        </SectionCard>

        <SectionCard icon={ListChecks} title="Configurable Lists"
          subtitle="Replaces what used to be fixed dropdowns — add your own values, system ones (marked with a lock) can be relabelled but not removed.">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 24 }}>
            <DropdownListEditor
              title="Service Categories"
              listEndpoint={API_ENDPOINTS.BILLING.SERVICE_CATEGORIES}
              itemEndpoint={API_ENDPOINTS.BILLING.SERVICE_CATEGORY}
              identityField="name"
            />
            <DropdownListEditor
              title="Payment Modes"
              listEndpoint={API_ENDPOINTS.BILLING.PAYMENT_MODES}
              itemEndpoint={API_ENDPOINTS.BILLING.PAYMENT_MODE}
              identityField="name"
              toggleable
              helpText="Switch off what you don't accept — patients see the remaining ones when booking. 'Online' needs a payment gateway connected before it actually works; leave it off until then."
            />
            <DropdownListEditor
              title="Invoice Statuses"
              listEndpoint={API_ENDPOINTS.BILLING.INVOICE_STATUSES}
              itemEndpoint={API_ENDPOINTS.BILLING.INVOICE_STATUS}
              identityField="value"
            />
          </div>
        </SectionCard>
      </PageShell>
    </AppShell>
  );
}
