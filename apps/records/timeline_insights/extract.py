"""
Timeline insights: the text of a document → the words it mentions, with the date each belongs to.

    extracted text → medSpaCy (vocabulary.csv words + ConText flags) → DocumentText.insights     (run_insights)
    insights + vocabulary.csv  → name, kind, acute / chronic → one finding per date and name      (build_timeline)

Extraction stores only what needs the text: the word as written, its date, its sentence and four flags (negated,
family, suspected, resolved / historical / planned). What a word *is* (its name, kind, acute or chronic) is looked up in
vocabulary.csv when the timeline is built, so changing a row's nature or name shows at once; a new row only matches
documents read after it was added (run_all(redo=True) re-reads the stored text).

Which date a finding gets: a hospital-issued document uses its own date for everything. A patient's upload uses the
date on the finding's line, else the first date in the document, else none: the finding is "undated" rather than
placed on the upload day, because a patient can upload a report from any year of their life.
"""
import csv
import logging
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from django.db.models import Q

from apps.atomwalk.models import DocumentText, MedicalDocument
from ..services import awaiting_review_q, extract_text

logger = logging.getLogger(__name__)
VERSION = 3
VOCABULARY = Path(__file__).with_name("vocabulary.csv")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

# 14/03/2026 (day first) · 2026-03-14 · 14 Mar 2026
_DATE = re.compile(r"(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{4})"
                   r"|(?P<y2>\d{4})-(?P<m2>\d{2})-(?P<d2>\d{2})"
                   r"|(?P<d3>\d{1,2})[ -](?P<mon>[A-Za-z]{3})[a-z]*[ ,-]+(?P<y3>\d{4})")
_BIRTH = re.compile(r"\bdob\b|d\.o\.b|date of birth|\bborn\b", re.I)       # a birth date is never the event's date
_UNCERTAIN = re.compile(r"suspect|unconfirmed|not confirmed|possible|probable|rule out|r/o|\bquery\b", re.I)
_RESOLVED = re.compile(r"resolved|recovered|settled|subsided|completed the (?:prescribed )?course", re.I)
_VACCINE = re.compile(r"vaccin|immuni[sz]|booster|birth dose|\bBCG\b|\bOPV\b|\bDPT\b|\bMMR\b", re.I)   # "Hepatitis B - birth dose" is a vaccine, not a diagnosis
_STRENGTH = re.compile(r"\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|iu)\b", re.I)
_FREQUENCY = re.compile(r"\b(?:OD|BD|BID|TDS|TID|QID|HS|SOS|\d-\d-\d|once daily|twice daily|thrice daily)\b", re.I)
_GLUED = re.compile(r"(?<=[A-Za-z]{3})(?=\d{2,}(?:mg|mcg|ml|g)?)", re.I)   # OCR joins a drug and its dose: "Aldactone25MG"
_PRODUCT = re.compile(r"\s*(?:syrup|syp|tablets?|tab|capsules?|cap|drops|lozenges?|cream|gel|ointment|spray|lotion|inhaler)", re.I)   # "Cough Syrup" is a product, not a cough


@lru_cache(maxsize=1)
def _vocabulary():
    """{word: (name, kind, nature)} from vocabulary.csv. A row's name and each of its synonyms are words."""
    with VOCABULARY.open(encoding="utf-8", newline="") as f:
        return {word.lower(): (row["name"], row["kind"], row["nature"] or "unknown")
                for row in csv.DictReader(f) for word in [row["name"], *filter(None, row["synonyms"].split("|"))]}


@lru_cache(maxsize=1)
def _pipeline():
    """The medSpaCy pipeline that finds the vocabulary's words and flags negated / family / suspected / historical."""
    import spacy
    from loguru import logger as pyrush_log
    from medspacy.target_matcher import TargetRule
    pyrush_log.disable("PyRuSH")                     # its sentence splitter logs every token at debug level
    nlp = spacy.blank("en")
    for name in ("medspacy_pyrush", "medspacy_target_matcher", "medspacy_context"):
        nlp.add_pipe(name)
    nlp.get_pipe("medspacy_target_matcher").add([TargetRule(word, kind) for word, (_, kind, _) in _vocabulary().items()])
    return nlp


