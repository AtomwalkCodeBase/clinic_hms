// ─── Common ICD-10 codes (expandable; backend search in Phase 2) ─────────────
// Broad, multi-specialty starter set so the picker has something relevant no
// matter what the patient booked for — general medicine, ENT, cardiology,
// pulmonology, GI, endocrine/metabolic, renal/urology, ortho/rheum, neuro,
// dermatology, gynae/obstetrics, ophthalmology, psychiatry, infectious
// disease, pediatrics, and routine/admin encounters. Each `keywords` list
// widens what a booked chief-complaint string can match against beyond just
// the clinical description text (see suggestForComplaint below).
export const ICD10_CODES = [
  // Respiratory / ENT
  { code: "J06.9",  desc: "Acute upper respiratory infection, unspecified", keywords: ["cold", "uri", "throat"] },
  { code: "J02.9",  desc: "Acute pharyngitis, unspecified", keywords: ["throat pain", "sore throat"] },
  { code: "J03.90", desc: "Acute tonsillitis, unspecified", keywords: ["tonsils", "throat"] },
  { code: "J00",    desc: "Acute nasopharyngitis (common cold)", keywords: ["cold", "runny nose", "sneezing"] },
  { code: "J01.90", desc: "Acute sinusitis, unspecified", keywords: ["sinus", "sinusitis", "nasal congestion"] },
  { code: "J31.0",  desc: "Chronic rhinitis", keywords: ["nasal congestion", "runny nose"] },
  { code: "H66.90", desc: "Otitis media, unspecified", keywords: ["ear pain", "ear infection"] },
  { code: "H61.20", desc: "Impacted cerumen (ear wax)", keywords: ["ear wax", "ear blockage"] },
  { code: "J18.9",  desc: "Pneumonia, unspecified", keywords: ["pneumonia", "chest infection"] },
  { code: "J20.9",  desc: "Acute bronchitis, unspecified", keywords: ["bronchitis", "cough", "chest cold"] },
  { code: "J45.9",  desc: "Asthma, unspecified", keywords: ["asthma", "wheeze", "breathless"] },
  { code: "J44.9",  desc: "Chronic obstructive pulmonary disease, unspecified", keywords: ["copd", "breathless"] },
  { code: "J30.9",  desc: "Allergic rhinitis, unspecified", keywords: ["allergy", "sneezing", "nasal congestion"] },
  // GI
  { code: "A09",    desc: "Gastroenteritis and colitis of unspecified origin", keywords: ["loose motion", "diarrhea", "vomiting"] },
  { code: "K21.0",  desc: "GERD with esophagitis", keywords: ["acidity", "heartburn", "reflux"] },
  { code: "K29.7",  desc: "Gastritis, unspecified", keywords: ["acidity", "stomach pain"] },
  { code: "K30",    desc: "Functional dyspepsia", keywords: ["indigestion", "bloating"] },
  { code: "K59.00", desc: "Constipation, unspecified", keywords: ["constipation"] },
  { code: "K52.9",  desc: "Noninfective gastroenteritis and colitis, unspecified", keywords: ["diarrhea", "loose motion"] },
  { code: "K80.20", desc: "Calculus of gallbladder without cholecystitis", keywords: ["gallstone", "gallbladder"] },
  { code: "K76.0",  desc: "Fatty liver, not elsewhere classified", keywords: ["fatty liver"] },
  { code: "K35.80", desc: "Acute appendicitis, unspecified", keywords: ["appendicitis", "abdominal pain"] },
  { code: "K64.9",  desc: "Unspecified hemorrhoids", keywords: ["piles", "hemorrhoids", "bleeding"] },
  // Endocrine / metabolic
  { code: "E11.9",  desc: "Type 2 diabetes mellitus without complications", keywords: ["diabetes", "sugar", "blood sugar"] },
  { code: "E11.65", desc: "Type 2 diabetes mellitus with hyperglycemia", keywords: ["diabetes", "high sugar"] },
  { code: "E10.9",  desc: "Type 1 diabetes mellitus without complications", keywords: ["diabetes", "sugar"] },
  { code: "E03.9",  desc: "Hypothyroidism, unspecified", keywords: ["thyroid", "hypothyroid", "fatigue"] },
  { code: "E05.90", desc: "Thyrotoxicosis, unspecified", keywords: ["thyroid", "hyperthyroid"] },
  { code: "E78.5",  desc: "Hyperlipidemia, unspecified", keywords: ["cholesterol", "lipid"] },
  { code: "E66.9",  desc: "Obesity, unspecified", keywords: ["obesity", "weight gain"] },
  { code: "E86.0",  desc: "Dehydration", keywords: ["dehydration", "weakness"] },
  // Cardiovascular
  { code: "I10",    desc: "Essential (primary) hypertension", keywords: ["hypertension", "high bp", "blood pressure"] },
  { code: "I25.1",  desc: "Atherosclerotic heart disease", keywords: ["heart disease", "chest pain"] },
  { code: "I50.9",  desc: "Heart failure, unspecified", keywords: ["heart failure", "breathless", "swelling"] },
  { code: "I48.91", desc: "Unspecified atrial fibrillation", keywords: ["palpitations", "irregular heartbeat"] },
  { code: "I95.1",  desc: "Orthostatic hypotension", keywords: ["low bp", "dizziness", "fainting"] },
  { code: "I83.90", desc: "Varicose veins of lower extremities, unspecified", keywords: ["varicose veins", "leg swelling"] },
  // Renal / urology
  { code: "N39.0",  desc: "Urinary tract infection, unspecified", keywords: ["uti", "urine infection", "burning urination"] },
  { code: "N18.9",  desc: "Chronic kidney disease, unspecified", keywords: ["kidney disease", "ckd"] },
  { code: "N20.0",  desc: "Calculus of kidney (kidney stone)", keywords: ["kidney stone", "renal stone", "flank pain"] },
  { code: "N40.1",  desc: "Benign prostatic hyperplasia with lower urinary tract symptoms", keywords: ["prostate", "urination"] },
  { code: "N30.90", desc: "Cystitis, unspecified", keywords: ["bladder infection", "burning urination"] },
  // Musculoskeletal / rheum
  { code: "M54.5",  desc: "Low back pain", keywords: ["back pain", "lower back pain"] },
  { code: "M54.2",  desc: "Cervicalgia", keywords: ["neck pain"] },
  { code: "M25.50", desc: "Pain in unspecified joint", keywords: ["joint pain"] },
  { code: "M19.90", desc: "Osteoarthritis, unspecified site", keywords: ["arthritis", "joint pain", "knee pain"] },
  { code: "M06.9",  desc: "Rheumatoid arthritis, unspecified", keywords: ["rheumatoid arthritis", "joint pain", "swelling"] },
  { code: "M79.1",  desc: "Myalgia", keywords: ["body ache", "muscle pain"] },
  { code: "M75.100", desc: "Rotator cuff syndrome, unspecified shoulder", keywords: ["shoulder pain"] },
  { code: "M17.9",  desc: "Osteoarthritis of knee, unspecified", keywords: ["knee pain", "knee arthritis"] },
  { code: "M81.0",  desc: "Age-related osteoporosis without pathological fracture", keywords: ["osteoporosis", "bone density"] },
  { code: "S93.401A", desc: "Sprain of ankle, unspecified, initial encounter", keywords: ["ankle sprain", "twisted ankle"] },
  // Neuro
  { code: "G43.9",  desc: "Migraine, unspecified", keywords: ["migraine", "headache"] },
  { code: "G89.29", desc: "Pain, unspecified", keywords: ["chronic pain"] },
  { code: "G40.909", desc: "Epilepsy, unspecified, not intractable", keywords: ["seizure", "epilepsy", "fits"] },
  { code: "G47.00", desc: "Insomnia, unspecified", keywords: ["insomnia", "sleeplessness", "can't sleep"] },
  { code: "G62.9",  desc: "Polyneuropathy, unspecified", keywords: ["tingling", "numbness", "neuropathy"] },
  { code: "R42",    desc: "Dizziness and giddiness", keywords: ["dizziness", "giddiness", "vertigo"] },
  { code: "R51",    desc: "Headache", keywords: ["headache"] },
  // General symptoms
  { code: "R50.9",  desc: "Fever, unspecified", keywords: ["fever", "high temperature"] },
  { code: "R05",    desc: "Cough", keywords: ["cough"] },
  { code: "R06.00", desc: "Dyspnea, unspecified", keywords: ["breathless", "shortness of breath", "dyspnea"] },
  { code: "R07.9",  desc: "Chest pain, unspecified", keywords: ["chest pain"] },
  { code: "R11.2",  desc: "Nausea with vomiting, unspecified", keywords: ["nausea", "vomiting"] },
  { code: "R10.9",  desc: "Abdominal pain, unspecified", keywords: ["stomach pain", "abdominal pain", "stomach ache"] },
  { code: "R53.83", desc: "Other fatigue", keywords: ["fatigue", "weakness", "tiredness"] },
  { code: "R11.0",  desc: "Nausea", keywords: ["nausea"] },
  { code: "R21",    desc: "Rash and other nonspecific skin eruption", keywords: ["rash", "skin eruption"] },
  { code: "R60.9",  desc: "Edema, unspecified", keywords: ["swelling", "edema"] },
  { code: "R09.81", desc: "Nasal congestion", keywords: ["nasal congestion", "blocked nose"] },
  { code: "R63.4",  desc: "Abnormal weight loss", keywords: ["weight loss"] },
  { code: "R41.0",  desc: "Disorientation, unspecified", keywords: ["confusion", "disorientation"] },
  // Infectious disease
  { code: "B34.9",  desc: "Viral infection, unspecified", keywords: ["viral fever", "viral infection"] },
  { code: "A91",    desc: "Dengue haemorrhagic fever", keywords: ["dengue"] },
  { code: "A90",    desc: "Dengue fever", keywords: ["dengue"] },
  { code: "B50.9",  desc: "Plasmodium falciparum malaria, unspecified", keywords: ["malaria"] },
  { code: "A01.00", desc: "Typhoid fever, unspecified", keywords: ["typhoid"] },
  { code: "B15.9",  desc: "Hepatitis A without hepatic coma", keywords: ["hepatitis", "jaundice"] },
  { code: "B02.9",  desc: "Zoster (shingles) without complications", keywords: ["shingles", "zoster"] },
  { code: "B01.9",  desc: "Varicella (chickenpox) without complication", keywords: ["chickenpox"] },
  { code: "U07.1",  desc: "COVID-19", keywords: ["covid", "coronavirus"] },
  // Dermatology
  { code: "L50.0",  desc: "Allergic urticaria", keywords: ["hives", "allergic rash", "urticaria"] },
  { code: "L20.9",  desc: "Atopic dermatitis, unspecified", keywords: ["eczema", "skin rash", "dermatitis"] },
  { code: "L30.9",  desc: "Dermatitis, unspecified", keywords: ["dermatitis", "skin rash", "itching"] },
  { code: "L70.0",  desc: "Acne vulgaris", keywords: ["acne", "pimples"] },
  { code: "B35.9",  desc: "Dermatophytosis, unspecified (fungal infection)", keywords: ["fungal infection", "ringworm"] },
  { code: "L03.90", desc: "Cellulitis, unspecified", keywords: ["cellulitis", "skin infection", "swelling"] },
  // Ophthalmology
  { code: "H10.9",  desc: "Unspecified conjunctivitis", keywords: ["eye redness", "conjunctivitis", "pink eye"] },
  { code: "H52.4",  desc: "Presbyopia", keywords: ["blurred vision", "reading difficulty"] },
  { code: "H53.9",  desc: "Unspecified visual disturbance", keywords: ["blurred vision", "vision problem"] },
  { code: "H25.9",  desc: "Unspecified age-related cataract", keywords: ["cataract", "vision loss"] },
  // Gynae / obstetrics
  { code: "N92.6",  desc: "Irregular menstruation, unspecified", keywords: ["irregular periods", "menstrual"] },
  { code: "N94.6",  desc: "Dysmenorrhea, unspecified", keywords: ["period pain", "menstrual cramps"] },
  { code: "N76.0",  desc: "Acute vaginitis", keywords: ["vaginal discharge", "vaginitis"] },
  { code: "Z34.90", desc: "Encounter for supervision of normal pregnancy, unspecified trimester", keywords: ["pregnancy", "antenatal checkup"] },
  { code: "O21.9",  desc: "Vomiting of pregnancy, unspecified", keywords: ["morning sickness", "pregnancy vomiting"] },
  { code: "N95.1",  desc: "Menopausal and female climacteric states", keywords: ["menopause", "hot flashes"] },
  // Pediatrics
  { code: "P59.9",  desc: "Neonatal jaundice, unspecified", keywords: ["jaundice", "newborn"] },
  { code: "R62.50", desc: "Unspecified lack of expected normal physiological development in childhood", keywords: ["growth delay", "development delay"] },
  { code: "J21.9",  desc: "Acute bronchiolitis, unspecified", keywords: ["bronchiolitis", "wheeze", "child cough"] },
  { code: "B77.9",  desc: "Ascariasis, unspecified (worm infestation)", keywords: ["worms", "worm infestation"] },
  // Psychiatry
  { code: "F32.9",  desc: "Major depressive episode, unspecified", keywords: ["depression", "low mood"] },
  { code: "F41.1",  desc: "Generalized anxiety disorder", keywords: ["anxiety", "stress", "nervousness"] },
  { code: "F41.0",  desc: "Panic disorder without agoraphobia", keywords: ["panic attack", "anxiety"] },
  { code: "F51.01", desc: "Primary insomnia", keywords: ["insomnia", "sleeplessness"] },
  // Dental / oral
  { code: "K02.9",  desc: "Dental caries, unspecified", keywords: ["tooth decay", "cavity", "tooth pain"] },
  { code: "K05.10", desc: "Chronic gingivitis, unspecified", keywords: ["gum disease", "gingivitis"] },
  // Nutrition / hematology
  { code: "D50.9",  desc: "Iron deficiency anemia, unspecified", keywords: ["anemia", "low hemoglobin", "weakness"] },
  { code: "D64.9",  desc: "Anemia, unspecified", keywords: ["anemia", "weakness"] },
  { code: "E55.9",  desc: "Vitamin D deficiency, unspecified", keywords: ["vitamin d deficiency", "weakness", "bone pain"] },
  { code: "E53.8",  desc: "Deficiency of other specified B group vitamins", keywords: ["vitamin b deficiency", "fatigue"] },
  // Routine / admin
  { code: "Z30.0",  desc: "Encounter for general examination", keywords: ["general checkup"] },
  { code: "Z00.0",  desc: "General adult medical examination", keywords: ["checkup", "routine checkup"] },
  { code: "Z00.129", desc: "Routine child health examination without abnormal findings", keywords: ["child checkup", "well baby visit"] },
  { code: "Z23",    desc: "Encounter for immunization", keywords: ["vaccination", "immunization"] },
  { code: "Z71.3",  desc: "Dietary counseling and surveillance", keywords: ["diet counseling", "nutrition advice"] },
  { code: "Z09",    desc: "Encounter for follow-up examination after completed treatment", keywords: ["follow up", "review"] },
];

