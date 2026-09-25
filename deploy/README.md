# Production: Celery, Redis and Flower on EC2 (Ubuntu)

Everything starts on boot and restarts itself on a crash — nobody logs in to
start Redis or the workers.

```
            nginx (TLS) ──► Django (gunicorn, hms-web)
                                 │  queues tasks
                                 ▼
                          Redis 127.0.0.1:6379   (redis-server)
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
   hms-celery-worker      hms-celery-beat          hms-flower
   runs the tasks         queues timed jobs        monitor (optional)
          │
          └──► PostgreSQL (task history, schedules, documents) · S3 (files)
```

| Service | What it does | If it stops |
|---|---|---|
| `redis-server` | Celery broker (queue) | systemd restarts it; queued tasks survive (append-only file) |
| `hms-celery-worker` | Document pipeline, scheduled jobs (queue `celery`) | Restarted in 5 s; un-finished tasks are re-delivered (`acks_late`) |
| `hms-celery-llm` | Every LLM call, one at a time (queue `llm`) | Restarted in 5 s; queued documents wait in the AI queue |
| `hms-celery-beat` | Queues scheduled jobs | Restarted in 5 s; a missed tick runs on the next one |
| `hms-flower` | Dashboard only | Nothing else is affected |
| `hms-web` (optional) | Django via gunicorn | Restarted in 5 s |

## 1. First-time setup

On the EC2 instance, with the repo at `/opt/hms` (change with `--app-dir`):

```bash
cd /opt/hms
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env            # then fill it in — see section 2
venv/bin/python manage.py migrate
venv/bin/python manage.py createcachetable   # classifier / lab-extraction caches
venv/bin/python manage.py collectstatic --noinput

sudo bash deploy/install.sh                 # Redis + workers + beat + flower
# sudo bash deploy/install.sh --with-web   # also run Django under gunicorn
# sudo bash deploy/install.sh --no-redis   # broker is ElastiCache (section 6)
```

`install.sh` installs Redis (local-only, persistent, `noeviction`), writes the
systemd units, enables them, sets up log rotation and prints anything missing
from `.env`. Re-run it any time; it's idempotent.

## 2. Production `.env` keys for background jobs

```ini
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_UI_PROCESS_CONTROL=False      # systemd owns the processes; the admin page only monitors
CELERY_LOG_DIR=/opt/hms/logs

# LLM: the GPU server (section 7)
LLM_MODE=production
LLM_GATEWAY_URL=http://<gpu-server>:<port>/llm_api
DOC_PIPELINE_LLM_ALWAYS=True       # every upload gets an AI check (queued, one at a time)
```

Worker concurrency, queues and the Flower login are in `/etc/hms/celery.env`
(see `deploy/celery.env.example`).

## 3. Check it's healthy

```bash
systemctl status redis-server hms-celery-worker hms-celery-llm hms-celery-beat hms-flower
redis-cli ping                                   # PONG
venv/bin/celery -A atomwalk inspect ping         # worker replies "pong"
tail -f logs/celery-worker.log                   # or: journalctl -u hms-celery-worker -f
```

Platform admin → **Background Jobs** shows the worker and Beat as RUNNING
(heartbeat), the queue depth, what's running now and the task history.

Reboot test once: `sudo reboot`, wait, then re-run the checks — everything
should be up without logging in.

## 4. Deploying a new version

```bash
cd /opt/hms && git pull
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py migrate
venv/bin/python manage.py createcachetable
venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart hms-web hms-celery-worker hms-celery-llm hms-celery-beat
```

The worker restarts warmly: it stops taking new tasks, finishes the running
ones (up to 120 s), then restarts on the new code. Queued tasks wait in Redis.

## 5. Flower

It listens on `127.0.0.1:5555` only — task arguments are visible in it.

- From your laptop: `ssh -L 5555:127.0.0.1:5555 ubuntu@<server>` then open
  `http://localhost:5555`.
- To expose it through nginx instead, first set `FLOWER_BASIC_AUTH=user:strongpass`
  in `/etc/hms/celery.env`, restart `hms-flower`, and serve it over HTTPS only.

Never open ports 6379 or 5555 in the EC2 security group.

## 6. Managed Redis (ElastiCache / Valkey) instead of local Redis

Point `CELERY_BROKER_URL` at it (TLS: `rediss://…:6379/0?ssl_cert_reqs=required`),
run `sudo bash deploy/install.sh --no-redis`, and allow the EC2 security group
to reach the cluster on 6379. Redis restarts and patching are then AWS's job.

## 7. The LLM server (local ↔ production toggle)

