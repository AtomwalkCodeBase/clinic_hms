"""
Management command: seed_drug_catalog

Makes the pharmacist module demo-ready in one shot:
  1. Seeds the configurable DrugFormType pick-list (Tablet, Capsule, Syrup,
     Injection, Drops, Cream / Ointment, Inhaler, Patch, Other) — every
     form is represented by at least one seeded drug below.
  2. Seeds a starter Drug catalog covering common, everyday prescribing
     needs across the widest practical range of symptoms/conditions a
     general hospital sees day to day (fever, infections, diabetes,
     hypertension, allergy, GI, pain, respiratory, skin, eye/ear, mental
     health, etc.) — enough breadth for a realistic demo, not an
     exhaustive formulary.

Codes are assigned through NNTM (entity="drug", prefix "DRG-"), same as
the Drug Catalog Setup page's "Add Drug" form — never typed by hand.
Existing rows (matched by name, case-insensitive) are skipped, so this is
safe to re-run.

Usage:
  python manage.py seed_drug_catalog --tenant aw_greenleaf_clinic
  python manage.py seed_drug_catalog --all-tenants
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from apps.tenants.models import Tenant
from apps.tenants.utils import _make_db_config
from apps.org.models import Branch, NextNumber
from apps.prescriptions.models import Drug, DrugFormType
from core.utils.nntm import get_next_number

# Every form used by at least one drug below.
DRUG_FORMS = [
    "Tablet", "Capsule", "Syrup", "Injection", "Drops",
    "Cream / Ointment", "Inhaler", "Patch", "Other",
]

# (name, generic_name, form, strength, unit) — grouped by form, each row's
# comment names the everyday symptom(s)/condition(s) it's a basic starter
# for. Not an indications field on the model (there isn't one) — just
# picking real, recognizable drugs that give the demo breadth across the
# common-symptoms list (fever, infections, diabetes, BP, allergy, GI,
# pain, respiratory, skin, eye/ear, mental health, and more).
STARTER_DRUGS = [
    # --- Tablet -------------------------------------------------------
    ("Paracetamol",              "Paracetamol",            "Tablet", "500mg",  "mg"),  # fever, body pain, headache
    ("Ibuprofen",                "Ibuprofen",               "Tablet", "400mg",  "mg"),  # pain, inflammation, arthritis
    ("Aspirin",                  "Acetylsalicylic Acid",    "Tablet", "75mg",   "mg"),  # heart attack/stroke prevention
    ("Azithromycin",             "Azithromycin",            "Tablet", "500mg",  "mg"),  # throat/sinus/respiratory infection
    ("Metformin",                "Metformin HCl",           "Tablet", "500mg",  "mg"),  # type 2 diabetes
    ("Glimepiride",              "Glimepiride",             "Tablet", "2mg",    "mg"),  # diabetes
    ("Amlodipine",               "Amlodipine Besylate",     "Tablet", "5mg",    "mg"),  # high blood pressure
    ("Losartan",                 "Losartan Potassium",      "Tablet", "50mg",   "mg"),  # hypertension
    ("Atorvastatin",             "Atorvastatin",            "Tablet", "10mg",   "mg"),  # high cholesterol
    ("Pantoprazole",             "Pantoprazole",            "Tablet", "40mg",   "mg"),  # acidity, gastritis, acid reflux
    ("Domperidone",              "Domperidone",             "Tablet", "10mg",   "mg"),  # nausea, vomiting, indigestion
    ("Ondansetron",              "Ondansetron",             "Tablet", "4mg",    "mg"),  # nausea, vomiting
    ("Loperamide",               "Loperamide",              "Tablet", "2mg",    "mg"),  # diarrhea
    ("Cetirizine",               "Cetirizine",              "Tablet", "10mg",   "mg"),  # allergy, allergic rhinitis
    ("Montelukast",              "Montelukast",             "Tablet", "10mg",   "mg"),  # asthma, allergic rhinitis
    ("Metronidazole",            "Metronidazole",           "Tablet", "400mg",  "mg"),  # gastroenteritis, infection
    ("Ciprofloxacin",            "Ciprofloxacin",           "Tablet", "500mg",  "mg"),  # UTI, infection
    ("Diclofenac",               "Diclofenac Sodium",       "Tablet", "50mg",   "mg"),  # joint pain, muscle strain, arthritis
    ("Sertraline",               "Sertraline",              "Tablet", "50mg",   "mg"),  # depression, anxiety, stress
    ("Alprazolam",               "Alprazolam",              "Tablet", "0.25mg", "mg"),  # anxiety, insomnia
    ("Levothyroxine",            "Levothyroxine Sodium",    "Tablet", "50mcg",  "mcg"), # hypothyroidism
    ("Folic Acid",               "Folic Acid",              "Tablet", "5mg",    "mg"),  # anemia, pregnancy support
    ("Calcium + Vitamin D3",     "Calcium Carbonate + D3",  "Tablet", "500mg",  "mg"),  # bone/joint health, weakness
    ("Multivitamin",             "Multivitamin & Minerals", "Tablet", "1 tab",  "unit"),# fatigue, weakness, general malaise
    ("Prednisolone",             "Prednisolone",             "Tablet", "10mg",   "mg"),  # severe allergy, inflammation
    ("Clopidogrel",              "Clopidogrel",             "Tablet", "75mg",   "mg"),  # heart disease, stroke prevention
    ("Phenytoin",                "Phenytoin Sodium",        "Tablet", "100mg",  "mg"),  # epilepsy, seizures
    ("Sumatriptan",              "Sumatriptan",             "Tablet", "50mg",   "mg"),  # migraine
    ("Rabeprazole",              "Rabeprazole",             "Tablet", "20mg",   "mg"),  # peptic ulcer, GERD
    ("Ferrous Sulfate",          "Iron + Folic Acid",       "Tablet", "325mg",  "mg"),  # anemia, weight loss recovery

    # --- Capsule --------------------------------------------------------
    ("Amoxicillin",              "Amoxicillin",             "Capsule", "500mg", "mg"),  # throat/skin/UTI infection
    ("Omeprazole",               "Omeprazole",              "Capsule", "20mg",  "mg"),  # acid reflux, gastritis
    ("Doxycycline",              "Doxycycline",             "Capsule", "100mg", "mg"),  # infection, acne
    ("Tramadol",                 "Tramadol HCl",            "Capsule", "50mg",  "mg"),  # moderate-severe pain
    ("Fluoxetine",               "Fluoxetine",              "Capsule", "20mg",  "mg"),  # depression

    # --- Syrup ------------------------------------------------------------
    ("Paracetamol Syrup",        "Paracetamol",             "Syrup", "125mg/5ml", "ml"), # fever, body pain (pediatric)
    ("Cough Syrup",              "Dextromethorphan",        "Syrup", "10mg/5ml",  "ml"), # dry cough
    ("Ambroxol Syrup",           "Ambroxol",                "Syrup", "15mg/5ml",  "ml"), # productive cough, bronchitis
    ("Cetirizine Syrup",         "Cetirizine",              "Syrup", "5mg/5ml",   "ml"), # allergy (pediatric)
    ("Amoxicillin Suspension",   "Amoxicillin",             "Syrup", "125mg/5ml", "ml"), # infection (pediatric)
    ("Lactulose Syrup",          "Lactulose",               "Syrup", "10g/15ml",  "ml"), # constipation

    # --- Injection --------------------------------------------------------
    ("Ceftriaxone Injection",    "Ceftriaxone",             "Injection", "1g",   "mg"),  # severe infection
    ("Diclofenac Injection",     "Diclofenac Sodium",       "Injection", "75mg", "mg"),  # severe pain
    ("Human Insulin (Mixtard)",  "Insulin",                 "Injection", "40IU/ml", "ml"), # diabetes
    ("Tetanus Toxoid (TT)",      "Tetanus Toxoid",          "Injection", "0.5ml", "ml"),  # wound/injury prevention
    ("Dexamethasone Injection",  "Dexamethasone",           "Injection", "4mg",  "mg"),   # severe allergy, asthma flare

    # --- Drops --------------------------------------------------------------
    ("Ciprofloxacin Eye Drops",  "Ciprofloxacin",           "Drops", "0.3%",  "%"),   # eye infection, conjunctivitis
    ("Carboxymethylcellulose Eye Drops", "Artificial Tears", "Drops", "0.5%", "%"),   # dry eyes
    ("Timolol Eye Drops",        "Timolol Maleate",         "Drops", "0.5%",  "%"),   # glaucoma
    ("Sodium Chloride Nasal Drops", "Saline",               "Drops", "0.9%",  "%"),   # common cold, sinusitis
    ("Ofloxacin Ear Drops",      "Ofloxacin",               "Drops", "0.3%",  "%"),   # ear infection, ear pain

    # --- Cream / Ointment -------------------------------------------------
    ("Clotrimazole Cream",       "Clotrimazole",            "Cream / Ointment", "1%", "%"),  # fungal infection
    ("Betamethasone Cream",      "Betamethasone",           "Cream / Ointment", "0.1%", "%"), # eczema, dermatitis, psoriasis
    ("Mupirocin Ointment",       "Mupirocin",               "Cream / Ointment", "2%", "%"),  # skin infection
    ("Diclofenac Gel",           "Diclofenac Sodium",       "Cream / Ointment", "1%", "%"),  # muscle spasm, joint pain
    ("Calamine Lotion",          "Calamine",                "Cream / Ointment", "15%", "%"), # skin rash, allergy
    ("Silver Sulfadiazine Cream","Silver Sulfadiazine",     "Cream / Ointment", "1%", "%"),  # skin ulcer

    # --- Inhaler ------------------------------------------------------------
    ("Salbutamol Inhaler",       "Salbutamol",              "Inhaler", "100mcg/puff", "mcg"), # asthma, wheezing, breathing difficulty
    ("Budesonide Inhaler",       "Budesonide",              "Inhaler", "200mcg/puff", "mcg"), # asthma, COPD
    ("Tiotropium Inhaler",       "Tiotropium Bromide",      "Inhaler", "18mcg/puff",  "mcg"), # COPD

    # --- Patch --------------------------------------------------------------
    ("Diclofenac Patch",         "Diclofenac",              "Patch", "100mg", "mg"),  # back pain, muscle spasm
    ("Fentanyl Patch",           "Fentanyl",                "Patch", "25mcg/hr", "mcg"), # severe chronic pain
    ("Nicotine Patch",           "Nicotine",                "Patch", "21mg",  "mg"),  # smoking cessation support

    # --- Other ----------------------------------------------------------------
    ("ORS Sachet",               "Oral Rehydration Salts",  "Other", "1 sachet/L", "unit"), # dehydration, diarrhea, vomiting
    ("Levosalbutamol Nebulizer Solution", "Levosalbutamol", "Other", "0.63mg/2.5ml", "ml"),  # breathing difficulty, wheezing
    ("Glucose Powder",           "Dextrose",                "Other", "1 sachet", "unit"),   # hypoglycemia
]


class Command(BaseCommand):
    help = ("Seed the configurable drug-form list and a starter drug catalog for a "
            "tenant (or all tenants), covering common everyday symptoms/conditions "
            "and every drug form. Safe to re-run — skips existing names.")

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="db_name", default=None,
                             help="Tenant db_name to target (e.g. aw_greenleaf_clinic).")
        parser.add_argument("--all-tenants", action="store_true",
                             help="Target every active tenant instead of one.")

    def handle(self, *args, **options):
        db_name = options.get("db_name")
        all_tenants = options.get("all_tenants")

        if not db_name and not all_tenants:
            raise CommandError("Specify --tenant <db_name> or --all-tenants.")

        tenants = Tenant.objects.filter(db_name=db_name) if db_name else Tenant.objects.filter(is_active=True)
        if db_name and not tenants.exists():
            raise CommandError(f"No tenant found with db_name='{db_name}'")

        total_forms = 0
        total_drugs = 0
        for tenant in tenants:
            if tenant.db_name not in settings.DATABASES:
                settings.DATABASES[tenant.db_name] = _make_db_config(tenant.db_name)
            db = tenant.db_name

            branch = Branch.objects.using(db).filter(is_active=True).order_by("id").first()
            if not branch:
                self.stdout.write(self.style.WARNING(f"  {tenant.name} ({db}): no branch found — skipped."))
                continue

            # 1. Drug forms.
            existing_forms = {n.lower() for n in DrugFormType.objects.using(db).values_list("name", flat=True)}
            form_count = 0
            for form_name in DRUG_FORMS:
                if form_name.lower() in existing_forms:
                    continue
                DrugFormType.objects.using(db).create(name=form_name, is_active=True)
                form_count += 1

            # 2. Drug catalog (NNTM code assignment, same as the Add Drug form).
            NextNumber.objects.using(db).get_or_create(
                branch_id=branch.id, entity="drug",
                defaults={"prefix": "DRG-", "pad_length": 4, "last_number": 0},
            )
            existing_drugs = {n.lower() for n in Drug.objects.using(db).values_list("name", flat=True)}
            drug_count = 0
            for name, generic_name, form, strength, unit in STARTER_DRUGS:
                if name.lower() in existing_drugs:
                    continue
                code, _ = get_next_number(branch_id=branch.id, entity="drug", using=db)
                Drug.objects.using(db).create(
                    name=name, generic_name=generic_name, drug_code=code,
                    form=form, strength=strength, unit=unit, is_active=True,
                )
                drug_count += 1

            self.stdout.write(self.style.SUCCESS(
                f"  {tenant.name} ({db}): +{form_count} drug form(s), +{drug_count} drug(s) "
                f"({len(DRUG_FORMS) - form_count} form(s) and {len(STARTER_DRUGS) - drug_count} drug(s) already present)."
            ))
            total_forms += form_count
            total_drugs += drug_count

        self.stdout.write(
            f"\nDone — {total_forms} drug form(s) and {total_drugs} drug(s) added across {tenants.count()} tenant(s)."
        )
