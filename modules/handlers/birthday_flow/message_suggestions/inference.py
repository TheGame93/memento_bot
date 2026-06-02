from __future__ import annotations

import random as _random
import re
import unicodedata
from datetime import datetime
from typing import Any

from modules.birthday_utils import calculate_turning_age
from modules.tags_logic import parse_tag

_EMOJI_TAG_GROUPS = (
    ("💼", "work"),
    ("🫂", "friends"),
    ("👨‍👩‍👧", "family"),
    ("❤️", "love"),
    ("🐾", "pet"),
    ("🚗", "car"),
    ("📂", "others"),
    ("🏥", "others"),
    ("🏠", "others"),
)

_NAME_TOKEN_TO_GROUP = {
    "work": "work",
    "office": "work",
    "job": "work",
    "friends": "friends",
    "friend": "friends",
    "family": "family",
    "love": "love",
    "partner": "love",
    "pet": "pet",
    "dog": "pet",
    "cat": "pet",
    "car": "car",
    "auto": "car",
    "vehicle": "car",
    "documents": "others",
    "document": "others",
    "health": "others",
    "home": "others",
}

_TITLE_HINT_KEYWORDS = {
    "mom": ("mom", "mother", "mum", "mamma"),
    "dad": ("dad", "father", "papa"),
    "sister": ("sister",),
    "brother": ("brother",),
    "boss": ("boss", "manager", "director", "chief"),
    "best_friend": ("best friend", "bff"),
    "partner": ("partner", "boyfriend", "girlfriend", "husband", "wife", "spouse", "fiance", "fiancee"),
    "colleague": ("colleague", "coworker", "teammate"),
    "child": ("child", "kid", "kiddo", "son", "daughter", "baby"),
    "pet": ("pet", "dog", "cat", "puppy", "kitty", "hamster", "rabbit", "parrot"),
    "car": ("car", "auto", "vehicle", "truck"),
}

