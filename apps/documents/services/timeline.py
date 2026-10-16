"""Assembles the timeline API payload from already-computed pieces."""

from datetime import date
from typing import List, Optional

from .clinical_rules import age_in_days, format_age
from .config import load_config
from .episodes import Episode


def _overlaps(start: date, end: Optional[date], p_from: date, p_to: date) -> bool:
    return start <= p_to and (end or p_to) >= p_from


def _age_fields(dob: date, d: date) -> dict:
    days = age_in_days(dob, d)
    return {"age_days": days, "age_label": format_age(days)}


def build_timeline(*, dob: date, sex: str, p_from: date, p_to: date,
                   episodes: List[Episode], events_by_id: dict, recurrence: List[dict],
                   growth_points: List[dict], growth_alerts: List[dict],
                   immunization: dict, admissions: List[dict], critical_labs: List[dict],
                   birth_history: Optional[dict], audience: str = "guardian",
                   cfg=None) -> dict:
    """events_by_id: {event_id: {"date": date, "severity": str, "document_id": int,"""
    cfg = cfg or load_config()
    labels = cfg.get("patient_labels", {})
    lbl = (lambda code: labels.get(code, code)) if audience == "guardian" else (lambda code: code)
    recurrent_groups = {r["group"]: r for r in recurrence}
    in_period = lambda d: p_from <= d <= p_to  # noqa: E731

    lanes = []

    # 1. birth baseline (always shown, regardless of period)
    if birth_history:
        lanes.append({"id": "birth", "type": "birth", "label": "Birth",
                      "items": [{"date": dob.isoformat(), **birth_history}]})

    # 2. growth
    pts = [p for p in growth_points if in_period(p["measured_on"])]
    if pts:
        series = {"weight_kg": [], "height_cm": [], "head_circ_cm": []}
        for p in pts:
            for k in series:
                m = p.get(k)
                if m and m.get("value") is not None:
                    series[k].append({"date": p["measured_on"].isoformat(),
                                      "age_months": p["age_months"], "value": m["value"],
                                      "z": m["z"], "percentile": m["percentile"],
                                      "flag": m["flag"], "document_id": p.get("document_id")})
        lanes.append({"id": "growth", "type": "growth", "label": "Growth", "series": series,
                      "alerts": [a for a in growth_alerts
                                 if p_from.isoformat() <= a["to"] <= p_to.isoformat()]})

    # 3. immunization
    imm_items = []
    for r in immunization.get("rows", []):
        d = date.fromisoformat(r["given_on"] or r["due_on"])
        if in_period(d) or r["status"] in ("OVERDUE", "DUE"):
            imm_items.append({**r, "date": d.isoformat(), "status_label": lbl(r["status"])})
    if imm_items:
        lanes.append({"id": "immunization", "type": "immunization", "label": "Vaccines",
                      "items": imm_items, "summary": immunization.get("summary")})

    # 4. conditions - chronic first, then acute groups (recurrent ones first)
    def episode_events(ep):
        evs = []
        for eid in ep.event_ids:
            e = events_by_id.get(eid)
            if e and in_period(e["date"]):
                evs.append({"id": eid, "date": e["date"].isoformat(), "severity": e["severity"],
                            "severity_label": lbl(e["severity"]), "document_id": e.get("document_id"),
                            "text": e.get("condition_text"), "verified": e.get("is_verified", False),
                            **_age_fields(dob, e["date"])})
        return evs

    chronic_lanes, acute_by_group = [], {}
    for ep in episodes:
        if ep.is_provisional and audience == "guardian":
            continue
        if not _overlaps(ep.start, ep.end, p_from, p_to):
            continue
        item = {**ep.as_dict(), "events": episode_events(ep),
                "onset_age": format_age(age_in_days(dob, ep.start)),
                "peak_severity_label": lbl(ep.peak_severity)}
        if ep.category == "CHRONIC":
            chronic_lanes.append({"id": f"chronic:{ep.group}", "type": "chronic", "label": ep.label,
                                  "category_label": lbl("CHRONIC"), "episode": item})
        else:
            acute_by_group.setdefault(ep.group, {"label": ep.label, "episodes": []})["episodes"].append(item)

    lanes.extend(chronic_lanes)
    acute_lanes = []
    for group, data in acute_by_group.items():
        rec = recurrent_groups.get(group, {})
        acute_lanes.append({
            "id": f"acute:{group}", "type": "acute", "label": data["label"],
            "is_recurrent": rec.get("is_recurrent", False),
            "recurrence": rec or None,
            "category_label": lbl("RECURRENT") if rec.get("is_recurrent") else lbl("ACUTE"),
            "episodes": data["episodes"],
        })
    acute_lanes.sort(key=lambda l: (not l["is_recurrent"], -len(l["episodes"]), l["label"]))
    lanes.extend(acute_lanes)

    # 5. hospital stays + critical labs
    stays = [a for a in admissions
             if _overlaps(a["admitted_on"], a.get("discharged_on"), p_from, p_to)]
    crit = [c for c in critical_labs if in_period(c["date"])]
    if stays or crit:
        items = [{"kind": "ADMISSION", "start": a["admitted_on"].isoformat(),
                  "end": a["discharged_on"].isoformat() if a.get("discharged_on") else None,
                  "ward": a["ward"], "reason": a.get("reason"), "is_critical": a["is_critical"],
                  "label": lbl("CRITICAL") if a["is_critical"] else "Hospital stay",
                  "document_id": a.get("document_id"), **_age_fields(dob, a["admitted_on"])}
                 for a in stays]
        items += [{"kind": "LAB", "start": c["date"].isoformat(), "end": None,
                   "analyte": c["analyte"], "value": c["value"], "direction": c["direction"],
                   "label": lbl("CRITICAL_LAB"), "is_critical": True,
                   "document_id": c.get("document_id"), **_age_fields(dob, c["date"])}
                  for c in crit]
        lanes.append({"id": "hospital", "type": "hospital", "label": "Hospital & critical",
                      "items": sorted(items, key=lambda i: i["start"])})

    # summary for the count cards
    confirmed = [e for e in episodes if not e.is_provisional
                 and _overlaps(e.start, e.end, p_from, p_to)]
    summary = {
        "chronic_conditions": sum(1 for e in confirmed if e.category == "CHRONIC"),
        "acute_episodes": sum(1 for e in confirmed if e.category == "ACUTE"),
        "recurrent_conditions": sum(1 for r in recurrence if r["is_recurrent"]),
        "hospital_stays": len(stays),
        "critical_events": sum(1 for a in stays if a["is_critical"]) + len(crit),
        "growth_flags": sum(1 for p in pts for k in ("weight_kg", "height_cm", "head_circ_cm")
                            if p.get(k) and p[k].get("flag")),
        "vaccines_overdue": immunization.get("summary", {}).get("overdue", 0),
        "vaccine_coverage_pct": immunization.get("summary", {}).get("coverage_pct"),
    }
    # reassurance notes for parents: only worth saying when the count looks high
    typical = [r for r in recurrence
               if r.get("context") == "typical for age" and r["episodes_last_12m"] >= 3]
    notes = [f"{r['episodes_last_12m']} episodes of {r['label'].lower()} in the last year "
             f"- this is typical for the child's age" for r in typical]

    return {
        "patient": {"dob": dob.isoformat(), "sex": sex,
                    "age_label": format_age(age_in_days(dob, p_to))},
        "period": {"from": p_from.isoformat(), "to": p_to.isoformat()},
        "audience": audience,
        "summary": summary,
        "notes": notes,
        "lanes": lanes,
    }
