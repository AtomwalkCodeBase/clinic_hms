# My Reports — deploy runbook

Segregation of patient documents into **Prescriptions** and **Lab reports**,
with QR verification for hospital-issued documents and OCR/keyword
classification for everything else. Registry-DB feature; nothing per-tenant.

## 1. Dependencies

**Python** (already in `requirements.txt`):

```
pypdf pytesseract
```

**System package** (the OCR engine — Debian / Ubuntu host):

```bash
sudo apt-get install -y tesseract-ocr
```

Optional but recommended. Without it, uploads still work — a document with
no QR and no PDF text layer simply lands in the patient's **Unsorted** tray
for a one-tap classification instead of being auto-filed.

## 2. Environment

Add to the production `.env` (see `.env.example`):

```ini
# recommended; falls back to SECRET_KEY if blank
DOC_QR_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">
```

S3 must already be configured (`AWS_S3_BUCKET`, `AWS_S3_REGION`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`). Every report is stored as a
PDF under **`patient-documents/<name>-<awpid>/patient-document-<hex>.pdf`** —
one prefix per patient. The database is the source of truth for a document's
type; the S3 path is only for browsing.

## 3. Migrate

```bash
python manage.py migrate registry     # applies 0027_my_reports_pipeline
```

Schema-only (every new column is nullable or defaulted). Existing rows get
`review_state="filed"`, so nothing disappears from any patient's list.
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

## 5. Cron — the bulk-upload drain

Folder / multi-file uploads (`POST /api/v1/portal/documents/batch/`) stage
files straight to S3 and are processed out of band. Add one cron entry:

```cron
* * * * *  cd /srv/hms/clinic_hms && /srv/hms/venv/bin/python manage.py process_document_batches >> /var/log/hms/doc_batches.log 2>&1
```

Same pattern as `generate_reminders`. It exits immediately when there is
nothing to do. `--limit N` caps items per run if the queue gets large.

## 6. Verify on staging

1. `python manage.py check` — clean.
2. Upload one external lab-report PDF via the portal → lands in **Lab reports**
   (or Unsorted if tesseract is absent and the PDF has no text layer).
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
