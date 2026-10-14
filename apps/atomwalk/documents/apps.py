from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.atomwalk.documents"
    label = "documents"
    verbose_name = "Documents"
    database = "atomwalk"    # which database the tables of this app live in (read by core/db_router.py)
