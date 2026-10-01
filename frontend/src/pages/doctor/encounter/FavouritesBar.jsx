import { useToast } from "../../../hooks/useToast";
import { useApi } from "../../../hooks/useApi";
import API_ENDPOINTS from "../../../config/api.config";
import { useState } from "react";
import { encounterApi } from "../../../api";
import { miniBtn } from "./styles";

// Doctor's saved drug bundles (apps.opd.PrescriptionFavourite) — one click
// re-adds every item in a bundle via the same POST DrugForm's "+ Add Drug"
// uses, or the current Rx can be saved as a new bundle for next time.
export function FavouritesBar({ currentItems, onApply, disabled }) {
  const { toastSuccess, toastApiError } = useToast();
  const { data: favData, refetch: refetchFavs } = useApi(API_ENDPOINTS.OPD.FAVOURITES);
  const favourites = favData || [];
  const [namingOpen, setNamingOpen] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [applyingId, setApplyingId] = useState(null);

  async function saveCurrent() {
    if (!name.trim() || !currentItems.length || saving) return;
    setSaving(true);
    try {
      const items = currentItems.map(it => ({
        drug_name: it.drug_name, dosage: it.dosage, frequency: it.frequency,
        route: it.route, duration_days: it.duration_days ?? null,
        instructions: it.instructions || "",
      }));
      await encounterApi.createFavourite(name.trim(), items);
      toastSuccess("Saved as favourite.");
      setName("");
      setNamingOpen(false);
      refetchFavs();
    } catch (err) {
      toastApiError(err, "Could not save this favourite — a bundle with that name may already exist.");
    } finally {
      setSaving(false);
    }
  }

  async function applyFav(fav) {
    if (applyingId) return;
    setApplyingId(fav.id);
    try {
      await onApply(fav.items || []);
    } finally {
      setApplyingId(null);
    }
  }

  async function removeFav(fav) {
    try {
      await encounterApi.deleteFavourite(fav.id);
      refetchFavs();
    } catch (err) {
      toastApiError(err, "Could not delete this favourite.");
    }
  }

  if (disabled && favourites.length === 0) return null;

  return (
    <div style={{ marginBottom: 10 }}>
      {favourites.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {favourites.map(fav => (
            <span key={fav.id} style={{
              display: "inline-flex", alignItems: "center", gap: 2,
              border: "1px solid var(--color-primary)", borderRadius: 6, overflow: "hidden",
            }}>
              <button
                type="button" onClick={() => applyFav(fav)}
                disabled={disabled || applyingId === fav.id}
                title={(fav.items || []).map(i => i.drug_name).join(", ")}
                style={{
                  fontSize: 11, fontWeight: 600, padding: "4px 8px", border: "none",
                  background: "transparent", color: "var(--color-primary)",
                  cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
                }}
              >
                {applyingId === fav.id ? "Adding…" : `☆ ${fav.name} (${(fav.items || []).length})`}
              </button>
              {!disabled && (
                <button
                  type="button" onClick={() => removeFav(fav)} aria-label={`Delete favourite ${fav.name}`}
                  style={{
                    fontSize: 11, padding: "4px 6px", border: "none", borderLeft: "1px solid var(--color-primary)",
                    background: "transparent", color: "var(--color-text-muted)", cursor: "pointer",
                  }}
                >
                  ×
                </button>
              )}
            </span>
          ))}
        </div>
      )}
      {!disabled && (
        namingOpen ? (
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            <input
              className="form-input" value={name} onChange={e => setName(e.target.value)}
              placeholder="Bundle name — e.g. Fever Bundle" style={{ fontSize: 12, flex: 1 }}
              autoFocus
            />
            <button type="button" onClick={saveCurrent} disabled={saving || !name.trim() || !currentItems.length}
              style={miniBtn("var(--color-primary)", "#fff", "var(--color-primary)", saving || !name.trim() || !currentItems.length)}>
              Save
            </button>
            <button type="button" onClick={() => { setNamingOpen(false); setName(""); }}
              style={miniBtn("var(--color-border)", "var(--color-text-muted)", "transparent", false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button
            type="button" onClick={() => setNamingOpen(true)} disabled={!currentItems.length}
            style={miniBtn("var(--color-border)", "var(--color-text-muted)", "transparent", !currentItems.length)}
          >
            ☆ Save current Rx as favourite
          </button>
        )
      )}
    </div>
  );
}
