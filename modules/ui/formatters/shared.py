"""
shared.py — Shared render helpers used by all six message formatters.

Provides tag-line rendering, type-specific tree-prefix rows, human-readable
countdowns, zodiac block assembly, interval labelling, and repetition-limit
detection. Functions were moved here from scheduler_messagelogic.py and
list_alerts.py so that the formatter layer has no dependency on handler code.
"""

from datetime import datetime

from modules import constants as C
from modules import zodiac as _zodiac
from modules.repetition_utils import (
    is_repetition_supported,
    normalize_repetition_payload,
    parse_until_date_strict,
)
from modules.scheduler_mathlogic import (
    format_datetime_human,
    get_next_occurrence,
)
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.tags_logic import parse_tag


# =============================================================================
# TAG LINE
# =============================================================================

def format_tags_line(tags: list) -> str:
    """Render a tag list as ':icon: name, :icon: name' or '🏷️ Untagged' when empty.

    Each entry is split via parse_tag(); icon and name are emitted together
    without an extra separator.  Returns the literal string '🏷️ Untagged'
    when the list is empty or None.
    """
    if not tags:
        return "🏷️ Untagged"
    parts = []
    for t in tags:
        icon, name = parse_tag(t)
        parts.append(f"{icon} {name}")
    return ", ".join(parts)


# =============================================================================
# TYPE-SPECIFIC SCHEDULE ROWS (IA detail card)
# =============================================================================

def format_alert_type_rows(alert: dict) -> list:
    """Return type-specific schedule fields with ├─ / ╰─ tree prefixes for the IA detail card.

    Returns [] for type 6 (birthday — handled by IB) and type 7 (the shared
    interval line is sufficient).  The last entry always uses '╰─'; earlier
    entries use '├─'.  All field values are passed through md_escape.
    """
    sch = alert.get("schedule") or {}
    a_type = alert.get("type")
    raw_rows = []

    if a_type == 1:
        days = ", ".join(map(str, sch.get("days", []))) or "None"
        raw_rows.append(f"Days: {_md_escape(days)}")
    elif a_type == 2:
        ords = sch.get("ordinals", [])
        wks = sch.get("weekdays", [])
        rel = ", ".join([f"{o} {w}" for o in ords for w in wks]) if ords and wks else "None"
        raw_rows.append(f"Relative: {_md_escape(rel)}")
    elif a_type == 3:
        weekdays = ", ".join(sch.get("weekdays", [])) or "None"
        raw_rows.append(f"Weekdays: {_md_escape(weekdays)}")
    elif a_type == 4:
        dates_raw = sch.get("dates", "None")
        if isinstance(dates_raw, list):
            dates = ", ".join(str(d) for d in dates_raw) or "None"
        else:
            dates = str(dates_raw) if dates_raw else "None"
        raw_rows.append(f"Dates: {_md_escape(dates)}")
    elif a_type == 5:
        date = str(sch.get("date", "None") or "None")
        raw_rows.append(f"Date: {_md_escape(date)}")
    # type 6 (birthday) → [] — IB path handles its own block
    # type 7 (daily)    → [] — the shared 🔁 Interval line is sufficient

    if not raw_rows:
        return []
    if len(raw_rows) == 1:
        return [f"╰─ {raw_rows[0]}"]
    result = [f"├─ {r}" for r in raw_rows[:-1]]
    result.append(f"╰─ {raw_rows[-1]}")
    return result


# =============================================================================
# INTERVAL LABEL  (moved from list_alerts.py)
# =============================================================================

def _format_interval_label(interval, unit) -> str:
    """Return 'Every N Units' label for interval display.

    Moved from list_alerts.py to shared.py so that info_text.py can import it
    without creating a cross-module dependency on the handler layer.
    interval=None or 1 produces 'Every Unit' (singular).
    """
    if interval in (None, 1):
        return f"Every {unit}"
    return f"Every {interval} {unit}s"


# =============================================================================
# REPETITION LIMIT CHECK  (moved from scheduler_messagelogic.py)
# =============================================================================

