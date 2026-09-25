"""
core/celery_runtime.py
----------------------
Everything platform admin → Background Jobs needs to run and watch Celery
without touching code or a terminal:

  broker_url()           the broker in force (settings table, else settings)
  status()               worker + beat: alive?, pid, uptime, cpu/mem, heartbeat;
                         broker, queue depths, running tasks
  start(kind) / stop(kind) / restart(kind)
                         launch or end the `celery worker` / `celery beat`
                         process on THIS machine with the saved settings
  log_tail(kind)         last lines of that process's log file
  send(task, kwargs)     queue a task on the configured broker

"Alive" means the process wrote a heartbeat in the last _ALIVE_SECS (see
atomwalk/celery.py) — works for processes started here, from a terminal, or
on another server. Start/stop only act on processes on this machine and are
disabled entirely when settings.CELERY_UI_PROCESS_CONTROL is False (a
process manager owns them in production; the screen then only monitors).
"""

import logging
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

KINDS = ("worker", "beat", "flower")
_ALIVE_SECS = 35
_cache = {"at": 0.0, "cfg": None}


class RuntimeError_(Exception):
    """A start/stop request that can't be honoured — message is user-facing."""


# ── config ───────────────────────────────────────────────────────────────
def config(fresh=False):
    from apps.registry.models import CeleryRuntimeConfig
    now = time.monotonic()
    if fresh or _cache["cfg"] is None or now - _cache["at"] > 10:
        _cache.update(at=now, cfg=CeleryRuntimeConfig.get())
    return _cache["cfg"]


def invalidate():
    _cache.update(at=0.0, cfg=None)


def broker_url(cfg=None):
    # Where a process manager (systemd) owns the workers, they read the broker
    # from .env — so must the web app, or the two could talk to different
    # queues. The screen's broker override only applies in dev.
    if not getattr(settings, "CELERY_UI_PROCESS_CONTROL", False):
        return settings.CELERY_BROKER_URL
    cfg = cfg or config()
    return (cfg.broker_url or "").strip() or settings.CELERY_BROKER_URL


def broker_label(url):
    """The broker URL with any password masked."""
    try:
        from kombu.utils.url import maybe_sanitize_url
        return maybe_sanitize_url(url)
    except Exception:
        return url.split("@")[-1]


def supports_broadcast(url):
    return url.split("://", 1)[0] in ("redis", "rediss", "amqp", "pyamqp", "amqps")


def flower_up():
    """Flower has no heartbeat of its own — ask its /healthcheck."""
    try:
        import requests
        r = requests.get(f"http://{settings.FLOWER_ADDRESS}:{settings.FLOWER_PORT}/healthcheck", timeout=1.5)
        return r.status_code == 200
    except Exception:
        return False


def alive(kind, cfg=None):
    if kind == "flower":
        return flower_up()
    cfg = cfg or config()
    hb = getattr(cfg, f"{kind}_heartbeat_at")
    return bool(hb and timezone.now() - hb < timedelta(seconds=_ALIVE_SECS))


# ── sending ──────────────────────────────────────────────────────────────
def send(task_name, args=None, kwargs=None, queue=None):
    """Queue `task_name` on the configured broker. Returns the task id."""
    from atomwalk.celery import app
    with app.connection_for_write(broker_url()) as conn:
        res = app.send_task(task_name, args=args or [], kwargs=kwargs or {},
                            queue=queue or None, connection=conn)
    return res.id


