const pad2 = x => String(x).padStart(2, "0");

// "YYYY-MM-DD" for a Date in the *local* timezone. Do not use date.toISOString().slice(0, 10) for this:
// that is the UTC date, which in timezones ahead of UTC (IST, UTC+5:30) is still "yesterday" for the first hours of the day.
export function toLocalISODate(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export const todayLocal = () => toLocalISODate(new Date());

// "YYYY-MM-DD" shifted by n days (built from local date parts, see above).
export function addDays(dateStr, n) {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + n);
  return toLocalISODate(d);
}

export function formatDateLabel(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

export function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function timeAgo(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return new Date(iso).toLocaleDateString();
}