export const FREQ_LABELS = { od:"OD", bd:"BD", td:"TD", qid:"QID", sos:"SOS", stat:"Stat", nocte:"Nocte", mane:"Mane" };

export const ROUTE_LABELS = { oral:"Oral", iv:"IV", im:"IM", sc:"SC", topical:"Topical", inhaled:"Inhaled", rectal:"Rectal", sublingual:"SL" };

// Below this, the handwriting model's self-reported confidence is treated as
// "don't trust this": note fields are not auto-filled and Rx lines are flagged
// in the review panel rather than added silently.
export const HW_LOW_CONFIDENCE = 0.35;

// A recognition that has sat "pending" longer than this is treated as stuck
// (the worker thread died, or a deploy restarted mid-run).
export const HW_PENDING_STALE_MS = 90_000;

export const ICD10_CODE_SET = new Set(ICD10_CODES.map(c => c.code.toUpperCase()));

// ─── Speech parsers (best-effort; doctor reviews before insert) ──────────────
// Rule-based, not model-based — deliberately kept that way (no LLM wired into
// this backend). Generalises across patients because it works purely on the
// SHAPE of the sentence (dose/unit/frequency/duration patterns), not on any
// patient-specific content, so it applies the same way to every dictation.
// Widened here to catch more of how doctors actually phrase things out loud —
// spelled-out numbers/durations, "every N hours" cadences, filler-word
// prefixes — while still leaving the doctor to review/edit before it's applied.