def _dates_in(line):
    found = []
    for m in _DATE.finditer(line):
        g = m.groupdict()
        try:
            if g["d"]:
                found.append(date(int(g["y"]), int(g["m"]), int(g["d"])))
            elif g["y2"]:
                found.append(date(int(g["y2"]), int(g["m2"]), int(g["d2"])))
            else:
                found.append(date(int(g["y3"]), _MONTHS.index(g["mon"].lower()) + 1, int(g["d3"])))
        except ValueError:                           # 31/02/2026, or three letters that are not a month
            pass
    latest = date.today() + timedelta(days=366)     # a misread year ("2614") is no date; a follow-up next month is
    return [d for d in found if date(1900, 1, 1) <= d <= latest]


def _line_dates(line):
    return [] if _BIRTH.search(line) else _dates_in(line)


def _dose(rest):
    """"500 mg BD" from what follows a medication on its line (up to the next comma), or None."""
    parts = [m.group(0) for m in (_STRENGTH.search(rest), _FREQUENCY.search(rest)) if m]
    return " ".join(parts) or None


def build_insights(text, fixed_date=None):
    """The insights JSON for one document's text. `fixed_date` is a hospital document's own date, given to every finding."""
    nlp = _pipeline()
    text = _GLUED.sub(" ", text)
    header = next((d for line in text.splitlines() for d in _line_dates(line)), None)
    entries = []
    for ent in nlp(text).ents:
        start = text.rfind("\n", 0, ent.start_char) + 1
        end = text.find("\n", ent.end_char)
        end = len(text) if end < 0 else end
        line = text[start:end].strip()
        if ent.label_ != "medication" and _PRODUCT.match(text[ent.end_char:end]):
            continue
        if ent.label_ == "condition" and _VACCINE.search(line):
            continue
        sentence = ent.sent.text
        on_line = _line_dates(line)
        when = fixed_date or (on_line[0] if on_line else header)
        entries.append({
            "date": when.isoformat() if when else None, "word": ent._.target_rule.literal.lower(), "evidence": line[:300],
            "dose": _dose(re.split(r"[,;]", text[ent.end_char:end])[0]) if ent.label_ == "medication" else None,
            "negated": ent._.is_negated, "family": ent._.is_family,
            "uncertain": bool(ent._.is_uncertain or _UNCERTAIN.search(sentence)),
            "when": "resolved" if _RESOLVED.search(sentence) else "history" if ent._.is_historical else "planned" if ent._.is_hypothetical else "current",
        })
    return {"version": VERSION, "entries": entries}


def _read_file(doc):
    doc.file.open("rb")
    try:
        return doc.file.read()
    finally:
        doc.file.close()


def _text_of(doc):
    """The document's extracted text. A hospital-issued document skipped the upload pipeline, so it has none yet:
    read it from its file now, the same way an upload is read."""
    try:
        return doc.text.extracted_text
    except DocumentText.DoesNotExist:
        text, engine = extract_text(_read_file(doc), doc.mime_type or "application/pdf")
        DocumentText.objects.create(document=doc, extracted_text=text, engine=engine)
        return text


def run_insights(document_id):
    """Read one document (extracting its text first if it has none) and save its insights."""
    doc = MedicalDocument.objects.get(pk=document_id)
    hospital_date = (doc.document_date or doc.created_at.date()) if doc.source_hospital_id else None
    insights = build_insights(_text_of(doc), hospital_date)
    DocumentText.objects.filter(document=doc).update(insights=insights)


def run_all(redo=False):
    """Insights for every finished document that has none yet, hospital-issued ones included (redo=True: for all, e.g.
    after adding rows to vocabulary.csv). Returns how many were done."""
    docs = MedicalDocument.objects.filter(status__in=(MedicalDocument.Status.COMPLETED, MedicalDocument.Status.REVIEW_REQUIRED))
    if not redo:
        docs = docs.filter(Q(text__isnull=True) | Q(text__insights__isnull=True))
    done = 0
    for document_id in list(docs.values_list("id", flat=True)):
        try:
            run_insights(document_id)
            done += 1
        except Exception:
            logger.warning("records: insights for document %s failed", document_id, exc_info=True)
    return done


