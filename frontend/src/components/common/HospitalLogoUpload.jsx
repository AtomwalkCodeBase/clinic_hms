/**
 * components/common/HospitalLogoUpload.jsx
 * -------------------------------------------
 * Rectangular logo uploader for a hospital's own branding (Tenant.logo) —
 * companion to ProfilePhotoUpload.jsx, but deliberately NOT circular (logos
 * are usually wide wordmarks, not square headshots) and kept as PNG rather
 * than re-encoded to JPEG, so a logo with a transparent background stays
 * transparent instead of gaining a white/black fill.
 *
 * Downsizes client-side (max 480x200) before uploading via PATCH
 * /org/settings/ — same base64-in-a-TextField storage convention as
 * StaffUser.photo (see apps.tenants.Tenant.logo), no object storage wired
 * up yet.
 */
import { useRef, useState } from "react";
import apiClient    from "../../services/api.client";
import { useToast } from "../../hooks/useToast";

const MAX_WIDTH  = 480;
const MAX_HEIGHT = 200;

function resizeToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.onload = () => {
      img.onerror = () => reject(new Error("Not a valid image."));
      img.onload = () => {
        let { width, height } = img;
        const scale = Math.min(MAX_WIDTH / width, MAX_HEIGHT / height, 1);
        width  = Math.round(width * scale);
        height = Math.round(height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        // PNG, not JPEG — preserves transparency for logos that have it.
        canvas.getContext("2d").drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL("image/png"));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

export default function HospitalLogoUpload({ logo, onUploaded }) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving]   = useState(false);
  const { toastSuccess, toastApiError } = useToast();

  async function handleFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toastApiError({ message: "Please choose an image file." }, "Invalid file.");
      return;
    }
    setUploading(true);
    try {
      const dataUrl = await resizeToDataUrl(file);
      const { data: res } = await apiClient.patch("/org/settings/", { logo: dataUrl });
      onUploaded?.(res?.data?.logo ?? dataUrl);
      toastSuccess("Hospital logo updated.");
    } catch (err) {
      toastApiError(err, "Could not upload logo.");
    } finally {
      setUploading(false);
    }
  }

  async function handleRemove() {
    if (!window.confirm("Remove your hospital's logo? Every login will fall back to the default monogram.")) return;
    setRemoving(true);
    try {
      await apiClient.patch("/org/settings/", { logo: "" });
      onUploaded?.("");
      toastSuccess("Logo removed.");
    } catch (err) {
      toastApiError(err, "Could not remove logo.");
    } finally {
      setRemoving(false);
    }
  }

  const busy = uploading || removing;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
      <div style={{
        width: 200, height: 84, borderRadius: 10, overflow: "hidden",
        background: "var(--color-bg)", border: "1.5px dashed var(--color-border)",
        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
      }}>
        {logo
          ? <img src={logo} alt="Hospital logo" style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} />
          : <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>No logo yet</span>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button
            type="button" className="btn-outline"
            style={{ fontSize: 12, padding: "6px 14px" }}
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            {uploading ? "Uploading…" : logo ? "Change logo" : "Upload logo"}
          </button>
          {logo && (
            <button
              type="button"
              style={{
                fontSize: 12, padding: "6px 10px", fontWeight: 600,
                background: "none", border: "none", cursor: busy ? "not-allowed" : "pointer",
                color: "var(--color-error, #b91c1c)", textDecoration: "underline",
              }}
              disabled={busy}
              onClick={handleRemove}
            >
              {removing ? "Removing…" : "Remove logo"}
            </button>
          )}
          <input ref={inputRef} type="file" accept="image/*" hidden onChange={handleFile} />
        </div>
        <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", maxWidth: 360 }}>
          Shown in place of your hospital's initials across every staff login, and to patients browsing or booking with your hospital. PNG with a transparent background works best.
        </div>
      </div>
    </div>
  );
}
