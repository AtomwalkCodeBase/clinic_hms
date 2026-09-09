"""
apps/patients/consult_pad_drug_aliases.py
-----------------------------------------
Doctor-shorthand aliases for ~130 common Indian OPD drugs, used ONLY to help
the consultation-pad recogniser resolve a scrawled / abbreviated drug name to
something the hospital actually stocks.

This is a name-resolution aid and nothing more:
  - it never sets a Drug foreign key,
  - it never adds a row to the tenant's catalog,
  - it never changes a dose, frequency, route or duration.

An alias only takes effect when its generic (or brand) is already present in
the tenant's apps.prescriptions.Drug catalog — see
apps/patients/consult_pad_views.py::_candidate_map. Keep each alias on exactly
one generic.
"""

# brand + generic + doctor-shorthand aliases. Strengths / forms deliberately
# omitted — this table is for name resolution only.
SEED_DRUGS = [
    {"brand": "Dolo", "generic": "Paracetamol", "aliases": ["pcm", "para", "paracetamol", "acetaminophen", "calpol", "crocin", "dolo 650", "p 650", "pcm 650", "febrinil"]},
    {"brand": "Combiflam", "generic": "Ibuprofen + Paracetamol", "aliases": ["ibuprofen+paracetamol", "brufen+pcm", "flexon", "ibugesic plus"]},
    {"brand": "Brufen", "generic": "Ibuprofen", "aliases": ["ibuprofen", "ibugesic", "brufen 400"]},
    {"brand": "Naprosyn", "generic": "Naproxen", "aliases": ["naproxen", "naxdom", "naprosyn 500"]},
    {"brand": "Zerodol", "generic": "Aceclofenac", "aliases": ["aceclofenac", "hifenac", "acenac", "zerodol sp", "zerodol p"]},
    {"brand": "Zerodol-P", "generic": "Aceclofenac + Paracetamol", "aliases": ["aceclofenac+paracetamol", "hifenac p", "acenac p"]},
    {"brand": "Voveran", "generic": "Diclofenac", "aliases": ["diclofenac", "dynapar", "voveran sr", "diclo"]},
    {"brand": "Etova", "generic": "Etoricoxib", "aliases": ["etoricoxib", "nucoxia", "etoshine"]},
    {"brand": "Ultracet", "generic": "Tramadol + Paracetamol", "aliases": ["tramadol+paracetamol", "dolotram", "tramazac"]},
    {"brand": "Augmentin", "generic": "Amoxicillin + Clavulanic acid", "aliases": ["amoxicillin+clavulanic acid", "amox-clav", "clavam", "moxikind cv", "advent", "amoxyclav", "augmentin 625", "co-amoxiclav"]},
    {"brand": "Mox", "generic": "Amoxicillin", "aliases": ["amoxicillin", "amoxil", "novamox", "mox 500", "amox"]},
    {"brand": "Azithral", "generic": "Azithromycin", "aliases": ["azithromycin", "azee", "azithral 500", "azithro", "zithromax", "azicip", "athm"]},
    {"brand": "Taxim-O", "generic": "Cefixime", "aliases": ["cefixime", "zifi", "cefix", "mahacef", "taxim o 200", "omnix"]},
    {"brand": "Cefpodox", "generic": "Cefpodoxime", "aliases": ["cefpodoxime", "cepodem", "doxcef", "podocef"]},
    {"brand": "Ciplox", "generic": "Ciprofloxacin", "aliases": ["ciprofloxacin", "cifran", "ciprobid", "ciplox 500"]},
    {"brand": "Levoflox", "generic": "Levofloxacin", "aliases": ["levofloxacin", "levoflox 500", "glevo", "l-cin", "levaquin"]},
    {"brand": "Oflox", "generic": "Ofloxacin", "aliases": ["ofloxacin", "zanocin", "oflox 200"]},
    {"brand": "Norflox", "generic": "Norfloxacin", "aliases": ["norfloxacin", "norflox tz", "noroxin"]},
    {"brand": "Metrogyl", "generic": "Metronidazole", "aliases": ["metronidazole", "flagyl", "metrogyl 400", "metron"]},
    {"brand": "Ornof", "generic": "Ofloxacin + Ornidazole", "aliases": ["ofloxacin+ornidazole", "oflomac oz", "normet", "zenflox oz", "o2"]},
    {"brand": "Doxy", "generic": "Doxycycline", "aliases": ["doxycycline", "doxt", "dox", "minocin", "doxy 1"]},
    {"brand": "Cef", "generic": "Cephalexin", "aliases": ["cephalexin", "sporidex", "phexin", "cephalexin 500"]},
    {"brand": "Cefadur", "generic": "Cefuroxime", "aliases": ["cefuroxime", "ceftum", "zocef", "supacef"]},
    {"brand": "Monocef", "generic": "Ceftriaxone", "aliases": ["ceftriaxone", "oframax", "mahacef inj", "rocephin"]},
    {"brand": "Pan", "generic": "Pantoprazole", "aliases": ["pantoprazole", "pantop", "pan 40", "pantocid", "pantodac"]},
    {"brand": "Pan-D", "generic": "Pantoprazole + Domperidone", "aliases": ["pantoprazole+domperidone", "pantop d", "pantocid d", "pan d"]},
    {"brand": "Omez", "generic": "Omeprazole", "aliases": ["omeprazole", "ocid", "omez 20", "omecip", "prilosec"]},
    {"brand": "Nexpro", "generic": "Esomeprazole", "aliases": ["esomeprazole", "esoz", "nexium", "nexpro 40", "esofag"]},
    {"brand": "Rantac", "generic": "Ranitidine", "aliases": ["ranitidine", "zinetac", "aciloc", "rantac 150"]},
    {"brand": "Razo", "generic": "Rabeprazole", "aliases": ["rabeprazole", "rabekind", "veloz"]},
    {"brand": "Digene", "generic": "Antacid gel", "aliases": ["antacid", "gelusil", "mucaine gel", "magaldrate", "digene gel"]},
    {"brand": "Cyclopam", "generic": "Dicyclomine + Paracetamol", "aliases": ["dicyclomine+paracetamol", "cyclopam", "spasmonil", "scompaz"]},
    {"brand": "Buscopan", "generic": "Hyoscine butylbromide", "aliases": ["hyoscine", "buscopan", "hyoscine butylbromide", "spasmo"]},
    {"brand": "Meftal-Spas", "generic": "Mefenamic acid + Dicyclomine", "aliases": ["mefenamic+dicyclomine", "meftal spas", "spasmindon"]},
    {"brand": "Drotin", "generic": "Drotaverine", "aliases": ["drotaverine", "drotin ds", "doverin"]},
    {"brand": "Cetzine", "generic": "Cetirizine", "aliases": ["cetirizine", "cet", "cetrizine", "alerid", "okacet", "zyrtec", "cetzine 10"]},
    {"brand": "Levocet", "generic": "Levocetirizine", "aliases": ["levocetirizine", "xyzal", "1 al", "levocet", "teczine", "vozet"]},
    {"brand": "Allegra", "generic": "Fexofenadine", "aliases": ["fexofenadine", "allegra 120", "fexova", "histafree"]},
    {"brand": "Avil", "generic": "Pheniramine", "aliases": ["pheniramine", "avil 25", "avil"]},
    {"brand": "Montek-LC", "generic": "Montelukast + Levocetirizine", "aliases": ["montelukast+levocetirizine", "montair lc", "monti lc", "montek lc", "romilast l"]},
    {"brand": "Montair", "generic": "Montelukast", "aliases": ["montelukast", "montek", "montair 10", "romilast"]},
    {"brand": "Deriphyllin", "generic": "Etophylline + Theophylline", "aliases": ["etophylline+theophylline", "deriphyllin retard", "deriphyllin"]},
    {"brand": "Asthalin", "generic": "Salbutamol", "aliases": ["salbutamol", "albuterol", "asthalin", "ventorlin", "levolin", "asthalin inhaler"]},
    {"brand": "Foracort", "generic": "Formoterol + Budesonide", "aliases": ["formoterol+budesonide", "symbicort", "foracort 200", "budamate"]},
    {"brand": "Budecort", "generic": "Budesonide", "aliases": ["budesonide", "budecort", "pulmicort"]},
    {"brand": "Ascoril", "generic": "Bromhexine + Terbutaline + Guaifenesin", "aliases": ["ascoril ls", "ascoril d", "bromhexine", "chericof"]},
    {"brand": "Wikoryl", "generic": "Paracetamol + Phenylephrine + CPM", "aliases": ["cold tablet", "sinarest", "coldarin", "d cold", "okacold", "wikoryl", "cold tab"]},
    {"brand": "Otrivin", "generic": "Xylometazoline", "aliases": ["xylometazoline", "otrivin", "nasivion", "nasal drops"]},
    {"brand": "Ondem", "generic": "Ondansetron", "aliases": ["ondansetron", "emeset", "vomikind", "ondem md", "zofran"]},
    {"brand": "Domstal", "generic": "Domperidone", "aliases": ["domperidone", "domstal", "vomistop", "motilium"]},
    {"brand": "Perinorm", "generic": "Metoclopramide", "aliases": ["metoclopramide", "perinorm", "reglan", "maxeron"]},
    {"brand": "Glycomet", "generic": "Metformin", "aliases": ["metformin", "glycomet", "gluconorm", "metformin sr", "obimet", "carbophage"]},
    {"brand": "Amaryl", "generic": "Glimepiride", "aliases": ["glimepiride", "amaryl", "glimestar", "zoryl", "glimy"]},
    {"brand": "Amaryl-M", "generic": "Glimepiride + Metformin", "aliases": ["glimepiride+metformin", "amaryl m", "glycomet gp", "zoryl m", "glimy m"]},
    {"brand": "Januvia", "generic": "Sitagliptin", "aliases": ["sitagliptin", "istavel", "januvia", "sitatab"]},
    {"brand": "Jardiance", "generic": "Empagliflozin", "aliases": ["empagliflozin", "jardiance", "gibtulio"]},
    {"brand": "Amlong", "generic": "Amlodipine", "aliases": ["amlodipine", "amlopres", "amlodac", "stamlo", "amlong 5", "norvasc"]},
    {"brand": "Telma", "generic": "Telmisartan", "aliases": ["telmisartan", "telma 40", "telsartan", "telvas", "arbitel"]},
    {"brand": "Telma-H", "generic": "Telmisartan + Hydrochlorothiazide", "aliases": ["telmisartan+hctz", "telma h", "telsartan h"]},
    {"brand": "Losar", "generic": "Losartan", "aliases": ["losartan", "losar 50", "repace", "covance"]},
    {"brand": "Envas", "generic": "Enalapril", "aliases": ["enalapril", "envas", "enam", "nuril"]},
    {"brand": "Metolar", "generic": "Metoprolol", "aliases": ["metoprolol", "metolar xr", "met xl", "starpress", "betaloc"]},
    {"brand": "Concor", "generic": "Bisoprolol", "aliases": ["bisoprolol", "concor", "corbis"]},
    {"brand": "Dytor", "generic": "Torsemide", "aliases": ["torsemide", "dytor", "tide"]},
    {"brand": "Lasix", "generic": "Furosemide", "aliases": ["furosemide", "lasix", "frusemide", "frusenex"]},
    {"brand": "Nebicard", "generic": "Nebivolol", "aliases": ["nebivolol", "nebicard", "nodon", "nebilong"]},
    {"brand": "Ecosprin", "generic": "Aspirin", "aliases": ["aspirin", "ecosprin 75", "aspirin 75", "disprin", "loprin"]},
    {"brand": "Clopilet", "generic": "Clopidogrel", "aliases": ["clopidogrel", "clopilet a", "deplatt", "plavix", "clavix"]},
    {"brand": "Atorva", "generic": "Atorvastatin", "aliases": ["atorvastatin", "atorlip", "storvas", "lipitor", "atorva 20", "tonact"]},
    {"brand": "Rosuvas", "generic": "Rosuvastatin", "aliases": ["rosuvastatin", "rozavel", "crestor", "rosuvas 10", "novastat"]},
    {"brand": "Thyronorm", "generic": "Levothyroxine", "aliases": ["levothyroxine", "eltroxin", "thyrox", "thyronorm 50", "thyup"]},
    {"brand": "Shelcal", "generic": "Calcium + Vitamin D3", "aliases": ["calcium", "shelcal 500", "gemcal", "calcimax", "ccm", "calcium carbonate"]},
    {"brand": "Uprise-D3", "generic": "Cholecalciferol", "aliases": ["vitamin d3", "calcirol", "d rise", "uprise d3", "cholecalciferol", "d3 60k"]},
    {"brand": "Neurobion", "generic": "Vitamin B complex", "aliases": ["b complex", "neurobion forte", "becosules"]},
    {"brand": "Nurokind", "generic": "Mecobalamin", "aliases": ["mecobalamin", "methylcobalamin", "nurokind", "methycobal", "cobadex"]},
    {"brand": "Zincovit", "generic": "Multivitamin", "aliases": ["multivitamin", "zincovit", "supradyn", "a to z", "polybion"]},
    {"brand": "Limcee", "generic": "Vitamin C", "aliases": ["vitamin c", "limcee", "celin", "ascorbic acid", "celwin"]},
    {"brand": "Livogen", "generic": "Ferrous ascorbate + Folic acid", "aliases": ["iron", "livogen", "dexorange", "orofer xt", "autrin", "fefol", "ferrous ascorbate", "iron folic"]},
    {"brand": "Folvite", "generic": "Folic acid", "aliases": ["folic acid", "folvite", "folinext"]},
    {"brand": "Electral", "generic": "Oral rehydration salts", "aliases": ["ors", "electral", "walyte", "prolyte", "rehydration"]},
    {"brand": "Sporlac", "generic": "Lactobacillus probiotic", "aliases": ["probiotic", "sporlac ds", "vizylac", "prowel", "econorm", "bifilac"]},
    {"brand": "Cremaffin", "generic": "Liquid paraffin + Milk of magnesia", "aliases": ["laxative", "cremaffin plus", "cremadu"]},
    {"brand": "Duphalac", "generic": "Lactulose", "aliases": ["lactulose", "duphalac", "looz", "livoluk"]},
    {"brand": "Dulcolax", "generic": "Bisacodyl", "aliases": ["bisacodyl", "dulcolax", "laxopeg"]},
    {"brand": "Isabgol", "generic": "Psyllium husk", "aliases": ["isabgol", "fibofit", "naturolax", "sat isabgol", "psyllium"]},
    {"brand": "Wysolone", "generic": "Prednisolone", "aliases": ["prednisolone", "wysolone", "omnacortil", "predmet", "deltacortril"]},
    {"brand": "Medrol", "generic": "Methylprednisolone", "aliases": ["methylprednisolone", "medrol", "solu medrol"]},
    {"brand": "Defcort", "generic": "Deflazacort", "aliases": ["deflazacort", "defcort", "zenflam", "moraceff"]},
    {"brand": "Betnesol", "generic": "Betamethasone", "aliases": ["betamethasone", "betnesol", "walacort"]},
    {"brand": "Ivermectol", "generic": "Ivermectin", "aliases": ["ivermectin", "ivermectol", "iverjohn", "scabishield"]},
    {"brand": "Zentel", "generic": "Albendazole", "aliases": ["albendazole", "zentel", "bandy", "albezole", "almex"]},
    {"brand": "Fluconazole", "generic": "Fluconazole", "aliases": ["fluconazole", "forcan", "zocon", "flucos", "fcn 150"]},
    {"brand": "Itraconazole", "generic": "Itraconazole", "aliases": ["itraconazole", "itraspor", "canditral", "sporanox", "itaspor"]},
    {"brand": "Terbinafine", "generic": "Terbinafine", "aliases": ["terbinafine", "terbicip", "zimig", "lamisil", "sebifin"]},
    {"brand": "Candid", "generic": "Clotrimazole", "aliases": ["clotrimazole", "candid cream", "canesten", "surfaz"]},
    {"brand": "Acivir", "generic": "Acyclovir", "aliases": ["acyclovir", "acivir 400", "zovirax", "ocuvir"]},
    {"brand": "Tamiflu", "generic": "Oseltamivir", "aliases": ["oseltamivir", "tamiflu", "fluvir", "antiflu"]},
    {"brand": "Betadine", "generic": "Povidone iodine", "aliases": ["povidone iodine", "betadine", "wokadine", "cipladine"]},
    {"brand": "Soframycin", "generic": "Framycetin", "aliases": ["framycetin", "soframycin", "framypen"]},
    {"brand": "T-Bact", "generic": "Mupirocin", "aliases": ["mupirocin", "t-bact", "supirocin", "bactroban"]},
    {"brand": "Silverex", "generic": "Silver sulfadiazine", "aliases": ["silver sulfadiazine", "silverex", "burnol", "argispread"]},
    {"brand": "Volini", "generic": "Diclofenac topical", "aliases": ["pain gel", "volini", "moov", "diclofenac gel", "dynapar gel"]},
    {"brand": "Liv-52", "generic": "Herbal hepatoprotective", "aliases": ["liv 52", "liv52 ds"]},
    {"brand": "Udiliv", "generic": "Ursodeoxycholic acid", "aliases": ["ursodeoxycholic acid", "udiliv", "udihep", "ursocol"]},
    {"brand": "Gabapin", "generic": "Gabapentin", "aliases": ["gabapentin", "gabapin", "gabantin", "neurontin"]},
    {"brand": "Pregabalin", "generic": "Pregabalin", "aliases": ["pregabalin", "pregeb", "nervup", "lyrica", "pregabid"]},
    {"brand": "Amitone", "generic": "Amitriptyline", "aliases": ["amitriptyline", "amitone", "tryptomer", "eliwel"]},
    {"brand": "Nexito", "generic": "Escitalopram", "aliases": ["escitalopram", "nexito", "cipralex", "szetalo", "feliz s"]},
    {"brand": "Levipil", "generic": "Levetiracetam", "aliases": ["levetiracetam", "levipil", "keppra", "torleva"]},
    {"brand": "Tegrital", "generic": "Carbamazepine", "aliases": ["carbamazepine", "tegrital", "zeptol", "mazetol"]},
]


