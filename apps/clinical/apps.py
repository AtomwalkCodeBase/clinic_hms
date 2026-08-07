from django.apps import AppConfig


class ClinicalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.clinical"

    def ready(self):
        import apps.clinical.signals  # noqa: F401 — registers signal handlers
