"""
Immunization status against the configured (IAP) schedule.

Given records come from vaccination cards / prescriptions via extraction, or
are entered by clinic staff. Brand and combination names are resolved to
component vaccines ("Hexaxim" -> DTaP, Hib, Hep B, IPV) so one shot fills
several schedule rows.
"""
import re
from datetime import date, timedelta
from typing import List, Optional

from .clinical_rules import format_age
from .config import load_config
from .text_clean import glued_in, squash, tokens, views

UPCOMING_WINDOW_DAYS = 60
EARLY_TOLERANCE_DAYS = 4  # IAP allows a short grace before the minimum age


def resolve_vaccines(text: str, cfg=None) -> List[str]:
    """'Pentavalent-2' -> ['DTwP/DTaP', 'Hib', 'Hepatitis B']. The name is also found when the OCR ran it into its neighbours
    ('Hexaximdose2', 'DTPbooster 1'): see text_clean."""
    cfg = cfg or load_config()
    sched = cfg["immunization_schedule"]
    texts = views(text)
    squashed, words = squash(text), tokens(text)
    found = set()
    for combo, parts in sched.get("combination_vaccines", {}).items():
        if combo.startswith("_"):
            continue
        if any(re.search(rf"\b{re.escape(combo)}\b", v) for v in texts) or glued_in(combo, words, squashed):
            found.update(parts)
    for vaccine, aliases in sched["vaccine_aliases"].items():
        for alias in aliases:
            if any(re.search(rf"(^|[^a-z]){re.escape(alias)}([^a-z]|$)", v) for v in texts) or glued_in(alias, words, squashed):
                found.add(vaccine)
                break
    return sorted(found)


def immunization_status(dob: date, given: List[dict], as_of: date, cfg=None) -> dict:
    """
    given: [{"vaccine_text": "Penta 1", "given_on": date, "document_id": 12, "id": 5}, ...]
    -> {
         "rows": [{code, vaccine, dose, due_on, due_age, status, given_on, delay_days, document_id}],
         "extra_doses": [...], "unresolved": [...],
         "summary": {"given", "overdue", "due", "upcoming", "coverage_pct"}
       }
    """
    cfg = cfg or load_config()
    doses = sorted(cfg["immunization_schedule"]["doses"], key=lambda d: (d["vaccine"], d["due_days"]))

    # vaccine -> sorted unique [(date, record)]
    shots: dict = {}
    unresolved = []
    for rec in given:
        vaccines = resolve_vaccines(rec.get("vaccine_text", ""), cfg)
        if not vaccines or not rec.get("given_on"):
            unresolved.append(rec)
            continue
        for v in vaccines:
            shots.setdefault(v, {})[rec["given_on"]] = rec
    shots = {v: sorted(d.items()) for v, d in shots.items()}

    rows, extra = [], []
    by_vaccine: dict = {}
    for d in doses:
        by_vaccine.setdefault(d["vaccine"], []).append(d)

    for vaccine, sched_doses in by_vaccine.items():
        queue = list(shots.get(vaccine, []))
        for d in sched_doses:
            due_on = dob + timedelta(days=d["due_days"])
            overdue_on = due_on + timedelta(days=d["grace_days"])
            row = {
                "code": d["code"], "vaccine": vaccine, "dose": d["dose"],
                "due_on": due_on.isoformat(), "due_age": format_age(d["due_days"]),
                "status": None, "given_on": None, "delay_days": None,
                "document_id": None, "early": False, "late": False,
            }
            # skip shots clearly given before this dose's window (they belong to an earlier dose
            # that is not in the schedule, e.g. pulse-polio OPV)
            while queue and (queue[0][0] - due_on).days < -EARLY_TOLERANCE_DAYS - 28:
                extra.append({"vaccine": vaccine, "given_on": queue[0][0].isoformat()})
                queue.pop(0)
            if queue:
                g_date, rec = queue.pop(0)
                row.update(status="GIVEN", given_on=g_date.isoformat(),
                           delay_days=max(0, (g_date - due_on).days),
                           late=g_date > overdue_on,
                           document_id=rec.get("document_id"),
                           early=(g_date - due_on).days < -EARLY_TOLERANCE_DAYS)
            elif as_of > overdue_on:
                row["status"] = "OVERDUE"
                row["delay_days"] = (as_of - due_on).days
            elif as_of >= due_on:
                row["status"] = "DUE"
            elif (due_on - as_of).days <= UPCOMING_WINDOW_DAYS:
                row["status"] = "UPCOMING"
            else:
                row["status"] = "SCHEDULED"
            rows.append(row)
        for g_date, _ in queue:
            extra.append({"vaccine": vaccine, "given_on": g_date.isoformat()})

    rows.sort(key=lambda r: (r["due_on"], r["vaccine"]))
    count = lambda s: sum(1 for r in rows if r["status"] == s)  # noqa: E731
    due_so_far = sum(1 for r in rows if date.fromisoformat(r["due_on"]) <= as_of)
    given_of_due = sum(1 for r in rows if r["status"] == "GIVEN"
                       and date.fromisoformat(r["due_on"]) <= as_of)
    return {
        "source": cfg["immunization_schedule"].get("source"),
        "rows": rows,
        "extra_doses": extra,
        "unresolved": [{"vaccine_text": u.get("vaccine_text"), "id": u.get("id")} for u in unresolved],
        "summary": {
            "given": count("GIVEN"), "overdue": count("OVERDUE"), "due": count("DUE"),
            "upcoming": count("UPCOMING"),
            "coverage_pct": round(100 * given_of_due / due_so_far, 1) if due_so_far else None,
        },
    }


def next_due(status: dict) -> Optional[dict]:
    pending = [r for r in status["rows"] if r["status"] in ("OVERDUE", "DUE", "UPCOMING")]
    return pending[0] if pending else None