export const WORD_NUM = {
  half: 0.5, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7,
  eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, twenty: 20,
};

// Lay-term → clinical-keyword expansions so common ways patients/doctors
// actually describe a complaint out loud ("sugar", "high bp") still match
// the ICD-10 description text, not just exact clinical vocabulary. Purely a
// static synonym table — still pattern matching, not model understanding, so
// it won't catch phrasing outside this list, but it materially widens what
// "for all the patients" dictation this can handle without an LLM.
export const SYMPTOM_SYNONYMS = {
  sugar: ["diabetes"], fever: ["pyrexia", "fever"], "high bp": ["hypertension"],
  "high blood pressure": ["hypertension"], "low bp": ["hypotension"],
  cold: ["rhinitis", "cough"], flu: ["influenza"], cough: ["cough", "bronchitis"],
  "chest pain": ["angina", "chest"], "throat pain": ["pharyngitis", "throat"],
  "sore throat": ["pharyngitis", "throat"], "stomach pain": ["gastritis", "abdominal"],
  "stomach ache": ["gastritis", "abdominal"], "loose motion": ["diarrhea", "diarrhoea"],
  "loose motions": ["diarrhea", "diarrhoea"], "joint pain": ["arthritis"],
  "skin rash": ["dermatitis"], rash: ["dermatitis"], "urine infection": ["urinary", "infection"],
  breathless: ["asthma", "dyspnea"], breathlessness: ["asthma", "dyspnea"],
  "back pain": ["back", "spine"], headache: ["headache", "migraine"],
};

