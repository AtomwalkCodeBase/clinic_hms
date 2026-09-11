# My Reports — deploy runbook

Segregation of patient documents into **Prescriptions** and **Lab reports**,
with QR verification for hospital-issued documents and OCR/keyword
classification for everything else. Registry-DB feature; nothing per-tenant.

## 1. Dependencies

**Python** (already in `requirements.txt`) — `pip install -r requirements.txt`:

```
pypdf  rapidocr-onnxruntime  pymupdf  pytesseract
```

`rapidocr-onnxruntime` is the primary OCR engine — PaddleOCR's PP-OCR
detection + recognition models on ONNX Runtime. **Pip-only, CPU, no system
package.** It pulls `onnxruntime`, `opencv-python-headless` and `numpy`
(~200 MB total incl. bundled models). `pymupdf` rasterises scanned /
image-only PDFs so they can be OCR'd. First OCR call in each worker loads the
models (~1–2 s); cached thereafter.

Engine is `settings.DOC_OCR_ENGINE` (`.env`: `DOC_OCR_ENGINE`), default
`auto` = RapidOCR if importable, else Tesseract. Force with `rapidocr` /
`paddleocr` / `tesseract` / `none`.

**Tesseract is now only the fallback.** Install it only if you want that
path (or set `DOC_OCR_ENGINE=tesseract`):

```bash
sudo apt-get install -y tesseract-ocr
```

With no OCR engine at all, uploads still work — a no-QR document with no PDF
text layer lands in the patient's **review tray** for a one-tap
classification instead of being auto-filed. A genuinely blurry photo is
rejected up front with a "retake" message regardless of engine.

### Classification fallbacks (LLM + vision)

Three layers, cheapest first, each only touching what the previous couldn't
settle:

1. **deterministic keyword pass** — free, instant, no network. Handles the bulk.
2. **text LLM** on the OCR text — rescues garbled / sparse OCR. `DOC_CLASSIFIER_LLM_*`
   (default Groq `openai/gpt-oss-20b`; blank key + no `GROQ_API_KEY` disables it).
3. **vision LLM** on the page image — last automated fallback for bad OCR /
   odd layouts / cross-layer disagreement. **OFF until `DOC_CLASSIFIER_VISION_MODEL`
   is set** (Groq has no VLM — point it at a local vLLM/Ollama VLM or OpenRouter).

Every layer is a labeller (kind / panel / date, never test values). A
confident keyword verdict is never overridden by an LLM; genuine disagreement
goes to the patient. Answers are cached (see §3) so a re-upload / backfill /
retry never pays the provider again.

## 2. Environment

Add to the production `.env` (see `.env.example`):

```ini
# recommended; falls back to SECRET_KEY if blank
DOC_QR_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">

DOC_OCR_ENGINE=auto            # rapidocr -> tesseract; or force one / "none"
DOC_CLASSIFIER_LLM_KEY=        # blank -> uses GROQ_API_KEY
DOC_CLASSIFIER_VISION_MODEL=   # blank -> vision layer stays OFF
```

