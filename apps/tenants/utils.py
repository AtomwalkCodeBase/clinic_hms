"""
Tenant utility functions:
  - AWPID generation (atomic, collision-safe)
  - DB provisioning helpers
"""

import re
import logging
from datetime import date
from django.db import connections, transaction
from django.conf import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tenant DB Provisioning
#
# Note: AWPID generation lives in core/utils/awpid.py (generate_unique_awpid,
# format AWPID-YYYYMMDD-XXXXXXXX) — that's the one actually called from
# apps/patients/services.py. An earlier, differently-formatted AWPID
# generator (AWP-YYYYMMDD-NNNNNN) used to live in this file too; it had no
# callers anywhere in the codebase and was removed to avoid two competing
# ID formats existing side by side.
# ─────────────────────────────────────────────────────────────────────────────

def build_tenant_db_name(slug: str) -> str:
    """Convert slug to a safe PostgreSQL DB name."""
    safe = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    return f"aw_tenant_{safe}"


def _make_db_config(name: str) -> dict:
    """
    Build a fully-normalised database config dict.
    Manually applies all defaults that Django's DatabaseWrapper accesses
    via direct key lookup (not .get()), mirroring what ConnectionHandler
    .ensure_defaults() does internally in Django 4.x.
    """
    t = settings.TENANT_DB_CONFIG_TEMPLATE
    return {
        "ENGINE":           t.get("ENGINE", "django.db.backends.postgresql"),
        "NAME":             name,
        "USER":             t.get("USER", ""),
        "PASSWORD":         t.get("PASSWORD", ""),
        "HOST":             t.get("HOST", "localhost"),
        "PORT":             t.get("PORT", "5432"),
        "CONN_MAX_AGE":     t.get("CONN_MAX_AGE", 0),
        "CONN_HEALTH_CHECKS": t.get("CONN_HEALTH_CHECKS", False),
        "TIME_ZONE":        t.get("TIME_ZONE", None),
        "OPTIONS":          t.get("OPTIONS", {}),
        "AUTOCOMMIT":       t.get("AUTOCOMMIT", True),
        "ATOMIC_REQUESTS":  t.get("ATOMIC_REQUESTS", False),
        "TEST":             t.get("TEST", {}),
    }


def create_tenant_database(db_name: str):
    """
    Create a new PostgreSQL database for a tenant.
    Must be called outside any transaction block.

    Always starts from a guaranteed-empty database: if a database with this
    name already exists, it is dropped and recreated rather than reused.
    A pre-existing DB here is never a legitimate "already provisioned"
    tenant (this function only runs as part of provisioning a brand-new
    Tenant row) — it's leftover cruft from an earlier attempt that failed
    partway through migrations, e.g. before drop_tenant_database() cleanup
    existed, or that crashed in a way the caller's exception handler
    couldn't fully unwind. Reusing such a DB silently is dangerous: it
    would already have SOME migrations applied and recorded, and running
    the full migrate against that half-migrated state is exactly how
    errors like "Related model 'app.model' cannot be resolved" happen —
    Django applies whatever remaining migrations it thinks are pending,
    but the historical state they expect doesn't match what's actually in
    the database. Guaranteeing a clean slate here removes that whole class
    of bug.
    """
    sys_db_config = _make_db_config("postgres")

    conn_alias = f"_sys_{db_name}"
    settings.DATABASES[conn_alias] = sys_db_config

    try:
        conn = connections[conn_alias]
        conn.ensure_connection()
        # autocommit required for CREATE DATABASE / DROP DATABASE
        conn.connection.autocommit = True
        with conn.connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", [db_name]
            )
            if cursor.fetchone():
                logger.warning(
                    "Tenant database already exists: %s — dropping stale "
                    "copy before recreating (leftover from a prior failed "
                    "provisioning attempt).",
                    db_name,
                )
                # Terminate any lingering connections first, same as
                # drop_tenant_database() — DROP DATABASE fails outright
                # while anything still holds a connection open to it.
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()", [db_name]
                )
                cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            cursor.execute(f'CREATE DATABASE "{db_name}"')
            logger.info("Created tenant database: %s", db_name)
    finally:
        connections[conn_alias].close()
        del settings.DATABASES[conn_alias]


def drop_tenant_database(db_name: str):
    """
    Drop a tenant's PostgreSQL database — used to clean up after a failed
    provisioning attempt (e.g. create_tenant_database() succeeded but
    run_tenant_migrations() then failed partway through, leaving a real but
    half-migrated database behind). Best-effort: logs and swallows errors
    rather than raising, since this itself runs from inside another
    exception handler and must not mask the original failure.
    """
    sys_db_config = _make_db_config("postgres")
    conn_alias = f"_sys_drop_{db_name}"
    settings.DATABASES[conn_alias] = sys_db_config

    try:
        conn = connections[conn_alias]
        conn.ensure_connection()
        conn.connection.autocommit = True
        with conn.connection.cursor() as cursor:
            # Terminate any lingering connections to the target DB first —
            # DROP DATABASE fails outright if anything (even this same
            # process's own tenant-DB alias, if migrate registered one)
            # still holds a connection open to it.
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()", [db_name]
            )
            cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            logger.info("Dropped tenant database: %s", db_name)
    except Exception as exc:
        logger.error("Could not drop tenant database %s during cleanup: %s", db_name, exc)
    finally:
        if db_name in settings.DATABASES:
            try:
                connections[db_name].close()
            except Exception:
                pass
            del settings.DATABASES[db_name]
        connections[conn_alias].close()
        del settings.DATABASES[conn_alias]


def run_tenant_migrations(db_name: str):
    """
    Run Django migrations for tenant apps against the new tenant DB.
    Called after create_tenant_database().
    """
    from django.core.management import call_command

    # Ensure DB is registered with all required keys
    if db_name not in settings.DATABASES:
        settings.DATABASES[db_name] = _make_db_config(db_name)

    # Run all migrations against the tenant DB.
    # The DB router's allow_migrate returns True for non-registry apps on non-default DBs,
    # so this will only apply tenant-app migrations.
    call_command(
        "migrate",
        database=db_name,
        verbosity=1,
        interactive=False,
    )
    logger.info("Migrations complete for tenant DB: %s", db_name)
