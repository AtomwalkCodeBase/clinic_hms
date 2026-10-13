/**
 * components/timeline/HealthTimeline.jsx
 * --------------------------------------
 * One patient's health timeline: the conditions, symptoms and medications read out of their confirmed documents, on a
 * vertical line with a year and month on the left and, for a single date, a bubble with the day on the line.
 *
 * It is shared by two screens that differ only in who is looking (`audience`) and where the data comes from
 * (`endpoint`, `fetchDocument`):
 *   patient  pages/patient/InsightsTimelinePage: plain wording, no medications, suspected / negated / family hidden
 *            until asked for.
 *   staff    the doctor's consultation screen (a "Health Timeline" tab): clinical wording, the medications with their
 *            dose and frequency, and provisional / negative / family history shown by default.
 *
 * A date is one card: its headline finding (a condition first, then a symptom, then a medication), with chips for the
 * other findings of that date and for its source documents. Opened, in place and with the rest of the timeline staying
 * put, it shows the sentences read from the reports, the related findings of that date and the unique source
 * documents; a document opens right there. A month with several dates, and a year, are summary cards that open to
 * their months and dates. Opening one card closes the others beside it. Findings from a report with no readable date
 * are listed apart at the end.
 *
 * What a card says is "this report mentions it", never "this is a diagnosis": category (Condition, Symptom,
 * Medication), nature (chronic / acute) and certainty (suspected, historical mention, resolved, planned) are separate
 * chips.
 *
 * The component fetches everything once and filters, groups and sorts in the browser, so it responds instantly.
 */
import { createContext, useContext, useEffect, useState } from "react";
import { Activity, ArrowUpDown, CalendarClock, ChevronDown, Droplet, FileText, Filter, Heart, Pill, Search, Stethoscope, Thermometer, Wind } from "lucide-react";
import useApi from "../../hooks/useApi";
import { chip, inputStyle } from "../../pages/patient/reports/reportStyles";

const KINDS = {
  condition:  { label: "Condition",  one: "condition",  many: "conditions",  color: "var(--color-error)",   Icon: Stethoscope },
  symptom:    { label: "Symptom",    one: "symptom",    many: "symptoms",    color: "var(--color-success)", Icon: Activity },
  medication: { label: "Medication", one: "medication", many: "medications", color: "var(--color-info)",    Icon: Pill },
};
const ORDER = Object.keys(KINDS);
// A more specific icon for what a finding is about; anything else gets its category's icon.
const ICONS = [
  [/fever|temperature/i, Thermometer],
  [/anemia|anaemia|blood|haemoglobin|hemoglobin/i, Droplet],
  [/asthma|wheez|cough|breath|pneumonia|bronchitis|copd|cold|throat|runny|nasal/i, Wind],
  [/heart|hypertension|cardiac|coronary|chest pain|palpitation|angina|regurgitation|ventricular|myocardial|atrial/i, Heart],
];
const iconFor = (e) => (ICONS.find(([re]) => re.test(e.name)) || [null, KINDS[e.kind].Icon])[1];
// The wording each audience sees: plain words for a patient, clinical ones for a doctor or nurse.
const COPY = {
  patient: {
    subtitle: "Conditions and symptoms found in your reports. It shows what they mention, not a diagnosis.",
    suspected: "Suspected", negative: "Not present", family: "Family",
    when: { history: "historical mention", planned: "planned", resolved: "resolved" },
    meta: { history: "historical", planned: "planned", resolved: "resolved", suspected: "suspected" },
    entries: "Extracted details", related: "Related items on this date",
    hiddenSwitch: "Show negated / suspected / family", inView: "In this view:",
    empty: "Nothing to show. Confirm your uploaded reports, or widen the filters.",
  },
  staff: {
    subtitle: "Conditions, symptoms and medications documented across this patient's records. Auto-extracted from the source text, not clinician-verified: check the document.",
    suspected: "Provisional", negative: "Negative", family: "Family history",
    when: { history: "past history", planned: "advised", resolved: "resolved" },
    meta: { history: "past history", planned: "advised", resolved: "resolved", suspected: "provisional" },
    entries: "Source text", related: "Co-documented",
    hiddenSwitch: "Include provisional, negative and family history", inView: "Documented:",
    empty: "Nothing documented for this patient yet.",
  },
};
const TimelineContext = createContext(null);          // { copy, fetchDocument } from the HealthTimeline above
const EMPTY = { from: "", to: "", kind: "", nature: "", name: "", hidden: false };
const TINT = (color, pct = 12) => `color-mix(in srgb, ${color} ${pct}%, transparent)`;
const TRACK = TINT("var(--color-primary)", 40);
const LEFT = 110;                                      // px: the year column on a wide screen
const RAIL = 64;                                       // px: the column the line and its bubbles run in
const MAX_NAMES = 3;                                   // names shown on a summary card
const muted = { fontSize: 12.5, color: "var(--color-text-muted)" };
const linkStyle = { background: "none", border: "none", padding: 0, cursor: "pointer", color: "var(--color-primary)", fontSize: 13, fontWeight: 500, whiteSpace: "nowrap" };
const pill = (color) => ({ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 999, background: TINT(color, 14), color });
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const yearOf = (iso) => iso.slice(0, 4);
const dateOf = (iso, opts) => new Date(`${iso.length === 7 ? `${iso}-01` : iso}T00:00:00`).toLocaleDateString("en-GB", opts);
const shortDate = (iso) => dateOf(iso, { day: "2-digit", month: "short", year: "numeric" });
const monthName = (key) => dateOf(key, { month: "long", year: "numeric" });
const isNarrow = () => window.innerWidth < 760;
const typeOf = (source) => (source && !["other", "not_classified"].includes(source.document_type) ? source.document_type.replace(/_/g, " ") : "report");
const byKind = (a, b) => ORDER.indexOf(a.e.kind) - ORDER.indexOf(b.e.kind);
const dominant = (items) => KINDS[ORDER.find((k) => items.some((it) => it.e.kind === k))].color;
const docsOf = (items) => [...new Map(items.flatMap(({ e, date }) => e.sources.map((s) => [s.document_id, { ...s, date }]))).values()];
const sameDate = (items) => items.every((it) => it.date === items[0].date);