def build_timeline(awpid, *, audience="patient", hospital_id=None, start=None, end=None, kind=None, name=None, nature=None, when=None, include_hidden=False):
    """{"days": [{"date", "entries"}], "undated": [entries]} for a patient's confirmed documents, newest day first.

    Each stored word is looked up in vocabulary.csv for its name, kind and acute / chronic (a word no longer in the
    vocabulary is skipped). One finding per date and name: a repeat in the same or another report only adds a source,
    and it is hidden (negated, family, suspected) only if every mention is. `start`/`end` are ISO dates, `name` is
    part of a name; undated findings are left out when a date range is asked for.

    `audience`: "patient" leaves medications out (a list of past drugs does nothing for the patient, and the
    Prescriptions page has them); "staff" (a doctor or nurse) includes them, with their dose and frequency.
    `hospital_id`: only the documents that hospital issued, for staff when the patient has not agreed to
    cross-hospital sharing."""
    from apps.hospitals.models import Hospital
    vocab = _vocabulary()
    docs = list(MedicalDocument.objects.filter(patient__awpid=awpid, text__insights__isnull=False,
                                               status__in=(MedicalDocument.Status.COMPLETED, MedicalDocument.Status.REVIEW_REQUIRED))
                .exclude(awaiting_review_q()).select_related("text"))
    if hospital_id is not None:
        docs = [d for d in docs if d.source_hospital_id == str(hospital_id)]
    hospitals = dict(Hospital.objects.using("default").filter(id__in={int(d.source_hospital_id) for d in docs if str(d.source_hospital_id or "").isdigit()})
                     .values_list("id", "name"))             # the hospital behind a hospital-issued document
    merged = {}
    for d in docs:
        for e in d.text.insights["entries"]:
            if e["word"] not in vocab:
                continue
            canonical, word_kind, word_nature = vocab[e["word"]]
            if audience == "patient" and word_kind == "medication":
                continue
            m = merged.setdefault((e["date"], canonical), {
                "date": e["date"], "name": canonical, "kind": word_kind, "nature": word_nature, "negated": True, "family": True,
                "uncertain": True, "whens": set(), "evidence": e["evidence"], "dose": None, "sources": {}})
            for flag in ("negated", "family", "uncertain"):
                m[flag] = m[flag] and e[flag]
            m["whens"].add(e["when"])
            m["dose"] = m["dose"] or e.get("dose")
            if e["when"] == "resolved":
                m["evidence"] = e["evidence"]            # "… resolved" says more than the heading before it
            m["sources"].setdefault(d.id, {"document_id": d.id, "file_name": d.file_name, "document_type": d.document_type, "evidence": e["evidence"],
                                           "hospital": hospitals.get(int(d.source_hospital_id), "") if str(d.source_hospital_id or "").isdigit() else ""})
    for m in merged.values():
        whens = m.pop("whens")
        m["when"] = "resolved" if "resolved" in whens else "current" if "current" in whens else sorted(whens)[0]
        m["sources"] = list(m["sources"].values())
        if m["uncertain"]:
            m["nature"] = "unknown"                      # "asthma is suspected" is not a chronic condition
    kept = [m for m in merged.values()
            if (include_hidden or not (m["negated"] or m["family"] or m["uncertain"]))
            and (not kind or m["kind"] == kind) and (not name or name.lower() in m["name"])
            and (not nature or m["nature"] == nature) and (not when or m["when"] == when)]
    dated = [m for m in kept if m["date"] and (not start or m["date"] >= start) and (not end or m["date"] <= end)]
    days = {}
    for m in sorted(dated, key=lambda m: m["date"], reverse=True):
        days.setdefault(m["date"], []).append(m)
    return {"days": [{"date": d, "entries": es} for d, es in days.items()],
            "undated": [] if (start or end) else [m for m in kept if not m["date"]]}
