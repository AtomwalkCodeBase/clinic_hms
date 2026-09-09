"""
apps/tasks/urls.py
---------------------
Retired (v7 table-count redesign) — this app is no longer mounted in
atomwalk/urls.py at all (see the comment there). Kept as an empty
urlpatterns list rather than deleted outright in case anything still does
`include("apps.tasks.urls")` during the transition; safe to delete this
file entirely once confirmed nothing does.
"""
urlpatterns = []