```ini
LLM_MODE=production                              # local = Ollama settings, production = GPU gateway
LLM_GATEWAY_URL=http://<gpu-server>:<port>/llm_api  # POST /ask/, GET /status/
LLM_GATEWAY_TOKEN=                               # sent as Bearer token if the gateway needs one
LLM_GATEWAY_MAX_CHARS=12000                      # page text per prompt (gateway runs 32k context)
```

Every LLM request is queued: documents wait in the AI queue
(`shared_document.llm_status = queued`) and the `hms-celery-llm` worker sends
them to the gateway strictly one at a time, oldest first. If the GPU server
is down, nothing fails — the queue pauses and Beat's "Run the AI queue" job
(every minute) resumes it as soon as `GET /status/` answers. Uploads are
never blocked: the keyword rules file each document immediately and the
LLM's verdict updates it later (unless the patient already confirmed it).
Platform admin → Document Classifier shows which server is in use, whether
it's online, and the queue.

Other options if the GPU server isn't available:

- **Hosted API** (Groq, OpenAI, …): set `DOC_CLASSIFIER_LLM_BASE/_MODEL/_KEY`.
  Fast; document text leaves the server, so check this against your data-privacy obligations first.
- **Ollama on a GPU instance** (e.g. g5): point `DOC_CLASSIFIER_LLM_BASE` at it.
- **Rules only**: leave the LLM settings empty. Uncertain documents go to the
  patient's review step, which catches them anyway.

With `DOC_PIPELINE_LLM_ALWAYS=False` the LLM only sees documents the keyword
rules are unsure about.

## 8. Upload routing (small vs bulk)

- An upload of up to **3 files** (Background Jobs → Settings → "Sort instantly
  up to") is sorted inside the upload request — the patient sees the result
  immediately.
- A bigger upload is marked `bulk` and sorted by the **"Process bulk uploads"**
  scheduled job (every 2 min by default, **25 files per run**, oldest first),
  so a 200-file upload can't swamp the web server or the worker.
- The LLM check always follows separately on the `llm` queue.

## 9. Scaling

- More throughput on one box: raise `CELERY_CONCURRENCY` in `/etc/hms/celery.env`.
- More boxes: run `hms-celery-worker` on each, all pointing at the same broker.
  Run `hms-celery-beat` on **one** server only.
- Separate queues (e.g. `documents` for uploads, `jobs` for scheduled work):
  set `CELERY_QUEUES` per worker and route tasks to them.

## 10. Mobile upload-and-extract (patient app)

The patient app's upload flow (`/api/v1/portal/documents/extract/…`,
`apps/registry/tasks.py`) follows the same design as My Reports (section 8) and runs on this
same Celery setup, on the default `celery` queue — no extra service. It only reads the text
(no classifying or filing yet).

- **Instant / bulk:** the same "Sort instantly up to" setting (Background Jobs → Settings,
  default 3) decides. Up to that many files are read inside the request. Bigger uploads go to S3
  first; **Start only marks the batch `queued` in the database** and the scheduled job
  **"Process mobile bulk uploads"** (every minute) reads the oldest queued files, at most
  "bulk_batch_limit" (default 25) per run, one after another. The app reads the limit from
  `GET /portal/documents/extract/config/`.
- **If Celery isn't running** (no fresh worker or Beat heartbeat) and "inline_fallback" is on,
  Start reads the batch inside the web server, exactly like My Reports bulk uploads.
- **Production must use Redis** (`CELERY_BROKER_URL=redis://127.0.0.1:6379/0`) for the queue
  that carries the scheduled jobs. Start itself no longer depends on Redis being up.
- **Memory:** every concurrent worker slot loads its own OCR model (~135 MB idle,
  ~424 MB while reading). On a 2 GB server keep `CELERY_CONCURRENCY=1` in
  `/etc/hms/celery.env`; the 2 in the example is for an 8 GB `t3.large`. Only one run reads
  files at a time (a database lock), so overlapping runs or the fallback never add up.
- **Scheduled jobs:** migration `0061` adds "Process mobile bulk uploads" (every minute) and
  "Recover mobile uploads" (every 5 minutes; closes stalled batches and fails files stuck in
  processing). Both are editable on Background Jobs. Beat must be running
  (`hms-celery-beat`).
- The files it reads are kept in S3 under `extraction-files/` — never put an expiry
  rule on that prefix.
- **Upgrading a database that already has the old-numbered mobile migrations**
  (0045–0051 from before the merge; they are now 0054–0060): delete those 7 names from
  `django_migrations`, run `migrate registry 0053`, then
  `migrate registry 0060_extractionitem_dispatch_tracking --fake`, then `migrate`.
  A fresh database needs only `migrate`.