# ── processes ────────────────────────────────────────────────────────────
def _log_path(kind):
    d = Path(settings.CELERY_LOG_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"celery-{kind}.log"


def _proc(pid, kind):
    """psutil.Process for `pid` if it is a live celery `kind` process, else None."""
    if not pid:
        return None
    try:
        import psutil
        p = psutil.Process(pid)
        cmd = " ".join(p.cmdline()).lower()
        if p.is_running() and "celery" in cmd and kind in cmd:
            return p
    except Exception:
        pass
    return None


def _command(kind, cfg):
    # -A / -b are global options in Celery 5 — they go before the subcommand.
    cmd = [sys.executable, "-m", "celery", "-A", "atomwalk", "-b", broker_url(cfg), kind,
           "-l", cfg.worker_loglevel or "INFO"]
    if kind == "worker":
        # "Workers" on the settings page = how many files at once. The pool
        # follows from it: 1 → solo (simplest), more → threads on Windows
        # (prefork isn't supported there) / prefork on Linux.
        workers = max(1, cfg.worker_concurrency or 1)
        pool = "solo" if workers == 1 else ("threads" if os.name == "nt" else "prefork")
        # -E: publish task events (Flower's live view needs them).
        cmd += ["-P", pool, "-E", "-n", f"hms-{os.getpid()}-{int(time.time())}@%h"]
        if pool != "solo":
            cmd += ["-c", str(workers)]
        queues = ",".join(q.strip() for q in (cfg.worker_queues or "").split(",") if q.strip())
        if queues:
            cmd += ["-Q", queues]
    elif kind == "beat":
        cmd += ["-S", settings.CELERY_BEAT_SCHEDULER]
    else:  # flower — local-only by default; it shows task arguments
        cmd = [sys.executable, "-m", "celery", "-A", "atomwalk", "-b", broker_url(cfg), "flower",
               f"--address={settings.FLOWER_ADDRESS}", f"--port={settings.FLOWER_PORT}"]
        if settings.FLOWER_BASIC_AUTH:
            cmd.append(f"--basic-auth={settings.FLOWER_BASIC_AUTH}")
    return cmd


def _require_control():
    if not getattr(settings, "CELERY_UI_PROCESS_CONTROL", False):
        raise RuntimeError_("Process control is turned off on this server "
                            "(CELERY_UI_PROCESS_CONTROL=False) — a process manager runs the workers.")


def start(kind, by=""):
    from apps.registry.models import CeleryRuntimeConfig
    _require_control()
    cfg = config(fresh=True)
    if alive(kind, cfg) or _proc(getattr(cfg, f"{kind}_pid"), kind):
        raise RuntimeError_(f"The {kind} is already running.")
    if kind == "flower" and not supports_broadcast(broker_url(cfg)):
        raise RuntimeError_("Flower needs a Redis (or RabbitMQ) broker — the Postgres queue can't broadcast "
                            "worker events. Set the broker URL to redis://localhost:6379/0 first.")

    log = _log_path(kind)
    if log.exists() and log.stat().st_size > 5 * 1024 * 1024:   # keep one old copy
        log.replace(log.with_suffix(".log.1"))
    fh = open(log, "a", encoding="utf-8", buffering=1)
    fh.write(f"\n===== {timezone.now():%Y-%m-%d %H:%M:%S} start {kind} (by {by or 'admin'}) =====\n")
    env = {**os.environ, "PYTHONUNBUFFERED": "1",
           "DJANGO_SETTINGS_MODULE": os.environ.get("DJANGO_SETTINGS_MODULE", "atomwalk.settings.development")}
    kw = {"cwd": str(settings.BASE_DIR), "env": env, "stdout": fh, "stderr": subprocess.STDOUT,
          "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(_command(kind, cfg), **kw)
    fh.close()

    fields = {f"{kind}_pid": proc.pid, f"{kind}_started_at": timezone.now(), "updated_by": (by or "")[:120]}
    if kind != "flower":
        fields[f"{kind}_heartbeat_at"] = None
    CeleryRuntimeConfig.objects.using("default").filter(pk=1).update(**fields)
    invalidate()
    return proc.pid


def stop(kind, by=""):
    from apps.registry.models import CeleryRuntimeConfig
    _require_control()
    cfg = config(fresh=True)
    p = _proc(getattr(cfg, f"{kind}_pid"), kind)
    clear = {f"{kind}_pid": None, **({} if kind == "flower" else {f"{kind}_heartbeat_at": None})}
    if p is None:
        CeleryRuntimeConfig.objects.using("default").filter(pk=1).update(**clear)
        invalidate()
        if alive(kind, cfg):
            raise RuntimeError_(f"The {kind} is running on another machine or wasn't started here — stop it there.")
        return False
    import psutil
    procs = p.children(recursive=True) + [p]
    for c in procs:
        try:
            c.terminate()
        except psutil.Error:
            pass
    _gone, left = psutil.wait_procs(procs, timeout=10)
    for c in left:
        try:
            c.kill()
        except psutil.Error:
            pass
    with open(_log_path(kind), "a", encoding="utf-8") as fh:
        fh.write(f"===== {timezone.now():%Y-%m-%d %H:%M:%S} stopped {kind} (by {by or 'admin'}) =====\n")
    CeleryRuntimeConfig.objects.using("default").filter(pk=1).update(**clear, updated_by=(by or "")[:120])
    invalidate()
    return True


def restart(kind, by=""):
    stop(kind, by)
    return start(kind, by)


LOGS = KINDS + ("pipeline",)     # "pipeline" = core/pipeline/log.py's document journey log


def log_tail(kind, lines=200):
    if kind == "pipeline":
        from core.pipeline import log as plog
        path = plog.path()
    else:
        path = _log_path(kind)
    if not path.exists():
        return ""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 256 * 1024))
        data = fh.read().decode("utf-8", "replace")
    return "\n".join(data.splitlines()[-max(1, min(lines, 2000)):])


