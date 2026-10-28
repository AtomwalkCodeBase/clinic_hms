"""Making OCR text readable for the rules. RapidOCR often runs words together ("ImmunisationVisit-10Weeks",
"Hexaximdose2", "PATIENTBILLCUMRECEIPT"). The rules look at the text three ways and a keyword counts if any of them finds it:
the text as it is, the text with the obvious joins cut, and (for long keywords) the words of the text with a keyword glued inside."""
import re

_LOWER_UPPER = re.compile(r"(?<=[a-z])(?=[A-Z])")
_CAPS_THEN_WORD = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z]{2,})")       # "DOBMale" -> "DOB Male"
_CAPS_THEN_LOWER = re.compile(r"(?<=[A-Z]{2})(?=[a-z]{4,})")        # "DTPbooster" -> "DTP booster"
_AFTER_MARK = re.compile(r"(?<=[:;,)\]])(?=[A-Za-z0-9])")           # "Patient:Aarav" -> "Patient: Aarav"
_SQUASH = re.compile(r"[^a-z0-9]")
_TOKEN = re.compile(r"[a-z0-9]+")

# A keyword shorter than this is only ever matched as a word of its own: "mmr", "opv", "rx", "tab" would otherwise
# turn up inside other words.
GLUE_MIN_LEN = 7
# A word that holds a long keyword counts as OCR glue only if it has at least this many other letters: "hexaxim" in "hexaximdose2" (5 more) is
# glue, "ointment" in "appointment" (3 more) is an ordinary word.
GLUE_EXTRA = 5
# Ordinary words that contain a long keyword.
_CONTAINS_ORDINARY_WORD = {"ointment": ("appointment",)}


def _cut(text, caps_rule):
    """A join cut where the OCR clearly lost a space: a capital after a lower-case letter ("ImmunisationVisit"), a letter right after : ; , )
    and a word stuck to a run of capitals (`caps_rule`). A digit next to a letter is left alone ("HbA1c", "PCV13", "B12" stay whole)."""
    if not text:
        return ""
    return _AFTER_MARK.sub(" ", caps_rule.sub(" ", _LOWER_UPPER.sub(" ", text)))


def views(text):
    """The text as the rules read it, lower-case, every way it may have been meant: as it is, and with the joins cut either way
    ("DOBMale" is "DOB Male", "OPVdose" is "OPV dose": a run of capitals can be cut before or after its last letter)."""
    text = text or ""
    return [text.lower(), _cut(text, _CAPS_THEN_WORD).lower(), _cut(text, _CAPS_THEN_LOWER).lower()]


def squash(text):
    """Only the letters and digits, lower-case: what is left when every space and sign is taken out."""
    return _SQUASH.sub("", (text or "").lower())


def tokens(text):
    """The runs of letters and digits of the text, lower-case."""
    return _TOKEN.findall((text or "").lower())


def glued_in(keyword, words, squashed_text):
    """True when a long keyword is in the text with its neighbours glued on by the OCR. A one-word keyword is looked for inside the
    words of the text ("hexaxim" in "hexaximdose2"), and only at the start or the end of a word with GLUE_EXTRA more letters, so "ointment" is
    not found in "appointment". A phrase is looked for in the squashed text; every word of it needs 3 letters, so "hepatitis a" is never found
    in "hepatitis antigen"."""
    parts = re.split(r"[\s\-]+", keyword.strip().lower())
    k = squash(keyword)
    if len(k) < GLUE_MIN_LEN or any(len(squash(w)) < 3 for w in parts):
        return False
    if len(parts) > 1:
        return k in squashed_text
    for w in words:
        for common in _CONTAINS_ORDINARY_WORD.get(k, ()):          # "appointmentslip" is not "ointment" glued to something
            w = w.replace(common, "")
        if len(w) - len(k) >= GLUE_EXTRA and (w.startswith(k) or w.endswith(k)):
            return True
    return False
