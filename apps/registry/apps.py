import os
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class RegistryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.registry"
    label = "registry"
    verbose_name = "Registry"

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(_bootstrap_platform_admin, sender=self)


def _bootstrap_platform_admin(sender, **kwargs):
    """
    After migrations run, ensure a Django superuser exists for the admin panel.

    Required env vars:
        DJANGO_SUPERUSER_USERNAME   (default: 'admin')
        DJANGO_SUPERUSER_EMAIL
        DJANGO_SUPERUSER_PASSWORD
    """
    try:
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin").strip()
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()

        if not password:
            return  # Not configured — skip silently

        from django.contrib.auth import get_user_model
        User = get_user_model()

        if User.objects.filter(is_superuser=True).exists():
            return  # Already have a superuser

        User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
        )
        logger.info("Platform superuser bootstrapped: %s", username)

    except Exception as e:
        logger.warning("Platform admin bootstrap skipped: %s", e)
