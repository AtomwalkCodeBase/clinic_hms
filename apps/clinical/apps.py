from django.apps import AppConfig


class ClinicalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clinical"

    # ready()'s signal-registration hook was removed along with this app's
    # models (HMS-07c-1) — see signals.py.
