import logging

from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import IsPatient
from core.response import error, success
from .models import SweepConfig
from .serializers import UploadSerializer
from .services import LLMUnavailable, llm_complete, llm_status, save_upload
from .tasks import extract_document_task

logger = logging.getLogger(__name__)


class UploadView(APIView):
    """
    POST /api/v1/records/upload/   multipart: files=<file> (repeat for more), patient_awpid=<optional family member>

    One UploadBatch, one SharedDocument per file. A batch of SweepConfig.instant_max_files or fewer
    (Platform Admin → Records settings) dispatches one extract_document_task per file immediately
    (which itself hands off to classify_document_task once extraction finishes — two independently
    queued stages, so a slow LLM call never blocks the next document's extraction); a larger (bulk)
    batch is left "queued" and drained a few at a time by the periodic sweep (recover_stuck_documents).
    Returns 202 at once; each document's processing_status moves queued → ocr → classifying → completed | failed.
    """
    permission_classes = [IsPatient]
    parser_classes = [MultiPartParser]

    def post(self, request):
        from apps.patients.portal_views import _resolve_target_awpid_and_dob
        awpid, _dob, err = _resolve_target_awpid_and_dob(request)
        if err:
            return err
        serializer = UploadSerializer(data={"files": request.FILES.getlist("files")})
        if not serializer.is_valid():
            return error("Upload rejected — nothing was saved.", errors=serializer.errors)
        try:
            batch, docs = save_upload(awpid, serializer.validated_data["files"])
        except Exception:
            logger.exception("records: upload to S3 failed")
            return error("Upload to storage failed — nothing was saved. Please try again.", status=503)
        if len(docs) <= SweepConfig.current().instant_max_files:
            for doc in docs:
                try:
                    extract_document_task.delay(doc.id)
                except Exception:   # broker down: stays "queued", the periodic sweep sends it later
                    logger.exception("records: couldn't queue document %s", doc.id)
        # else: a bulk batch — left "queued" for the periodic sweep to drain gradually
        return success(data={
            "batch_id": batch.id,
            "documents": [{"id": d.id, "file_name": d.file_name, "processing_status": d.processing_status} for d in docs],
        }, status=202)


class _LLMCompleteView(APIView):
    """Shared by LLMAskView and LLMChatView — both have the identical request/response contract,
    routed through services.llm_complete() (local Ollama or production, per LLM_MODE)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_prompt = (request.data.get("user_prompt") or "").strip()
        if not user_prompt:
            return error("user_prompt is required.", status=400)
        system_prompt = (request.data.get("system_prompt") or "").strip()
        try:
            temperature = float(request.data.get("temperature", 0.3))
            max_tokens = int(request.data.get("max_tokens", 1024))
        except (TypeError, ValueError):
            return error("temperature must be a number and max_tokens must be an integer.", status=400)
        try:
            result = llm_complete(system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens)
        except LLMUnavailable as exc:
            return error(str(exc), status=503)
        except ValueError as exc:                    # LLM_MODE itself is misconfigured
            return error(str(exc), status=500)
        return success(data=result)


class LLMAskView(_LLMCompleteView):
    """POST /llm_api/ask/ — {system_prompt, user_prompt, temperature, max_tokens}."""


class LLMChatView(_LLMCompleteView):
    """POST /llm_api/chat/ — same request/response contract as ask/."""


class LLMStatusView(APIView):
    """GET /llm_api/status/ — {mode, reachable}. No secrets, no server URLs/tokens exposed."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success(data=llm_status())
