"""
apps/org/services.py
--------------------
Per-hospital numbering setup shared by org, platform_admin and the tenant provisioning
commands. Moved out of org/views.py, where other apps imported underscore-prefixed view
functions to reach it.
"""

# NNTM entity config: (entity_key, prefix, pad_length)
_NNTM_ENTITIES = [
    ("uhid",         "UHID-", 6),
    ("invoice",      "INV-",  6),
    ("lab_report",   "LAB-",  6),
    ("lab_test",     "LT-",   4),
    ("lab_request",  "LR-",   6),
    ("prescription", "RX-",   6),
    ("queue",        "Q-",    4),
]


def seed_next_numbers(branch_id: int, db_name: str) -> None:
    """Create NNTM counter rows for a new branch (idempotent — skips if already exist)."""
    from apps.org.models import NextNumber
    for entity, prefix, pad in _NNTM_ENTITIES:
        NextNumber.objects.using(db_name).get_or_create(
            branch_id=branch_id,
            entity=entity,
            defaults={"prefix": prefix, "pad_length": pad, "last_number": 0},
        )


def next_employee_id(db_name: str) -> str:
    """
    Auto-generate the next Employee ID via NNTM — see core/utils/nntm.py and
    docs/onboarding_auth_rbac_architecture.md 3.1.2. Unlike UHID/invoice/etc,
    Employee ID is a hospital-WIDE sequence (a staff member isn't tied to one
    branch the way a UHID is), so it uses the sentinel branch_id=0 rather
    than being seeded per-branch in seed_next_numbers above. Lazily
    get_or_create's its counter row on first use so this self-heals for
    tenants provisioned before this feature existed, with no migration or
    provisioning-script change required.

    Never manually editable — see StaffInviteSerializer / StaffDetailView.
    """
    from apps.org.models import NextNumber
    from core.utils.nntm import get_next_number

    NextNumber.objects.using(db_name).get_or_create(
        branch_id=0, entity="employee_id",
        defaults={"prefix": "EMP-", "pad_length": 6, "last_number": 0},
    )
    formatted_id, _ = get_next_number(0, "employee_id", using=db_name)
    return formatted_id