function useNarrow() {
  const [narrow, setNarrow] = useState(isNarrow);
  useEffect(() => {
    const on = () => setNarrow(isNarrow());
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return narrow;
}

// Items arrive in date order, so the ones that share a key are next to each other.
function groupBy(items, keyOf) {
  const groups = [];
  for (const it of items) {
    const key = keyOf(it);
    if (groups.length && groups[groups.length - 1].key === key) groups[groups.length - 1].items.push(it);
    else groups.push({ key, items: [it] });
  }
  return groups;
}

// Opening a card closes the others beside it: props(key) gives a card its open state and its toggle. A list that
// holds one lives in a component that is only mounted while its parent is open, so closing the parent resets it.
function useAccordion() {
  const [openKey, setOpenKey] = useState(null);
  return [(key) => ({ open: openKey === key, onToggle: () => setOpenKey(openKey === key ? null : key) }), () => setOpenKey(null)];
}

function IconTile({ e, size = 44 }) {
  const Icon = iconFor(e);
  const color = KINDS[e.kind].color;
  return (
    <div style={{ width: size, height: size, borderRadius: 12, background: TINT(color), display: "grid", placeItems: "center", flexShrink: 0 }}>
      <Icon size={size * 0.5} style={{ color }} />
    </div>
  );
}

// Nature and certainty, each its own chip (the category is shown apart).
function Tags({ e }) {
  const { copy } = useContext(TimelineContext);
  return (
    <>
      {e.nature === "chronic" && <span style={chip("warn")}>Chronic</span>}
      {e.nature === "acute" && <span style={pill(KINDS.medication.color)}>Acute</span>}
      {e.uncertain && <span style={chip("warn")}>{copy.suspected}</span>}
      {e.when !== "current" && <span style={chip("type")}>{copy.when[e.when]}</span>}
      {e.negated && <span style={chip("bad")}>{copy.negative}</span>}
      {e.family && <span style={chip("bad")}>{copy.family}</span>}
    </>
  );
}

// The document itself, in place: the signed link the screen's own document endpoint returns.
function DocPreview({ s }) {
  const { fetchDocument } = useContext(TimelineContext);
  const [file, setFile] = useState(null);                // null: loading, "": no preview, else the link
  useEffect(() => {
    let alive = true;
    fetchDocument(s.document_id)
      .then((res) => { if (alive) setFile((res.data?.data || res.data)?.file_data || ""); })
      .catch(() => { if (alive) setFile(""); });
    return () => { alive = false; };
  }, [s.document_id, fetchDocument]);
  const isImage = /^data:image/.test(file || "") || /\.(png|jpe?g|gif|webp)$/i.test(s.file_name || "");
  return (
    <div style={{ margin: "0 16px 16px", minHeight: 120, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--color-surface, #fff)", border: "1px solid var(--color-border)", borderRadius: 10, overflow: "hidden" }}>
      {file === null ? <span style={muted}>Loading…</span>
        : !file ? <span style={{ ...muted, padding: 20, textAlign: "center" }}>A preview isn’t available for this file.</span>
        : isImage ? <img src={file} alt={s.file_name} style={{ maxWidth: "100%", maxHeight: 520 }} />
        : <iframe title={s.file_name || "Report"} src={file} style={{ width: "100%", height: 520, border: "none" }} />}
    </div>
  );
}

// What a date holds: the sentences read from the reports, the other findings of that date, and the unique documents.
function DateBody({ items }) {
  const { copy } = useContext(TimelineContext);
  const [doc, setDoc] = useState(null);
  const sorted = [...items].sort(byKind);
  const lines = [...new Set(sorted.map(({ e }) => e.evidence))];
  const rest = sorted.slice(1);
  const docs = docsOf(items);
  const heading = { fontSize: 13, fontWeight: 600, marginBottom: 8 };
  return (
    <div style={{ background: "var(--color-bg)", borderTop: "1px solid var(--color-border)", borderRadius: "0 0 12px 12px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 20, padding: 16 }}>
        <div>
          <div style={heading}>{copy.entries}</div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 13.5 }}>{lines.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
        <div>
          <div style={heading}>{copy.related}</div>
          {rest.length === 0 && <div style={muted}>No other findings on this date.</div>}
          <div style={{ display: "grid", gap: 10 }}>
            {rest.map(({ e }) => (
              <div key={`${e.kind}-${e.name}`} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <IconTile e={e} size={34} />
                <div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}><strong style={{ fontSize: 13.5, textTransform: "capitalize" }}>{e.name}</strong>{e.dose && <span style={muted}>{e.dose}</span>}<Tags e={e} /></div>
                  <div style={muted}>{KINDS[e.kind].label}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div style={heading}>Source documents ({docs.length})</div>
          <div style={{ display: "grid", gap: 8 }}>
            {docs.map((d) => (
              <div key={d.document_id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 10px", border: "1px solid var(--color-border)", borderRadius: 10, background: "var(--color-surface, #fff)" }}>
                <FileText size={20} style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, overflowWrap: "anywhere" }}>{d.file_name || `Report ${d.document_id}`}</div>
                  <div style={{ ...muted, fontSize: 12 }}><span style={{ textTransform: "capitalize" }}>{typeOf(d)}</span>{d.date && ` · ${shortDate(d.date)}`}{d.hospital && ` · ${d.hospital}`}</div>
                </div>
                <button onClick={() => setDoc(doc?.document_id === d.document_id ? null : d)} style={linkStyle}>{doc?.document_id === d.document_id ? "Hide" : "View"}</button>
              </div>
            ))}
          </div>
        </div>
      </div>
      {doc && <DocPreview key={doc.document_id} s={doc} />}
    </div>
  );
}

// One date: its headline finding, with chips for its other findings and its source documents. Opens in place.
function DateCard({ items, open, onToggle, nested }) {
  const sorted = [...items].sort(byKind);
  const head = sorted[0].e;
  const others = ORDER.map((k) => [k, sorted.slice(1).filter((it) => it.e.kind === k).length]).filter(([, n]) => n);
  const date = items[0].date;
  return (
    <div className={nested ? undefined : "card"} style={{ borderRadius: 12, ...(nested ? { background: "var(--color-surface, #fff)", border: "1px solid var(--color-border)" } : {}) }}>
      <div onClick={onToggle} style={{ display: "flex", gap: 14, alignItems: "flex-start", padding: "12px 16px", cursor: "pointer" }}>
        <IconTile e={head} size={40} />
        <div style={{ flex: 1, minWidth: 0 }}>
          {date && (isNarrow() || nested) && <div style={{ ...muted, fontWeight: 600, marginBottom: 2 }}>{shortDate(date)}</div>}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
            <strong style={{ fontSize: 17, textTransform: "capitalize", marginRight: 2 }}>{head.name}</strong>
            {head.dose && <span style={muted}>{head.dose}</span>}
            <Tags e={head} />
          </div>
          <div style={{ ...muted, fontSize: 13.5, margin: "2px 0 4px", ...(open ? {} : { display: "-webkit-box", WebkitLineClamp: 1, WebkitBoxOrient: "vertical", overflow: "hidden" }) }}>{head.evidence}</div>
          <div style={{ ...muted, fontSize: 12 }}>
            {[KINDS[head.kind].label, ...others.map(([k, n]) => plural(n, KINDS[k].one, KINDS[k].many)), plural(docsOf(items).length, "source document", "source documents")].join("  •  ")}
          </div>
        </div>
        <ChevronDown size={18} style={{ color: "var(--color-text-muted)", marginTop: 10, flexShrink: 0, transform: open ? "rotate(180deg)" : "none" }} />
      </div>
      {open && <DateBody items={sorted} />}
    </div>
  );
}

// A year, or a month with several dates: a title with a few names, and counts. Opens to its months or dates.
function GroupCard({ items, level, title, open, onToggle, nested }) {
  const { copy } = useContext(TimelineContext);
  const narrow = isNarrow();
  const uniq = [...new Map(items.map(({ e }) => [`${e.kind}:${e.name}`, e])).values()].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  const withNature = (k) => {
    const of = uniq.filter((e) => e.kind === k);
    const n = (nature) => of.filter((e) => e.nature === nature).length;
    return of.length > 0 && (
      <span key={k} style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
        {plural(of.length, KINDS[k].one, KINDS[k].many)}
        {n("chronic") > 0 && <span style={chip("warn")}>{n("chronic")} chronic</span>}
        {n("acute") > 0 && <span style={pill(KINDS.medication.color)}>{n("acute")} acute</span>}
      </span>
    );
  };
  const status = (test, label, style) => uniq.filter(test).length > 0 && <span key={label} style={style}>{uniq.filter(test).length} {label}</span>;
  const meta = [
    ...ORDER.map(withNature),
    status((e) => e.when === "history", copy.meta.history, chip("type")), status((e) => e.when === "resolved", copy.meta.resolved, pill(KINDS.symptom.color)),
    status((e) => e.when === "planned", copy.meta.planned, chip("neutral")), status((e) => e.uncertain, copy.meta.suspected, chip("warn")),
    <span key="docs">{plural(docsOf(items).length, "source document", "source documents")}</span>,
  ].filter(Boolean).flatMap((m, i) => (i ? [<span key={`dot${i}`}>•</span>, m] : [m]));
  const shown = uniq.slice(0, MAX_NAMES);
  return (
    <div className={nested ? undefined : "card"} style={{ borderRadius: 12, ...(nested ? { background: "var(--color-surface, #fff)", border: "1px solid var(--color-border)" } : {}) }}>
      <div onClick={onToggle} style={{ display: "flex", gap: 12, alignItems: "center", padding: "14px 16px", cursor: "pointer" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 10px", alignItems: "center" }}>
            <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 17, marginRight: 4 }}>{title}</span>
            {shown.map((e) => <span key={`${e.kind}:${e.name}`} style={{ ...pill(KINDS[e.kind].color), textTransform: "capitalize" }}>{e.name}</span>)}
            {uniq.length > shown.length && <span style={muted}>+{uniq.length - shown.length} more</span>}
          </div>
          <div style={{ ...muted, marginTop: 6, display: "flex", flexWrap: "wrap", gap: "4px 10px", alignItems: "center" }}>{meta}</div>
        </div>
        {!narrow && <span style={linkStyle}>{open ? "Hide details" : "View details"}</span>}
        <ChevronDown size={18} style={{ color: "var(--color-text-muted)", flexShrink: 0, transform: open ? "rotate(180deg)" : "none" }} />
      </div>
      {open && <div style={{ padding: "0 14px 14px" }}><GroupBody items={items} level={level} /></div>}
    </div>
  );
}

// A date card for a single date, a summary card otherwise.
function Cluster({ items, level, title, ...rest }) {
  return level !== "year" && sameDate(items) && items[0].date ? <DateCard items={items} {...rest} /> : <GroupCard items={items} level={level} title={title} {...rest} />;
}

// What a year or a month holds: its months or dates, each a card of its own.
function GroupBody({ items, level }) {
  const [props] = useAccordion();
  const groups = groupBy(items, level === "year" ? (it) => it.date.slice(0, 7) : (it) => it.date);
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {groups.map((g) => (
        <Cluster key={g.key} nested items={g.items} level={level === "year" ? "month" : "day"}
                 title={level === "year" ? monthName(g.key) : shortDate(g.key)} {...props(g.key)} />
      ))}
    </div>
  );
}

// One row: the year and month on the left, the line with a day bubble (or a dot) in the middle, the card on the right.
function Row({ row, prev, isFirst, isLast, narrow }) {
  const showYear = !prev || prev.year !== row.year;
  const bubble = !narrow && row.bubble;
  const lift = narrow && showYear ? 34 : 0;            // the year label above the card on a phone
  const nodeY = (bubble ? 36 : 27) + lift;
  const segment = isFirst && isLast ? null : isFirst ? { top: nodeY, bottom: 0 } : isLast ? { top: 0, height: nodeY } : { top: 0, bottom: 0 };
  const yearChip = <span style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15, padding: "4px 14px", borderRadius: 10, background: TINT("var(--color-primary)", 10) }}>{row.year}</span>;
  return (
    <div style={{ display: "grid", gridTemplateColumns: narrow ? "24px minmax(0, 1fr)" : `${LEFT}px ${RAIL}px minmax(0, 1fr)`, paddingBottom: 10 }}>
      {!narrow && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", paddingTop: 14, paddingRight: 6 }}>
          <span>{showYear && yearChip}</span>
          {!row.bubble && <span style={{ fontSize: 14, fontWeight: 500, paddingTop: 3 }}>{row.label}</span>}
        </div>
      )}
      <div style={{ position: "relative" }}>
        {segment && <div style={{ position: "absolute", left: "50%", width: 2, marginLeft: -1, background: TRACK, ...segment }} />}
        {bubble ? (
          <div style={{ position: "absolute", left: "50%", top: nodeY - 20, transform: "translateX(-50%)", textAlign: "center", width: RAIL }}>
            <div style={{ width: 40, height: 40, margin: "0 auto", borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 15,
                          background: `linear-gradient(${TINT(row.color, 12)}, ${TINT(row.color, 12)}), var(--color-bg)`, border: `2px solid ${row.color}`, boxShadow: "0 0 0 3px var(--color-bg)" }}>{row.bubble.day}</div>
            <div style={{ ...muted, fontSize: 11.5, marginTop: 2, background: "var(--color-bg)" }}>{row.bubble.sub}</div>
          </div>
        ) : (
          <div style={{ position: "absolute", left: "50%", top: nodeY - 6, width: 12, height: 12, borderRadius: "50%", background: row.color, transform: "translateX(-50%)",
                        border: "2px solid var(--color-surface, #fff)", boxShadow: `0 0 0 1.5px ${TINT(row.color, 45)}` }} />
        )}
      </div>
      <div>
        {narrow && showYear && <div style={{ marginBottom: 8 }}>{yearChip}</div>}
        {row.card}
      </div>
    </div>
  );
}

export default function HealthTimeline({ endpoint, params, fetchDocument, audience = "patient" }) {
  const copy = COPY[audience];
  const staff = audience === "staff";
  const kinds = staff ? ORDER : ORDER.filter((k) => k !== "medication");      // a patient's timeline has no medications
  const base = { ...EMPTY, hidden: staff };                                  // a doctor sees provisional / negative / family by default
  const narrow = useNarrow();
  const [filters, setFilters] = useState(base);
  const [zoom, setZoom] = useState("month");
  const [newestFirst, setNewestFirst] = useState(true);
  const [showFilters, setShowFilters] = useState(false);
  const [top, closeTop] = useAccordion();                // the cards of the timeline itself: one open at a time
  const set = (key) => (ev) => setFilters({ ...filters, [key]: ev.target.type === "checkbox" ? ev.target.checked : ev.target.value });

  const { data, isLoading, error } = useApi(endpoint, { params });

  const word = filters.name.trim().toLowerCase();
  const keep = (e) => (filters.hidden || !(e.negated || e.family || e.uncertain))
    && (!filters.from || e.date >= filters.from) && (!filters.to || e.date <= filters.to)
    && (!filters.kind || e.kind === filters.kind) && (!filters.nature || e.nature === filters.nature) && e.name.includes(word);
  const undated = filters.from || filters.to ? [] : (data?.undated || []).filter(keep);          // no date: outside any date range
  const dated = (data?.days || []).flatMap((d) => d.entries.filter(keep).map((e) => ({ e, date: d.date })));
  const items = newestFirst ? dated : [...dated].reverse();

  // The Timeline Insights panel: what the current filters show, by unique name and unique document.
  const shown = [...dated.map((it) => it.e), ...undated];
  const uniqueOf = (k) => new Set(shown.filter((e) => e.kind === k).map((e) => e.name)).size;
  const documents = new Set(shown.flatMap((e) => e.sources.map((s) => s.document_id))).size;

  const keyOf = { day: (it) => it.date, month: (it) => it.date.slice(0, 7), year: (it) => yearOf(it.date) }[zoom];
  const rows = groupBy(items, keyOf).map((g) => {
    const first = g.items[0].date;
    const one = zoom !== "year" && sameDate(g.items);
    return {
      key: g.key, year: yearOf(first), color: dominant(g.items),
      label: zoom === "year" ? "" : dateOf(first, { month: "short" }),
      bubble: one ? { day: first.slice(8), sub: dateOf(first, { month: "short" }) } : null,
      card: <Cluster items={g.items} level={zoom} title={zoom === "year" ? g.key : monthName(g.key)} {...top(g.key)} />,
    };
  });

  return (
    <TimelineContext.Provider value={{ copy, fetchDocument }}>
      <>
        <p style={{ ...muted, fontSize: 13.5, margin: "0 0 14px" }}>{copy.subtitle}</p>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 10 }}>
          <div role="group" aria-label="Zoom" style={{ display: "inline-flex", border: "1px solid var(--color-border)", borderRadius: 10, overflow: "hidden" }}>
            {["year", "month", "day"].map((z) => (
              <button key={z} onClick={() => { setZoom(z); closeTop(); }} style={{ padding: "8px 20px", fontSize: 13.5, border: "none", cursor: "pointer", textTransform: "capitalize",
                                                                                    background: zoom === z ? "var(--color-primary)" : "transparent", color: zoom === z ? "#fff" : "inherit", fontWeight: zoom === z ? 600 : 400 }}>{z}</button>
            ))}
          </div>
          <input type="date" aria-label="From" value={filters.from} onChange={set("from")} style={inputStyle} />
          <span style={muted}>to</span>
          <input type="date" aria-label="To" value={filters.to} onChange={set("to")} style={inputStyle} />
          <div style={{ position: "relative", flex: "1 1 220px", minWidth: 200 }}>
            <Search size={15} style={{ position: "absolute", left: 10, top: 11, color: "var(--color-text-muted)" }} />
            <input type="search" placeholder="Search by condition, symptom, medication…" value={filters.name} onChange={set("name")} style={{ ...inputStyle, width: "100%", paddingLeft: 32 }} />
          </div>
          <button className="btn-outline" onClick={() => setShowFilters(!showFilters)} style={{ display: "inline-flex", gap: 6, alignItems: "center", padding: "8px 14px", fontSize: 13 }}>
            <Filter size={15} /> Filters{[filters.kind, filters.nature, filters.hidden !== base.hidden].filter(Boolean).length > 0 && ` (${[filters.kind, filters.nature, filters.hidden !== base.hidden].filter(Boolean).length})`}
          </button>
          <button className="btn-outline" onClick={() => { setNewestFirst(!newestFirst); closeTop(); }} style={{ display: "inline-flex", gap: 6, alignItems: "center", padding: "8px 14px", fontSize: 13 }}>
            <ArrowUpDown size={15} /> {newestFirst ? "Newest first" : "Oldest first"}
          </button>
          {JSON.stringify(filters) !== JSON.stringify(base) && (
            <button onClick={() => setFilters(base)} style={linkStyle}>Clear filters</button>
          )}
        </div>

        {showFilters && (
          <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", padding: "10px 14px", borderRadius: 12, marginBottom: 10 }}>
            <select aria-label="Kind" value={filters.kind} onChange={set("kind")} style={inputStyle}>
              <option value="">All event types</option>
              {kinds.map((k) => <option key={k} value={k}>{KINDS[k].label}</option>)}
            </select>
            <select aria-label="Chronic or acute" value={filters.nature} onChange={set("nature")} style={inputStyle}>
              <option value="">Chronic and acute</option>
              <option value="chronic">Chronic</option>
              <option value="acute">Acute</option>
            </select>
            <label style={{ ...muted, display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={filters.hidden} onChange={set("hidden")} /> {copy.hiddenSwitch}
            </label>
          </div>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 22px", alignItems: "center", marginBottom: 16, ...muted, fontSize: 13 }}>
          {kinds.map((k) => (
            <span key={k} style={{ display: "inline-flex", gap: 7, alignItems: "center", color: "var(--color-text)" }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: KINDS[k].color }} />{KINDS[k].label}
            </span>
          ))}
          <span style={{ marginLeft: "auto" }}>
            {copy.inView} {[["condition", "conditions", uniqueOf("condition")], ["symptom", "symptoms", uniqueOf("symptom")], ["medication", "medications", uniqueOf("medication")], ["source document", "source documents", documents]]
              .filter(([one]) => staff || one !== "medication")
              .map(([one, many, n]) => <span key={one}><b style={{ color: "var(--color-text)" }}>{n}</b> {n === 1 ? one : many}</span>)
              .flatMap((m, i) => (i ? [" · ", m] : [m]))}
          </span>
        </div>

        {staff && data && data.consent_given === false && (
          <p style={{ ...muted, margin: "0 0 12px" }}>This patient hasn't agreed to cross-hospital record sharing, so only this hospital's records are shown.</p>
        )}

        {isLoading ? (
          <div style={muted}>Loading…</div>
        ) : error && !data ? (
          <div style={muted}>Couldn't load your timeline right now.</div>
        ) : rows.length === 0 && undated.length === 0 ? (
          <div className="card" style={{ padding: "32px 16px", textAlign: "center", borderRadius: 12 }}>
            <CalendarClock size={28} style={{ color: "var(--color-text-muted)", marginBottom: 8 }} />
            <div style={muted}>{copy.empty}</div>
          </div>
        ) : (
          <>
            {rows.map((row, i) => <Row key={row.key} row={row} prev={rows[i - 1]} isFirst={i === 0} isLast={i === rows.length - 1} narrow={narrow} />)}
            {undated.length > 0 && (
              <div style={{ marginTop: 20 }}>
                <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 15 }}>No date found in the report</div>
                <p style={{ ...muted, margin: "2px 0 10px" }}>These reports don't show a readable date, so they can't be placed on the timeline.</p>
                <div className="card" style={{ borderRadius: 12, overflow: "hidden" }}><DateBody items={undated.map((e) => ({ e, date: null }))} /></div>
              </div>
            )}
          </>
        )}
      </>
    </TimelineContext.Provider>
  );
}
