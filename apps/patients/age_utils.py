"""
apps/patients/age_utils.py
---------------------------
Single source of truth for turning a date_of_birth into an age, used by
every login/view that displays a patient's (or staff member's) age:
front desk, doctor, hospital-admin, the patient portal, and the public
consult-pad/emergency-QR views. Previously each of those re-implemented
whole-year subtraction independently, which meant an infant under one
year old surfaced inconsistently (or not at all) depending on which
screen you were looking at. Compute years+months here once, everywhere.
"""
from datetime import date


def age_years_months(dob):
    """
    Returns (years, months) elapsed from dob to today, or None if dob is
    missing/invalid/in the future. Callers needing just whole years (e.g.
    an is_minor >= 18 check) can take result[0].
    """
    if not dob:
        return None
    today = date.today()
    years = today.year - dob.year
    months = today.month - dob.month
    if today.day < dob.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    if years < 0:
        return None
    return years, months


def age_years(dob):
    """Whole-years age only (backward-compatible with the old int field)."""
    ym = age_years_months(dob)
    return ym[0] if ym else None