def _is_repetition_limit_reached(alert, reference_dt=None) -> bool:
    """Return True when the alert's repetition is exhausted at reference_dt (defaults to now)."""
    if not isinstance(alert, dict):
        return False
    alert_type = alert.get("type")
    if not is_repetition_supported(alert_type):
        return False
    repetition = normalize_repetition_payload(alert_type, alert.get("repetition"))
    if not isinstance(repetition, dict):
        return False

    mode = repetition.get("mode")
    if mode == C.REPETITION_MODE_COUNT:
        try:
            return int(repetition.get("count_remaining") or 0) <= 0
        except Exception:
            return True

    if mode == C.REPETITION_MODE_UNTIL_DATE:
        until_date = parse_until_date_strict(repetition.get("until_date"))
        if until_date is None:
            return False
        ref_dt = reference_dt if isinstance(reference_dt, datetime) else datetime.now()
        return ref_dt.date() >= until_date

    return False


# =============================================================================
# TIME COUNTDOWN  (moved from scheduler_messagelogic.py)
# =============================================================================

def format_time_until(main_trigger_time, now=None) -> str:
    """Return a human-readable countdown string for time remaining until main_trigger_time.

    Rounds down to the nearest whole unit (minutes → hours → days → weeks).
    Returns 'Unknown' when main_trigger_time is falsy and 'less than a minute'
    when already past or within the first minute.
    """
    if not main_trigger_time:
        return "Unknown"
    if not now:
        now = datetime.now()
    delta = main_trigger_time - now
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "less than a minute"
    minutes = max(1, total_seconds // 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    days = hours // 24
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''}"
    weeks = days // 7
    return f"{weeks} week{'s' if weeks != 1 else ''}"


# =============================================================================
# NEXT-OCCURRENCE LINE  (moved from scheduler_messagelogic.py)
# =============================================================================

def format_next_occurrence_line(alert, reference_dt) -> str | None:
    """Return a formatted next-occurrence line, or None when no future occurrences exist.

    Returns a repetition-limit message instead of None when the repetition is
    exhausted so callers can render a human-readable termination notice.
    """
    next_occ = get_next_occurrence(alert, reference_dt or datetime.now())
    if next_occ:
        return f"Next occurrence: `{format_datetime_human(next_occ)}`"
    if _is_repetition_limit_reached(alert, reference_dt):
        return "Next occurrence: `No further occurrences (repetition limit reached)`"
    return None


# =============================================================================
# ZODIAC BLOCK  (moved from scheduler_messagelogic.py)
# =============================================================================

def append_zodiac_block(alert, user_prefs) -> str:
    """Return a zodiac info string (with leading \\n\\n) to append to birthday messages.

    Returns '' if zodiac mode is none, parsing fails, or no zodiac data available.
    """
    mode = (user_prefs or {}).get("birthday_zodiac_mode", C.BIRTHDAY_ZODIAC_MODE_NONE)
    if mode == C.BIRTHDAY_ZODIAC_MODE_NONE:
        return ""
    try:
        schedule = alert.get("schedule") or {}
        parts = (schedule.get("date") or "").split("/")
        day, month = int(parts[0]), int(parts[1])
    except Exception:
        return ""
    birth_year = alert.get("birth_year")
    try:
        info = _zodiac.get_zodiac_info(day, month, birth_year)
    except Exception:
        return ""
    western = info.get("western")
    eastern = info.get("eastern")
    lines = []
    if mode in (C.BIRTHDAY_ZODIAC_MODE_WESTERN, C.BIRTHDAY_ZODIAC_MODE_BOTH):
        if western:
            sign = _md_escape(western["sign"])
            date_range = _md_escape(western["date_range"])
            element = _md_escape(western["element"])
            lines.append(f"🔮 `{sign}` ({date_range}) · {element}")
    if mode in (C.BIRTHDAY_ZODIAC_MODE_EASTERN, C.BIRTHDAY_ZODIAC_MODE_BOTH):
        if eastern:
            animal = _md_escape(eastern["animal"])
            yin_yang = _md_escape(eastern["yin_yang"])
            element = _md_escape(eastern["element"])
            lines.append(f"🐉 `{animal}` · {yin_yang} · {element}")
    if not lines:
        return ""
    return "\n\n" + "\n".join(lines)
