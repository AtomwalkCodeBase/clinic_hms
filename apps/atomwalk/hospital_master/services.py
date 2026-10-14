"""Hospital database set-up, plan limits and feature defaults."""
import re
import logging
import threading
from django.db import connections
from django.conf import settings
from apps.hospital_master.staff.models import StaffUser
from apps.hospital_master.facility.models import Branch


logger = logging.getLogger(__name__)
# ─────────────────────────────────────────────────────────────────────────────
# Hospital DB Provisioning
#
# Note: AWPID generation lives in core/utils/awpid.py (generate_unique_awpid,
# format AWPID-YYYYMMDD-XXXXXXXX) — that's the one actually called from
# apps/hospital_patients/services.py. An earlier, differently-formatted AWPID
# generator (AWP-YYYYMMDD-NNNNNN) used to live in this file too; it had no
# callers anywhere in the codebase and was removed to avoid two competing
# ID formats existing side by side.
# ─────────────────────────────────────────────────────────────────────────────

def build_hospital_db_name(slug: str) -> str:
    """Convert slug to a safe PostgreSQL DB name."""
    safe = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    return f"aw_hospital_{safe}"
def _make_db_config(name: str) -> dict:
    """
    Build a fully-normalised database config dict.
    Manually applies all defaults that Django's DatabaseWrapper accesses
    via direct key lookup (not .get()), mirroring what ConnectionHandler
    .ensure_defaults() does internally in Django 4.x.
    """
    t = settings.HOSPITAL_DB_CONFIG_TEMPLATE
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
_alias_lock = threading.Lock()
def ensure_hospital_db(db_name):
    """
    Make sure `db_name` is a configured Django database alias, registering it from the
    hospital template if it is not. The one place that mutates settings.DATABASES — the
    request path (JWT middleware, login, OTP, portal, compliance), Celery workers and the
    management commands all call this instead of repeating the snippet. Idempotent and
    guarded by a lock so two threads registering the same hospital can't race.
    """
    if db_name in settings.DATABASES:
        return
    with _alias_lock:
        if db_name not in settings.DATABASES:
            settings.DATABASES[db_name] = _make_db_config(db_name)
def resolve_source_hospital_id(db_alias) -> int:
    """
    Atomwalk id of the hospital whose database `db_alias` is — the value the write-through
    code stamps into `source_hospital_id`. For code that has no request to read
    `request.hospital_id` from (model signals, helpers).

    core.middleware only sets the DB alias on the thread-local, never a hospital id, so the
    old `getattr(_thread_local, "hospital_id", 0)` was always 0 outside the seed commands
    (which do set it, and still win here). 0 means "unknown".
    """
    from core.db_router import _thread_local
    from apps.atomwalk.hospital_master.models import Hospital

    explicit = getattr(_thread_local, "hospital_id", 0)
    if explicit:
        return explicit
    if not db_alias:
        return 0
    return Hospital.objects.using("default").filter(db_name=db_alias).values_list("id", flat=True).first() or 0
def create_hospital_database(db_name: str):
    """
    Create a new PostgreSQL database for a hospital.
    Must be called outside any transaction block.

    Always starts from a guaranteed-empty database: if a database with this
    name already exists, it is dropped and recreated rather than reused.
    A pre-existing DB here is never a legitimate "already provisioned"
    hospital (this function only runs as part of provisioning a brand-new
    Hospital row) — it's leftover cruft from an earlier attempt that failed
    partway through migrations, e.g. before drop_hospital_database() cleanup
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
                    "Hospital database already exists: %s — dropping stale "
                    "copy before recreating (leftover from a prior failed "
                    "provisioning attempt).",
                    db_name,
                )
                # Terminate any lingering connections first, same as
                # drop_hospital_database() — DROP DATABASE fails outright
                # while anything still holds a connection open to it.
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()", [db_name]
                )
                cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            cursor.execute(f'CREATE DATABASE "{db_name}"')
            logger.info("Created hospital database: %s", db_name)
    finally:
        connections[conn_alias].close()
        del settings.DATABASES[conn_alias]
def drop_hospital_database(db_name: str):
    """
    Drop a hospital's PostgreSQL database — used to clean up after a failed
    provisioning attempt (e.g. create_hospital_database() succeeded but
    run_hospital_migrations() then failed partway through, leaving a real but
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
            # process's own hospital-DB alias, if migrate registered one)
            # still holds a connection open to it.
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()", [db_name]
            )
            cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
            logger.info("Dropped hospital database: %s", db_name)
    except Exception as exc:
        logger.error("Could not drop hospital database %s during cleanup: %s", db_name, exc)
    finally:
        if db_name in settings.DATABASES:
            try:
                connections[db_name].close()
            except Exception:
                pass
            del settings.DATABASES[db_name]
        connections[conn_alias].close()
        del settings.DATABASES[conn_alias]
def run_hospital_migrations(db_name: str):
    """
    Run Django migrations for hospital apps against the new hospital DB.
    Called after create_hospital_database().
    """
    from django.core.management import call_command

    # Ensure DB is registered with all required keys
    ensure_hospital_db(db_name)

    # Run all migrations against the hospital DB.
    # The DB router's allow_migrate returns True for non-atomwalk apps on non-default DBs,
    # so this will only apply hospital-app migrations.
    call_command(
        "migrate",
        database=db_name,
        verbosity=1,
        interactive=False,
    )
    logger.info("Migrations complete for hospital DB: %s", db_name)


