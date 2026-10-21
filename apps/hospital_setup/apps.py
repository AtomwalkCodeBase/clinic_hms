import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


def _sync_roles(sender, using, **kwargs):
    if using == "default":
        return
    from apps.hospital_setup.rbac import sync_roles_and_permissions
    try:
        sync_roles_and_permissions(using)
    except Exception:
        logger.warning("Roles and permissions were not synced for %s", using, exc_info=True)


class HospitalSetupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hospital_setup"
    label = "hospital_setup"
    verbose_name = "Hospital set-up"
    database = "hospital"

    def ready(self):
        post_migrate.connect(_sync_roles, sender=self)

