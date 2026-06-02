from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_TF = None
_TF_ERROR = None


def _get_finder():
    global _TF, _TF_ERROR
    if _TF or _TF_ERROR:
        return _TF
    try:
        from timezonefinder import TimezoneFinder
    except Exception as exc:
        _TF_ERROR = exc
        logger.warning("timezonefinder not available: %s", exc)
        return None
    _TF = TimezoneFinder()
    return _TF


def resolve_timezone_from_location(latitude: float, longitude: float) -> Optional[str]:
    """Resolve an IANA timezone name from geographic coordinates."""
    finder = _get_finder()
    if not finder:
        return None
    try:
        tz_name = finder.timezone_at(lat=latitude, lng=longitude)
        if tz_name:
            return tz_name
        return finder.closest_timezone_at(lat=latitude, lng=longitude)
    except Exception as exc:
        logger.warning("timezonefinder lookup failed: %s", exc)
        return None