# Common handwriting / OCR misreads of frequent OPD drugs -> the standard
# generic. These give the consult-pad recogniser an EXACT hit (no fuzzy
# threshold to clear) for the mistakes that actually recur on the pad.
# surface is lower-case; value must match a `generic` in SEED_DRUGS above.
MISREADS = {
    "panacetamol": "Paracetamol", "paracetmol": "Paracetamol",
    "paracetamal": "Paracetamol", "paracetemol": "Paracetamol",
    "paracitamol": "Paracetamol", "parcetamol": "Paracetamol",
    "pcm": "Paracetamol",
    "azithromicin": "Azithromycin", "azithromyacin": "Azithromycin",
    "azithromycine": "Azithromycin", "azithral": "Azithromycin",
    "amoxycillin": "Amoxicillin", "amoxicilin": "Amoxicillin",
    "amoxycillin trihydrate": "Amoxicillin",
    "pantoprazol": "Pantoprazole", "pantaprazole": "Pantoprazole",
    "pantoprozole": "Pantoprazole",
    "omeprazol": "Omeprazole", "omeprazol e": "Omeprazole",
    "rabeprazol": "Rabeprazole",
    "cetrizine": "Cetirizine", "cetirizin": "Cetirizine",
    "levocetrizine": "Levocetirizine", "levocitirizine": "Levocetirizine",
    "montelukas": "Montelukast", "montelukaste": "Montelukast",
    "metronidazol": "Metronidazole", "metronidazole 400": "Metronidazole",
    "ciprofloxacin hcl": "Ciprofloxacin", "ciprofloxacine": "Ciprofloxacin",
    "levofloxacine": "Levofloxacin", "ofloxacine": "Ofloxacin",
    "diclofenac sodium": "Diclofenac", "diclophenac": "Diclofenac",
    "aceclofinac": "Aceclofenac", "aceclofenak": "Aceclofenac",
    "ibuprufen": "Ibuprofen", "ibuprofin": "Ibuprofen",
    "metformin hcl": "Metformin", "metformine": "Metformin",
    "amlodipin": "Amlodipine", "amlodypine": "Amlodipine",
    "telmisartan h": "Telmisartan", "telmisarton": "Telmisartan",
    "atorvastatin calcium": "Atorvastatin", "atorvastatine": "Atorvastatin",
    "rosuvastatine": "Rosuvastatin",
    "azithromycin 500": "Azithromycin", "cefixime 200": "Cefixime",
    "cefixim": "Cefixime", "cefpodoxim": "Cefpodoxime",
    "domperidon": "Domperidone", "ondansetrone": "Ondansetron",
    "prednisolon": "Prednisolone", "methylprednisolon": "Methylprednisolone",
}


