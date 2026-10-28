"""apps/opd/patient_services.py"""

import logging
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from core.validation  import stored_mobile, normalize_mobile
from core.utils    import generate_unique_awpid
from apps.hospital_setup.models import NextNumber
from apps.hospital_setup.models import Branch
from apps.patients.models import Patient, PatientRelationship
from apps.documents.models import ClinicalEvent, LabResult
from apps.hospital_patients.vitals_service import history_readings
from apps.documents.models import MedicalDocument
from apps.hospital_patients.models import HospitalPatient

logger = logging.getLogger(__name__)

PERSONAL_FIELDS = ("alternate_mobile", "address_line1", "city", "state", "pincode", "marital_status", "nationality", "occupation")
_GENDER_MAP = {"male": "M", "female": "F", "other": "O", "prefer_not_to_say": "O"}


def _normalize_gender(gender_raw: str) -> str:
    """Frontend sends verbose gender strings ('male'/'female'/...); model wants a single char."""
    if not gender_raw:
        return ""
    return _GENDER_MAP.get(gender_raw.lower(), gender_raw[:1].upper())


class PatientService:

    @staticmethod
    def attach_network_patient(mobile_raw: str, branch_id: int, db_name: str) -> HospitalPatient:
        """Create this hospital's operational record for an existing Atomwalk identity."""
        mobile_norm = normalize_mobile(mobile_raw)
        identity = Patient.objects.using("default").filter(
            mobile=stored_mobile(mobile_norm)
        ).first()
        if not identity:
            raise ValueError("No Atomwalk patient was found for this mobile number.")
        existing = HospitalPatient.objects.using(db_name).filter(awpid=identity.awpid).first()
        if existing:
            return existing
        try:
            branch = Branch.objects.get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            raise ValueError("Select an active branch before booking this patient.")
        uhid, _ = NextNumber.next(branch.pk, "uhid", db_name)
        return HospitalPatient.objects.using(db_name).create(awpid=identity.awpid, uhid=uhid)

    # ── Registration ──────────────────────────────────────────────────────
    @staticmethod
    def register(data: dict, hospital_id: int, db_name: str, request=None) -> HospitalPatient:
        """Register a patient at a branch."""
        branch_id = data["branch_id"]
        try:
            branch = Branch.objects.get(pk=branch_id, is_active=True)
        except Branch.DoesNotExist:
            raise ValueError(f"Branch {branch_id} not found.")

        is_dependent = bool(data.get("is_dependent"))
        personal = {f: data[f] for f in PERSONAL_FIELDS if data.get(f)}
        mobile_raw = ""

        if is_dependent:
            guardian_awpid = (data.get("guardian_awpid") or "").strip()
            guardian_mobile_raw = data.get("guardian_mobile", "")

            if guardian_awpid:
                guardian_identity = Patient.objects.using("default").filter(awpid=guardian_awpid).first()
                if not guardian_identity:
                    raise ValueError("Guardian not found — the guardian must be registered first.")
            elif guardian_mobile_raw:
                # Emergency quick-register path: front desk doesn't have an
                guardian_mobile_norm = normalize_mobile(guardian_mobile_raw)
                guardian_mobile = stored_mobile(guardian_mobile_norm)
                with transaction.atomic(using="default"):
                    guardian_identity, _ = Patient.objects.using("default").get_or_create(
                        mobile=guardian_mobile,
                        defaults={
                            "awpid": generate_unique_awpid(),
                            "full_name": data.get("guardian_name", "") or "Guardian",
                            "preferred_language": data.get("preferred_language", "en"),
                            "created_by": "hospital", "source_hospital_id": hospital_id,
                        },
                    )
                guardian_awpid = guardian_identity.awpid
            else:
                raise ValueError("A guardian must be selected to register a dependent patient.")

            identity, created = PatientService.resolve_dependent_identity(
                guardian_awpid=guardian_awpid,
                guardian_mobile=guardian_identity.mobile,
                full_name=data["full_name"],
                date_of_birth=data.get("date_of_birth"),
                gender=data.get("gender", ""),
                relationship=data.get("relationship", "other"),
                email=data.get("email", ""),
                blood_group=data.get("blood_group", ""),
                preferred_language=data.get("preferred_language", "en"),
                created_by="hospital", source_hospital_id=hospital_id, personal=personal,
            )
        else:
            mobile_raw  = data.get("mobile", "")
            mobile_norm = normalize_mobile(mobile_raw)
            mobile_value = stored_mobile(mobile_norm)

            # ── Find or create Patient in Atomwalk DB ─────────────
            with transaction.atomic(using="default"):
                identity, created = Patient.objects.using("default").get_or_create(
                    mobile=mobile_value,
                    defaults={
                        "awpid":              generate_unique_awpid(),
                        "full_name":          data["full_name"],
                        "date_of_birth":      data.get("date_of_birth"),
                        "gender":             _normalize_gender(data.get("gender", "")),
                        "email":              data.get("email", ""),
                        "blood_group":        data.get("blood_group", ""),
                        "preferred_language": data.get("preferred_language", "en"),
                        "emergency_contact_name": data.get("emergency_name", "") or data.get("emergency_contact_name", ""),
                        "emergency_contact_phone": data.get("emergency_phone", "") or data.get("emergency_contact_phone", ""),
                        "emergency_contact_relation": data.get("emergency_relation", ""),
                        **personal,
                        "created_by": "hospital", "source_hospital_id": hospital_id,
                    },
                )

        # ── Check if patient already registered at this hospital ──────────
        existing = HospitalPatient.objects.using(db_name).filter(awpid=identity.awpid).first()
        if existing:
            raise ValueError(
                f"Patient already registered at this hospital — UHID {existing.uhid}. Use their existing record."
            )

        # ── Generate UHID ─────────────────────────────────────────────────
        uhid, _ = NextNumber.next(branch.pk, "uhid", db_name)

        # ── Create the hospital's own patient row (who the patient is lives in the shared record above) ──
        patient = HospitalPatient.objects.using(db_name).create(
            awpid=identity.awpid,
            uhid=uhid,
            created_by_id=getattr(getattr(request, "user", None), "id", None),
        )
        logger.info(
            "Patient registered: awpid=%s uhid=%s branch=%s (new_identity=%s, dependent=%s)",
            identity.awpid, uhid, branch.name, created, is_dependent,
        )

        return patient

    # ── Dependents / family members ─────────────────────────────────────
    @staticmethod
    def resolve_dependent_identity(guardian_awpid: str, guardian_mobile, full_name: str,
                                    date_of_birth, gender: str = "", relationship: str = "other",
                                    email: str = "", blood_group: str = "",
                                    preferred_language: str = "en", created_by: str = "patient",
                                    source_hospital_id=None, personal=None):
        """Find-or-create a dependent's Patient under a guardian."""
        with transaction.atomic(using="default"):
            existing_rel_awpids = list(
                PatientRelationship.objects.using("default")
                .filter(guardian__awpid=guardian_awpid)
                .values_list("dependent__awpid", flat=True)
            )
            identity = None
            if existing_rel_awpids:
                identity = Patient.objects.using("default").filter(
                    awpid__in=existing_rel_awpids,
                    full_name__iexact=full_name,
                    date_of_birth=date_of_birth,
                ).first()

            if identity is None and guardian_mobile:
                identity = Patient.objects.using("default").filter(
                    guardian_mobile=guardian_mobile,
                    full_name__iexact=full_name,
                    date_of_birth=date_of_birth,
                    is_dependent=True,
                ).exclude(awpid__in=existing_rel_awpids).first()

            created = identity is None
            if identity is None:
                identity = Patient.objects.using("default").create(
                    awpid=generate_unique_awpid(),
                    full_name=full_name,
                    date_of_birth=date_of_birth,
                    gender=_normalize_gender(gender),
                    mobile=None,
                    guardian_mobile=guardian_mobile or "",
                    is_dependent=True,
                    email=email,
                    blood_group=blood_group,
                    preferred_language=preferred_language,
                    created_by=created_by, source_hospital_id=source_hospital_id, **(personal or {}),
                )
            # Covers all three paths above uniformly: brand-new identity (no
            PatientRelationship.objects.using("default").get_or_create(
                dependent=identity, guardian=Patient.objects.using("default").get(awpid=guardian_awpid),
                defaults={"relationship": relationship},
            )
        return identity, created

    @staticmethod
    def list_family_members(guardian_awpid: str, db_name: str | None = None) -> list:
        """Every dependent linked to a guardian AWPID. If db_name is given,"""
        from apps.hospital_patients.models import HospitalPatient as _Patient  # local import avoids a cycle at module load

        members = []
        rels = PatientRelationship.objects.using("default").filter(guardian__awpid=guardian_awpid).select_related("dependent")
        for rel in rels:
            dep = rel.dependent
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
    def add_family_member(guardian_awpid: str, guardian_mobile: str, data: dict) -> dict:
        """Portal self-service equivalent of the dependent path in register() —"""
        if not data.get("full_name", "").strip():
            raise ValueError("Full name is required.")
        if not data.get("date_of_birth"):
            raise ValueError("Date of birth is required to identify a family member across hospitals.")

        identity, created = PatientService.resolve_dependent_identity(
            guardian_awpid=guardian_awpid,
            guardian_mobile=guardian_mobile or "",
            full_name=data["full_name"],
            date_of_birth=data.get("date_of_birth"),
            gender=data.get("gender", ""),
            relationship=data.get("relationship", "other"),
        )
        PatientRelationship.objects.using("default").filter(
            dependent=identity, guardian__awpid=guardian_awpid,
        ).update(relationship=data.get("relationship", "other"))
        return {
            "awpid": identity.awpid,
            "full_name": identity.full_name,
            "date_of_birth": identity.date_of_birth,
            "gender": identity.gender,
            "relationship": data.get("relationship", "other"),
            "created": created,
        }

    @staticmethod
    def update_family_member(guardian_awpid: str, dependent_awpid: str, data: dict) -> dict:
        """Portal self-service edit — a guardian correcting a typo'd name/DOB or"""
        rel = PatientRelationship.objects.using("default").filter(
            guardian__awpid=guardian_awpid, dependent__awpid=dependent_awpid,
        ).first()
        if not rel:
            raise ValueError("Family member not found.")

        identity = Patient.objects.using("default").filter(awpid=dependent_awpid).first()
        if not identity:
            raise ValueError("Family member not found.")

        if "full_name" in data:
            full_name = (data.get("full_name") or "").strip()
            if not full_name:
                raise ValueError("Full name is required.")
            identity.full_name = full_name
        if "date_of_birth" in data:
            if not data.get("date_of_birth"):
                raise ValueError("Date of birth is required to identify a family member across hospitals.")
            identity.date_of_birth = data["date_of_birth"]
        if "gender" in data:
            identity.gender = _normalize_gender(data.get("gender", ""))
        identity.save(using="default")

        if "relationship" in data:
            rel.relationship = data.get("relationship", "other")
            rel.save(using="default", update_fields=["relationship"])

        return {
            "awpid": identity.awpid,
            "full_name": identity.full_name,
            "date_of_birth": identity.date_of_birth,
            "gender": identity.gender,
            "relationship": rel.relationship,
        }

    @staticmethod
    def remove_family_member(guardian_awpid: str, dependent_awpid: str) -> None:
        """Unlinks a dependent from this guardian's family list. Deliberately"""
        rel = PatientRelationship.objects.using("default").filter(
            guardian__awpid=guardian_awpid, dependent__awpid=dependent_awpid,
        ).first()
        if not rel:
            raise ValueError("Family member not found.")
        rel.delete(using="default")

    # ── Family tree ──────────────────────────────────────────────────────
    @staticmethod
    def get_family_tree(awpid: str, db_name: str) -> dict:
        """Given any one person's AWPID (guardian or dependent), resolve the"""
        from apps.hospital_patients.models import HospitalPatient as _Patient

        # Is this person a guardian? (has dependents registered under them)
        is_guardian = PatientRelationship.objects.using("default").filter(
            guardian__awpid=awpid
        ).exists()

        if is_guardian:
            guardian_awpid = awpid
        else:
            # Is this person a dependent? Find who their guardian is.
            rel = PatientRelationship.objects.using("default").filter(
                dependent__awpid=awpid
            ).first()
            guardian_awpid = rel.guardian.awpid if rel else None

        if not guardian_awpid:
            return {"guardian_awpid": None, "members": []}

        members = PatientService.list_family_members(guardian_awpid, db_name=db_name)

        # The guardian themself isn't a "dependent" so list_family_members()
        guardian_identity = Patient.objects.using("default").filter(
            awpid=guardian_awpid
        ).first()
        if guardian_identity:
            entry = {
                "awpid": guardian_identity.awpid,
                "full_name": guardian_identity.full_name,
                "date_of_birth": guardian_identity.date_of_birth,
                "gender": guardian_identity.gender,
                "relationship": "self" if guardian_awpid == awpid else "guardian",
            }
            if db_name:
                local = _Patient.objects.using(db_name).filter(awpid=guardian_awpid).first()
                entry["already_registered_here"] = bool(local)
                entry["existing_uhid"] = local.uhid if local else None
            members.insert(0, entry)

        for m in members:
            m["is_self"] = (m["awpid"] == awpid)

        return {"guardian_awpid": guardian_awpid, "members": members}

    # ── Duplicate check ──────────────────────────────────────────────────
    @staticmethod
    def lookup_by_mobile(mobile_raw: str, db_name: str) -> dict:
        """Called as front desk types a mobile number during registration, so"""
        mobile_norm = normalize_mobile(mobile_raw)
        mobile_value = stored_mobile(mobile_norm)

        identity = Patient.objects.using("default").filter(mobile=mobile_value).first()
        if not identity:
            return {"exists_in_network": False, "already_registered_here": False}

        local = HospitalPatient.objects.using(db_name).filter(awpid=identity.awpid).first()
        family_members = PatientService.list_family_members(identity.awpid, db_name=db_name)

        return {
            "exists_in_network": True,
            "awpid": identity.awpid,
            "full_name": identity.full_name,
            "date_of_birth": identity.date_of_birth,
            "gender": identity.gender,
            "already_registered_here": bool(local),
            "existing_patient_id": local.pk if local else None,
            "existing_uhid": local.uhid if local else None,
            "existing_branch_name": None,
            "family_members": family_members,
        }

    # ── Search ────────────────────────────────────────────────────────────
    @staticmethod
    def search(query: str, branch_id: int | None, db_name: str):
        """Search patients by UHID, AWPID, name, or mobile (prefix match). The name and mobile are in the shared record: the words are
        looked up there first, then matched to this hospital's patients by awpid."""
        qs = HospitalPatient.objects.using(db_name)

        query = (query or "").strip()
        if not query:
            return qs.order_by("-registered_at")

        combined = Q()
        for word in query.split():
            in_shared_record = list(
                Patient.objects.using("default").filter(
                    Q(full_name__icontains=word) | Q(awpid__icontains=word) | Q(mobile__startswith=word)
                ).values_list("awpid", flat=True)
            )
            # Dependents (children etc.) often get searched for by the guardian's name
            of_guardian = list(
                PatientRelationship.objects.using("default").filter(guardian__full_name__icontains=word)
                .values_list("dependent__awpid", flat=True)
            )
            combined &= (
                Q(uhid__icontains=word)
                | Q(awpid__icontains=word)
                | Q(awpid__in=in_shared_record)
                | Q(awpid__in=of_guardian)
            )
        return qs.filter(combined).distinct().order_by("-registered_at")

    @staticmethod
    def matching_awpids(db_name: str, text: str) -> list:
        """The awpids of this hospital's patients matching `text` in their number (UHID), awpid, name or mobile number."""
        text = (text or "").strip()
        if not text:
            return []
        shared = Patient.objects.using("default").filter(
            Q(full_name__icontains=text) | Q(mobile__icontains=text) | Q(awpid__icontains=text)
        ).values_list("awpid", flat=True)
        return list(
            HospitalPatient.objects.using(db_name).filter(
                Q(uhid__icontains=text) | Q(awpid__in=list(shared))
            ).values_list("awpid", flat=True)
        )

    # ── Cross-hospital HIE history ──────────────────────────────────────────
    @staticmethod
    def get_shared_history(awpid: str) -> dict:
        """Fetch all shared clinical records for a patient from the Atomwalk DB."""
        diagnoses = list(
            ClinicalEvent.objects.using("default")
            .filter(patient__awpid=awpid, event_type="DIAGNOSIS").exclude(verification_status="rejected")
            .order_by("-event_date", "-pk")
            .values("clinical_status", created_at=F("event_date"), icd10_code=F("icd10"), description=F("condition_text"), onset_date=F("event_date"))
        )

        vitals = history_readings(awpid, 20)  # last 20 vital records

        lab_results = list(
            LabResult.objects.using("default")
            .filter(patient__awpid=awpid, delivered_at__isnull=False)
            .values("test_name", "result_summary", "delivered_at", "document_id", lab_result_id=F("pk"))
            .order_by("-delivered_at")[:20]
        )
        for r in lab_results:
            r["has_file"] = bool(r.pop("document_id", None))

        prescriptions = []
        for rx in (
            MedicalDocument.objects.using("default")
            .filter(patient__awpid=awpid, source_type=MedicalDocument.Source.ENCOUNTER, doc_classification="prescription")
            .order_by("-document_date")[:10]
        ):
            # The medicines are in the prescription's own PDF; the drug catalog table that once listed them here was removed
            prescriptions.append({"prescribed_on": rx.document_date, "items": []})

        # Lightweight only — no file_data here, so this history payload stays
        from apps.documents.lib_documents import awaiting_review_q
        from apps.documents.lib_documents import document_rows
        documents = document_rows(
            MedicalDocument.objects.using("default")
            .filter(patient__awpid=awpid)
            .exclude(awaiting_review_q())
            .filter(status="completed")
        )

        return {
            "awpid":        awpid,
            "diagnoses":    diagnoses,
            "vitals":       vitals,
            "lab_results":  lab_results,
            "prescriptions":prescriptions,
            "documents":    documents,
        }
