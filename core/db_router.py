"""
core/db_router.py
-----------------
TenantDatabaseRouter — routes every ORM query to the correct database.

Database alias convention (configured in settings.DATABASES):
  "default"       → Registry DB (shared: patient_identity, tenant, subscription, shared_* HIE tables)
  "<db_name>"     → Per-hospital PostgreSQL DB (e.g. "apollo_delhi", "max_mumbai")

The tenant's db_name is injected into the request by JWTTenantMiddleware and
stored on the thread-local _thread_local.db_alias.

Rules:
  1. Registry models → always "default"
  2. All other models → thread-local tenant alias or "default" as fallback

Registry apps are listed in REGISTRY_APPS. Any model belonging to those apps
goes to "default". Everything else goes to the current tenant DB.
"""

import threading

_thread_local = threading.local()

# Apps whose models live in the shared Registry DB.
REGISTRY_APPS = frozenset(
    [
        "tenants",         # Tenant, Subscription, NextNumber (registry-side)
        "registry",        # PatientIdentity, shared HIE tables
        "auth",            # Django's built-in auth (registry-side users)
        "contenttypes",    # Django framework
        "sessions",        # Django sessions
        "admin",           # Django admin
    ]
)


def set_tenant_db(db_alias: str | None) -> None:
    """
    Called by JWTTenantMiddleware after JWT decode.
    Sets the DB alias for the current thread.
    """
    _thread_local.db_alias = db_alias


def get_tenant_db() -> str:
    """Returns the current thread's tenant DB alias, defaulting to 'default'."""
    return getattr(_thread_local, "db_alias", "default") or "default"


class TenantDatabaseRouter:
    """
    A database router that separates registry data from tenant data.
    Register in settings.py:
        DATABASE_ROUTERS = ["core.db_router.TenantDatabaseRouter"]
    """

    def _is_registry_model(self, model) -> bool:
        return model._meta.app_label in REGISTRY_APPS

    def db_for_read(self, model, **hints):
        if self._is_registry_model(model):
            return "default"
        return get_tenant_db()

    def db_for_write(self, model, **hints):
        if self._is_registry_model(model):
            return "default"
        return get_tenant_db()

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations only within the same database.
        Cross-DB relations (registry ↔ tenant) are intentionally prohibited
        at the ORM level — use IDs and separate queries instead.
        """
        db1 = "default" if obj1._meta.app_label in REGISTRY_APPS else get_tenant_db()
        db2 = "default" if obj2._meta.app_label in REGISTRY_APPS else get_tenant_db()
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Registry apps only migrate on "default".
        Tenant apps only migrate on non-default aliases.
        """
        if app_label in REGISTRY_APPS:
            return db == "default"
        return db != "default"
