from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenants"
    label = "tenants"
    verbose_name = "Tenants"

    def ready(self):
        """
        Auto-register all tenant DBs at startup so they're available everywhere:
        shell, management commands, Celery workers — not just HTTP requests.
        The JWT middleware still handles on-demand registration for any tenant
        added after the process started.
        """
        self._register_tenant_databases()

    @staticmethod
    def _register_tenant_databases():
        try:
            from apps.tenants.utils import ensure_tenant_db
            from apps.tenants.models import Tenant

            tenants = Tenant.objects.using("default").filter(is_active=True).values("db_name")
            for row in tenants:
                db_name = row["db_name"]
                if db_name:
                    ensure_tenant_db(db_name)
        except Exception:
            # Table may not exist yet during first migrate — silently skip
            pass
