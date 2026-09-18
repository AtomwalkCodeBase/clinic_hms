"""
core/geo.py
------------
Distance math for "hospitals near me". Deliberately not a geocoding
client — geocoding (address → lat/lng) happens once, out of band, when
platform admin sets a hospital's coordinates; nothing in the request path
calls out to a third-party API, so there's no external dependency, cost,
or failure mode to worry about at request time.
"""

from math import radians, sin, cos, sqrt, atan2

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lng points, in kilometers."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(1 - a))


def parse_lat_lng(request):
    """
    Pulls optional ?lat=&lng= query params off a request, validated to real
    coordinate ranges. Returns (lat, lng) floats, or (None, None) if either
    is missing/invalid — callers treat that as "no location given" rather
    than raising, since location is always an optional refinement here,
    never a required parameter.
    """
    lat_raw = (request.query_params.get("lat") or "").strip()
    lng_raw = (request.query_params.get("lng") or "").strip()
    if not lat_raw or not lng_raw:
        return None, None
    try:
        lat, lng = float(lat_raw), float(lng_raw)
    except ValueError:
        return None, None
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return None, None
    return lat, lng
