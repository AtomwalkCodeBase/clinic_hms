"""
Episode grouping and recurrent-episode detection.

ClinicalEvent  = "this condition was mentioned in this document on this date"
Episode        = the real-world illness instance the events belong to (built on demand, never stored)

Rules
-----
* CHRONIC group  -> exactly one episode per patient; it opens at the first
  confirmed mention and stays open (end=None). Later mentions are follow-ups.
* ACUTE group    -> events of the same group whose gap from the previous event
  is <= merge_days collapse into one episode; a larger gap starts a new one.
* Provisional-only episodes ("? dengue", "r/o UTI") are kept but flagged and
  excluded from recurrence counts and summary numbers.
* Recurrence     -> sliding window over episode start dates per group, any
  window rule in config satisfied => RECURRENT.
"""
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from .clinical_rules import (age_in_days, classify_condition, max_severity)
from .config import load_config


@dataclass
class EventIn:
    id: int
    event_date: date
    icd10: Optional[str]
    condition_text: str = ""
    severity: str = "NORMAL"
    is_provisional: bool = False
    document_id: Optional[int] = None
    event_type: str = "DIAGNOSIS"


@dataclass
class Episode:
    key: str
    group: str
    label: str
    category: str
    start: date
    end: Optional[date]
    last_seen: date
    peak_severity: str
    event_ids: List[int] = field(default_factory=list)
    document_ids: List[int] = field(default_factory=list)
    is_provisional: bool = True
    known_group: bool = True

    @property
    def event_count(self):
        return len(self.event_ids)

    def as_dict(self):
        return {
            "key": self.key, "group": self.group, "label": self.label,
            "category": self.category, "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "last_seen": self.last_seen.isoformat(),
            "peak_severity": self.peak_severity, "event_count": self.event_count,
            "event_ids": self.event_ids,
            "document_ids": sorted(set(d for d in self.document_ids if d)),
            "is_provisional": self.is_provisional, "known_group": self.known_group,
        }


def _absorb(ep: Episode, ev: EventIn):
    ep.event_ids.append(ev.id)
    if ev.document_id:
        ep.document_ids.append(ev.document_id)
    ep.last_seen = max(ep.last_seen, ev.event_date)
    ep.peak_severity = max_severity(ep.peak_severity, ev.severity)
    if not ev.is_provisional:
        ep.is_provisional = False


def build_episodes(events: List[EventIn], cfg=None) -> List[Episode]:
    cfg = cfg or load_config()
    events = sorted(events, key=lambda e: (e.event_date, e.id))
    chronic: dict = {}
    open_acute: dict = {}
    episodes: List[Episode] = []

    for ev in events:
        cls = classify_condition(ev.icd10, cfg)
        group = cls["group"]
        label = cls["label"] or ev.condition_text or group

        if cls["category"] == "CHRONIC":
            ep = chronic.get(group)
            if ep is None:
                ep = Episode(key=f"{group}", group=group, label=label, category="CHRONIC",
                             start=ev.event_date, end=None, last_seen=ev.event_date,
                             peak_severity="NORMAL", known_group=cls["known"])
                chronic[group] = ep
                episodes.append(ep)
            # A provisional first mention shouldn't fix the onset date once
            # a confirmed mention arrives.
            if ep.is_provisional and not ev.is_provisional:
                ep.start = ev.event_date
            _absorb(ep, ev)
            continue

        ep = open_acute.get(group)
        gap = (ev.event_date - ep.last_seen).days if ep else None
        if ep is None or gap > cls["merge_days"]:
            ep = Episode(key=f"{group}:{ev.event_date.isoformat()}", group=group, label=label,
                         category="ACUTE", start=ev.event_date, end=ev.event_date,
                         last_seen=ev.event_date, peak_severity="NORMAL",
                         known_group=cls["known"])
            open_acute[group] = ep
            episodes.append(ep)
        _absorb(ep, ev)
        ep.end = ep.last_seen

    return sorted(episodes, key=lambda e: (e.start, e.group))


# ------------------------------------------------------------------ recurrence
def _add_months(d: date, months: int) -> date:
    # month arithmetic without dateutil
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def detect_recurrence(episodes: List[Episode], dob: date, as_of: date, cfg=None) -> List[dict]:
    """
    Returns one entry per condition group that has an episode or a rule:
    {
      "group", "label", "is_recurrent", "triggered_on", "rule": {"min_count","window_months"},
      "episodes_last_12m", "expected_per_year", "context": "typical for age" | ...,
      "clinical_hint", "episode_keys": [...]
    }
    Only groups with at least one confirmed acute episode are returned.
    """
    cfg = cfg or load_config()
    rules = {k: v for k, v in cfg["recurrence_rules"].items() if not k.startswith("_")}
    by_group: dict = {}
    for ep in episodes:
        if ep.category != "ACUTE" or ep.is_provisional:
            continue
        by_group.setdefault(ep.group, []).append(ep)

    one_year_ago = as_of - timedelta(days=365)
    out = []
    for group, eps in by_group.items():
        eps.sort(key=lambda e: e.start)
        rule = rules.get(group, {})
        age_max = rule.get("age_max_days")
        considered = [e for e in eps
                      if age_max is None or age_in_days(dob, e.start) <= age_max]
        starts = [e.start for e in considered]

        triggered_on, trig_rule, trig_keys = None, None, []
        for win in rule.get("windows", []):
            n, months = win["min_count"], win["window_months"]
            for i, s in enumerate(starts):
                window_end = _add_months(s, months)
                j = bisect_left(starts, window_end)  # episodes with start < window_end
                if j - i >= n:
                    hit_date = starts[i + n - 1]  # the episode that completed the count
                    if triggered_on is None or hit_date < triggered_on:
                        triggered_on, trig_rule = hit_date, win
                        trig_keys = [e.key for e in considered[i:i + n]]
                    break

        last_12m = sum(1 for e in eps if e.start >= one_year_ago)
        expected = None
        if "expected_per_year" in rule:
            age_now_days = age_in_days(dob, as_of)
            exp = rule["expected_per_year"]
            expected = exp["under_5y"] if age_now_days < 1826 else exp["over_5y"]

        if triggered_on:
            context = "recurrent"
        elif expected is not None and last_12m <= expected:
            context = "typical for age"
        else:
            context = None

        out.append({
            "group": group,
            "label": eps[0].label,
            "is_recurrent": triggered_on is not None,
            "triggered_on": triggered_on.isoformat() if triggered_on else None,
            "rule": trig_rule,
            "episodes_total": len(eps),
            "episodes_last_12m": last_12m,
            "expected_per_year": expected,
            "context": context,
            "clinical_hint": rule.get("clinical_hint") if triggered_on else None,
            "episode_keys": trig_keys,
        })
    return sorted(out, key=lambda r: (not r["is_recurrent"], r["group"]))
