"""
core/login_lockout.py
----------------------
Shared per-ACCOUNT lockout helper for password login. StaffUser (per-tenant,
apps.org) and PatientAccount (registry DB, apps.registry) both carry the
same two fields — failed_login_attempts, locked_until — and follow the
exact same policy, so the increment/check/reset logic lives in one place
rather than being copied into each login view. Mirrors core.otp's
MAX_VERIFY_ATTEMPTS pattern (see core/otp.py), just applied to password
login instead of OTP verification.

Why this exists alongside the "login" ScopedRateThrottle (see
DEFAULT_THROTTLE_RATES in atomwalk/settings/base.py): that throttle limits
how fast ONE IP can hit the login endpoint (10/min) — it does nothing to
stop a slow attack against ONE account spread across many IPs, or across a
longer time window than a minute. This is the account-side complement.

Both callers already resolve the account row before checking the password
(StaffLoginView / PatientLoginView), so the functions here take that
already-fetched instance rather than re-querying.
"""
from datetime import timedelta

from django.utils import timezone

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def is_locked(account) -> bool:
    return bool(account.locked_until and account.locked_until > timezone.now())


def lockout_minutes_remaining(account) -> int:
    """Whole minutes left, rounded up, so "0 minutes" is never shown while
    still locked (e.g. 10 seconds left reads as "1 minute", not "0")."""
    if not is_locked(account):
        return 0
    seconds_left = (account.locked_until - timezone.now()).total_seconds()
    return max(1, -(-int(seconds_left) // 60))  # ceil division


def record_failed_attempt(account, db_alias) -> None:
    """Call after a wrong password on an account that wasn't already locked."""
    account.failed_login_attempts = (account.failed_login_attempts or 0) + 1
    update_fields = ["failed_login_attempts"]
    if account.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
        account.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_MINUTES)
        update_fields.append("locked_until")
    account.save(using=db_alias, update_fields=update_fields)


def record_successful_login(account, db_alias) -> None:
    """Call once a login has actually succeeded — clears any prior strikes
    so an occasional mistyped password doesn't accumulate toward a lockout
    days later."""
    if account.failed_login_attempts or account.locked_until:
        account.failed_login_attempts = 0
        account.locked_until = None
        account.save(using=db_alias, update_fields=["failed_login_attempts", "locked_until"])
