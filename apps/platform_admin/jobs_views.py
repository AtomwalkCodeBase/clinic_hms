"""
apps/platform_admin/jobs_views.py
---------------------------------
Platform admin → Background Jobs: run, configure and watch Celery.

Runtime (worker + beat processes, settings table core.celery_runtime):
  GET   /api/v1/platform/jobs/runtime/                     status + config
  PATCH /api/v1/platform/jobs/runtime/                     save settings
  POST  /api/v1/platform/jobs/runtime/<worker|beat>/<start|stop|restart>/
  GET   /api/v1/platform/jobs/runtime/<worker|beat|flower|pipeline>/log/?lines=200
        ("pipeline" = every document's journey, core/pipeline/log.py)

Scheduled jobs (django_celery_beat.PeriodicTask; the Beat process picks up
changes by itself):
  GET/POST       /api/v1/platform/jobs/schedules/
  PATCH/DELETE   /api/v1/platform/jobs/schedules/<id>/
  POST           /api/v1/platform/jobs/schedules/<id>/run/     run now
  GET            /api/v1/platform/jobs/tasks/                  task catalog + hospitals
  POST           /api/v1/platform/jobs/run/                    run a catalog task once

History (django_celery_results.TaskResult):
  GET            /api/v1/platform/jobs/history/?status=&task=&limit=

Hospital-scoped jobs: pick a hospital and its database key becomes the job
name's prefix ("aw_sunrise_clinic: Daily reminders") and the task's
`tenant_db` kwarg — the key the task uses to point at that hospital's DB.
"""

import json
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin
from core.response import created, error, not_found, success

_PERIODS = ("days", "hours", "minutes", "seconds")
_TENANT_SEP = ": "


def _who(request):
    return (getattr(request.user, "email", "") or str(getattr(request.user, "id", "")))[:120]


# ── runtime ──────────────────────────────────────────────────────────────
class JobsRuntimeView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from core import celery_runtime as rt
        return success(data=rt.status())

    def patch(self, request):
        from apps.registry.models import CeleryRuntimeConfig
        from core import celery_runtime as rt
        cfg = CeleryRuntimeConfig.get()
        d = request.data
        broker_changed = "broker_url" in d and str(d["broker_url"] or "").strip() != (cfg.broker_url or "")
        if broker_changed and not getattr(settings, "CELERY_UI_PROCESS_CONTROL", False):
            return error("The broker is set in the server's .env (CELERY_BROKER_URL) on this server.")
        if "broker_url" in d:
            url = str(d["broker_url"] or "").strip()
            if url and "://" not in url:
                return error("Broker URL must look like redis://host:6379/0 or sqla+postgresql://…")
            cfg.broker_url = url[:300]
        if "worker_pool" in d:
            if d["worker_pool"] not in CeleryRuntimeConfig.POOLS:
                return error("Pool must be solo, threads or prefork.")
            cfg.worker_pool = d["worker_pool"]
        if "worker_concurrency" in d:
            try:
                cfg.worker_concurrency = max(1, min(8, int(d["worker_concurrency"])))
            except (TypeError, ValueError):
                return error("Workers must be a number from 1 to 8.")
        if "worker_queues" in d:
            qs = [q.strip() for q in str(d["worker_queues"] or "").split(",") if q.strip()]
            cfg.worker_queues = ",".join(qs)[:200] or "celery"
        if "worker_loglevel" in d:
            lvl = str(d["worker_loglevel"] or "").upper()
            if lvl not in CeleryRuntimeConfig.LOG_LEVELS:
                return error("Unknown log level.")
            cfg.worker_loglevel = lvl
        if "inline_fallback" in d:
            cfg.inline_fallback = bool(d["inline_fallback"])
        for key, lo, hi in (("instant_max_files", 0, 50), ("bulk_batch_limit", 1, 500)):
            if key in d:
                try:
                    setattr(cfg, key, max(lo, min(hi, int(d[key]))))
                except (TypeError, ValueError):
                    return error(f"{key} must be a number.")
        cfg.updated_by = _who(request)
        cfg.save(using="default")
        rt.invalidate()
        return success(data=rt.status(), message="Saved. Restart the worker/beat to apply process settings.")


class JobsProcessActionView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request, kind, action):
        from core import celery_runtime as rt
        if kind not in rt.KINDS or action not in ("start", "stop", "restart"):
            return not_found("Unknown action.")
        try:
            getattr(rt, action)(kind, by=_who(request))
        except rt.RuntimeError_ as exc:
            return error(str(exc), status=409)
        return success(data=rt.status(), message=f"{kind.title()} {action} requested.")


class JobsProcessLogView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request, kind):
        from core import celery_runtime as rt
        if kind not in rt.LOGS:
            return not_found("Unknown log.")
        try:
            lines = int(request.query_params.get("lines") or 200)
        except ValueError:
            lines = 200
        return success(data={"kind": kind, "log": rt.log_tail(kind, lines)})


# ── catalog ──────────────────────────────────────────────────────────────
def _tenants():
    from apps.tenants.models import Tenant
    return [{"db_name": t.db_name, "name": t.name}
            for t in Tenant.objects.using("default").order_by("name").only("db_name", "name")]


