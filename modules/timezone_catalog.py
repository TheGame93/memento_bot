from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from modules import constants as C
from modules.timezone_utils import format_tz_offset

_TZ_CACHE: list[str] | None = None
_AREA_CACHE: set[str] | None = None


def _normalize_query(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    cleaned = cleaned.replace("_", " ").replace("-", " ")
    return cleaned


def list_timezones() -> list[str]:
    """Return the cached sorted list of available IANA timezone names."""
    global _TZ_CACHE, _AREA_CACHE
    if _TZ_CACHE is None:
        _TZ_CACHE = sorted(available_timezones())
        _AREA_CACHE = {tz.split("/", 1)[0].lower() for tz in _TZ_CACHE if "/" in tz}
    return list(_TZ_CACHE)


def list_areas() -> set[str]:
    """Return top-level timezone area names derived from the catalog cache."""
    if _AREA_CACHE is None:
        list_timezones()
    return set(_AREA_CACHE or set())


def _score_match(query: str, candidate: str) -> float:
    if not query:
        return 0.0
    cand_norm = candidate.lower().replace("_", " ").replace("/", " ")
    score = SequenceMatcher(None, query, cand_norm).ratio()
    if query in cand_norm:
        score += 0.35
    return min(score, 1.0)


def describe_timezone(tz_name: str, reference: datetime | None = None) -> str:
    """Render a timezone label including its current UTC offset."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return tz_name
    now = reference or datetime.now(tz)
    offset = format_tz_offset(now, tz)
    return f"{tz_name} ({offset})"


def suggest_timezones(query: str, limit: int | None = None) -> list[str]:
    """Return best-match timezone suggestions for free-text user input."""
    limit = int(limit or C.TIMEZONE_SUGGESTION_LIMIT)
    if limit <= 0:
        return []
    raw = (query or "").strip()
    if not raw:
        return []

    normalized = _normalize_query(raw)
    tzs = list_timezones()

    exact = [
        tz for tz in tzs
        if tz.lower() == normalized or tz.lower().replace("_", " ") == normalized
    ]
    if exact:
        return exact[:limit]

    area_matches = []
    if normalized in list_areas():
        area_prefix = normalized + "/"
        area_matches = [tz for tz in tzs if tz.lower().startswith(area_prefix)]
        if area_matches:
            return area_matches[:limit]

    scored = []
    for tz in tzs:
        score = _score_match(normalized, tz)
        if score < 0.35:
            continue
        scored.append((score, tz))
    scored.sort(key=lambda item: (-item[0], item[1]))

    return [tz for _, tz in scored[:limit]]
