/**
 * components/common/ProfilePhotoUpload.jsx
 * --------------------------------------------
 * Circular avatar with an upload button. Reads the chosen image, downsizes
 * it client-side (max 480px, JPEG ~0.82 quality) so it comfortably fits the
 * base64-in-a-TextField storage used by StaffUser.photo, then uploads it via
 * PATCH /org/me/profile/ and calls onUploaded(newPhoto) with the result.
 *
 * No object storage is wired up yet, so photos live as base64 data URIs —
 * fine for avatar-sized images, not meant for anything larger.
 */
import { useRef, useState } from "react";
import apiClient     from "../../services/api.client";
import API_ENDPOINTS from "../../config/api.config";
import { useToast }  from "../../hooks/useToast";

const MAX_DIMENSION = 480;
const JPEG_QUALITY   = 0.82;

function resizeToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.onload = () => {
      img.onerror = () => reject(new Error("Not a valid image."));
      img.onload = () => {
        let { width, height } = img;
        if (width > height && width > MAX_DIMENSION) {
          height = Math.round(height * (MAX_DIMENSION / width));
          width  = MAX_DIMENSION;
        } else if (height > MAX_DIMENSION) {
          width  = Math.round(width * (MAX_DIMENSION / height));
          height = MAX_DIMENSION;
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        canvas.getContext("2d").drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL("image/jpeg", JPEG_QUALITY));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

export default function ProfilePhotoUpload({
  photo, onUploaded, size = 72, initials = "?",
  endpoint = API_ENDPOINTS.ORG.MY_PROFILE,
  // "dark" renders the button legible on a dark hero/gradient background
  // (My Profile's hero header) instead of the default green outline button.
  variant = "light",
  avatarBorderColor,
}) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const { toastSuccess, toastApiError } = useToast();

  async function handleFile(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toastApiError({ message: "Please choose an image file." }, "Invalid file.");
      return;
    }
    setUploading(true);
    try {
      const dataUrl = await resizeToDataUrl(file);
      const { data: res } = await apiClient.patch(endpoint, { photo: dataUrl });
      onUploaded?.(res?.data?.photo ?? dataUrl);
      toastSuccess("Photo updated.");
    } catch (err) {
      toastApiError(err, "Could not upload photo.");
    } finally {
      setUploading(false);
    }
  }

  async function handleRemove() {
    if (!window.confirm("Remove your profile photo?")) return;
    setRemoving(true);
    try {
      // Both StaffUser.photo and PatientAccount.photo are TextField(blank=True)
      // with no null=True, so "no photo" is represented as "" — not null —
      // matching the model's own storage convention.
      await apiClient.patch(endpoint, { photo: "" });
      onUploaded?.("");
      toastSuccess("Photo removed.");
    } catch (err) {
      toastApiError(err, "Could not remove photo.");
    } finally {
      setRemoving(false);
    }
  }

  const dark = variant === "dark";
  const busy = uploading || removing;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
      <div style={{
        width: size, height: size, borderRadius: "50%", overflow: "hidden",
        background: dark ? "color-mix(in srgb, var(--color-hero-text) 10%, transparent)" : "var(--color-primary-light)",
        color: dark ? "#fff" : "var(--color-primary)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: dark ? "var(--font-display)" : undefined,
        fontSize: size * 0.36, fontWeight: dark ? 600 : 700, flexShrink: 0,
        border: `2px solid ${avatarBorderColor || (dark ? "var(--color-accent)" : "var(--color-border)")}`,
      }}>
        {photo
          ? <img src={photo} alt="Profile" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          : initials}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          className={dark ? undefined : "btn-outline"}
          style={dark ? {
            fontSize: 12, padding: "6px 14px", fontWeight: 700, borderRadius: "var(--radius-button)",
            background: "color-mix(in srgb, var(--color-hero-text) 14%, transparent)", color: "#fff", border: "1px solid color-mix(in srgb, var(--color-hero-text) 35%, transparent)",
          } : { fontSize: 12, padding: "6px 14px" }}
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {uploading ? "Uploading…" : photo ? "Change photo" : "Upload photo"}
        </button>
        {photo && (
          <button
            type="button"
            style={{
              fontSize: 12, padding: "6px 10px", fontWeight: 600,
              background: "none", border: "none", cursor: busy ? "not-allowed" : "pointer",
              color: dark ? "color-mix(in srgb, var(--color-hero-text) 70%, transparent)" : "var(--color-error, #b91c1c)",
              textDecoration: "underline",
            }}
            disabled={busy}
            onClick={handleRemove}
          >
            {removing ? "Removing…" : "Remove photo"}
          </button>
        )}
        <input
          ref={inputRef} type="file" accept="image/*" hidden
          onChange={handleFile}
        />
      </div>
    </div>
  );
}