// ─── Document viewer drawer (Overleaf-style resizable pane) ─────────────────
// Fixed to the right edge, drag the left border to resize, scrolls entirely
// within itself — the SOAP/vitals workspace behind it is untouched.
// `doc` can either carry file_data/mime_type directly (e.g. a lab report
// already fetched as part of this tenant's own lab-order list — no extra
// round trip needed) or a `fetchUrl` to load full content from (cross-tenant
// HIE attachments / lab results, kept out of the summary payload for size).
export const DRAWER_DEFAULT_WIDTH = 520;

export const DRAWER_MIN_WIDTH = 320;

export const VITAL_BADGE = {
  normal: { label: "Normal", bg: "#DCFCE7", color: "#166534" },
  watch:  { label: "Watch",  bg: "#FEF3C7", color: "#92400E" },
  high:   { label: "High",   bg: "#FEE2E2", color: "#991B1B" },
};

// ─── Lab orders — structured picker against the catalog ─────────────────────
// Lives inside the "Investigations / Orders" card itself (the free-text box
// there is now only for imaging/misc orders that aren't in the lab catalog).
// Ordering here creates real LabRequest rows the patient sees on their
// portal to choose in-house vs outside, and that the nurse/lab-tech
// workflows key off.
export const CHOICE_BADGE = {
  pending:  { label: "Awaiting patient choice", bg: "var(--color-border)", color: "var(--color-text-muted)" },
  in_house: { label: "In-house",  bg: "#DBEAFE", color: "#1E40AF" },
  outside:  { label: "Outside",   bg: "#FEF3C7", color: "#92400E" },
};

