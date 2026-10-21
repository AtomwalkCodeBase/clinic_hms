"""apps/org/services.py"""

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
    from apps.hospital_setup.models import NextNumber
    for entity, prefix, pad in _NNTM_ENTITIES:
        NextNumber.objects.using(db_name).get_or_create(
            branch_id=branch_id,
            entity=entity,
            defaults={"prefix": prefix, "pad_length": pad, "last_number": 0},
        )


def next_employee_id(db_name: str) -> str:
    """Auto-generate the next Employee ID via NNTM — see core/utils/nntm.py and"""
    from apps.hospital_setup.models import NextNumber
    from core.utils.nntm import get_next_number

    NextNumber.objects.using(db_name).get_or_create(
        branch=None, entity="employee_id",
        defaults={"prefix": "EMP-", "pad_length": 6, "last_number": 0},
    )
    formatted_id, _ = get_next_number(None, "employee_id", using=db_name)
    return formatted_id
