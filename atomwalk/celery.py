"""
atomwalk/celery.py
------------------
Celery app for background work. Workers and the Beat scheduler are normally
started from platform admin → Background Jobs (core.celery_runtime), which
also holds their settings. By hand, the equivalent is:

    celery -A atomwalk worker -l info -P solo          # Windows
    celery -A atomwalk beat -l info

Broker: settings.CELERY_BROKER_URL (registry Postgres by default) unless the
Background Jobs screen overrides it (passed with -b at start).

Liveness: each process writes a heartbeat to celery_runtime_config every
_HEARTBEAT seconds. That works on any broker — Postgres can't answer the
broadcast `inspect`/`ping` commands Redis/RabbitMQ can.
"""

import os
import socket
import threading

from celery import Celery
from celery.signals import after_setup_logger, beat_init, worker_ready, worker_shutdown

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "atomwalk.settings.development")

app = Celery("atomwalk")
app.config_from_object("django.conf:settings", namespace="CELERY")
# core/tasks.py: the My Reports document pipeline and scheduled jobs.
# apps/registry/tasks.py: the mobile upload-and-extract scheduled jobs
# (process_bulk_extractions every minute, periodic_reconcile every 5 minutes).
# Both run on the same worker (default "celery" queue).
app.autodiscover_tasks(["core", "apps.registry"], related_name="tasks")

_HEARTBEAT = 10
_stop = threading.Event()


def _beat_loop(kind):
    from django.db import close_old_connections
    from django.utils import timezone
    from apps.registry.models import CeleryRuntimeConfig

    CeleryRuntimeConfig.get()
    fields = {f"{kind}_pid": os.getpid()}
    if kind == "worker":
        fields["worker_hostname"] = socket.gethostname()[:120]
    while not _stop.is_set():
        try:
            close_old_connections()
            CeleryRuntimeConfig.objects.using("default").filter(pk=1).update(
                **fields, **{f"{kind}_heartbeat_at": timezone.now()})
        except Exception:
            pass
        _stop.wait(_HEARTBEAT)


def _start_heartbeat(kind):
    threading.Thread(target=_beat_loop, args=(kind,), name=f"{kind}-heartbeat", daemon=True).start()


@after_setup_logger.connect
def _quiet_sql(**_):
    # Dev settings log every SQL query at DEBUG — in a worker that buries the
    # log the Background Jobs screen shows (heartbeats alone are a query each).
    import logging
    logging.getLogger("django.db.backends").setLevel(logging.WARNING)
    logging.getLogger("django.db.backends").propagate = False


@worker_ready.connect
def _on_worker_ready(**_):
    _start_heartbeat("worker")


@beat_init.connect
def _on_beat_init(**_):
    _start_heartbeat("beat")


@worker_shutdown.connect
def _on_worker_shutdown(**_):
    _stop.set()
    try:
        from apps.registry.models import CeleryRuntimeConfig
        CeleryRuntimeConfig.objects.using("default").filter(pk=1).update(worker_heartbeat_at=None)
    except Exception:
        pass
