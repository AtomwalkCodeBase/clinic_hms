"""apps/hospital_patients/views.py"""

import logging

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.api.response import success, created, error, not_found
from core.api.pagination import paginate_queryset
from core import storage as blob_storage

logger = logging.getLogger(__name__)
from core.api.permissions import IsHospitalStaff, IsDoctorOrNurse, IsFrontDesk

from apps.opd.patient_serializers import (
    PatientRegisterSerializer,
    PatientEmergencyRegisterSerializer,
    PatientDetailSerializer,
    PatientSearchSerializer,
    AllergySerializer,
)
from apps.opd.patient_services import PatientService
from apps.opd.models import HospitalPatient, Allergy


def _maybe_charge_registration_fee(patient, hospital_id, db, user):
    """If this hospital has registration_fee_enabled (Hospital Admin → Settings,"""
    try:
        from apps.hospital_master.models import Hospital
        from apps.hospital_master.services import parameters_of
        from apps.billing.models import Invoice, InvoiceItem
        from apps.billing.services import recompute_invoice_totals
        from core.utils.nntm import get_next_number

        hospital = Hospital.objects.using("default").get(pk=hospital_id)
        params = parameters_of(hospital)
        if not params.registration_fee_enabled or not params.registration_fee_amount:
            return
        if not getattr(patient, "branch_id", None):
            return

        invoice_number, _ = get_next_number(branch_id=patient.branch_id, entity="invoice", using=db)
        invoice = Invoice.objects.using(db).create(
            patient=patient,
            branch_id=patient.branch_id,
            invoice_number=invoice_number,
            status="draft",
            created_by_id=getattr(user, "id", None),
            notes="Auto-generated registration fee",
        )
        InvoiceItem.objects.using(db).create(
            invoice=invoice,
            description="Registration Fee",
            quantity=1,
            unit_price=params.registration_fee_amount,
            tax_rate=params.default_tax_rate,
            total=params.registration_fee_amount,
        )
        recompute_invoice_totals(invoice, db)
    except Exception as exc:
        logger.warning("Could not auto-generate registration fee invoice: %s", exc)


class PatientRegisterView(APIView):
    """POST /api/v1/patients/register/"""
    permission_classes = [IsAuthenticated, IsFrontDesk | IsHospitalStaff]

    def post(self, request):
        serializer = PatientRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        try:
            patient = PatientService.register(
                data=serializer.validated_data,
                hospital_id=request.hospital_id,
                db_name=request.hospital_db,
                request=request,
            )
        except ValueError as exc:
            return error(message=str(exc))
        except Exception as exc:
            logger.exception("Patient registration failed: %s", exc)
            return error(
                message=f"Registration failed: {exc}",
                status=500,
            )
        _maybe_charge_registration_fee(patient, request.hospital_id, request.hospital_db, request.user)

        from core.utils.audit import log_action
        log_action(request, request.hospital_db, action="patient.register",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)

        return created(
            data=PatientDetailSerializer(patient).data,
            message="Patient registered successfully.",
        )


class PatientEmergencyRegisterView(APIView):
    """POST /api/v1/patients/register-emergency/"""
    permission_classes = [IsAuthenticated, IsFrontDesk | IsHospitalStaff]

    def post(self, request):
        serializer = PatientEmergencyRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        try:
            patient = PatientService.register_emergency(
                data=serializer.validated_data,
                db_name=request.hospital_db,
                request=request,
            )
        except ValueError as exc:
            return error(message=str(exc))
        except Exception as exc:
            logger.exception("Emergency patient registration failed: %s", exc)
            return error(message=f"Registration failed: {exc}", status=500)

        from core.utils.audit import log_action
        log_action(
            request, request.hospital_db, action="patient.register_emergency",
            resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk,
            metadata={"is_mlc": patient.is_mlc, "arrival_channel": patient.arrival_channel},
        )

        return created(
            data=PatientDetailSerializer(patient).data,
            message="Emergency patient registered — provisional identity.",
        )


class PatientLookupView(APIView):
    """GET /api/v1/patients/lookup/?mobile="""
    permission_classes = [IsAuthenticated, IsFrontDesk | IsHospitalStaff]

    def get(self, request):
        mobile = (request.query_params.get("mobile") or "").strip()
        if len(mobile) < 6:
            return success(data={"exists_in_network": False, "already_registered_here": False})
        result = PatientService.lookup_by_mobile(mobile_raw=mobile, db_name=request.hospital_db)
        return success(data=result)


