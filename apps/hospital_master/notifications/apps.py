from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_master.notifications"
    label = "notifications"
    verbose_name = "Notifications"
    database = "hospital"    # which database the tables of this app live in (read by core/db_router.py)
