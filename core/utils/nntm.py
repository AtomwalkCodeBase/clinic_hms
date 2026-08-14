"""
core/utils/nntm.py
------------------
Next Number Table Manager (NNTM) — generates sequential, collision-free IDs.

All sequential numbers in the system go through here:
  - UHID (patient hospital ID)
  - Invoice number
  - Lab report number
  - Prescription (Rx) number
  - Queue token

CRITICAL: Uses SELECT FOR UPDATE inside an atomic transaction.
Never generate IDs in application code — always call get_next_number().
"""

import logging
from django.db import transaction

logger = logging.getLogger(__name__)


def get_next_number(branch_id: int, entity: str, using: str = "default") -> tuple[str, int]:
    """
    Atomically increment the counter for a given branch+entity and return
    the formatted ID string and the raw integer number.

    Args:
        branch_id: The branch this number belongs to. For 'employee_id',
                   which is a hospital-wide (not per-branch) sequence, pass 0
                   — see apps.org.views._next_employee_id.
        entity:    One of: 'uhid', 'invoice', 'lab_report', 'lab_test', 'prescription', 'queue', 'employee_id', 'drug'.
        using:     The database alias to use (tenant DB name).

    Returns:
        Tuple of (formatted_id: str, number: int)
        e.g. ("UHID-000042", 42)

    Raises:
        NextNumber.DoesNotExist if the entity is not configured for this branch.
        ValueError if entity is not a recognized type.
    """
    # Import here to avoid circular imports
    from apps.org.models import NextNumber

    # 'drug' was missing here even though DrugCatalogView._next_drug_code()
    # (apps/prescriptions/views.py) has called get_next_number(entity="drug")
    # since the drug catalog was built — every manual "Add Drug" submission
    # with a blank code was hitting this ValueError. Added alongside the
    # drug-form-configurability work when the same bug showed up seeding
    # demo data.
    VALID_ENTITIES = {"uhid", "invoice", "lab_report", "lab_test", "prescription", "queue", "employee_id", "drug"}
    if entity not in VALID_ENTITIES:
        raise ValueError(f"Unknown entity '{entity}'. Must be one of: {VALID_ENTITIES}")

    with transaction.atomic(using=using):
        # Lock the row for this branch+entity — prevents concurrent duplicates
        nn = NextNumber.objects.using(using).select_for_update().get(
            branch_id=branch_id,
            entity=entity,
        )
        nn.last_number += 1
        nn.save(using=using, update_fields=["last_number"])

        padded = str(nn.last_number).zfill(nn.pad_length)
        formatted_id = f"{nn.prefix}{padded}"

        logger.debug(
            "NNTM: branch=%s entity=%s → %s",
            branch_id, entity, formatted_id,
        )
        return formatted_id, nn.last_number
