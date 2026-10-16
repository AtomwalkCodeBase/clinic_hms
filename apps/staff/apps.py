from django.apps import AppConfig


class StaffConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.staff"
    label = "staff"
    verbose_name = "Staff"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
