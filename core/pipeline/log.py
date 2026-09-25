"""
core/pipeline/log.py — the document pipeline's own, human-readable log.

Every stage writes one line, e.g.

  2026-09-25 11:02:14 | doc 131   | UPLOADED   | "Blood test.pdf" · batch of 1 · route=instant
  2026-09-25 11:02:15 | doc 131   | TEXT       | 1,765 characters read in 0.4s
  2026-09-25 11:02:15 | doc 131   | RULES      | lab_report 96%
  2026-09-25 11:02:15 | doc 131   | FILED      | as lab_report · ready for the patient's check
  2026-09-25 11:02:15 | doc 131   | AI QUEUED  | waiting for the LLM (local · qwen2.5-coder:7b)
  2026-09-25 11:02:36 | doc 131   | AI RESULT  | lab_report 90% in 20.3s → kept as lab_report

The web server (instant uploads) and the Celery workers (bulk runs, AI queue)
all append to the same file, logs/doc-pipeline.log, so one document's whole
journey reads top to bottom. It also goes to the normal console / worker log.
Shown on platform admin → Background Jobs → "Pipeline log".
"""

import logging
from pathlib import Path

from django.conf import settings

FILE_NAME = "doc-pipeline.log"
_logger = logging.getLogger("hms.pipeline")


def path() -> Path:
    return Path(settings.CELERY_LOG_DIR) / FILE_NAME


def _ensure_handler():
    if getattr(_logger, "_hms_ready", False):
        return
    _logger.setLevel(logging.INFO)
    try:
        path().parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path(), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
        _logger.addHandler(fh)
    except OSError:
        pass                    # no writable log dir — console only
    _logger._hms_ready = True


def event(doc_id, stage: str, message: str) -> None:
    """One line: `doc <id> | <STAGE> | <message>`. Never raises."""
    try:
        _ensure_handler()
        _logger.info("doc %-5s | %-10s | %s", doc_id if doc_id is not None else "-", stage, message)
    except Exception:
        pass


def error(doc_id, stage: str, message: str) -> None:
    try:
        _ensure_handler()
        _logger.error("doc %-5s | %-10s | %s", doc_id if doc_id is not None else "-", stage, message)
    except Exception:
        pass


def pct(x) -> str:
    return f"{round((x or 0) * 100)}%"