class PatientAttachNetworkView(APIView):
    """Attach a searched Atomwalk identity to this hospital for a visit."""
    permission_classes = [IsAuthenticated, IsFrontDesk | IsHospitalStaff]

    def post(self, request):
        mobile = (request.data.get("mobile") or "").strip()
        branch_id = request.data.get("branch_id") or getattr(request.user, "branch_id", None)
        if not mobile or not branch_id:
            return error("mobile and an active branch are required.")
        try:
            patient = PatientService.attach_network_patient(mobile, int(branch_id), request.hospital_db)
        except ValueError as exc:
            return error(str(exc))
        return success(data=PatientDetailSerializer(patient).data, message="Atomwalk patient ready for booking.")


class PatientSearchView(APIView):
    """GET /api/v1/patients/search/?q=&branch_id="""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        query     = request.query_params.get("q", "").strip()
        branch_id = request.query_params.get("branch_id")
        if query and len(query) < 2:
            return error(message="Search query must be at least 2 characters.")
        qs = PatientService.search(
            query=query,
            branch_id=int(branch_id) if branch_id else None,
            db_name=request.hospital_db,
        )

        # Two callers share this endpoint:
        if "page" in request.query_params:
            page_items, meta = paginate_queryset(request, qs)
            return success(data={
                "results": PatientSearchSerializer(page_items, many=True).data,
                "pagination": meta,
                "is_browse": not query,
            })

        total_matches = qs.count()
        limit = 50

        # If nothing matched locally and the query looks like a mobile
        network_match = None
        digits = "".join(ch for ch in query if ch.isdigit())
        if total_matches == 0 and len(digits) >= 6:
            result = PatientService.lookup_by_mobile(mobile_raw=query, db_name=request.hospital_db)
            if result.get("exists_in_network") and not result.get("already_registered_here"):
                network_match = {
                    "full_name": result.get("full_name"),
                    "date_of_birth": result.get("date_of_birth"),
                    "gender": result.get("gender"),
                }

        return success(data={
            "results": PatientSearchSerializer(qs[:limit], many=True).data,
            "total_matches": total_matches,
            "truncated": total_matches > limit,
            "is_browse": not query,
            "network_match": network_match,
        })


class PatientFamilyTreeView(APIView):
    """GET /api/v1/patients/family-tree/?awpid="""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request):
        awpid = (request.query_params.get("awpid") or "").strip()
        if not awpid:
            return error(message="awpid is required.")
        result = PatientService.get_family_tree(awpid=awpid, db_name=request.hospital_db)
        return success(data=result)


class PatientDetailView(APIView):
    """GET /api/v1/patients/<id>/"""
    permission_classes = [IsAuthenticated, IsHospitalStaff]

    def get(self, request, pk):
        try:
            patient = HospitalPatient.objects.using(request.hospital_db).get(pk=pk)
        except HospitalPatient.DoesNotExist:
            return not_found("Patient not found.")

        from core.utils.audit import log_action
        log_action(request, request.hospital_db, action="patient.view",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)

        return success(data=PatientDetailSerializer(patient).data)


