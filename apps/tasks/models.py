"""
apps/tasks/models.py
---------------------
Retired (v7 table-count redesign). This app used to hold Task/TaskAssignment
— a complete, working staff-coordination API (GET/POST /api/v1/tasks/,
POST .../complete/) — but had zero frontend consumer anywhere in
frontend/src, re-confirmed by grep before removal (API_ENDPOINTS.TASKS.*
was defined in frontend/src/config/api.config.js but never imported by any
page or component; the nurse-facing "Tasks" page reads from
API_ENDPOINTS.OPD.MONITORING and API_ENDPOINTS.LAB.* instead — an
unrelated endpoint that happens to share the word "task").

The app stays registered in INSTALLED_APPS (empty of models is valid) so
its migration history remains resolvable — see
apps/tasks/migrations/0003_retire_tasks.py for the table drops.
"""
