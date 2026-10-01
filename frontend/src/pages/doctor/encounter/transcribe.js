import { encounterApi } from "../../../api";

// ─── Voice dictation button (Whisper) ────────────────────────────────────────
// Shared: send an audio Blob/File to the transcription endpoint and hand the
// resulting text back. Used by both live mic recording and file upload —
// TranscribeView on the backend just reads request.FILES["audio"], it
// doesn't care whether the bytes came from MediaRecorder or a picked file.
export async function transcribeAudio(blob, filename) {
  const fd = new FormData();
  fd.append("audio", blob, filename);
  const { data } = await encounterApi.transcribe(fd);
  return data?.text || data?.data?.text || "";
}
