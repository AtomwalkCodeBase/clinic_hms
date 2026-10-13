"""Small helpers every staff pediatric view uses."""
from datetime import date, datetime

from apps.patients.models import Patient
from core.response import error

PATIENT_NOT_FOUND = "Patient not found."


def get_patient(request, pk):
    """This hospital's patient row, or None."""
    return Patient.objects.using(request.tenant_db).filter(pk=pk).first()


def text(data, key):
    """A request field as stripped text ('' when missing)."""
    return (data.get(key) or "").strip()


def staff_name(request, fallback="Staff"):
    """Who is doing this, for the 'recorded by' columns."""
    return getattr(request.user, "full_name", None) or getattr(request.user, "email", fallback)


def has_measurement(reading):
    return bool(reading.height_cm or reading.weight_kg or reading.head_circumference_cm)


def growth_point(reading, source):
    """One growth-chart point from a Vitals or SharedVital row."""
    number = lambda x: float(x) if x else None                      # noqa: E731
    return {"date": str(reading.recorded_at.date()), "height_cm": number(reading.height_cm),
            "weight_kg": number(reading.weight_kg), "head_circumference_cm": number(reading.head_circumference_cm),
            "source": source}


def parse_date(value, field, label, *, allow_future=False):
    """
    (date, None) for a YYYY-MM-DD value between 1900 and today (or later when allow_future); a blank value gives
    (None, None); anything else gives (None, a 400 response to return as it is).
    """
    if not value:
        return None, None
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, error(f"{label} must be a valid date.", errors={field: "Enter a valid date."})
    if parsed.year < 1900 or (parsed > date.today() and not allow_future):
        return None, error(f"{label} ({parsed.isoformat()}) doesn't look right — please check the date.",
                           errors={field: "Check the date — it is out of range."})
    return parsed, None
