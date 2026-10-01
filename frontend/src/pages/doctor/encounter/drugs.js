import { _FREQ_CODES, _ROUTE_CODES } from "./constants";

export function mapFreq(v) {
  const s = String(v || "").trim().toLowerCase();
  if (_FREQ_CODES.has(s)) return s;
  if (/\b(bid|bd|twice|1-0-1|bis)\b/.test(s)) return "bd";
  if (/\b(tid|tds|thrice|three times|1-1-1)\b/.test(s)) return "td";
  if (/\b(qid|qds|four times)\b/.test(s)) return "qid";
  if (/\b(prn|sos|as needed|as required|if needed)\b/.test(s)) return "sos";
  if (/\b(stat|immediately|at once|now)\b/.test(s)) return "stat";
  // Checked after the multi-dose patterns: "twice daily" / "1-0-1 daily" contain the word "daily".
  if (/\b(qd|once|1-0-0|daily|hs\s*morning|om)\b/.test(s)) return "od";
  if (/\b(hs|nocte|night|bedtime|bed time)\b/.test(s)) return "nocte";
  if (/\b(mane|morning)\b/.test(s)) return "mane";
  return "od";
}

export function mapRoute(v) {
  const s = String(v || "").trim().toLowerCase();
  if (_ROUTE_CODES.has(s)) return s;
  if (/\b(po|by mouth|per oral|orally)\b/.test(s)) return "oral";
  if (/\b(i\.?v\.?|intravenous)\b/.test(s)) return "iv";
  if (/\b(i\.?m\.?|intramuscular)\b/.test(s)) return "im";
  if (/\b(s\.?c\.?|subcut|subcutaneous)\b/.test(s)) return "sc";
  if (/\b(topical|local|apply)\b/.test(s)) return "topical";
  if (/\b(inhal|neb|puff)\b/.test(s)) return "inhaled";
  if (/\b(pr|rectal|per rectum)\b/.test(s)) return "rectal";
  if (/\b(sl|sublingual|under tongue)\b/.test(s)) return "sublingual";
  return "oral";
}
