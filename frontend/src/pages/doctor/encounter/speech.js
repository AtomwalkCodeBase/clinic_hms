import { EMPTY_DRUG, WORD_NUM } from "./constants";

export function wordsToNumber(str) {
  const s = str.trim().toLowerCase();
  if (/^\d+(\.\d+)?$/.test(s)) return parseFloat(s);
  const parts = s.split(/\s+/);
  if (parts.length === 2 && parts[1] === "hundred" && WORD_NUM[parts[0]] != null) {
    return WORD_NUM[parts[0]] * 100;
  }
  return WORD_NUM[s] ?? null;
}

export function parseDrugSpeech(t) {
  const text = t.toLowerCase().replace(/[.,]/g, " ").replace(/\s+/g, " ").trim();
  const d = { ...EMPTY_DRUG };

  // Dose — numeric ("500 mg") or spelled-out ("five hundred milligrams").
  const UNIT_RE = "mg|milligrams?|ml|millilit(?:re|er)s?|mcg|micrograms?|g|grams?|units?|iu";
  let dose = text.match(new RegExp(`(\\d+(?:\\.\\d+)?)\\s*(${UNIT_RE})\\b`));
  let doseIndex = dose?.index;
  if (dose) {
    const unit = dose[2].startsWith("milligram") ? "mg"
      : dose[2].startsWith("millilit") ? "ml"
      : dose[2].startsWith("microgram") ? "mcg"
      : dose[2].startsWith("gram") ? "g"
      : dose[2];
    d.dosage = `${dose[1]}${unit}`;
  } else {
    const spelled = text.match(new RegExp(`\\b((?:${Object.keys(WORD_NUM).join("|")})(?:\\s+hundred)?)\\s+(${UNIT_RE})\\b`));
    if (spelled) {
      const n = wordsToNumber(spelled[1]);
      const unit = spelled[2].startsWith("milligram") ? "mg"
        : spelled[2].startsWith("millilit") ? "ml"
        : spelled[2].startsWith("microgram") ? "mcg"
        : spelled[2].startsWith("gram") ? "g"
        : spelled[2];
      if (n != null) { d.dosage = `${n}${unit}`; doseIndex = spelled.index; }
    }
  }

  // Duration — digits or spelled-out, days/weeks/months all normalised to days.
  const durNum = "(\\d+|" + Object.keys(WORD_NUM).join("|") + "|a|an|couple(?:\\s+of)?)";
  const dur = text.match(new RegExp(`for\\s+${durNum}\\s+(day|days|week|weeks|month|months)\\b`));
  if (dur) {
    let n = /^\d+$/.test(dur[1]) ? parseInt(dur[1], 10)
      : /^(a|an)$/.test(dur[1]) ? 1
      : /couple/.test(dur[1]) ? 2
      : wordsToNumber(dur[1]);
    if (n != null) {
      const unit = dur[2].startsWith("week") ? 7 : dur[2].startsWith("month") ? 30 : 1;
      d.duration_days = String(Math.round(n * unit));
    }
  }

  // Frequency — including "every N hours" cadences and common shorthand.
  const everyHrs = text.match(/every\s+(\d+)\s*hours?/);
  if (everyHrs) {
    const h = parseInt(everyHrs[1], 10);
    d.frequency = h <= 6 ? "qid" : h <= 8 ? "td" : h <= 12 ? "bd" : "od";
  } else if (/four times|qid/.test(text)) d.frequency = "qid";
  else if (/three times|thrice|\btid\b|\btds\b/.test(text)) d.frequency = "td";
  else if (/twice|two times|\bbd\b|morning and (night|evening)/.test(text)) d.frequency = "bd";
  else if (/at night|nocte|bedtime|before (bed|sleep)/.test(text)) d.frequency = "nocte";
  else if (/every morning|in the morning|\bmane\b/.test(text)) d.frequency = "mane";
  else if (/as needed|\bsos\b|when required|if required|if needed/.test(text)) d.frequency = "sos";
  else if (/once (a day|daily)|one time|\bod\b/.test(text)) d.frequency = "od";
  else d.frequency = "od";

  const instr = text.match(/(after (food|meals)|before (food|meals)|with (food|milk|water)|on an? empty stomach|empty stomach)/);
  if (instr) d.instructions = instr[1].charAt(0).toUpperCase() + instr[1].slice(1);

  // Drug name — strip common spoken filler before/around the dose so the
  // remaining words are (usually) just the drug name.
  const FILLER = /\b(please|start|prescribe|give|add|put (?:him|her|them) on|let'?s start|tab|tablet|cap|capsule|syrup|syp|inj|injection|the patient on|patient on)\b/g;
  if (doseIndex != null) {
    const before = text.slice(0, doseIndex).replace(FILLER, "").trim();
    const words = before.split(/\s+/).filter(Boolean);
    d.drug_name = words.slice(-2).join(" ").trim() || before;
  } else {
    const cleaned = text.replace(FILLER, "").trim();
    d.drug_name = cleaned.split(/\s+/).slice(0, 2).join(" ");
  }
  d.drug_name = d.drug_name.replace(/\b\w/g, c => c.toUpperCase());
  return d;
}
