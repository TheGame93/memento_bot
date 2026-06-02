from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from modules import constants as C

_UNTIL_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_UNTIL_DATE_INPUT_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")


def is_repetition_supported(alert_type: Any) -> bool:
    """Return whether the alert type supports persisted repetition settings."""
    try:
        normalized_type = int(alert_type)
    except (TypeError, ValueError):
        return False
    return normalized_type in C.REPETITION_SUPPORTED_TYPES


def default_repetition_payload(alert_type: Any) -> dict | None:
    """Return the default normalized repetition payload for supported alert types."""
    if not is_repetition_supported(alert_type):
        return None
    return {
        "mode": C.REPETITION_MODE_FOREVER,
        "until_date": None,
        "count_remaining": None,
    }


def parse_until_date_strict(raw_text: Any) -> date | None:
    """Parse a strict `DD/MM/YYYY` repetition-until value into a valid date."""
    if not isinstance(raw_text, str):
        return None
    value = raw_text.strip()
    if not _UNTIL_DATE_RE.match(value):
        return None
    try:
        parsed = datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None
    if parsed.strftime("%d/%m/%Y") != value:
        return None
    return parsed


def parse_until_date_input(raw_text: Any) -> tuple[date | None, bool]:
    """
    Parse user-facing repetition-until input.
    Accepted forms: d/m/yy, dd/mm/yy, d/m/yyyy, dd/mm/yyyy.
    Returns (parsed_date, used_two_digit_year).
    """
    if not isinstance(raw_text, str):
        return None, False
    value = raw_text.strip()
    match = _UNTIL_DATE_INPUT_RE.match(value)
    if not match:
        return None, False
    try:
        day = int(match.group(1))
        month = int(match.group(2))
        year_token = match.group(3)
        if len(year_token) == 2:
            year = 2000 + int(year_token)
            used_two_digit_year = True
        else:
            year = int(year_token)
            used_two_digit_year = False
        parsed = date(year, month, day)
    except Exception:
        return None, False
    return parsed, used_two_digit_year


def _normalize_supported_payload(repetition_raw: Any) -> dict:
    default_payload = {
        "mode": C.REPETITION_MODE_FOREVER,
        "until_date": None,
        "count_remaining": None,
    }
    if not isinstance(repetition_raw, dict):
        return default_payload

    raw_mode = repetition_raw.get("mode")
    mode = raw_mode.strip().lower() if isinstance(raw_mode, str) else ""

    if mode == C.REPETITION_MODE_UNTIL_DATE:
        parsed_until = parse_until_date_strict(repetition_raw.get("until_date"))
        if parsed_until is None:
            return default_payload
        return {
            "mode": C.REPETITION_MODE_UNTIL_DATE,
            "until_date": parsed_until.strftime("%d/%m/%Y"),
            "count_remaining": None,
        }

    if mode == C.REPETITION_MODE_COUNT:
        raw_count = repetition_raw.get("count_remaining")
        try:
            if isinstance(raw_count, bool):
                raise ValueError("bool is not a valid count")
            count_value = int(raw_count)
        except (TypeError, ValueError):
            return default_payload
        # Allow 0 to preserve exhausted-runtime state without reviving to forever.
        if count_value < 0:
            return default_payload
        return {
            "mode": C.REPETITION_MODE_COUNT,
            "until_date": None,
            "count_remaining": count_value,
        }

    if mode == C.REPETITION_MODE_FOREVER:
        return default_payload

    return default_payload


def normalize_repetition_payload(alert_type: Any, repetition_raw: Any) -> dict | None:
    """Normalize repetition data to the canonical storage schema for the alert type."""
    if not is_repetition_supported(alert_type):
        return None
    return _normalize_supported_payload(repetition_raw)


def format_repetition_human(alert_type: Any, repetition_raw: Any) -> str:
    """Render repetition data as a user-facing summary label."""
    if not is_repetition_supported(alert_type):
        return "N/A"

    normalized = _normalize_supported_payload(repetition_raw)
    mode = normalized.get("mode")

    if mode == C.REPETITION_MODE_UNTIL_DATE:
        until_date = normalized.get("until_date")
        return f"Until {until_date} (inclusive)"
    if mode == C.REPETITION_MODE_COUNT:
        count_remaining = int(normalized.get("count_remaining") or 0)
        unit = "event" if count_remaining == 1 else "events"
        return f"Next {count_remaining} {unit}"
    return "Forever"


def _coerce_candidate_date(candidate_dt: Any) -> date | None:
    if isinstance(candidate_dt, datetime):
        return candidate_dt.date()
    if isinstance(candidate_dt, date):
        return candidate_dt
    return None


def candidate_allowed_by_repetition(alert_type: Any, repetition_raw: Any, candidate_dt: Any) -> bool:
    """Return whether a candidate occurrence is allowed by repetition limits."""
    if not is_repetition_supported(alert_type):
        return True

    normalized = _normalize_supported_payload(repetition_raw)
    mode = normalized.get("mode")

    if mode == C.REPETITION_MODE_FOREVER:
        return True

    if mode == C.REPETITION_MODE_COUNT:
        count_remaining = int(normalized.get("count_remaining") or 0)
        return count_remaining > 0

    if mode == C.REPETITION_MODE_UNTIL_DATE:
        candidate_date = _coerce_candidate_date(candidate_dt)
        until_date = parse_until_date_strict(normalized.get("until_date"))
        if candidate_date is None or until_date is None:
            return False
        return candidate_date <= until_date

    return True


def decrement_count_if_needed(repetition_raw: Any, *, should_count: bool):
    """Update count-based repetition for one due occurrence and report transition details.

    Returns `(normalized_payload, before, after, exhausted)` where `before/after`
    are count values (or `None` when mode is not `count`) and `exhausted`
    indicates whether the resulting payload has no remaining occurrences.
    """
    normalized = _normalize_supported_payload(repetition_raw)

    before = None
    after = None
    exhausted = False

    if normalized.get("mode") != C.REPETITION_MODE_COUNT:
        return normalized, before, after, exhausted

    before = int(normalized.get("count_remaining") or 0)
    after = before

    if not should_count:
        exhausted = before <= 0
        return normalized, before, after, exhausted

    after = max(before - 1, 0)
    normalized = dict(normalized)
    normalized["count_remaining"] = after
    exhausted = after <= 0
    return normalized, before, after, exhausted
