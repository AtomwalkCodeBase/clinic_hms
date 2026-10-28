"""apps/hospital_patients/views.py"""

import logging
import re

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from core.api.response import success, created, error, not_found
from core.api.pagination import paginate_queryset
from core import storage as blob_storage

logger = logging.getLogger(__name__)
from core.api.permissions import IsHospitalStaff, IsDoctorOrNurse, IsFrontDesk

from apps.hospital_patients.serializers import (
    PatientRegisterSerializer,
    PatientDetailSerializer,
    PatientSearchSerializer,
)
from apps.hospital_patients.services import PatientService
from apps.hospital_patients.models import HospitalPatient


def _maybe_charge_registration_fee(patient, branch_id, hospital_id, db, user):
    """If this hospital has registration_fee_enabled (Hospital Admin → Settings,"""
    try:
        from apps.hospital_master.models import Hospital
        from apps.hospital_master.services import parameters_of
        from apps.billing.models import Invoice
        from apps.billing.services import line_from_request, recompute_invoice_totals
        from apps.hospital_setup.models import NextNumber

        hospital = Hospital.objects.using("default").get(pk=hospital_id)
        params = parameters_of(hospital)
        if not params.registration_fee_enabled or not params.registration_fee_amount:
            return
        if not branch_id:
            return

        invoice_number, _ = NextNumber.next(branch_id, "invoice", db)
        invoice = Invoice.objects.using(db).create(
            patient=patient,
            branch_id=branch_id,
            invoice_number=invoice_number,
            status="draft",
            created_by_id=getattr(user, "id", None),
            notes="Auto-generated registration fee",
            lines=[line_from_request({"description": "Registration Fee", "quantity": 1, "unit_price": params.registration_fee_amount,
                                      "tax_rate": params.default_tax_rate})],
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
        _maybe_charge_registration_fee(patient, request.data.get("branch_id"), request.hospital_id, request.hospital_db, request.user)

        from apps.hospital_setup.compliance_services import log_action
        log_action(request, request.hospital_db, action="patient.register",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient)

        return created(
            data=PatientDetailSerializer(patient).data,
            message="Patient registered successfully.",
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
            for p in page_items[:1]:
                p.get_patient_details(batch=page_items)
            return success(data={
                "results": PatientSearchSerializer(page_items, many=True).data,
                "pagination": meta,
                "is_browse": not query,
            })

        total_matches = qs.count()
        limit = 50
        # Name order: the names are in the shared record, so the matches (the most recent 500 at most) are sorted here
        found = list(qs[:500])
        for p in found[:1]:
            p.get_patient_details(batch=found)
        found.sort(key=lambda p: (p.get_patient_details()["full_name"] or "").lower())

        # If nothing matched locally and the query looks like a mobile
        network_match = None
        digits = "".join(ch for ch in query if ch.isdigit())
        looks_like_mobile = re.fullmatch(r"[+\d\s-]+", query) is not None      # an AWPID or a name with digits is not a number
        if total_matches == 0 and len(digits) >= 6 and looks_like_mobile:
            try:
                result = PatientService.lookup_by_mobile(mobile_raw=query, db_name=request.hospital_db)
            except ValueError:                                                   # digits that are not a valid mobile number
                result = {}
            if result.get("exists_in_network") and not result.get("already_registered_here"):
                network_match = {
                    "full_name": result.get("full_name"),
                    "date_of_birth": result.get("date_of_birth"),
                    "gender": result.get("gender"),
                }

        return success(data={
            "results": PatientSearchSerializer(found[:limit], many=True).data,
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

        from apps.hospital_setup.compliance_services import log_action
        log_action(request, request.hospital_db, action="patient.view",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient)

        return success(data=PatientDetailSerializer(patient).data)


class PatientHistoryView(APIView):
    """GET /api/v1/patients/<id>/history/"""
    permission_classes = [IsAuthenticated, IsDoctorOrNurse]

    def get(self, request, pk):
        try:
            patient = HospitalPatient.objects.using(request.hospital_db).get(pk=pk)
        except HospitalPatient.DoesNotExist:
            return not_found("Patient not found.")

        history = PatientService.get_shared_history(awpid=patient.awpid)

        from apps.hospital_setup.compliance_services import log_action
        log_action(request, request.hospital_db, action="patient.history.view",
                    resource_type="Patient", resource_id=patient.pk, patient_id=patient)

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

        from apps.hospital_setup.compliance_services import log_action
        log_action(request, request.hospital_db, action="patient.document.view",
                    resource_type="SharedDocument", resource_id=doc.pk)

        # Rows written before object storage (and the consult-pad's no-S3
        want_download = (request.query_params.get("download") or "").lower() in ("1", "true", "yes")
        from apps.documents.lib_documents import display_name, mime_of
        dl_name = display_name(doc) or "document.pdf"
        file_data = blob_storage.signed_url(doc.file_name.name, download_name=dl_name if want_download else None)

        return success(data={
            "medical_document_id": doc.pk, "title": display_name(doc), "doc_type": doc.doc_classification,
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

        from apps.hospital_setup.compliance_services import log_action
        log_action(request, request.hospital_db, action="patient.lab_result.view",
                    resource_type="LabResult", resource_id=r.pk)

        from apps.documents.lib_documents import mime_of
        return success(data={
            "id": r.pk, "test_name": r.test_name, "result_summary": r.result_summary,
            "mime_type": mime_of(r.document) if r.document_id else "",
            "file_data": blob_storage.signed_url(r.document.file_name.name) if r.document_id else "", "delivered_at": r.delivered_at,
        })

