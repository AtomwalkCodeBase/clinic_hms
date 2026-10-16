"""Config loader for the pediatric health timeline."""

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings


APP_DIR = Path(__file__).resolve().parent.parent                      # apps/documents
DEFAULT_CONFIG_PATH = APP_DIR / "health_config.json"
GROWTH_REFERENCE_DIR = APP_DIR / "growth_reference"


def _resolve_path(path=None):
    return Path(path or getattr(settings, "PEDIATRIC_HEALTH_CONFIG", None) or DEFAULT_CONFIG_PATH)


def load_config(path=None):
    return _read_config(str(_resolve_path(path)))


@lru_cache(maxsize=4)
def _read_config(path):
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    _validate(cfg)
    return cfg


def _validate(cfg):
    required = ["age_bands", "lab_thresholds", "condition_groups",
                "recurrence_rules", "growth", "immunization_schedule"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"pediatric_health_config missing keys: {missing}")
    groups = {k for k in cfg["condition_groups"] if not k.startswith("_")}
    unknown = [k for k in cfg["recurrence_rules"] if not k.startswith("_") and k not in groups]
    if unknown:
        raise ValueError(f"recurrence_rules reference unknown condition groups: {unknown}")
