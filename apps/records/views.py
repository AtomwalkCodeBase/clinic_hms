import logging
import time

from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from apps.patients.portal_access import resolve_target_awpid_and_dob
from core.permissions import IsPatient
from core.response import error, not_found, success
from .models import DocumentBatch, SweepConfig
from .serializers import UploadSerializer
from .services import batch_summary, save_upload
from .tasks import dispatch_documents

logger = logging.getLogger(__name__)


class UploadView(APIView):
    """
    POST /api/v1/records/upload/   multipart: files=<file> (repeat for more), patient_awpid=<optional family member>

    Only the sizes are checked here (no empty file, none over 250 MB, 50 files and 250 MB at most). One DocumentBatch
    per upload; every file is stored in S3 under patients/<awpid>/… with a "queued" MedicalDocument.
    A small upload
    (SweepConfig.instant_max_files or fewer) is handed to Celery at once; a bigger one is left "queued" for the
    periodic dispatcher (recover_stuck_documents). Returns 202 with the batch id; follow it with
    GET /api/v1/records/batches/<id>/. Each document moves queued → extracting → classifying →
    completed | failed | rejected (duplicate) — the content check happens in the extraction job.
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
        started = time.monotonic()
        try:
            batch, docs = save_upload(awpid, serializer.validated_data["files"])
            logger.info("records: batch %s — %d file(s), %.1f MB stored in %.1fs", batch.id, len(docs),
                        sum(d.size or 0 for d in docs) / 1048576, time.monotonic() - started)
        except Exception:
            logger.exception("records: upload to S3 failed")
            return error("Upload to storage failed — nothing was saved. Please try again.", status=503)
        if len(docs) <= SweepConfig.current().instant_max_files:
            try:
                dispatch_documents(len(docs), ids=[d.id for d in docs])
            except Exception:   # broker or database hiccup: stays "queued", the dispatcher sends it later
                logger.exception("records: couldn't dispatch the new documents")
        # else: a bulk batch — left "queued" for the periodic dispatcher to drain gradually
        return success(data={
            "batch_id": batch.id,
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
        batch = DocumentBatch.objects.filter(pk=batch_id, awpid=awpid).first()
        if not batch:
            return not_found("Batch not found.")
        return success(data=batch_summary(batch))
