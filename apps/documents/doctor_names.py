"""
The doctor's name on a document, read from its text.

`find_doctor_name(text)` looks for "Dr." / "Dr" followed by a name and returns just the name ("Anita Rao"),
never the prefix: the app writes "Dr. " itself. It returns "" when no believable name is there. A name that looks
broken (two words stuck together, digits, a field label such as "UHID" right after it) is never returned: showing
nothing is better than showing something wrong. It reads whatever the OCR or PDF text layer gave, so it is a hint
the patient can correct, not a fact.

`clean_doctor_name(value)` is the one rule for a name typed by the patient: letters and spaces, plus the apostrophe,
hyphen and dot that real names carry (D'Souza, Anand-Kumar, A. K. Rao), at most 60 characters.
"""
import re

MAX_LENGTH = 60

_PREFIX = re.compile(r"\bdr\b\.?", re.IGNORECASE)
_WORD = re.compile(r"^[A-Za-z][A-Za-z'’\-]*$")
_GLUED = re.compile(r"[a-z][A-Z]")                      # "MukeshPanda": two words that lost their space
_TYPED = re.compile(r"^[A-Za-z][A-Za-z '’.\-]*$")

# Words that follow a name on a line (qualifications, field labels, the place) and are never part of it.
_STOP = {
    "mbbs", "md", "ms", "dnb", "bds", "mds", "dgo", "dch", "frcs", "dm", "mch", "phd", "msc", "bams", "bhms",
    "uhid", "reg", "regd", "registration", "regn", "no", "number", "id", "mob", "mobile", "ph", "phone", "tel",
    "consultant", "specialist", "physician", "surgeon", "radiologist", "pathologist", "officer", "medical",
    "date", "age", "sex", "gender", "patient", "name", "ref", "referred", "by", "signature", "sign", "stamp",
    "department", "dept", "hospital", "clinic", "laboratory", "laboratories", "lab", "labs", "pathlabs", "diagnostics",
    "centre", "center", "institute", "technique", "modality", "findings", "impression", "report", "address",
    "and", "the", "for", "of", "at", "on", "in", "to", "from", "with", "dr", "doctor",
    # a speciality printed after the name: "Dr. Veena Kulkarni - ENT", "Dr. Ravi Thakur Pulmonology"
    "ent", "general", "medicine", "surgery", "surgical", "paediatrics", "pediatrics", "paediatrician", "pediatrician",
    "orthopaedics", "orthopedics", "orthopaedic", "orthopedic", "cardiology", "cardiologist", "dermatology",
    "dermatologist", "neurology", "neurologist", "urology", "urologist", "ophthalmology", "ophthalmologist",
    "pulmonology", "pulmonologist", "endocrinology", "endocrinologist", "gastroenterology", "gastroenterologist",
    "gynaecology", "gynecology", "gynaecologist", "gynecologist", "nephrology", "oncology", "psychiatry", "psychiatrist",
    "radiology", "pathology", "geriatrics", "ger", "dentist", "dental", "diabetology", "rheumatology", "anaesthesia",
}


def _clean_word(token):
    return token.strip(",;:()[]{}|")


def find_doctor_name(text):
    """The first believable name after "Dr." in `text`, without the prefix, or ""."""
    for match in _PREFIX.finditer(text or ""):
        rest = (text[match.end():match.end() + 90]).split("\n")[0]
        words, broken = [], False
        for token in rest.split():
            closes = token[-1:] in ",;:)]|"
            word = _clean_word(token).rstrip(".")
            if not word:
                break
            if "-" in word:                              # "Kulkarni-ENT": the name is the part before a speciality
                head, _, tail = word.partition("-")
                if head and tail.lower() in _STOP:
                    word, closes = head, True
            if word.lower() in _STOP:
                break
            if not _WORD.match(word) or _GLUED.search(word) or word.lower().endswith(("'s", "’s")):
                broken = True
                break
            words.append(word)
            if closes or len(words) == 3:
                break
        if broken or not words or not any(len(w) >= 3 for w in words):
            continue
        name = " ".join(w.title() if (w.isupper() or w.islower()) else w for w in words)
        return name[:MAX_LENGTH]
    return ""


def clean_doctor_name(value):
    """A name typed by the patient, tidied, or None when it isn't acceptable. "" is acceptable (it clears the name)."""
    if value is None:
        return None
    name = re.sub(r"\s+", " ", str(value)).strip()
    if name.lower().startswith("dr.") or name.lower().startswith("dr "):
        name = name[3:].strip()                     # the app adds "Dr." itself
    if not name:
        return ""
    if len(name) > MAX_LENGTH or not _TYPED.match(name):
        return None
    return name
