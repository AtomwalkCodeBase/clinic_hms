"""
Config loader for the pediatric health timeline.

Loaded once at process start (Atomwalk convention: JSON config loaded at startup).
Path resolution order:
  1. explicit argument
  2. settings.PEDIATRIC_HEALTH_CONFIG (if Django is configured)
  3. env PEDIATRIC_HEALTH_CONFIG
  4. <this package>/config/pediatric_health_config.json
"""
import json
import os
from functools import lru_cache
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "config" / "pediatric_health_config.json"
GROWTH_REFERENCE_DIR = PACKAGE_DIR / "config" / "growth_reference"


def _resolve_path(path=None):
    if path:
        return Path(path)
    try:
        from django.conf import settings  # noqa: WPS433
        if settings.configured and getattr(settings, "PEDIATRIC_HEALTH_CONFIG", None):
            return Path(settings.PEDIATRIC_HEALTH_CONFIG)
    except Exception:  # Django not installed / not configured (unit tests)
        pass
    env = os.environ.get("PEDIATRIC_HEALTH_CONFIG")
    return Path(env) if env else DEFAULT_CONFIG_PATH


@lru_cache(maxsize=4)
def load_config(path=None):
    with open(_resolve_path(path), encoding="utf-8") as fh:
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
