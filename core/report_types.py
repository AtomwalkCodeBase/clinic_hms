"""
core/report_types.py
--------------------
The catalogue of lab-report *categories* ("panels") the My Reports vault
sorts an outside lab report into — CBC, Lipid Profile, Thyroid, and so on.

This is intentionally a code module, not a DB table: a medical taxonomy is
something we want reviewed and version-controlled, and adding a panel is a
one-line change plus a deploy, not a data edit. If it ever needs to be
clinician-editable at runtime, this shape ports cleanly to a model.

Each panel carries the *printed vocabulary* a real report of that kind
contains — analyte names, section titles, units. `classify()` scores a
document's text (already extracted — PDF text layer or OCR) against every
panel and returns the ranked matches. It never looks at the values, only
which names are present.

`STRONG` markers count double: they are near-unique to one panel
("triglycerides", "hba1c", "tsh"), where a plain marker ("glucose",
"protein") can appear in several.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Panel:
    slug: str
    label: str
    group: str                      # rough clinical grouping, for the UI
    markers: tuple = ()             # analyte / section names, lowercase substrings
    strong: tuple = ()             # near-unique markers, weighted x2
    titles: tuple = ()             # panel-heading phrases; a hit is weighted x3


# ── the catalogue ────────────────────────────────────────────────────────
# Ordered roughly by how common the panel is in Indian outpatient care.
PANELS: tuple = (
    Panel(
        slug="cbc", label="Complete Blood Count", group="Haematology",
        titles=("complete blood count", "cbc", "haemogram", "hemogram", "complete hemogram", "blood count"),
        strong=("haemoglobin", "hemoglobin", "platelet count", "total leucocyte", "total leukocyte",
                "differential count", "packed cell volume", "mcv", "mch", "mchc", "rdw"),
        markers=("wbc", "rbc", "neutrophil", "lymphocyte", "monocyte", "eosinophil", "basophil",
                 "haematocrit", "hematocrit", "pcv", "platelet", "leucocyte", "leukocyte",
                 "red cell", "white cell", "corpuscular"),
    ),
    Panel(
        slug="lipid", label="Lipid Profile", group="Biochemistry",
        titles=("lipid profile", "lipid panel", "lipidogram", "cholesterol profile"),
        strong=("triglyceride", "hdl cholesterol", "ldl cholesterol", "vldl", "hdl - cholesterol",
                "non-hdl", "non hdl", "chol/hdl", "cholesterol/hdl"),
        markers=("total cholesterol", "cholesterol", "hdl", "ldl", "serum cholesterol"),
    ),
    Panel(
        slug="lft", label="Liver Function Test", group="Biochemistry",
        titles=("liver function test", "liver function", "lft", "liver panel", "hepatic function"),
        strong=("sgpt", "sgot", "alt (sgpt)", "ast (sgot)", "bilirubin total", "bilirubin direct",
                "bilirubin indirect", "alkaline phosphatase", "ggt", "gamma gt", "serum albumin",
                "a/g ratio", "globulin"),
        markers=("alt", "ast", "bilirubin", "alp", "total protein", "albumin", "transaminase"),
    ),
    Panel(
        slug="kft", label="Kidney Function Test", group="Biochemistry",
        titles=("kidney function test", "renal function test", "kft", "rft", "renal panel",
                "kidney function", "renal profile"),
        strong=("serum creatinine", "blood urea nitrogen", "bun", "egfr", "e-gfr", "uric acid",
                "urea nitrogen", "creatinine clearance", "bun/creatinine"),
        markers=("creatinine", "urea", "sodium", "potassium", "chloride", "calcium", "phosphorus"),
    ),
    Panel(
        slug="thyroid", label="Thyroid Profile", group="Endocrinology",
        titles=("thyroid profile", "thyroid function test", "thyroid panel", "tft", "thyroid function"),
        strong=("tsh", "free t3", "free t4", "ft3", "ft4", "total t3", "total t4",
                "thyroid stimulating hormone", "anti tpo", "anti-tpo", "thyroglobulin"),
        markers=("t3", "t4", "triiodothyronine", "thyroxine"),
    ),
    Panel(
        slug="diabetes", label="Blood Sugar & HbA1c", group="Diabetes",
        titles=("diabetic profile", "diabetes profile", "glycaemic", "glycemic", "blood sugar",
                "glucose tolerance"),
        strong=("hba1c", "hb a1c", "glycated haemoglobin", "glycosylated haemoglobin", "glycated hemoglobin",
                "estimated average glucose", "fasting blood sugar", "postprandial blood sugar",
                "post prandial", "ogtt", "random blood sugar"),
        markers=("glucose", "fbs", "ppbs", "rbs", "sugar", "insulin", "c-peptide"),
    ),
    Panel(
        slug="urine", label="Urine Routine", group="Clinical Pathology",
        titles=("urine routine", "urine analysis", "urinalysis", "urine r/m", "urine routine and microscopy",
                "urine examination", "urine complete"),
        strong=("pus cells", "epithelial cells", "specific gravity", "urine albumin", "microscopic examination",
                "physical examination", "chemical examination", "casts", "crystals", "sediment"),
        markers=("urobilinogen", "ketone", "nitrite", "leucocyte esterase", "bacteria", "amorphous",
                 "colour", "appearance", "reaction", "deposits"),
    ),
    Panel(
        slug="electrolytes", label="Serum Electrolytes", group="Biochemistry",
        titles=("serum electrolytes", "electrolytes panel", "electrolyte panel", "electrolytes"),
        strong=("serum sodium", "serum potassium", "serum chloride", "serum bicarbonate", "anion gap",
                "ionized calcium"),
        markers=("sodium", "potassium", "chloride", "bicarbonate", "magnesium"),
    ),
    Panel(
        slug="vitamin", label="Vitamin & Mineral", group="Biochemistry",
        titles=("vitamin profile", "vitamin panel", "nutritional anaemia", "nutritional anemia",
                "bone health", "anaemia profile", "anemia profile", "iron studies"),
        strong=("25-hydroxy vitamin d", "25 oh vitamin d", "vitamin d3", "vitamin b12", "cyanocobalamin",
                "serum ferritin", "folate", "folic acid", "transferrin saturation", "tibc",
                "serum iron", "vitamin b-12"),
        markers=("vitamin d", "vitamin b12", "ferritin", "iron", "calcium", "phosphate"),
    ),
    Panel(
        slug="inflammation", label="Inflammatory Markers", group="Immunology",
        titles=("inflammatory markers", "acute phase reactants", "infection profile"),
        strong=("c-reactive protein", "c reactive protein", "hs-crp", "hs crp", "erythrocyte sedimentation rate",
                "procalcitonin", "d-dimer", "d dimer", "serum ferritin (crp"),
        markers=("crp", "esr", "sedimentation"),
    ),
    Panel(
        slug="cardiac", label="Cardiac Markers", group="Cardiology",
        titles=("cardiac profile", "cardiac markers", "cardiac risk markers", "cardiac panel"),
        strong=("troponin i", "troponin t", "trop-i", "trop i", "ck-mb", "ck mb", "nt-probnp", "nt probnp",
                "bnp", "creatine kinase mb", "high sensitivity troponin", "homocysteine", "lipoprotein (a)",
                "lipoprotein a", "apolipoprotein"),
        markers=("troponin", "creatine kinase", "cpk", "myoglobin"),
    ),
    Panel(
        slug="coagulation", label="Coagulation Profile", group="Haematology",
        titles=("coagulation profile", "coagulation panel", "clotting profile", "bt ct", "pt inr"),
        strong=("prothrombin time", "pt (inr)", "inr", "activated partial thromboplastin",
                "aptt", "a-ptt", "bleeding time", "clotting time", "d-dimer", "fibrinogen"),
        markers=("prothrombin", "thromboplastin", "coagulation"),
    ),
    Panel(
        slug="hormone", label="Hormone Panel", group="Endocrinology",
        titles=("hormone profile", "hormonal assay", "fertility profile", "reproductive hormones",
                "pcod profile", "pcos profile"),
        strong=("follicle stimulating hormone", "luteinizing hormone", "serum prolactin", "estradiol",
                "progesterone", "testosterone total", "free testosterone", "dhea-s", "dheas",
                "anti mullerian hormone", "amh", "shbg", "17-oh progesterone"),
        markers=("fsh", "lh", "prolactin", "testosterone", "cortisol", "growth hormone"),
    ),
    Panel(
        slug="infection", label="Infection Serology", group="Microbiology",
        titles=("fever profile", "febrile profile", "infection panel", "tropical fever", "viral panel"),
        strong=("dengue ns1", "dengue igg", "dengue igm", "widal test", "malaria parasite", "malaria antigen",
                "typhidot", "leptospira", "chikungunya", "scrub typhus", "hbsag", "anti hcv", "hiv 1 & 2",
                "vdrl", "covid-19 rt-pcr", "sars-cov-2"),
        markers=("dengue", "malaria", "widal", "typhoid", "salmonella", "antibody", "antigen", "igg", "igm"),
    ),
    Panel(
        slug="culture", label="Culture & Sensitivity", group="Microbiology",
        titles=("culture and sensitivity", "culture & sensitivity", "c/s", "culture report",
                "antibiotic sensitivity", "aerobic culture"),
        strong=("organism isolated", "colony count", "antibiotic susceptibility", "sensitive to",
                "resistant to", "no growth after", "growth of", "sensitivity pattern", "mic "),
        markers=("culture", "sensitivity", "isolate", "cfu", "susceptibility", "pathogen"),
    ),
)

PANELS_BY_SLUG = {p.slug: p for p in PANELS}
SLUGS = tuple(p.slug for p in PANELS)


def label_for(slug: str) -> str:
    p = PANELS_BY_SLUG.get(slug)
    return p.label if p else (slug or "").replace("_", " ").title()


# ── scoring ──────────────────────────────────────────────────────────────
CONFIDENT = 0.72         # a single-panel result at/above this auto-files
MULTI_KEEP = 0.55        # secondary panels at/above this join a health-package
_WORD = re.compile(r"[a-z0-9]+")


def _hits(text_lc: str, needles) -> int:
    return sum(1 for n in needles if n in text_lc)


def _hits_nonoverlapping(text_lc: str, needles) -> int:
    """
    Like _hits, but a needle that is itself a substring of another matched
    needle doesn't count separately. Several panels list both a full title
    phrase and a shorter form of it ("liver function test" / "liver
    function", "complete blood count" / "blood count", "thyroid function
    test" / "thyroid function") — counting both for one mention inflates
    that panel's title score relative to panels whose phrases don't nest.
    """
    matched = [n for n in needles if n in text_lc]
    return sum(1 for n in matched if not any(n != other and n in other for other in matched))


@dataclass
class PanelMatch:
    slug: str
    label: str
    score: int
    confidence: float


@dataclass
class PanelResult:
    categories: list = field(default_factory=list)   # slugs, primary first
    labels: list = field(default_factory=list)       # display labels, aligned with categories
    confidence: float = 0.0                          # of the primary
    multi: bool = False                              # health-package (>1 panel)
    matches: list = field(default_factory=list)      # all PanelMatch, ranked

    @property
    def primary(self):
        return self.categories[0] if self.categories else None

    @property
    def confident(self) -> bool:
        return bool(self.categories) and self.confidence >= CONFIDENT


def classify(text: str) -> PanelResult:
    """
    Rank the lab panels this text looks like. `text` is the already-extracted
    document text (PDF layer or OCR). Returns a PanelResult; `.confident` is
    the "file it without asking" gate, `.multi` flags a health package that
    should sit under every matched category.
    """
    if not text:
        return PanelResult()
    lc = " ".join(_WORD.findall(text.lower()))
    lc = " " + lc + " "                       # word-boundary-ish for short markers

    raw = []
    for p in PANELS:
        s = _hits(lc, p.markers) + 2 * _hits(lc, p.strong) + 3 * _hits_nonoverlapping(lc, p.titles)
        if s:
            raw.append((p, s))
    if not raw:
        return PanelResult()

    raw.sort(key=lambda t: t[1], reverse=True)
    top_score = raw[0][1]

    matches = []
    for p, s in raw:
        # confidence: a title hit or several strong analytes is decisive;
        # one or two plain markers is not.
        if s >= 6:
            c = min(0.97, 0.60 + 0.06 * s)
        elif s >= 4:
            c = 0.68
        elif s >= 2:
            c = 0.5
        else:
            c = 0.3
        matches.append(PanelMatch(p.slug, p.label, s, round(c, 2)))

    primary = matches[0]
    kept = [primary]
    for m in matches[1:]:
        # a secondary panel joins only if it stands on its own feet, not just
        # because a shared marker ("glucose", "calcium") leaked across.
        if m.score >= 4 and m.confidence >= MULTI_KEEP and m.score >= top_score * 0.5:
            kept.append(m)

    return PanelResult(
        categories=[m.slug for m in kept],
        labels=[m.label for m in kept],
        confidence=primary.confidence,
        multi=len(kept) > 1,
        matches=matches,
    )
