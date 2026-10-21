"""core/utils/nntm.py"""

import logging
from django.db import transaction

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "uhid": ("UHID-", 6), "invoice": ("INV-", 6), "lab_report": ("LAB-", 6), "lab_test": ("LT-", 4), "lab_request": ("LR-", 6),
    "prescription": ("RX-", 6), "queue": ("Q-", 4), "employee_id": ("EMP-", 6), "drug": ("DRG-", 4), "admission": ("ADM-", 6),
}


def get_next_number(branch_id: int | None, entity: str, using: str = "default") -> tuple[str, int]:
    """Atomically increment the counter for a given branch+entity and return"""
    # Import here to avoid circular imports
    from apps.hospital_setup.models import NextNumber

    # 'drug' was missing here even though DrugCatalogView._next_drug_code()
    VALID_ENTITIES = {"uhid", "invoice", "lab_report", "lab_test", "lab_request", "prescription", "queue", "employee_id", "drug", "admission"}
    if entity not in VALID_ENTITIES:
        raise ValueError(f"Unknown entity '{entity}'. Must be one of: {VALID_ENTITIES}")

    prefix, pad = _DEFAULTS[entity]
    NextNumber.objects.using(using).get_or_create(
        branch_id=branch_id, entity=entity, defaults={"prefix": prefix, "pad_length": pad, "last_number": 0})

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
