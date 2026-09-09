"""
apps/patients/consult_pad_lab_aliases.py
----------------------------------------
Doctor-shorthand aliases for ~95 common Indian OPD investigations, used ONLY
to help the consultation-pad recogniser turn a scrawled / abbreviated test
name into a standard one the front desk and lab will recognise.

This is a name-resolution aid and nothing more:
  - it never sets a LabTest foreign key,
  - it never adds a row to the tenant's lab_test catalog,
  - it never orders a test or changes a sample type.

Unlike apps/patients/consult_pad_drug_aliases.py (whose aliases only fire when
the generic is already stocked in the tenant's Drug catalog), this table is
usable on its own: most clinics do not maintain a full LabTest catalog, and an
investigation name carries no dosing risk. Where the tenant DOES have a
lab_test catalog, its names are layered on top and win for spelling — see
apps/patients/consult_pad_views.py::_lab_candidate_map.

Every `canonical` is the full standard name; `aliases` are the abbreviations,
acronyms and casual forms a doctor might actually write on the pad.
"""

# canonical standard name + the shorthand a doctor might scrawl.
SEED_TESTS = [
    # ── Haematology ──────────────────────────────────────────────────────────
    {"canonical": "Complete Blood Count", "aliases": ["cbc", "cp", "complete blood picture", "hemogram", "haemogram", "cbc with esr", "full blood count", "fbc", "blood count"]},
    {"canonical": "Haemoglobin", "aliases": ["hb", "hgb", "haemoglobin", "hemoglobin"]},
    {"canonical": "Total Leucocyte Count", "aliases": ["tlc", "tc", "wbc count", "total count", "leucocyte count"]},
    {"canonical": "Differential Leucocyte Count", "aliases": ["dlc", "dc", "differential count"]},
    {"canonical": "Platelet Count", "aliases": ["platelet", "plt", "platelets", "platelet count"]},
    {"canonical": "Peripheral Smear", "aliases": ["ps", "psmear", "peripheral blood smear", "pbs", "smear"]},
    {"canonical": "Erythrocyte Sedimentation Rate", "aliases": ["esr", "sed rate"]},
    {"canonical": "Reticulocyte Count", "aliases": ["retic", "retic count", "reticulocyte"]},
    {"canonical": "Prothrombin Time / INR", "aliases": ["pt", "pt inr", "pt/inr", "inr", "prothrombin time"]},
    {"canonical": "Activated Partial Thromboplastin Time", "aliases": ["aptt", "ptt"]},
    {"canonical": "D-Dimer", "aliases": ["d dimer", "ddimer", "d-dimer"]},
    {"canonical": "Blood Group & Rh Typing", "aliases": ["blood group", "bl grp", "abo rh", "grouping", "blood grouping", "abo typing"]},

    # ── Diabetes / glycaemic ────────────────────────────────────────────────
    {"canonical": "Fasting Blood Sugar", "aliases": ["fbs", "fbg", "fasting sugar", "fasting glucose", "gf"]},
    {"canonical": "Post Prandial Blood Sugar", "aliases": ["ppbs", "pp sugar", "post prandial sugar", "pp glucose", "gpp", "2hr ppbs"]},
    {"canonical": "Random Blood Sugar", "aliases": ["rbs", "random sugar", "random glucose", "grbs", "cbg"]},
    {"canonical": "HbA1c (Glycated Haemoglobin)", "aliases": ["hba1c", "hb a1c", "a1c", "glycated hb", "glycosylated hb"]},
    {"canonical": "Oral Glucose Tolerance Test", "aliases": ["ogtt", "gtt", "glucose tolerance test"]},
    {"canonical": "Fasting Insulin", "aliases": ["fasting insulin", "s insulin", "serum insulin"]},

    # ── Renal / electrolytes ────────────────────────────────────────────────
    {"canonical": "Renal Function Test", "aliases": ["rft", "kft", "renal function", "kidney function test", "kidney function"]},
    {"canonical": "Blood Urea", "aliases": ["urea", "blood urea", "b urea"]},
    {"canonical": "Blood Urea Nitrogen", "aliases": ["bun"]},
    {"canonical": "Serum Creatinine", "aliases": ["creatinine", "s creatinine", "s.creat", "creat", "sr creatinine"]},
    {"canonical": "Serum Uric Acid", "aliases": ["uric acid", "s uric acid", "sua"]},
    {"canonical": "Serum Electrolytes", "aliases": ["electrolytes", "s electrolytes", "serum electrolyte", "na k cl", "na/k", "na k", "rft with electrolytes"]},
    {"canonical": "Serum Sodium", "aliases": ["sodium", "s sodium", "na+", "s na"]},
    {"canonical": "Serum Potassium", "aliases": ["potassium", "s potassium", "k+", "s k"]},
    {"canonical": "Serum Calcium", "aliases": ["calcium", "s calcium", "s ca", "ca++"]},
    {"canonical": "Serum Phosphorus", "aliases": ["phosphorus", "phosphate", "s phosphorus", "po4"]},
    {"canonical": "Serum Magnesium", "aliases": ["magnesium", "s magnesium", "s mg", "mg++"]},

    # ── Liver ───────────────────────────────────────────────────────────────
    {"canonical": "Liver Function Test", "aliases": ["lft", "liver function", "liver panel", "lfts"]},
    {"canonical": "Serum Bilirubin (Total & Direct)", "aliases": ["bilirubin", "s bilirubin", "t bili", "total bilirubin", "sbr"]},
    {"canonical": "SGPT (ALT)", "aliases": ["sgpt", "alt", "alat"]},
    {"canonical": "SGOT (AST)", "aliases": ["sgot", "ast", "asat"]},
    {"canonical": "Alkaline Phosphatase", "aliases": ["alp", "alk phos", "s alp"]},
    {"canonical": "Gamma GT", "aliases": ["ggt", "gamma gt", "g gt", "ggtp"]},
    {"canonical": "Serum Total Protein & Albumin", "aliases": ["total protein", "protein albumin", "tp alb", "s protein", "a/g ratio", "albumin globulin"]},
    {"canonical": "Serum Albumin", "aliases": ["albumin", "s albumin", "s alb"]},
    {"canonical": "Serum Amylase", "aliases": ["amylase", "s amylase"]},
    {"canonical": "Serum Lipase", "aliases": ["lipase", "s lipase"]},

    # ── Lipids ──────────────────────────────────────────────────────────────
    {"canonical": "Lipid Profile", "aliases": ["lipid profile", "lipids", "lp", "fasting lipid profile", "flp", "lipid panel"]},
    {"canonical": "Total Cholesterol", "aliases": ["cholesterol", "t chol", "total cholesterol", "s cholesterol"]},
    {"canonical": "Serum Triglycerides", "aliases": ["triglycerides", "tg", "tgl", "s triglycerides"]},
    {"canonical": "HDL Cholesterol", "aliases": ["hdl", "hdl cholesterol"]},
    {"canonical": "LDL Cholesterol", "aliases": ["ldl", "ldl cholesterol"]},

    # ── Thyroid / endocrine ────────────────────────────────────────────────
    {"canonical": "Thyroid Profile (T3 T4 TSH)", "aliases": ["thyroid profile", "tft", "t3 t4 tsh", "thyroid function test", "thyroid panel"]},
    {"canonical": "TSH", "aliases": ["tsh", "s tsh", "thyroid stimulating hormone"]},
    {"canonical": "Free T3", "aliases": ["ft3", "free t3"]},
    {"canonical": "Free T4", "aliases": ["ft4", "free t4"]},
    {"canonical": "Serum Cortisol", "aliases": ["cortisol", "s cortisol", "am cortisol"]},
    {"canonical": "Serum Prolactin", "aliases": ["prolactin", "prl", "s prolactin"]},
    {"canonical": "Vitamin D (25-OH)", "aliases": ["vitamin d", "vit d", "25 oh vit d", "vitamin d3 level", "25-hydroxy vitamin d", "vit d level"]},
    {"canonical": "Vitamin B12", "aliases": ["vitamin b12", "vit b12", "b12", "cobalamin level", "s b12"]},
    {"canonical": "Serum Ferritin", "aliases": ["ferritin", "s ferritin"]},
    {"canonical": "Iron Studies", "aliases": ["iron studies", "iron profile", "serum iron", "tibc", "iron tibc"]},
    {"canonical": "Serum Folate", "aliases": ["folate", "folic acid level", "s folate", "rbc folate"]},

    # ── Cardiac ─────────────────────────────────────────────────────────────
    {"canonical": "Troponin I", "aliases": ["trop", "trop i", "troponin", "trop-i", "hs trop"]},
    {"canonical": "Troponin T", "aliases": ["trop t", "troponin t"]},
    {"canonical": "CPK-MB", "aliases": ["cpk mb", "ck mb", "ckmb", "cpk-mb"]},
    {"canonical": "CPK Total", "aliases": ["cpk", "ck total", "cpk total", "creatine kinase"]},
    {"canonical": "NT-proBNP", "aliases": ["bnp", "nt probnp", "pro bnp", "nt-pro bnp"]},

    # ── Inflammatory / infectious markers ──────────────────────────────────
    {"canonical": "C-Reactive Protein", "aliases": ["crp", "c reactive protein", "hs crp", "quantitative crp"]},
    {"canonical": "Procalcitonin", "aliases": ["pct", "procalcitonin"]},
    {"canonical": "Widal Test", "aliases": ["widal", "widal test", "typhoid widal"]},
    {"canonical": "Dengue NS1 Antigen", "aliases": ["ns1", "dengue ns1", "ns1 antigen", "dengue antigen"]},
    {"canonical": "Dengue Serology (IgG / IgM)", "aliases": ["dengue serology", "dengue igg igm", "dengue igm", "dengue elisa"]},
    {"canonical": "Malaria Parasite / Antigen", "aliases": ["mp", "malaria parasite", "mp smear", "malaria antigen", "qbc malaria", "mpqbc"]},
    {"canonical": "Peripheral Smear for Malarial Parasite", "aliases": ["psmp", "ps for mp", "smear for mp"]},
    {"canonical": "Scrub Typhus IgM", "aliases": ["scrub typhus", "scrub igm", "scrub typhus serology"]},
    {"canonical": "Leptospira IgM", "aliases": ["lepto", "leptospira", "lepto igm"]},
    {"canonical": "Blood Culture & Sensitivity", "aliases": ["blood culture", "bl c/s", "blood c/s", "bactec"]},
    {"canonical": "Urine Culture & Sensitivity", "aliases": ["urine culture", "urine c/s", "ur c/s"]},
    {"canonical": "COVID-19 RT-PCR", "aliases": ["covid rtpcr", "covid pcr", "rtpcr covid", "sars cov 2 pcr"]},
    {"canonical": "COVID-19 Rapid Antigen", "aliases": ["covid rat", "rapid antigen covid", "covid antigen"]},

    # ── Viral serology ─────────────────────────────────────────────────────
    {"canonical": "HBsAg", "aliases": ["hbsag", "hbs ag", "hepatitis b surface antigen", "australia antigen"]},
    {"canonical": "Anti-HCV", "aliases": ["hcv", "anti hcv", "hcv antibody", "hepatitis c antibody"]},
    {"canonical": "HIV I & II (ELISA)", "aliases": ["hiv", "hiv 1 2", "hiv elisa", "hiv i ii", "retroviral screen"]},
    {"canonical": "Viral Marker Screen (HBsAg, HCV, HIV)", "aliases": ["viral markers", "viral marker", "vm screen", "hbsag hcv hiv", "hiv hbsag hcv"]},

    # ── Urine / stool ─────────────────────────────────────────────────────
    {"canonical": "Urine Routine & Microscopy", "aliases": ["urine r/m", "urine re", "urine routine", "ur r/m", "urine r/e", "cue", "complete urine examination", "urine analysis", "urinalysis"]},
    {"canonical": "Urine Pregnancy Test", "aliases": ["upt", "urine pregnancy", "pregnancy test"]},
    {"canonical": "Urine Microalbumin", "aliases": ["microalbumin", "urine microalbumin", "spot microalbumin", "acr", "albumin creatinine ratio"]},
    {"canonical": "24-hour Urine Protein", "aliases": ["24 hr urine protein", "24 hour protein", "24h urine protein"]},
    {"canonical": "Stool Routine & Microscopy", "aliases": ["stool r/m", "stool re", "stool routine", "stool r/e", "stool examination"]},
    {"canonical": "Stool Occult Blood", "aliases": ["stool occult blood", "occult blood", "fobt", "stool for ob"]},

    # ── Imaging / cardiology procedures ───────────────────────────────────
    {"canonical": "Chest X-Ray PA View", "aliases": ["cxr", "chest x ray", "x ray chest", "chest xray", "cxr pa", "x-ray chest pa"]},
    {"canonical": "X-Ray", "aliases": ["x ray", "xray", "x-ray", "plain radiograph"]},
    {"canonical": "Ultrasound Abdomen & Pelvis", "aliases": ["usg abdomen", "usg abd pelvis", "usg w/a", "usg whole abdomen", "us abdomen", "sonography abdomen", "usg kub"]},
    {"canonical": "Ultrasound", "aliases": ["usg", "ultrasound", "sonography", "us scan"]},
    {"canonical": "Electrocardiogram", "aliases": ["ecg", "ekg", "12 lead ecg"]},
    {"canonical": "2D Echocardiography", "aliases": ["2d echo", "echo", "echocardiography", "2decho", "2d-echo"]},
    {"canonical": "Treadmill Test", "aliases": ["tmt", "treadmill test", "stress test", "ett"]},
    {"canonical": "CT Scan", "aliases": ["ct", "ct scan", "cect", "ncct"]},
    {"canonical": "MRI", "aliases": ["mri", "mr scan", "mri scan"]},
    {"canonical": "Mammography", "aliases": ["mammography", "mammogram"]},
    {"canonical": "Bone Mineral Density (DEXA)", "aliases": ["bmd", "dexa", "dexa scan", "bone density"]},

    # ── Misc common ──────────────────────────────────────────────────────
    {"canonical": "Serum Vitamin B-complex Panel", "aliases": ["b complex panel", "vitamin b panel"]},
    {"canonical": "Rheumatoid Factor", "aliases": ["ra factor", "rf", "rheumatoid factor", "ra test"]},
    {"canonical": "Anti-CCP", "aliases": ["anti ccp", "ccp", "acpa"]},
    {"canonical": "ANA (Antinuclear Antibody)", "aliases": ["ana", "antinuclear antibody", "ana by if"]},
    {"canonical": "Anti-Streptolysin O", "aliases": ["aso", "aslo", "aso titre"]},
    {"canonical": "Serum PSA", "aliases": ["psa", "prostate specific antigen", "s psa", "total psa"]},
    {"canonical": "Serum Beta-hCG", "aliases": ["beta hcg", "b hcg", "bhcg", "serum hcg", "quantitative hcg"]},
    {"canonical": "Sputum for AFB", "aliases": ["sputum afb", "afb", "sputum for afb", "zn stain sputum", "afb smear"]},
    {"canonical": "Sputum CBNAAT / GeneXpert", "aliases": ["cbnaat", "genexpert", "sputum genexpert", "gene xpert", "tb pcr"]},
    {"canonical": "Mantoux Test", "aliases": ["mantoux", "tst", "ppd", "tuberculin test"]},
    {"canonical": "Arterial Blood Gas", "aliases": ["abg", "blood gas", "arterial blood gas analysis"]},
    {"canonical": "Serum Procalcitonin", "aliases": ["s pct"]},
    {"canonical": "G6PD", "aliases": ["g6pd", "g 6 pd", "glucose 6 phosphate dehydrogenase"]},
    {"canonical": "Serum LDH", "aliases": ["ldh", "s ldh", "lactate dehydrogenase"]},
]


def alias_pairs():
    """
    Yield (surface_lower, canonical) for every canonical name and alias in the
    seed table. `surface` is the lower-cased string a doctor might scrawl;
    `canonical` is the standard, properly-cased test name it maps to. The
    canonical name also yields a pair against its own lower-case form so an
    already-standard string snaps to the canonical casing.
    """
    for t in SEED_TESTS:
        canon = (t.get("canonical") or "").strip()
        if not canon:
            continue
        yield canon.lower(), canon
        for a in t.get("aliases") or []:
            a = (a or "").strip().lower()
            if a:
                yield a, canon
