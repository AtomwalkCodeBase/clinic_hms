"""
core/doc_dates.py
-----------------
Pull the clinically meaningful date off an outside document's text.

A lab report usually prints three or four dates — sample collected, sample
received, reported, printed. We want the *earliest clinically meaningful*
one for sorting the vault, which is normally the collection date, then the
report date. This module finds every date in the text, reads the label
sitting just before it, and picks by that priority instead of grabbing the
first date it sees.

It returns both a primary `report_date` (what the vault sorts by) and, when
distinct, the `collection_date`, plus `source` (which label won) and a
confidence. Nothing here reads or stores anything but the date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# label -> bucket. Checked as substrings in the ~48 chars before a date.
_LABELS = (
    ("collection", ("collected on", "collection date", "sample collected", "specimen collected",
                    "sample drawn", "blood drawn", "coll. date", "coll date", "collected date",
                    "date of collection", "sampled on", "s. coll", "spec. collected")),
    ("report",     ("reported on", "report date", "result date", "date of report", "reporting date",
                    "verified on", "released on", "authenticated on", "approved on", "result released",
                    "date of reporting", "reported date")),
    ("received",   ("received on", "sample received", "registered on", "registration date",
                    "accessioned on", "recd on", "date of registration", "booking date")),
    ("issue",      ("printed on", "print date", "date of printing", "issue date", "generated on",
                    "issued on", "date of issue")),
    ("consult",    ("prescribed on", "date of consultation", "visit date", "consultation date",
                    "opd date", "date of visit")),
)
_PRIORITY = ("collection", "report", "consult", "received", "issue", "bare")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# All matches carry a full-string span so we can look back for a label.
_NUMERIC = re.compile(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})\b")
_ISO = re.compile(r"\b(20\d{2})[\/\-.](\d{1,2})[\/\-.](\d{1,2})\b")
_DMONY = re.compile(r"\b(\d{1,2})[\s\-]([A-Za-z]{3,9})[\s\-,]+(\d{4})\b")
_MONDY = re.compile(r"\b([A-Za-z]{3,9})[\s\-]+(\d{1,2})[\s\-,]+(\d{4})\b")


@dataclass
class DateResult:
    report_date: date | None = None
    collection_date: date | None = None
    source: str = ""                 # collection | report | received | issue | consult | bare | ""
    confidence: float = 0.0
    found: list = field(default_factory=list)   # (bucket, date) for every dated line, debug/audit


def _mk(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _plausible(dt: date) -> bool:
    if dt is None:
        return False
    today = date.today()
    if dt > today + timedelta(days=2):        # tolerate a little clock skew
        return False
    if dt.year < 2000:
        return False
    return True


def _scan(text: str):
    """Yield (bucket, date) for every date found, bucket from the label before it."""
    low = text.lower()
    for rx, kind in ((_ISO, "iso"), (_NUMERIC, "num"), (_DMONY, "dmony"), (_MONDY, "mondy")):
        for m in rx.finditer(text):
            if kind == "iso":
                dt = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif kind == "num":
                a, b, c = (int(x) for x in m.groups())
                dt = _mk(c, b, a) or _mk(c, a, b)     # day-first, then month-first
            elif kind == "dmony":
                mon = _MONTHS.get(m.group(2).lower()[:4]) or _MONTHS.get(m.group(2).lower()[:3])
                dt = _mk(int(m.group(3)), mon, int(m.group(1))) if mon else None
            else:
                mon = _MONTHS.get(m.group(1).lower()[:4]) or _MONTHS.get(m.group(1).lower()[:3])
                dt = _mk(int(m.group(3)), mon, int(m.group(2))) if mon else None
            if not _plausible(dt):
                continue
            back = low[max(0, m.start() - 48):m.start()]
            bucket = "bare"
            for name, phrases in _LABELS:
                if any(p in back for p in phrases):
                    bucket = name
                    break
            yield bucket, dt


def extract(text: str) -> DateResult:
    if not text:
        return DateResult()

    by_bucket: dict = {}
    found = []
    for bucket, dt in _scan(text):
        found.append((bucket, dt))
        by_bucket.setdefault(bucket, []).append(dt)

    if not found:
        return DateResult(found=found)

    collection = min(by_bucket["collection"]) if by_bucket.get("collection") else None

    primary = None
    source = ""
    for b in _PRIORITY:
        if by_bucket.get(b):
            primary = min(by_bucket[b])
            source = b
            break

    # confidence: a labelled date we trust; a bare-only date less so; a very
    # old lone bare date least of all.
    if source in ("collection", "report", "consult"):
        conf = 0.92
    elif source in ("received", "issue"):
        conf = 0.8
    else:  # bare
        oldest_ok = primary and primary >= date.today() - timedelta(days=365 * 6)
        conf = 0.55 if (oldest_ok and len(found) == 1) else 0.4

    return DateResult(
        report_date=primary,
        collection_date=collection if (collection and collection != primary) else None,
        source=source,
        confidence=round(conf, 2),
        found=found,
    )