logger = logging.getLogger(__name__)
# Roles counted against max_staff. Doctors are deliberately excluded here —
# they're counted against max_doctors instead (see check_limit below).
_NON_DOCTOR_ROLES = ["hospital_admin", "nurse", "front_desk", "lab_tech", "pharmacist"]
LIMIT_LABELS = {
    "doctors":  "doctor",
    "branches": "branch",
    "staff":    "staff member",
}
def get_usage_counts(db_name):
    """Live counts from one hospital's own database: {doctors, branches, staff}."""
    doctors = StaffUser.objects.using(db_name).filter(role="doctor", is_active=True).count()
    branches = Branch.objects.using(db_name).filter(is_active=True).count()
    staff = StaffUser.objects.using(db_name).filter(
        role__in=_NON_DOCTOR_ROLES, is_active=True
    ).count()

    # Custom-role staff (a hospital-defined Role — see apps.hospital_master.staff.rbac) count
    # against whichever bucket their acts_as implies. "doctor" wins if
    # present: one login = one hire, so a solo-clinic role that acts as
    # doctor+nurse+front_desk only consumes 1 doctor slot, not a doctor slot
    # AND a staff slot for the same person — matching how a literal doctor
    # already counts as exactly 1 regardless of how many things they do.
    # Small in-Python pass rather than a JSONField query since this list is
    # normally empty/tiny (custom roles are an enterprise add-on).
    custom_staff = StaffUser.objects.using(db_name).filter(
        role="custom", is_active=True
    ).select_related("custom_role")
    for cs in custom_staff:
        acts_as = set((cs.custom_role.acts_as if cs.custom_role else []) or [])
        if "doctor" in acts_as:
            doctors += 1
        elif acts_as & set(_NON_DOCTOR_ROLES):
            staff += 1

    return {"doctors": doctors, "branches": branches, "staff": staff}
class LimitCheckFailed(Exception):
    """Raised by check_limit() — carries a user-facing message and HTTP status."""
    def __init__(self, message, status=403):
        super().__init__(message)
        self.message = message
        self.status = status
def check_limit(hospital, db_name, resource, increment=1):
    """
    Raises LimitCheckFailed if adding `increment` more of `resource`
    ("doctors" | "branches" | "staff") would exceed the hospital's
    subscription limit. Returns None (silently) if within limits.

    Fails CLOSED: any error resolving the subscription or counting current
    usage blocks the request (status=503, retryable) instead of allowing
    it through — a hard cap that can be silently bypassed by an unrelated
    DB error isn't actually a hard cap.
    """
    from apps.atomwalk.hospital_master.models import Subscription

    try:
        sub = Subscription.objects.using("default").get(hospital=hospital)
    except Subscription.DoesNotExist:
        logger.error("check_limit: no Subscription for hospital_id=%s", hospital.id)
        raise LimitCheckFailed(
            "Unable to verify your plan limits right now. Please try again shortly.",
            status=503,
        )

    limit_field = {"doctors": "max_doctors", "branches": "max_branches", "staff": "max_staff"}[resource]
    limit = getattr(sub, limit_field)
    if limit <= 0:
        return  # 0 = unlimited on this tier

    try:
        usage = get_usage_counts(db_name)
    except Exception as exc:
        logger.error("check_limit: usage count failed for %s (%s): %s", db_name, resource, exc)
        raise LimitCheckFailed(
            "Unable to verify your current usage right now. Please try again shortly.",
            status=503,
        )

    current = usage[resource]
    if current + increment > limit:
        label = LIMIT_LABELS[resource]
        plural = "" if limit == 1 else "s"
        raise LimitCheckFailed(
            f"{label.capitalize()} limit reached ({limit} {label}{plural} allowed on the "
            f"{sub.license_tier} plan). Please upgrade your plan to add more.",
            status=403,
        )


TIER_FEATURE_DEFAULTS = {
    "starter": {
        "feat_lab": False, "feat_pharmacy": False, "feat_whatsapp": False,
        "feat_multi_branch": False, "feat_ai_voice": False, "feat_patient_app": False,
        "feat_analytics": False, "feat_video": False, "feat_face_recog": False,
        "feat_custom_roles": False,
        "max_doctors": 3, "max_branches": 1, "max_staff": 5,
    },
    "growth": {
        "feat_lab": True, "feat_pharmacy": True, "feat_whatsapp": True,
        "feat_multi_branch": False, "feat_ai_voice": False, "feat_patient_app": False,
        "feat_analytics": False, "feat_video": False, "feat_face_recog": False,
        "feat_custom_roles": False,
        "max_doctors": 10, "max_branches": 1, "max_staff": 15,
    },
    "pro": {
        "feat_lab": True, "feat_pharmacy": True, "feat_whatsapp": True,
        "feat_multi_branch": True, "feat_ai_voice": True, "feat_patient_app": True,
        "feat_analytics": True, "feat_video": False, "feat_face_recog": False,
        "feat_custom_roles": False,
        "max_doctors": 50, "max_branches": 5, "max_staff": 75,
    },
    "enterprise": {
        "feat_lab": True, "feat_pharmacy": True, "feat_whatsapp": True,
        "feat_multi_branch": True, "feat_ai_voice": True, "feat_patient_app": True,
        "feat_analytics": True, "feat_video": True, "feat_face_recog": True,
        "feat_custom_roles": True,
        "max_doctors": 9999, "max_branches": 999, "max_staff": 9999,
    },
}
