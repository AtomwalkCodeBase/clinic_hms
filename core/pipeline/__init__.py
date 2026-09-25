"""
core/pipeline — what happens to a My Reports upload, one stage per file.

Read in this order (it's the order a document travels):

  1. routing.py     Small upload (≤ 3 files) → sorted right now, inside the
                    upload request. Bigger upload → "bulk", sorted later by the
                    periodic "Process bulk uploads" Celery job, a batch per run.

  2. processing.py  process_document(): the steps for ONE file —
                      read text (PDF text layer, else OCR)
                      → keyword rules pick the type
                      → file it (filing.py) → convert to PDF
                      → if an AI check is wanted, put it in the AI queue.

  3. filing.py      Turns a classifier verdict into database fields
                    (doc_type, review state, what the patient still has to confirm).

  4. llm_queue.py   The AI queue. One document at a time, oldest first, to the
                    LLM (local Ollama or the production GPU server — LLM_MODE).
                    The verdict updates the document unless the patient has
                    already confirmed it. Waits while the LLM server is down.

  5. log.py         One readable line per step for every document, from the web
                    server and the Celery workers alike → logs/doc-pipeline.log
                    (Background Jobs → "Pipeline log").

Who calls what:
  upload API (apps/patients/portal_views.py)  → routing.route_for, processing.process_document
  Celery tasks (core/tasks.py)                → routing.process_bulk, llm_queue.drain_llm_queue
  classifier (core/doc_classifier.py …)       ← called by processing / llm_queue
"""