class JobsTaskCatalogView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from atomwalk.celery import app
        from core.tasks import TASK_CATALOG
        app.loader.import_default_modules()
        tasks = [{"name": n, **meta, "registered": n in app.tasks} for n, meta in TASK_CATALOG.items()]
        return success(data={"tasks": tasks, "tenants": _tenants(), "timezone": settings.CELERY_TIMEZONE})


class JobsRunNowView(APIView):
    """Run a catalog task once, right now."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request):
        from core import celery_runtime as rt
        from core.tasks import TASK_CATALOG
        name = str(request.data.get("task") or "")
        if name not in TASK_CATALOG:
            return error("Unknown task.")
        kwargs = request.data.get("kwargs") or {}
        if not isinstance(kwargs, dict):
            return error("kwargs must be an object.")
        try:
            tid = rt.send(name, kwargs=kwargs)
        except Exception as exc:
            return error(f"Could not queue the task: {exc.__class__.__name__}", status=503)
        return success(data={"task_id": tid, "worker_alive": rt.alive("worker")},
                       message="Queued." if rt.alive("worker") else "Queued — start the worker to run it.")


# ── schedules ────────────────────────────────────────────────────────────
def _schedule_dict(pt):
    kwargs = {}
    try:
        kwargs = json.loads(pt.kwargs or "{}")
    except ValueError:
        pass
    tenant_db = kwargs.get("tenant_db") or ""
    label = pt.name.split(_TENANT_SEP, 1)[1] if tenant_db and pt.name.startswith(tenant_db + _TENANT_SEP) else pt.name
    out = {
        "id": pt.id, "name": pt.name, "label": label, "task": pt.task,
        "kwargs": {k: v for k, v in kwargs.items() if k != "tenant_db"},
        "tenant_db": tenant_db, "enabled": pt.enabled, "one_off": pt.one_off,
        "queue": pt.queue or "", "description": pt.description,
        "last_run_at": pt.last_run_at, "total_run_count": pt.total_run_count,
        "date_changed": pt.date_changed, "schedule_type": None, "next_run_at": None,
    }
    sched = None
    if pt.crontab_id:
        c = pt.crontab
        out["schedule_type"] = "crontab"
        out["crontab"] = {"minute": c.minute, "hour": c.hour, "day_of_week": c.day_of_week,
                          "day_of_month": c.day_of_month, "month_of_year": c.month_of_year}
        sched = c.schedule
    elif pt.interval_id:
        i = pt.interval
        out["schedule_type"] = "interval"
        out["interval"] = {"every": i.every, "period": i.period}
        sched = i.schedule
    if sched is not None and pt.enabled:
        try:
            last = pt.last_run_at or timezone.now()
            out["next_run_at"] = timezone.now() + max(sched.remaining_estimate(last), timedelta(0))
        except Exception:
            pass
    return out


def _apply_schedule(pt, d):
    """Validate + copy request fields onto a PeriodicTask. Returns an error string or None."""
    from celery.schedules import crontab as celery_crontab
    from django_celery_beat.models import CrontabSchedule, IntervalSchedule
    from core.tasks import TASK_CATALOG

    if "task" in d:
        meta = TASK_CATALOG.get(d["task"])
        if not meta or not meta.get("schedulable"):
            return "Pick a task from the list."
        pt.task = d["task"]
    meta = TASK_CATALOG.get(pt.task) or {}

    kwargs = d.get("kwargs", None)
    if kwargs is None:
        try:
            kwargs = json.loads(pt.kwargs or "{}")
        except ValueError:
            kwargs = {}
    if not isinstance(kwargs, dict):
        return "Arguments must be a JSON object."
    kwargs = {k: v for k, v in kwargs.items() if k != "tenant_db"}

    tenant_db = d.get("tenant_db", None)
    if tenant_db is None:
        try:
            tenant_db = json.loads(pt.kwargs or "{}").get("tenant_db") or ""
        except ValueError:
            tenant_db = ""
    tenant_db = str(tenant_db or "").strip()
    if tenant_db:
        if not meta.get("tenant_aware"):
            return "This task runs platform-wide — it can't be scoped to one hospital."
        if tenant_db not in {t["db_name"] for t in _tenants()}:
            return "Unknown hospital."
        kwargs["tenant_db"] = tenant_db
    pt.kwargs = json.dumps(kwargs)
    pt.args = pt.args or "[]"

    label = str(d.get("label") if "label" in d else (pt.name.split(_TENANT_SEP, 1)[-1] if pt.name else "")).strip()
    if not label:
        return "Give the job a name."
    pt.name = (f"{tenant_db}{_TENANT_SEP}{label}" if tenant_db else label)[:200]

    stype = d.get("schedule_type")
    if stype == "crontab":
        c = d.get("crontab") or {}
        f = {k: str(c.get(k, "*") or "*").strip() for k in
             ("minute", "hour", "day_of_week", "day_of_month", "month_of_year")}
        try:
            celery_crontab(**f)
        except Exception as exc:
            return f"Invalid schedule: {exc}"
        pt.crontab, _ = CrontabSchedule.objects.using("default").get_or_create(
            **f, timezone=settings.CELERY_TIMEZONE)
        pt.interval = None
    elif stype == "interval":
        i = d.get("interval") or {}
        try:
            every = int(i.get("every"))
        except (TypeError, ValueError):
            return "Interval must be a number."
        period = i.get("period")
        if every < 1 or period not in _PERIODS:
            return "Interval must be at least 1 and a period of days/hours/minutes/seconds."
        if period == "seconds" and every < 10:
            return "Run at most every 10 seconds."
        pt.interval, _ = IntervalSchedule.objects.using("default").get_or_create(every=every, period=period)
        pt.crontab = None
    elif stype is not None:
        return "Schedule type must be crontab or interval."
    if not pt.crontab_id and not pt.interval_id and pt.crontab is None and pt.interval is None:
        return "Set a schedule."

    for k in ("enabled", "one_off"):
        if k in d:
            setattr(pt, k, bool(d[k]))
    if "description" in d:
        pt.description = str(d["description"] or "")[:500]
    if "queue" in d:
        pt.queue = (str(d["queue"] or "").strip() or None)
    return None


class JobsScheduleListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from django_celery_beat.models import PeriodicTask
        from django.db.models import Q
        rows = (PeriodicTask.objects.using("default").select_related("crontab", "interval")
                .filter(~Q(task__startswith="celery.") | Q(task="celery.backend_cleanup"))
                .order_by("name"))
        return success(data=[_schedule_dict(p) for p in rows])

    def post(self, request):
        from django_celery_beat.models import PeriodicTask
        pt = PeriodicTask(name="", task="")
        if "task" not in request.data:
            return error("Pick a task.")
        msg = _apply_schedule(pt, request.data)
        if msg:
            return error(msg)
        if PeriodicTask.objects.using("default").filter(name=pt.name).exists():
            return error("A job with that name already exists.")
        pt.save(using="default")
        return created(data=_schedule_dict(pt), message="Job scheduled.")


class JobsScheduleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def _get(self, pk):
        from django_celery_beat.models import PeriodicTask
        return PeriodicTask.objects.using("default").select_related("crontab", "interval").filter(pk=pk).first()

    def patch(self, request, pk):
        from django_celery_beat.models import PeriodicTask
        pt = self._get(pk)
        if not pt:
            return not_found("Job not found.")
        msg = _apply_schedule(pt, request.data)
        if msg:
            return error(msg)
        if PeriodicTask.objects.using("default").filter(name=pt.name).exclude(pk=pk).exists():
            return error("A job with that name already exists.")
        pt.save(using="default")
        return success(data=_schedule_dict(pt), message="Job saved.")

    def delete(self, request, pk):
        pt = self._get(pk)
        if not pt:
            return not_found("Job not found.")
        pt.delete()
        return success(data={"id": pk, "deleted": True}, message="Job deleted.")


class JobsScheduleRunView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def post(self, request, pk):
        from django_celery_beat.models import PeriodicTask
        from core import celery_runtime as rt
        pt = PeriodicTask.objects.using("default").filter(pk=pk).first()
        if not pt:
            return not_found("Job not found.")
        try:
            kwargs = json.loads(pt.kwargs or "{}")
            args = json.loads(pt.args or "[]")
            tid = rt.send(pt.task, args=args, kwargs=kwargs, queue=pt.queue)
        except Exception as exc:
            return error(f"Could not queue the job: {exc.__class__.__name__}", status=503)
        alive = rt.alive("worker")
        return success(data={"task_id": tid, "worker_alive": alive},
                       message="Queued." if alive else "Queued — start the worker to run it.")


# ── history ──────────────────────────────────────────────────────────────
class JobsHistoryView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from django_celery_results.models import TaskResult
        qs = TaskResult.objects.using("default").all()
        st = (request.query_params.get("status") or "").upper()
        if st:
            qs = qs.filter(status=st)
        task = request.query_params.get("task") or ""
        if task:
            qs = qs.filter(task_name=task)
        try:
            limit = max(1, min(500, int(request.query_params.get("limit") or 100)))
        except ValueError:
            limit = 100
        since = timezone.now() - timedelta(hours=24)
        counts = dict(TaskResult.objects.using("default").filter(date_created__gte=since)
                      .values_list("status").annotate(n=Count("id")))
        rows = []
        for r in qs.order_by("-date_created")[:limit]:
            dur = None
            if r.date_done and r.date_created and r.status in ("SUCCESS", "FAILURE"):
                dur = round((r.date_done - r.date_created).total_seconds(), 2)
            rows.append({
                "task_id": r.task_id, "task_name": r.task_name, "status": r.status,
                "worker": r.worker, "periodic_task_name": r.periodic_task_name,
                "task_kwargs": r.task_kwargs, "date_created": r.date_created, "date_done": r.date_done,
                "duration_s": dur,
                "result": (r.result or "")[:2000] if r.status != "FAILURE" else "",
                "traceback": (r.traceback or "")[-3000:] if r.status == "FAILURE" else "",
            })
        return success(data={"results": rows, "last_24h": counts})
