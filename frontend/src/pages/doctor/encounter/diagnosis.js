import { ICD10_CODES, SYMPTOM_SYNONYMS } from "./constants";

// Best-effort ICD-10 code for a free-text diagnosis description, using the
// same starter table the manual picker uses. "" when nothing matches.
export function icdCodeForDescription(desc) {
  const d = (desc || "").trim().toLowerCase();
  if (!d) return "";
  const exact = ICD10_CODES.find(c => c.desc.toLowerCase() === d);
  if (exact) return exact.code;
  const part = ICD10_CODES.find(c => {
    const cd = c.desc.toLowerCase();
    return cd.includes(d) || d.includes(cd) || (c.keywords || []).some(k => d.includes(k));
  });
  return part ? part.code : "";
}

export function matchICD(t, limit = 6) {
  if (!t) return [];
  const lower = t.toLowerCase();
  let expanded = lower;
  for (const [phrase, syns] of Object.entries(SYMPTOM_SYNONYMS)) {
    if (lower.includes(phrase)) expanded += " " + syns.join(" ");
  }
  const words = expanded.split(/[^a-z]+/).filter(w => w.length > 3);
  return ICD10_CODES
    .map(c => {
      // Curated keyword phrases (e.g. "back pain", "high bp") are a much
      // stronger signal than incidental word overlap with the clinical
      // description text, so they're weighted heavier and checked as
      // whole-phrase substring matches against the raw complaint text.
      const keywordHits = (c.keywords || []).filter(k => lower.includes(k)).length;
      const wordHits = words.filter(w => c.desc.toLowerCase().includes(w)).length;
      return { c, score: keywordHits * 3 + wordHits };
    })
    .filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map(x => x.c);
}