class PatientHistoryView(APIView):
    """GET /api/v1/patients/<id>/history/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, pk):
        try:
            patient = HospitalPatient.objects.using(request.hospital_db).get(pk=pk)
        except HospitalPatient.DoesNotExist:
            return not_found("Patient not found.")

        if not patient.hie_consent_given:
            from core.utils.audit import log_action
            log_action(request, request.hospital_db, action="patient.history.view_blocked_no_consent",
                        resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)
            # Documents THIS hospital captured for THIS visit — the consult
            from apps.documents.models import MedicalDocument
            from apps.documents.lib_documents import document_rows
            own_notes = document_rows(
                MedicalDocument.objects.using("default")
                .filter(patient__awpid=patient.awpid, source_hospital_id=request.hospital_id)
            )
            return success(data={
                "awpid": patient.awpid, "consent_given": False,
                "diagnoses": [], "vitals": [], "allergies": [],
                "lab_results": [], "prescriptions": [], "documents": own_notes,
            })

        history = PatientService.get_shared_history(awpid=patient.awpid)
        history["consent_given"] = True

        from core.utils.audit import log_action
        log_action(request, request.hospital_db, action="patient.history.view",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient.pk)

        return success(data=history)


class PatientDocumentDetailView(APIView):
    """GET /api/v1/patients/documents/<doc_id>/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, doc_id):
        from apps.documents.models import MedicalDocument
        try:
            doc = MedicalDocument.objects.using("default").get(pk=doc_id)
        except MedicalDocument.DoesNotExist:
            return not_found("Document not found.")

        # Same HIE-consent gate PatientHistoryView applies to the lightweight
        owner = HospitalPatient.objects.using(request.hospital_db).filter(awpid=doc.patient.awpid).first()
        # A document this hospital captured for this visit (consult note,
        own_hospital_doc = doc.source_hospital_id == request.hospital_id
        if not own_hospital_doc and (not owner or not owner.hie_consent_given):
            from core.utils.audit import log_action
            log_action(request, request.hospital_db, action="patient.document.view_blocked_no_consent",
                        resource_type="SharedDocument", resource_id=doc.id)
            return error("This patient hasn't consented to cross-hospital record sharing.", status=403)

        from core.utils.audit import log_action
        log_action(request, request.hospital_db, action="patient.document.view",
                    resource_type="SharedDocument", resource_id=doc.id)

        # Rows written before object storage (and the consult-pad's no-S3
        want_download = (request.query_params.get("download") or "").lower() in ("1", "true", "yes")
        from apps.documents.lib_documents import display_name, mime_of
        dl_name = display_name(doc) or "document.pdf"
        file_data = blob_storage.signed_url(doc.file_name.name, download_name=dl_name if want_download else None)

        return success(data={
            "id": doc.id, "title": display_name(doc), "doc_type": doc.doc_classification,
            "file_name": display_name(doc), "mime_type": mime_of(doc),
            "file_data": file_data, "created_at": doc.created_at,
            "download": want_download,
        })


class PatientLabResultDetailView(APIView):
    """GET /api/v1/patients/lab-results/<result_id>/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, result_id):
        from apps.documents.models import LabResult
        try:
            r = LabResult.objects.using("default").select_related("document").get(pk=result_id)
        except LabResult.DoesNotExist:
            return not_found("Lab result not found.")

        # Same HIE-consent gate as PatientDocumentDetailView above — see
        owner = HospitalPatient.objects.using(request.hospital_db).filter(awpid=r.patient.awpid if r.patient_id else "").first()
        if not owner or not owner.hie_consent_given:
            from core.utils.audit import log_action
            log_action(request, request.hospital_db, action="patient.lab_result.view_blocked_no_consent",
                        resource_type="LabResult", resource_id=r.id)
            return error("This patient hasn't consented to cross-hospital record sharing.", status=403)

        from core.utils.audit import log_action
        log_action(request, request.hospital_db, action="patient.lab_result.view",
                    resource_type="LabResult", resource_id=r.id)

        from apps.documents.lib_documents import mime_of
        return success(data={
            "id": r.id, "test_name": r.test_name, "result_summary": r.result_summary,
            "mime_type": mime_of(r.document) if r.document_id else "",
            "file_data": blob_storage.signed_url(r.document.file_name.name) if r.document_id else "", "delivered_at": r.delivered_at,
        })


class PatientAllergyListCreateView(APIView):
    """GET + POST /api/v1/patients/<id>/allergies/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, pk):
        try:
            patient = HospitalPatient.objects.using(request.hospital_db).get(pk=pk)
        except HospitalPatient.DoesNotExist:
            return not_found("Patient not found.")
        allergies = Allergy.objects.using(request.hospital_db).filter(patient=patient)
        return success(data=AllergySerializer(allergies, many=True).data)

    def post(self, request, pk):
        try:
            patient = HospitalPatient.objects.using(request.hospital_db).get(pk=pk)
        except HospitalPatient.DoesNotExist:
            return not_found("Patient not found.")
        serializer = AllergySerializer(data=request.data)
        if not serializer.is_valid():
            return error(message="Validation error.", errors=serializer.errors)
        allergy = Allergy.objects.using(request.hospital_db).create(
            patient=patient,
            recorded_by_id=request.user.id,
            **serializer.validated_data,
        )
        return created(data=AllergySerializer(allergy).data)