# ── status ───────────────────────────────────────────────────────────────
def _proc_status(kind, cfg):
    pid = getattr(cfg, f"{kind}_pid")
    p = _proc(pid, kind)
    out = {
        "alive": alive(kind, cfg),
        "pid": pid,
        "process_running": p is not None,
        "started_at": getattr(cfg, f"{kind}_started_at"),
        "heartbeat_at": getattr(cfg, f"{kind}_heartbeat_at", None),
        "cpu_percent": None, "memory_mb": None,
    }
    if p is not None:
        try:
            out["cpu_percent"] = round(sum(c.cpu_percent(interval=0.05) for c in [p] + p.children(recursive=True)), 1)
            out["memory_mb"] = round(sum(c.memory_info().rss for c in [p] + p.children(recursive=True)) / 1048576, 1)
        except Exception:
            pass
    # starting = launched here but hasn't sent its first heartbeat yet
    out["state"] = ("running" if out["alive"]
                    else "starting" if p is not None else "stopped")
    return out


def queue_depths(cfg=None):
    cfg = cfg or config()
    from atomwalk.celery import app
    names = [q.strip() for q in (cfg.worker_queues or "celery").split(",") if q.strip()] or ["celery"]
    out = {}
    try:
        with app.connection_for_read(broker_url(cfg)) as conn:
            conn.ensure_connection(max_retries=1, timeout=3)
            ch = conn.channel()
            for q in names:
                try:
                    out[q] = ch.queue_declare(queue=q, passive=True).message_count
                except Exception:
                    out[q] = 0
    except Exception as exc:
        return {"error": f"Broker unreachable: {exc.__class__.__name__}"}
    return out


def active_tasks(cfg=None):
    """Running tasks. Broadcast brokers answer live; otherwise the result
    table's STARTED rows (CELERY_TASK_TRACK_STARTED) stand in."""
    cfg = cfg or config()
    url = broker_url(cfg)
    if supports_broadcast(url):
        try:
            from atomwalk.celery import app
            with app.connection_for_read(url) as conn:
                act = app.control.inspect(timeout=1.0, connection=conn).active() or {}
            return [{"task_id": t["id"], "task_name": t["name"], "worker": w,
                     "started": t.get("time_start")} for w, ts in act.items() for t in ts]
        except Exception:
            pass
    from django_celery_results.models import TaskResult
    rows = TaskResult.objects.using("default").filter(status="STARTED").order_by("-date_created")[:50]
    return [{"task_id": r.task_id, "task_name": r.task_name, "worker": r.worker,
             "started": r.date_created} for r in rows]


def status():
    cfg = config(fresh=True)
    url = broker_url(cfg)
    return {
        "config": {
            "broker_url": cfg.broker_url,
            "worker_pool": cfg.worker_pool,
            "worker_concurrency": cfg.worker_concurrency,
            "worker_queues": cfg.worker_queues,
            "worker_loglevel": cfg.worker_loglevel,
            "inline_fallback": cfg.inline_fallback,
            "instant_max_files": cfg.instant_max_files,
            "bulk_batch_limit": cfg.bulk_batch_limit,
            "updated_by": cfg.updated_by,
            "updated_at": cfg.updated_at,
        },
        "broker": {"url": broker_label(url), "default_url": broker_label(settings.CELERY_BROKER_URL),
                   "broadcast": supports_broadcast(url)},
        "process_control": bool(getattr(settings, "CELERY_UI_PROCESS_CONTROL", False)),
        "worker": {**_proc_status("worker", cfg), "hostname": cfg.worker_hostname},
        "beat": _proc_status("beat", cfg),
        "flower": {**_proc_status("flower", cfg), "url": settings.FLOWER_URL,
                   "needs_broker": not supports_broadcast(url)},
        "queues": queue_depths(cfg),
        "active": active_tasks(cfg),
    }