def alias_pairs():
    """
    Yield (surface_lower, generic_lower) for every brand and alias in the
    seed table. `surface` is the abbreviated/branded string a doctor might
    write; `generic` is what it maps to.
    """
    for d in SEED_DRUGS:
        gen = (d.get("generic") or "").strip().lower()
        if not gen:
            continue
        brand = (d.get("brand") or "").strip().lower()
        if brand:
            yield brand, gen
        for a in d.get("aliases") or []:
            a = (a or "").strip().lower()
            if a:
                yield a, gen


def seed_name_pairs():
    """
    Yield (surface_lower, canonical) where `canonical` is the standard,
    properly-cased generic name — for use as a STANDALONE drug-name resolver
    when the tenant has no (or a sparse) Drug catalog. Covers every generic,
    brand and alias in SEED_DRUGS plus the MISREADS table. The generic also
    maps to itself so an already-standard string snaps to the right casing.
    """
    for d in SEED_DRUGS:
        gen = (d.get("generic") or "").strip()
        if not gen:
            continue
        yield gen.lower(), gen
        brand = (d.get("brand") or "").strip().lower()
        if brand:
            yield brand, gen
        for a in d.get("aliases") or []:
            a = (a or "").strip().lower()
            if a:
                yield a, gen
    for surface, canon in MISREADS.items():
        yield surface, canon
