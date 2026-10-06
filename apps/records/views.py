import logging
import time

from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from apps.patients.portal_access import resolve_target_awpid_and_dob
from core.permissions import IsPatient
from core.response import error, not_found, success
from . import classification as rules
from .models import DocumentBatch
from .serializers import SubmitSerializer, UploadSerializer
from .services import (BULK_QUEUE, INSTANT_QUEUE, awaiting_review_q, batch_summary, save_upload, start_processing,
                       submit_decisions)

logger = logging.getLogger(__name__)


class UploadView(APIView):
    """
    POST /api/v1/records/upload/   multipart: files=<file> (repeat for more), mode=instant|bulk, patient_awpid=<optional>

    mode "instant" takes exactly one file and is queued on its own fast lane; "bulk" takes up to 50 and is queued on
    the bulk lane, so a single file never waits behind someone's big upload. Left out, it is "instant" for one file
    and "bulk" for several. The mode is only used to pick the queue; it is not stored.

    Only the sizes are checked here (no empty file, none over 250 MB, 50 files and 250 MB at most). One DocumentBatch
    per upload; every file is stored in S3 under patients/<awpid>/… with a "queued" MedicalDocument, and every file
    is handed to Celery at once. Returns 202 with the batch id; follow it with GET /api/v1/records/batches/<id>/.
    Each document moves queued → extracting → classifying → completed | review_required | failed — the content
    check happens in the extraction job.
    """
    permission_classes = [IsPatient]
    parser_classes = [MultiPartParser]

    def post(self, request):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        serializer = UploadSerializer(data={"files": request.FILES.getlist("files")})
        if not serializer.is_valid():
            return error("Upload rejected — nothing was saved.", errors=serializer.errors)
        files = serializer.validated_data["files"]
        mode = (request.data.get("mode") or ("instant" if len(files) == 1 else "bulk")).strip().lower()
        if mode not in ("instant", "bulk"):
            return error("Upload rejected - mode must be instant or bulk.")
        if mode == "instant" and len(files) != 1:
            return error("Upload rejected - an instant upload takes exactly one file.")
        started = time.monotonic()
        try:
            batch, docs = save_upload(awpid, files)
            logger.info("records: batch %s — %d file(s), %.1f MB stored in %.1fs", batch.id, len(docs),
                        sum(d.size or 0 for d in docs) / 1048576, time.monotonic() - started)
        except Exception:
            logger.exception("records: upload to S3 failed")
            return error("Upload to storage failed — nothing was saved. Please try again.", status=503)
        start_processing([d.id for d in docs], INSTANT_QUEUE if mode == "instant" else BULK_QUEUE)
        docs = list(batch.documents.order_by("id"))      # fresh: a file that couldn't be queued is already "failed"
        return success(data={
            "batch_id": batch.id, "mode": mode,
            "documents": [{"id": d.id, "file_name": d.file_name, "processing_status": d.processing_status} for d in docs],
        }, status=202)


class BatchDetailView(APIView):
    """GET /api/v1/records/batches/<id>/ — the batch, its counts by status, then each of its documents.
    The patient (or the family member they act for) can only read their own batches."""
    permission_classes = [IsPatient]

    def get(self, request, batch_id):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        batch = DocumentBatch.objects.filter(pk=batch_id, patient__awpid=awpid).first()
        if not batch:
            return not_found("Batch not found.")
        return success(data=batch_summary(batch))


class TypesView(APIView):
    """GET /api/v1/records/types/ - the categories a document can be filed under (the one list every app reads).
    {"types": [{"code", "label"}]}"""
    permission_classes = [IsPatient]

    def get(self, request):
        return success(data={"types": rules.document_type_choices()})


class SubmitView(APIView):
    """
    POST /api/v1/records/submit/   {"decisions": [{"document_id": 1, "document_type": "lab_report"}]}   (1 to 100)

    The patient's final answer. Each file is checked on its own (yours, finished reading, not already confirmed, a
    valid type); the ones that pass get the person's type and are locked for good - nobody can change them again.
    Returns {"submitted": [ids], "rejected": [{"document_id", "reason"}], "counts": {"awaiting_review"}}. Sending the
    same list twice is safe: confirmed files are skipped.
    """
    permission_classes = [IsPatient]

    def post(self, request):
        awpid, _dob, err = resolve_target_awpid_and_dob(request)
        if err:
            return err
        serializer = SubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return error("Nothing was submitted - check the list and try again.", errors=serializer.errors)
        result = submit_decisions(awpid, serializer.validated_data["decisions"])
        from .models import MedicalDocument
        result["counts"] = {"awaiting_review": MedicalDocument.objects.using("default")
                            .filter(awaiting_review_q(), patient__awpid=awpid,
                                    status__in=(MedicalDocument.Status.COMPLETED, MedicalDocument.Status.REVIEW_REQUIRED)).count()}
        return success(data=result)
