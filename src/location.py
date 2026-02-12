"""Pincode → latitude/longitude resolution using pgeocode (offline) with geopy fallback."""

import pgeocode
from geopy.geocoders import Nominatim


def resolve_pincode(pincode: str) -> tuple[float, float]:
    """Resolve an Indian pincode to (latitude, longitude).

    Tries pgeocode (offline) first, falls back to geopy/Nominatim.
    Raises ValueError if resolution fails.
    """
    lat, lon = _resolve_pgeocode(pincode)
    if lat is not None and lon is not None:
        return lat, lon

    lat, lon = _resolve_geopy(pincode)
    if lat is not None and lon is not None:
        return lat, lon

    raise ValueError(
        f"Could not resolve pincode {pincode}. "
        "Try providing --lat and --lon directly."
    )


def _resolve_pgeocode(pincode: str) -> tuple[float | None, float | None]:
    """Offline resolution via pgeocode."""
    nomi = pgeocode.Nominatim("in")
    result = nomi.query_postal_code(pincode)

    import math
    lat = result.get("latitude") if hasattr(result, "get") else getattr(result, "latitude", None)
    lon = result.get("longitude") if hasattr(result, "get") else getattr(result, "longitude", None)

    # pgeocode returns NaN for unknown pincodes
    if lat is not None and lon is not None:
        try:
            if not math.isnan(float(lat)) and not math.isnan(float(lon)):
                return float(lat), float(lon)
        except (TypeError, ValueError):
            pass

    return None, None


def _resolve_geopy(pincode: str) -> tuple[float | None, float | None]:
    """Online fallback via geopy Nominatim."""
    try:
        geolocator = Nominatim(user_agent="blinkit-scraper")
        location = geolocator.geocode(f"{pincode}, India")
        if location:
            return location.latitude, location.longitude
    except Exception:
        pass
    return None, None
