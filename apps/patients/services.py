"""
apps/patients/services.py
--------------------------
PatientService — all business logic for patient registration and HIE lookup.
Views are thin wrappers; they call these methods and return the result.
"""

import logging
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.utils.hashing  import hash_mobile, normalize_mobile
from core.utils.awpid    import generate_unique_awpid
from core.utils.nntm     import get_next_number
from apps.org.models     import Branch
from apps.registry.models import (
    PatientIdentity, PatientRelationship,
    SharedDiagnosis, SharedVital, SharedAllergy,
    SharedLabResult, SharedPrescription, SharedDocument,
)
from .models import Patient, Allergy

logger = logging.getLogger(__name__)

_GENDER_MAP = {"male": "M", "female": "F", "other": "O", "prefer_not_to_say": "O"}


def _normalize_gender(gender_raw: str) -> str:
    """Frontend sends verbose gender strings ('male'/'female'/...); model wants a single char."""
    if not gender_raw:
        return ""
    return _GENDER_MAP.get(gender_raw.lower(), gender_raw[:1].upper())


class PatientService:

    # ── Registration ──────────────────────────────────────────────────────
    @staticmethod
    def register(data: dict, tenant_id: int, db_name: str) -> Patient:
        """
        Register a patient at a branch.

        Two identity-resolution paths:

          Adults (has their own mobile) — unchanged: normalize + hash the
          mobile, look up/create a PatientIdentity by mobile_hash.

          Dependents (data["is_dependent"] — a child, or anyone with no
          mobile of their own) — identity is never tied to a mobile number
          at all. Dedup key is instead (guardian_awpid, full_name,
          date_of_birth) via PatientRelationship, so the same child
          registered at a second hospital under the same guardian reuses
          their existing AWPID instead of getting a disconnected duplicate.
          A patient record must be able to exist independently of whether
          that person has a login/mobile — a dependent is a patient because
          they receive care, not because they can be reached directly.

        Raises:
          ValueError — if branch not found, guardian not found, or patient
          already registered at this branch.
        """
        branch_id = data["branch_id"]
        try:
            branch = Branch.objects.get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            raise ValueError(f"Branch {branch_id} not found.")

        is_dependent = bool(data.get("is_dependent"))
        mobile_raw = ""

        if is_dependent:
            guardian_awpid = (data.get("guardian_awpid") or "").strip()
            if not guardian_awpid:
                raise ValueError("A guardian must be selected to register a dependent patient.")
            guardian_identity = PatientIdentity.objects.using("default").filter(awpid=guardian_awpid).first()
            if not guardian_identity:
                raise ValueError("Guardian not found — the guardian must be registered first.")

            identity, created = PatientService.resolve_dependent_identity(
                guardian_awpid=guardian_awpid,
                guardian_mobile_hash=guardian_identity.mobile_hash,
                full_name=data["full_name"],
                date_of_birth=data.get("date_of_birth"),
                gender=data.get("gender", ""),
                relationship=data.get("relationship", "other"),
                email=data.get("email", ""),
                blood_group=data.get("blood_group", ""),
                preferred_language=data.get("preferred_language", "en"),
            )
        else:
            mobile_raw  = data.get("mobile", "")
            mobile_norm = normalize_mobile(mobile_raw)
            mobile_hash = hash_mobile(mobile_norm)

            # ── Find or create PatientIdentity in Registry DB ─────────────
            with transaction.atomic(using="default"):
                identity, created = PatientIdentity.objects.using("default").get_or_create(
                    mobile_hash=mobile_hash,
                    defaults={
                        "awpid":              generate_unique_awpid(),
                        "full_name":          data["full_name"],
                        "date_of_birth":      data.get("date_of_birth"),
                        "gender":             data.get("gender", ""),
                        "email":              data.get("email", ""),
                        "blood_group":        data.get("blood_group", ""),
                        "preferred_language": data.get("preferred_language", "en"),
                    },
                )

        # ── Check if patient already registered at this hospital ──────────
        # Hospital-wide, not just this branch — a patient who visited Branch A
        # last month and walks into Branch B today is still the same person at
        # the same hospital and must reuse their one UHID, not get a second.
        existing = Patient.objects.using(db_name).filter(awpid=identity.awpid).first()
        if existing:
            raise ValueError(
                f"Patient already registered at this hospital — UHID {existing.uhid}"
                f"{f' ({existing.branch.name})' if existing.branch else ''}. Use their existing record."
            )

        # ── Generate UHID ─────────────────────────────────────────────────
        uhid, _ = get_next_number(branch_id=branch.id, entity="uhid", using=db_name)

        # ── Normalise gender from frontend verbose → model single char ────────
        gender = _normalize_gender(data.get("gender", ""))

        # ── Create tenant Patient ─────────────────────────────────────────────
        patient = Patient.objects.using(db_name).create(
            awpid=identity.awpid,
            uhid=uhid,
            branch=branch,
            # Personal
            full_name=data["full_name"],
            date_of_birth=data.get("date_of_birth"),
            gender=gender,
            blood_group=data.get("blood_group", ""),
            marital_status=data.get("marital_status", ""),
            nationality=data.get("nationality", "Indian"),
            occupation=data.get("occupation", ""),
            # Contact
            mobile=mobile_raw,
            alternate_mobile=data.get("alternate_mobile", ""),
            email=data.get("email", ""),
            address_line1=data.get("address_line1", ""),
            city=data.get("city", ""),
            state=data.get("state", ""),
            pincode=data.get("pincode", ""),
            # Emergency — frontend sends emergency_name / emergency_phone
            emergency_contact_name=data.get("emergency_name", "") or data.get("emergency_contact_name", ""),
            emergency_contact_phone=data.get("emergency_phone", "") or data.get("emergency_contact_phone", ""),
            emergency_contact_relation=data.get("emergency_relation", ""),
            # Insurance
            payer_type=data.get("payer_type", "self"),
            insurance_provider=data.get("insurance_provider", ""),
            policy_number=data.get("policy_number", ""),
            tpa_name=data.get("tpa_name", ""),
            # Dependent / guardian (plain per-tenant copy for display here)
            is_dependent=is_dependent,
            guardian_name=data.get("guardian_name", "") if is_dependent else "",
            guardian_mobile=data.get("guardian_mobile", "") if is_dependent else "",
            guardian_relation=data.get("relationship", "") if is_dependent else "",
            guardian_awpid=data.get("guardian_awpid", "") if is_dependent else "",
            # Consent
            dpdp_consent_captured=bool(data.get("dpdp_consent", False)),
            dpdp_consent_at=timezone.now() if data.get("dpdp_consent") else None,
            hie_consent_given=bool(data.get("hie_consent", False)),
            hie_consent_at=timezone.now() if data.get("hie_consent") else None,
            preferred_language=data.get("preferred_language", "en"),
        )

        logger.info(
            "Patient registered: awpid=%s uhid=%s branch=%s (new_identity=%s, dependent=%s)",
            identity.awpid, uhid, branch.name, created, is_dependent,
        )
        return patient

    # ── Dependents / family members ─────────────────────────────────────
    # Shared by front-desk registration (register(), above) and the patient
    # portal's self-service "Family Members" section — one identity-
    # resolution path so a dependent added either way dedupes the same way.
    @staticmethod
    def resolve_dependent_identity(guardian_awpid: str, guardian_mobile_hash, full_name: str,
                                    date_of_birth, gender: str = "", relationship: str = "other",
                                    email: str = "", blood_group: str = "",
                                    preferred_language: str = "en"):
        """
        Find-or-create a dependent's PatientIdentity under a guardian.

        Dedup key: (guardian_awpid, full_name, date_of_birth) — not a mobile
        number, since a dependent may never have one. Reuses an existing
        dependent's AWPID if the same guardian already has one by that name
        and DOB (registered here, at another hospital, or via the portal),
        so the same child never ends up with two disconnected records.

        Returns (identity, created).
        """
        with transaction.atomic(using="default"):
            existing_rel_awpids = list(
                PatientRelationship.objects.using("default")
                .filter(guardian_awpid=guardian_awpid)
                .values_list("dependent_awpid", flat=True)
            )
            identity = None
            if existing_rel_awpids:
                identity = PatientIdentity.objects.using("default").filter(
                    awpid__in=existing_rel_awpids,
                    full_name__iexact=full_name,
                    date_of_birth=date_of_birth,
                ).first()

            created = identity is None
            if identity is None:
                identity = PatientIdentity.objects.using("default").create(
                    awpid=generate_unique_awpid(),
                    full_name=full_name,
                    date_of_birth=date_of_birth,
                    gender=_normalize_gender(gender),
                    mobile_hash=None,
                    guardian_mobile_hash=guardian_mobile_hash or "",
                    is_dependent=True,
                    email=email,
                    blood_group=blood_group,
                    preferred_language=preferred_language,
                )
                PatientRelationship.objects.using("default").get_or_create(
                    dependent_awpid=identity.awpid, guardian_awpid=guardian_awpid,
                    defaults={"relationship": relationship},
                )
        return identity, created

    @staticmethod
    def list_family_members(guardian_awpid: str, db_name: str | None = None) -> list:
        """
        Every dependent linked to a guardian AWPID. If db_name is given,
        each entry also says whether that dependent has a local Patient row
        at that hospital yet (used by front-desk lookup); portal callers
        that just need the family list can omit db_name.
        """
        from .models import Patient as _Patient  # local import avoids a cycle at module load

        members = []
        rels = PatientRelationship.objects.using("default").filter(guardian_awpid=guardian_awpid)
        for rel in rels:
            dep = PatientIdentity.objects.using("default").filter(awpid=rel.dependent_awpid).first()
            if not dep:
                continue
            entry = {
                "awpid": dep.awpid,
                "full_name": dep.full_name,
                "date_of_birth": dep.date_of_birth,
                "gender": dep.gender,
                "relationship": rel.relationship,
            }
            if db_name:
                dep_local = _Patient.objects.using(db_name).filter(awpid=dep.awpid).first()
                entry["already_registered_here"] = bool(dep_local)
                entry["existing_uhid"] = dep_local.uhid if dep_local else None
            members.append(entry)
        return members

    @staticmethod
    def add_family_member(guardian_awpid: str, guardian_mobile_raw: str, data: dict) -> dict:
        """
        Portal self-service equivalent of the dependent path in register() —
        adds a family member under the logged-in account without needing a
        hospital branch (identity only; a local Patient row gets created the
        first time that family member is actually booked somewhere, same as
        the account owner's own first booking).
        """
        if not data.get("full_name", "").strip():
            raise ValueError("Full name is required.")
        if not data.get("date_of_birth"):
            raise ValueError("Date of birth is required to identify a family member across hospitals.")

        guardian_mobile_hash = ""
        if guardian_mobile_raw:
            try:
                guardian_mobile_hash = hash_mobile(normalize_mobile(guardian_mobile_raw))
            except ValueError:
                pass

        identity, created = PatientService.resolve_dependent_identity(
            guardian_awpid=guardian_awpid,
            guardian_mobile_hash=guardian_mobile_hash,
            full_name=data["full_name"],
            date_of_birth=data.get("date_of_birth"),
            gender=data.get("gender", ""),
            relationship=data.get("relationship", "other"),
        )
        PatientRelationship.objects.using("default").filter(
            dependent_awpid=identity.awpid, guardian_awpid=guardian_awpid,
        ).update(relationship=data.get("relationship", "other"))
        return {
            "awpid": identity.awpid,
            "full_name": identity.full_name,
            "date_of_birth": identity.date_of_birth,
            "gender": identity.gender,
            "relationship": data.get("relationship", "other"),
            "created": created,
        }

    # ── Duplicate check ──────────────────────────────────────────────────
    @staticmethod
    def lookup_by_mobile(mobile_raw: str, db_name: str) -> dict:
        """
        Called as front desk types a mobile number during registration, so
        the same real person never ends up with two disconnected identities
        (one hospital's Patient row unaware of another's) just because two
        different hospitals each typed them in fresh. Checks:
          1. Does a PatientIdentity already exist for this mobile (i.e. has
             this person been registered — here or at any other hospital —
             before)?
          2. If so, does THIS hospital's tenant DB already have a Patient
             row for that AWPID (i.e. don't just dedupe globally, dedupe
             locally too — no point creating a second local record)?
          3. Does this person have any dependents (children, etc.) already
             registered under them anywhere in the network? Returned as
             family_members so front desk can pick an existing dependent
             instead of re-typing (and re-guessing) their details, or add a
             new one — the "Associated Family Members" screen.
        Never reveals which other hospital a patient has visited — only
        that they exist in the network at all.
        """
        mobile_norm = normalize_mobile(mobile_raw)
        mobile_hash = hash_mobile(mobile_norm)

        identity = PatientIdentity.objects.using("default").filter(mobile_hash=mobile_hash).first()
        if not identity:
            return {"exists_in_network": False, "already_registered_here": False}

        local = Patient.objects.using(db_name).filter(awpid=identity.awpid).first()
        family_members = PatientService.list_family_members(identity.awpid, db_name=db_name)

        return {
            "exists_in_network": True,
            "awpid": identity.awpid,
            "full_name": identity.full_name,
            "date_of_birth": identity.date_of_birth,
            "gender": identity.gender,
            "already_registered_here": bool(local),
            "existing_patient_id": local.id if local else None,
            "existing_uhid": local.uhid if local else None,
            "existing_branch_name": local.branch.name if local and local.branch else None,
            "family_members": family_members,
        }

    # ── Search ────────────────────────────────────────────────────────────
    @staticmethod
    def search(query: str, branch_id: int | None, db_name: str):
        """
        Search patients by UHID, AWPID, name, or mobile (prefix match).
        Returns a queryset.

        An empty query is "browse mode" — the most recently registered
        patients at this hospital, so front desk can scan a short list
        instead of being forced to type an exact match first.

        A multi-word query (e.g. "rohan john varghese") requires each word
        to match somewhere (name/UHID/AWPID/mobile) rather than the whole
        phrase matching literally in one field — a plain
        full_name__icontains=query on the combined string used to miss
        anyone typed with a middle name skipped, reordered, or with extra
        whitespace, even though the patient record itself was correct.
        """
        qs = Patient.objects.using(db_name).select_related("branch")
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        query = (query or "").strip()
        if not query:
            return qs.order_by("-registered_at")

        combined = Q()
        for word in query.split():
            combined &= (
                Q(full_name__icontains=word)
                | Q(uhid__icontains=word)
                | Q(awpid__icontains=word)
                | Q(mobile__startswith=word)
            )
        return qs.filter(combined).distinct().order_by("full_name")

    # ── Cross-tenant HIE history ──────────────────────────────────────────
    @staticmethod
    def get_shared_history(awpid: str) -> dict:
        """
        Fetch all shared clinical records for a patient from the Registry DB.
        source_tenant_id is EXCLUDED from all results.
        """
        diagnoses = list(
            SharedDiagnosis.objects.using("default")
            .filter(awpid=awpid)
            .values("icd10_code", "description", "clinical_status", "onset_date", "created_at")
            .order_by("-created_at")
        )

        vitals = list(
            SharedVital.objects.using("default")
            .filter(awpid=awpid)
            .values(
                "recorded_at", "source", "bp_systolic", "bp_diastolic", "pulse_rate",
                "spo2", "temperature", "weight_kg", "height_cm", "resp_rate",
                "blood_sugar_mgdl"
            )
            .order_by("-recorded_at")[:20]  # last 20 vital records
        )

        allergies = list(
            SharedAllergy.objects.using("default")
            .filter(awpid=awpid, is_active=True)
            .values("substance", "reaction", "severity", "is_active", "recorded_at")
        )

        lab_results = list(
            SharedLabResult.objects.using("default")
            .filter(awpid=awpid)
            .values("id", "test_name", "result_summary", "delivered_at", "mime_type")
            .order_by("-delivered_at")[:20]
        )
        for r in lab_results:
            r["has_file"] = bool(r.pop("mime_type", None))

        prescriptions = []
        for rx in (
            SharedPrescription.objects.using("default")
            .filter(awpid=awpid)
            .prefetch_related("items")
            .order_by("-prescribed_on")[:10]
        ):
            prescriptions.append({
                "prescribed_on": rx.prescribed_on,
                "items": list(rx.items.values(
                    "drug_name", "dose", "unit", "frequency", "route", "duration_days"
                )),
            })

        # Lightweight only — no file_data here, so this history payload stays
        # small. Full content is fetched separately (by id) only when a
        # doctor actually opens a document.
        documents = list(
            SharedDocument.objects.using("default")
            .filter(awpid=awpid)
            .values("id", "title", "doc_type", "file_name", "mime_type", "uploaded_by", "created_at")
            .order_by("-created_at")[:50]
        )

        return {
            "awpid":        awpid,
            "diagnoses":    diagnoses,
            "vitals":       vitals,
            "allergies":    allergies,
            "lab_results":  lab_results,
            "prescriptions":prescriptions,
            "documents":    documents,
        }
