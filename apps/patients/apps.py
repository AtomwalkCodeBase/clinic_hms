from django.apps import AppConfig


class PatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.patients"
    label = "patients"
    verbose_name = "Patients (shared)"
    database = "atomwalk"    # which database the tables of this app live in (read by core/db_router.py)
