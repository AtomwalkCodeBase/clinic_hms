from django.apps import AppConfig


class PatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.patients"

    def ready(self):
        import apps.patients.signals  # noqa: F401 — registers signal handlers
