from django.urls import path
from .consult_pad_views import ConsultPadView

# One path, both verbs — GET fetches the patient header for the phone
# screen, POST files the finished note. Deliberately its own top-level
# prefix (see atomwalk/urls.py), not under /portal/ or /patients/, since
# those imply a session; this endpoint is intentionally public.
urlpatterns = [
    path("<str:token>/", ConsultPadView.as_view(), name="consult-pad"),
]