export { LAB_STATUS_BADGE } from "../../../constants/badges";

// ─── Drug entry form ──────────────────────────────────────────────────────────
export const EMPTY_DRUG = { drug: null, drug_name: "", dosage: "", frequency: "od", route: "oral", duration_days: "", instructions: "" };

// Normalise a free-text / abbreviation frequency or route (e.g. from the
// handwriting recogniser) to the codes PrescriptionItem accepts.
export const _FREQ_CODES = new Set(["od", "bd", "td", "qid", "sos", "stat", "nocte", "mane"]);

export const _ROUTE_CODES = new Set(["oral", "iv", "im", "sc", "topical", "inhaled", "rectal", "sublingual"]);

// ─── Main Page ────────────────────────────────────────────────────────────────
// ─── Admission Referral tab ─── embedded IPD referral, Phase 1 ─────────────────────
// Lives inside the consultation workspace so a doctor never has to leave a
// consultation and re-search for the patient. Creates an AdmissionReferral
// (RecommendAdmissionView, apps/ipd/views.py, IsDoctor-gated) ─ the only
// artifact that lets an admission exist; front desk cannot originate one.
// source_encounter_id links this referral straight back to this consultation.
export const EXTERNAL_ADMISSION_SOURCES = new Set(["external_referral", "transfer_in", "ambulance_ems", "medical_tourism"]);
