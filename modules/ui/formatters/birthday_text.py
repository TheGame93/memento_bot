"""
birthday_text.py — Text formatters for birthday alert notifications.

Covers PB (pre-alert of birthday) and BB (birthday notification).
Non-birthday alert renderers live in alert_text.py.

Layout for PB:
    🔔 UPCOMING ALERT

    ⚠️ This alert is due in <countdown>
    📅 Scheduled: `Mon 27 Mar - 10:00`

    🎂 Birthday of
    `NAME ALL CAPS`

    🎉 Name will turn <age>!   ← or mystery line when birth_year unknown

    [Additional info: <text>   ← only when non-empty]

    <tags line>

Note: zodiac is intentionally excluded from PB notifications.

Layout for BB:
    🎂 Birthday of
    `NAME ALL CAPS`

    🎉 Name turns <age> today!  ← or mystery line when birth_year unknown

    [Additional info: <text>    ← only when non-empty]

    [zodiac block               ← only when user_prefs enables it]

    <tags line>
"""

from modules.birthday_utils import calculate_turning_age
from modules.scheduler_mathlogic import format_datetime_human
from modules.shared.markdown_utils import (
    md_escape as _md_escape,
    md_escape_inline_code as _md_escape_inline_code,
    md_escape_multiline_text as _md_escape_multiline_text,
)
from modules.ui.formatters.shared import (
    append_zodiac_block,
    format_tags_line,
    format_time_until,
)

_MYSTERY_LINE = "🎉 {name}'s age is a mystery! Discover the birthyear and update this entry!"


def _birthday_block_lines(alert: dict) -> list:
    """Return the two-line birthday block ['🎂 Birthday of', '`NAME ALL CAPS`']."""
    name_caps = _md_escape_inline_code((alert.get("title") or "Untitled").upper())
    return ["🎂 Birthday of", f"`{name_caps}`"]


def _turning_line(alert: dict, turning_year: int | None, verb: str) -> str:
    """Return the turning-age line or the standardised mystery line.

    verb is 'will turn' (PB) or 'turns today' (BB).
    """
    name = _md_escape(alert.get("title") or "Untitled")
    turning = calculate_turning_age(alert.get("birth_year"), turning_year)
    if turning is not None:
        if verb == "will turn":
            return f"🎉 {name} will turn **{turning}**!"
        return f"🎉 {name} turns **{turning}** today!"
    return _MYSTERY_LINE.format(name=name)


# =============================================================================
# PRE-ALERT BIRTHDAY NOTIFICATION (PB)
# =============================================================================

def format_pb(alert: dict, main_trigger_time, scheduled_time=None, user_prefs=None) -> str:
    """Render the pre-alert notification text for a birthday alert (PB).

    Opens with the UPCOMING ALERT header, countdown, and main trigger datetime.
    Follows with the birthday block (🎂 Birthday of / `NAME`), turning-age line
    using 'will turn' wording, additional_info when non-empty, and tags line.
    Zodiac is intentionally excluded from pre-alert birthday notifications.
    scheduled_time is accepted for API symmetry but is not rendered.
    """
    time_until = format_time_until(main_trigger_time)
    main_time_str = _md_escape_inline_code(
        format_datetime_human(main_trigger_time) if main_trigger_time else "Unknown"
    )

    turning_year = main_trigger_time.year if main_trigger_time is not None else None

    lines = [
        "🔔 UPCOMING ALERT",
        "",
        f"⚠️ This alert is due in {time_until}",
        f"📅 Scheduled: `{main_time_str}`",
        "",
        *_birthday_block_lines(alert),
        "",
        _turning_line(alert, turning_year, verb="will turn"),
        "",
    ]

    info = (alert.get("additional_info") or "").strip()
    if info:
        lines.append(f"Additional info:\n{_md_escape_multiline_text(info)}")
        lines.append("")

    lines.append(format_tags_line(alert.get("tags") or []))
    return "\n".join(lines)


# =============================================================================
# MAIN BIRTHDAY NOTIFICATION (BB)
# =============================================================================

def format_bb(alert: dict, scheduled_time=None, user_prefs=None) -> str:
    """Render the main birthday notification text (BB).

    Contains the birthday block (🎂 Birthday of / `NAME`), turning-age line
    using 'turns today' wording, additional_info when non-empty, zodiac block
    when user_prefs enables it, and tags line.
    """
    turning_year = scheduled_time.year if scheduled_time is not None else None

    lines = [
        *_birthday_block_lines(alert),
        "",
        _turning_line(alert, turning_year, verb="turns today"),
        "",
    ]

    info = (alert.get("additional_info") or "").strip()
    if info:
        lines.append(f"Additional info:\n{_md_escape_multiline_text(info)}")
        lines.append("")

    zodiac = append_zodiac_block(alert, user_prefs)
    if zodiac:
        # append_zodiac_block returns "\n\n..." — strip the leading newlines
        # and emit as a clean block separated by a blank line
        lines.append(zodiac.lstrip("\n"))
        lines.append("")

    lines.append(format_tags_line(alert.get("tags") or []))
    return "\n".join(lines)
