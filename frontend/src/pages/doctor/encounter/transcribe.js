import { encounterApi } from "../../../api";

// ─── Voice dictation button (Whisper) ────────────────────────────────────────
export async function transcribeAudio(blob, filename) {
  const fd = new FormData();
  fd.append("audio", blob, filename);
  const { data } = await encounterApi.transcribe(fd);
  return data?.text || data?.data?.text || "";
}