_FEMALE_KEYWORDS = ("mom", "mother", "mum", "mamma", "sister", "daughter", "wife", "girlfriend", "her")
_MALE_KEYWORDS = ("dad", "father", "papa", "brother", "son", "husband", "boyfriend", "him")


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _tokenize_text(value: Any) -> list[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return []
    return normalized.split()


def infer_tag_groups(tags: Any) -> list[str]:
    """Infer canonical tag groups from birthday tag values."""
    if not isinstance(tags, list):
        return ["others"]

    groups = []
    for raw_tag in tags:
        tag_text = str(raw_tag or "").strip()
        if not tag_text:
            continue

        group = None
        for emoji_prefix, mapped in _EMOJI_TAG_GROUPS:
            if tag_text.startswith(emoji_prefix):
                group = mapped
                break

        if group is None:
            _emoji, name = parse_tag(tag_text)
            tokens = _tokenize_text(name) or _tokenize_text(tag_text)
            for token in tokens:
                mapped = _NAME_TOKEN_TO_GROUP.get(token)
                if mapped:
                    group = mapped
                    break

        if group is None:
            group = "others"

        if group not in groups:
            groups.append(group)

    if not groups:
        return ["others"]
    return groups


def infer_title_hints(title: Any) -> list[str]:
    """Infer title-hint categories from normalized birthday title text."""
    normalized = _normalize_text(title)
    tokens = set(normalized.split()) if normalized else set()

    hints = []

    def _add_hint(value: str) -> None:
        if value not in hints:
            hints.append(value)

    for hint, keywords in _TITLE_HINT_KEYWORDS.items():
        for keyword in keywords:
            if " " in keyword:
                if keyword in normalized:
                    _add_hint(hint)
                    break
            elif keyword in tokens:
                _add_hint(hint)
                break

    if "generic" not in hints:
        hints.append("generic")
    return hints


def infer_gender_hint(title: Any, *, title_hints: list[str] | None = None) -> str:
    """Infer gender hint from title tokens and inferred title hints."""
    hints = set(title_hints or [])
    tokens = set(_tokenize_text(title))

    female_hit = any(token in tokens for token in _FEMALE_KEYWORDS) or bool(hints.intersection({"mom", "sister"}))
    male_hit = any(token in tokens for token in _MALE_KEYWORDS) or bool(hints.intersection({"dad", "brother"}))

    if female_hit and male_hit:
        return "neutral"
    if female_hit:
        return "female"
    if male_hit:
        return "male"
    return "any"


def infer_turning_age(
    alert: dict[str, Any] | None,
    *,
    occurrence_time: datetime | None = None,
    occurrence_year: int | None = None,
) -> int | None:
    """Infer turning age for the occurrence year when birth year is valid."""
    if occurrence_year is None and isinstance(occurrence_time, datetime):
        occurrence_year = occurrence_time.year
    if occurrence_year is None:
        return None

    raw_birth_year = None
    if isinstance(alert, dict):
        raw_birth_year = alert.get("birth_year")
    if raw_birth_year is None or isinstance(raw_birth_year, bool):
        return None

    try:
        birth_year = int(raw_birth_year)
    except (TypeError, ValueError):
        return None

    if birth_year < 1900 or birth_year > occurrence_year:
        return None
    return calculate_turning_age(birth_year, occurrence_year)


def infer_message_context(
    alert: dict[str, Any] | None,
    *,
    occurrence_time: datetime | None = None,
    occurrence_year: int | None = None,
) -> dict[str, Any]:
    """Build message-selection context from alert metadata and occurrence timing."""
    title = alert.get("title") if isinstance(alert, dict) else ""
    tags = alert.get("tags") if isinstance(alert, dict) else None

    title_hints = infer_title_hints(title)
    gender_hint = infer_gender_hint(title, title_hints=title_hints)
    tag_groups = infer_tag_groups(tags)
    turning_age = infer_turning_age(
        alert if isinstance(alert, dict) else None,
        occurrence_time=occurrence_time,
        occurrence_year=occurrence_year,
    )

    resolved_year = occurrence_year
    if resolved_year is None and isinstance(occurrence_time, datetime):
        resolved_year = occurrence_time.year

    return {
        "tag_groups": tag_groups,
        "title_hints": title_hints,
        "gender_hint": gender_hint,
        "turning_age": turning_age,
        "turning_age_known": turning_age is not None,
        "occurrence_year": resolved_year,
    }


def infer_zodiac_context(
    alert: dict[str, Any] | None,
    user_prefs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Infer zodiac context for birthday message generation.

    Returns
    -------
    dict with keys:
    - ``zodiac_mode``: str — current ``birthday_zodiac_mode`` setting
    - ``western_info``: dict | None — output of ``zodiac.get_western_zodiac``
    - ``eastern_info``: dict | None — output of ``zodiac.get_eastern_zodiac``
    - ``use_western``: bool
    - ``use_eastern``: bool
    - ``eastern_missing_year``: bool — True when eastern was requested/preferred
      but ``birth_year`` was absent or out of the CNY lookup range
    """
    from modules import constants as C
    from modules import zodiac as _zodiac

    zodiac_mode = (user_prefs or {}).get(
        "birthday_zodiac_mode", C.BIRTHDAY_ZODIAC_MODE_NONE
    )

    western_info: dict | None = None
    eastern_info: dict | None = None
    eastern_missing_year = False

    if isinstance(alert, dict):
        try:
            schedule = alert.get("schedule") or {}
            parts = (schedule.get("date") or "").split("/")
            day, month = int(parts[0]), int(parts[1])
            western_info = _zodiac.get_western_zodiac(day, month)
            birth_year = alert.get("birth_year")
            if birth_year is not None:
                eastern_info = _zodiac.get_eastern_zodiac(day, month, birth_year)
            else:
                eastern_missing_year = True
        except Exception:
            pass

    if zodiac_mode == C.BIRTHDAY_ZODIAC_MODE_WESTERN:
        use_western = True
        use_eastern = False
    elif zodiac_mode == C.BIRTHDAY_ZODIAC_MODE_EASTERN:
        if eastern_info is not None:
            use_western = False
            use_eastern = True
        else:
            eastern_missing_year = True   # covers out-of-range year too
            use_western = True
            use_eastern = False
    elif zodiac_mode == C.BIRTHDAY_ZODIAC_MODE_BOTH:
        use_western = True
        use_eastern = True
    else:
        # NONE: randomly pick between western and eastern; prefer western when
        # eastern is unavailable (no birth_year or year out of CNY range).
        if eastern_info is not None:
            use_western = bool(_random.choice([True, False]))
            use_eastern = not use_western
        else:
            use_western = True
            use_eastern = False

    return {
        "zodiac_mode": zodiac_mode,
        "western_info": western_info,
        "eastern_info": eastern_info,
        "use_western": use_western,
        "use_eastern": use_eastern,
        "eastern_missing_year": eastern_missing_year,
    }
