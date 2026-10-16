"""apps/hospital_patients/age_utils.py"""
from datetime import date


def age_years_months(dob):
    """Returns (years, months) elapsed from dob to today, or None if dob is"""
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
