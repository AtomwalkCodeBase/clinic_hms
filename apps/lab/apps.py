from django.apps import AppConfig


class LabConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.lab"
    label = "lab"
    verbose_name = "Laboratory"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)

    def ready(self):
        import apps.lab.signals  # noqa: F401 — registers signal handlers
