import { useState, useRef } from "react";
import { Mic, Square, Upload } from "lucide-react";
import { transcribeAudio } from "./transcribe";

export function DictateButton({ onTranscript, disabled }) {
  const [state, setState] = useState("idle"); // idle | rec | busy
  const recRef = useRef(null);
  const chunksRef = useRef([]);
  const fileInputRef = useRef(null);

  async function toggle() {
    if (disabled || state === "busy") return;
    if (state === "rec") { recRef.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = e => { if (e.data.size) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        setState("busy");
        try {
          const blob = new Blob(chunksRef.current, { type: mr.mimeType || "audio/webm" });
          const text = await transcribeAudio(blob, "dictation.webm");
          if (text.trim()) onTranscript(text.trim());
          else window.alert("Nothing was transcribed — please try again, speaking clearly.");
        } catch (err) {
          window.alert(err?.data?.error || err?.message || "Transcription failed. Is faster-whisper installed on the server?");
        }
        setState("idle");
      };
      mr.start();
      recRef.current = mr;
      setState("rec");
    } catch {
      window.alert("Microphone access denied. Allow the mic in your browser settings.");
    }
  }

  async function onFilePicked(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file later
    if (!file || disabled || state === "busy") return;
    setState("busy");
    try {
      const text = await transcribeAudio(file, file.name || "upload.wav");
      if (text.trim()) onTranscript(text.trim());
      else window.alert("Nothing was transcribed from that file — try a clearer recording.");
    } catch (err) {
      window.alert(err?.data?.error || err?.message || "Transcription failed. Is faster-whisper installed on the server?");
    }
    setState("idle");
  }

  const looks = {
    idle: { label: "Dictate", icon: Mic,    bg: "var(--color-primary-light)", color: "var(--color-primary)", border: "1px solid var(--color-primary)" },
    rec:  { label: "Stop",    icon: Square, bg: "var(--color-error)",          color: "#fff",                   border: "1px solid var(--color-error)" },
    busy: { label: "… Transcribing", icon: null, bg: "var(--color-border)",     color: "var(--color-text-muted)", border: "1px solid var(--color-border)" },
  }[state];

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <button type="button" onClick={toggle} disabled={disabled || state === "busy"}
        style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          fontSize: 11, fontWeight: 700, padding: "4px 12px", borderRadius: 20,
          background: looks.bg, color: looks.color, border: looks.border,
          cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
          animation: state === "rec" ? "pulse 1.2s infinite" : "none",
        }}>
        {looks.icon && <looks.icon size={11} />}
        {looks.label}
      </button>
      {/* Upload-audio alternative — lets you test the dictation pipeline with
          a pre-recorded file instead of a live mic (e.g. no mic on this
          machine, or you want a repeatable sample clip). Goes through the
          exact same transcribe endpoint as live recording. */}
      <button type="button" title="Upload an audio file instead of recording live"
        onClick={() => fileInputRef.current?.click()}
        disabled={disabled || state !== "idle"}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 22, height: 22, borderRadius: "50%",
          background: "var(--color-surface)", color: "var(--color-text-muted)",
          border: "1px solid var(--color-border)",
          cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
        }}>
        <Upload size={12} />
      </button>
      <input ref={fileInputRef} type="file" accept="audio/*" onChange={onFilePicked} style={{ display: "none" }} />
    </span>
  );
}
