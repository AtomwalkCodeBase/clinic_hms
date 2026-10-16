"""core/utils/nntm.py"""

import logging
from django.db import transaction

logger = logging.getLogger(__name__)


def get_next_number(branch_id: int, entity: str, using: str = "default") -> tuple[str, int]:
    """Atomically increment the counter for a given branch+entity and return"""
    # Import here to avoid circular imports
    from apps.hospital_setup.models import NextNumber

    # 'drug' was missing here even though DrugCatalogView._next_drug_code()
    VALID_ENTITIES = {"uhid", "invoice", "lab_report", "lab_test", "lab_request", "prescription", "queue", "employee_id", "drug", "admission"}
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

        # Counters are per branch but most number columns are unique
        infix = ""
        if branch_id:
            from apps.hospital_setup.models import Branch
            first = Branch.objects.using(using).order_by("id").values_list("id", flat=True).first()
            if first is not None and branch_id != first:
                infix = f"B{branch_id}-"

        padded = str(nn.last_number).zfill(nn.pad_length)
        formatted_id = f"{nn.prefix}{infix}{padded}"

        logger.debug(
            "NNTM: branch=%s entity=%s → %s",
            branch_id, entity, formatted_id,
        )
        return formatted_id, nn.last_number