S3 must already be configured (`AWS_S3_BUCKET`, `AWS_S3_REGION`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`). Every report is stored as a
PDF under **`patient-documents/<name>-<awpid>/patient-document-<hex>.pdf`** —
one prefix per patient. The database is the source of truth for a document's
type; the S3 path is only for browsing.

## 3. Migrate

```bash
python manage.py migrate registry     # 0027 pipeline … 0031 categories, 0032 cache
```

Schema-only (every new column is nullable or defaulted). Existing rows get
`review_state="filed"`, so nothing disappears from any patient's list.
**`0032_doc_classify_cache`** runs `createcachetable` for the `doc_classify`
cache (persistent, worker-shared store of the LLM/vision answers) — idempotent,
re-runnable. If it's ever skipped, run it by hand:

```bash
python manage.py createcachetable doc_classify_cache --database default
```

Reversible: `python manage.py migrate registry 0026`.

## 4. Backfill — one-time, two commands

### 4a. Mirror existing prescriptions & lab reports into the vault

Prescriptions live in `opd.Prescription` (tenant DBs) and lab reports in
`lab.LabReport`; neither was ever copied into the `registry.SharedDocument`
vault that My Reports reads. New ones now mirror automatically (prescriptions
on encounter sign, lab reports on `deliver()`). This catches up everything
that predates that:

```bash
python manage.py backfill_documents_from_records --dry-run           # preview counts
python manage.py backfill_documents_from_records --limit 500          # in chunks
python manage.py backfill_documents_from_records                      # finish
```

Idempotent (skips anything whose `source_ref` already exists). Each mirrored
row is `verification_status="verified"`, `review_state="filed"` — the type is
known, so no classification runs. `--kind prescription|lab_report` and
`--tenant <db_name>` narrow it.

### 4b. Re-classify old patient uploads

Patient uploads previously filed as `other` / `scan`:

```bash
python manage.py backfill_document_classification --dry-run          # preview counts
python manage.py backfill_document_classification --limit 1000        # process in chunks
python manage.py backfill_document_classification                     # finish the rest
```

Idempotent and resumable — it only touches rows where
`classification_method = ""`. Flags:

| flag | effect |
|---|---|
| `--dry-run` | report only, write nothing |
| `--limit N` | cap this run; re-run to continue |
| `--awpid <id>` | one patient only (testing) |
| `--reclassify` | also re-run on rows already typed prescription/lab_report |
| `--unsorted-low-confidence` | send unsure rows to the Unsorted tray instead of leaving them |

## 5. The bulk-upload drain

Folder / multi-file uploads (`POST /api/v1/portal/documents/batch/`) stage
files straight to S3 and are processed out of band. Two ways to run the drain
— **prefer the daemon**: the OCR model loads once (~3–4 s) and stays warm,
instead of every cron process paying that cold start.

**Daemon (recommended)** — a systemd unit:

```ini
# /etc/systemd/system/hms-doc-batches.service
[Unit]
Description=HMS My Reports — document batch drain
After=network.target postgresql.service

[Service]
Type=simple
User=hms
WorkingDirectory=/srv/hms/clinic_hms
ExecStart=/srv/hms/venv/bin/python manage.py process_document_batches --forever --interval 5
Restart=always
RestartSec=5
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now hms-doc-batches
journalctl -u hms-doc-batches -f
```

It drains, sleeps `--interval` seconds, repeats; SIGTERM lets the in-flight
item finish and then exits cleanly.

**Cron (simpler, works fine at low volume)** — still supported unchanged:

```cron
* * * * *  cd /srv/hms/clinic_hms && /srv/hms/venv/bin/python manage.py process_document_batches --limit 60 >> /var/log/hms/doc_batches.log 2>&1
```

Either way a **Postgres advisory lock** serialises drains — a cron tick that
fires while the previous run is still going (a big photo batch takes minutes)
no-ops instead of racing. `--limit N` bounds one pass; the rest is picked up
next pass. Use one **or** the other, not both.

## 6. Verify on staging

1. `python manage.py check` — clean.
2. Upload one external lab-report PDF via the portal → lands in **Lab reports**
   (or the review tray if no OCR engine is installed and the PDF has no text
   layer). `python -c "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','atomwalk.settings.development');django.setup();from core import ocr;print(ocr.available())"`
   should print `rapidocr`.
3. Generate a prescription PDF → the header shows the "Scan to save in My
   Reports" QR.
4. Re-upload a photo of that prescription with the decoded `qr_token` in the
   POST → filed under **Prescriptions**, `verification_status = "verified"`,
   no duplicate created on a second attempt.
5. Upload a folder → `documents/batch/` returns presigned URLs; after
   `.../process/` the cron drain fills the summary counters.

## Rollback

```bash
python manage.py migrate registry 0026
git revert <this commit>
```

The migration reverse drops the new columns/tables; no data loss for
pre-existing document rows (the added columns held only pipeline metadata).
