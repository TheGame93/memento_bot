"""
info_text.py — Detail-card text formatters for alert and birthday info views.

Covers IA (info card for a regular alert) and IB (info card for a birthday alert).
These replace _format_detailed_card and _format_detailed_card_birthday from
list_alerts.py.

IA layout:
    ℹ️ Detailed INFO

    🟢 ─ `TITLE ALL IN CAPS`
    📑 Type: <type_name>
    [├─ / ╰─ type-specific rows]

    🔁 Interval: <interval_label>
    Repetition: <repetition_label>   ← only if repetition supported
    ⏰ Time: HH:MM                   ← only if time is set
    🔔 Pre-alert: <labels>           ← only if pre_alerts non-empty

    [Additional info: <text>         ← only if non-empty]

    Last Triggered: YYYY-MM-DD       ← only if present
    Next Scheduled: DD Month - HH:MM

    <tags line>

IB layout:
    ℹ️ Detailed INFO

    🟢 ─ 🎂 Birthday of
    `NAME ALL CAPS`

    Birth date: <DD Month YYYY>      ← 'DD Month (year unknown)' when birth_year missing
    🎂 Current age: <age>            ← only if birth_year known

    🔔 Pre-alert: <labels>           ← only if pre_alerts non-empty

    [Additional info: <text>         ← only if non-empty]

    [zodiac block                    ← only when user_prefs enables it]

    <tags line>
"""

from datetime import datetime

from modules.birthday_utils import calculate_current_age
from modules.repetition_utils import (
    format_repetition_human,
    is_repetition_supported,
)
from modules.scheduler_mathlogic import (
    format_pre_alert_display,
    get_next_occurrence,
    resolve_pre_alert_fire_time,
)
from modules.shared.markdown_utils import (
    md_escape as _md_escape,
    md_escape_inline_code as _md_escape_inline_code,
    md_escape_multiline_text as _md_escape_multiline_text,
)
from modules.ui.formatters.shared import (
    _format_interval_label,
    _is_repetition_limit_reached,
    append_zodiac_block,
    format_alert_type_rows,
    format_tags_line,
)


# Maps alert type → interval unit string used with _format_interval_label.
# Types 5 (once) and 6 (birthday → IB path) are excluded intentionally.
_TYPE_INTERVAL_UNIT = {
    1: "Month",
    2: "Month",
    3: "Week",
    4: "Year",
    7: "Day",
}


# =============================================================================
# Private helpers
# =============================================================================

def _get_next_dt(alert):
    """Return next occurrence datetime, preferring the stored next_scheduled field."""
    raw = alert.get("next_scheduled")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            pass
    return get_next_occurrence(alert)


def _ordered_pre_alerts(alert, due_dt):
    """Return pre-alert tokens sorted by fire time (earliest first), unknowns last."""
    tokens = list(alert.get("pre_alerts") or [])
    if not tokens or not due_dt:
        return tokens
    dated = []
    unknown = []
    for token in tokens:
        pre_dt, _kind = resolve_pre_alert_fire_time(alert, token, due_dt)
        if not pre_dt:
            unknown.append(token)
        else:
            dated.append((pre_dt, token))
    dated.sort(key=lambda x: x[0])
    return [t for _, t in dated] + unknown


def _format_last_triggered(alert):
    """Return last_triggered as 'YYYY-MM-DD' string, or None when absent."""
    raw = alert.get("last_triggered")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d")
    except Exception:
        return None


def _format_next_scheduled_str(alert, next_dt):
    """Return a human-readable next-scheduled string for the IA detail card.

    Returns a repetition-exhausted notice when no future occurrences remain,
    'Not scheduled' when no next_dt and repetition is open-ended, or a
    formatted datetime otherwise (same-year: 'DD Month - HH:MM', else
    'DD Month YYYY - HH:MM').
    """
    if not next_dt:
        if _is_repetition_limit_reached(alert):
            return "No future occurrences (repetition exhausted)"
        return "Not scheduled"
    same_year = next_dt.year == datetime.now().year
    if same_year:
        return next_dt.strftime("%d %B - %H:%M")
    return next_dt.strftime("%d %B %Y - %H:%M")


# =============================================================================
# IA — Alert detail card
# =============================================================================

def format_ia(alert: dict, user_prefs=None) -> str:
    """Render the alert detail card text (IA).

    Opens with 'ℹ️ Detailed INFO' header, then status_icon ─ TITLE, type
    line, tree-formatted type-specific fields (via format_alert_type_rows),
    interval/repetition/time/pre-alert section, additional_info when non-empty,
    last-triggered and next-scheduled timestamps, and tags line.
    """
    a_type = alert.get("type")
    sch = alert.get("schedule") or {}
    status_dot = "🟢" if alert.get("active", True) else "🔴"
    title = _md_escape_inline_code((alert.get("title") or "Untitled").upper())
    type_name = _md_escape(alert.get("type_name") or "Unknown")

    lines = [
        "ℹ️ Detailed INFO",
        "",
        f"{status_dot} ─ `{title}`",
        f"📑 Type: {type_name}",
    ]

    type_rows = format_alert_type_rows(alert)
    lines.extend(type_rows)
    lines.append("")  # separator after type block, always present

    # Interval / repetition / time / pre-alert block.
    # Collected separately so a trailing blank is only added when the block is non-empty.
    interval_section = []

    unit = _TYPE_INTERVAL_UNIT.get(a_type)
    if unit:
        if a_type == 7 and sch.get("interval_mode") == "fuzzy":
            try:
                mean_val = int(round(float(sch.get("fuzzy_mean", sch.get("interval", 1)))))
            except Exception:
                mean_val = 1
            try:
                std_val = int(round(float(sch.get("fuzzy_std", 0))))
            except Exception:
                std_val = 0
            interval_section.append(
                f"🔁 Interval: {_md_escape(f'Fuzzy ({mean_val}±{std_val}) days')}"
            )
        elif a_type == 7:
            try:
                interval = int(sch.get("interval", 1))
                if interval < 1:
                    interval = 1
            except Exception:
                interval = 1
            interval_section.append(
                f"🔁 Interval: {_md_escape(_format_interval_label(interval, unit))}"
            )
        else:
            interval = sch.get("interval", 1)
            interval_section.append(
                f"🔁 Interval: {_md_escape(_format_interval_label(interval, unit))}"
            )

    if is_repetition_supported(a_type):
        rep_label = format_repetition_human(a_type, alert.get("repetition"))
        if rep_label:
            interval_section.append(f"Repetition: {_md_escape(rep_label)}")

    time_str = sch.get("time")
    if time_str:
        interval_section.append(f"⏰ Time: {_md_escape(str(time_str))}")

    next_dt = _get_next_dt(alert)
    ordered_tokens = _ordered_pre_alerts(alert, next_dt)
    if ordered_tokens:
        pre_labels = [
            format_pre_alert_display(alert, token, due_dt=next_dt, user_prefs=user_prefs)
            for token in ordered_tokens
        ]
        pre_labels = [lbl for lbl in pre_labels if isinstance(lbl, str) and lbl.strip()]
        if pre_labels:
            interval_section.append(
                f"🔔 Pre-alert: {_md_escape(', '.join(pre_labels))}"
            )

    lines.extend(interval_section)
    if interval_section:
        lines.append("")

    # Additional info block
    info = (alert.get("additional_info") or "").strip()
    if info:
        lines.append(f"Additional info:\n{_md_escape_multiline_text(info)}")
        lines.append("")

    # Last triggered / Next scheduled
    last_triggered = _format_last_triggered(alert)
    if last_triggered:
        lines.append(f"Last Triggered: {last_triggered}")
    lines.append(f"Next Scheduled: {_format_next_scheduled_str(alert, next_dt)}")
    lines.append("")

    lines.append(format_tags_line(alert.get("tags") or []))
    return "\n".join(lines)


# =============================================================================
# IB — Birthday detail card
# =============================================================================

def format_ib(alert: dict, user_prefs=None) -> str:
    """Render the birthday detail card text (IB).

    Opens with `ℹ️ Detailed INFO` header, then birthday block (status icon
    prefix, name, birth date, current age when birth_year is known), pre-alert
    line, additional_info when non-empty, zodiac block when user_prefs enables
    it, and tags line.
    """
    status_dot = "🟢" if alert.get("active", True) else "🔴"
    name_caps = _md_escape_inline_code((alert.get("title") or "Untitled").upper())

    lines = [
        "ℹ️ Detailed INFO",
        "",
        f"{status_dot} ─ 🎂 Birthday of",
        f"`{name_caps}`",
        "",
    ]

    schedule = alert.get("schedule") or {}
    date_str = schedule.get("date") or ""
    birth_year = alert.get("birth_year")
    parts = date_str.split("/") if date_str else []

    if len(parts) == 2:
        try:
            day, month = int(parts[0]), int(parts[1])
            month_name = _md_escape(f"{day} {datetime(2000, month, 1).strftime('%B')}")
        except (ValueError, TypeError):
            month_name = _md_escape(date_str)
        if birth_year is not None:
            lines.append(f"Birth date: {month_name} {birth_year}")
            try:
                age = calculate_current_age(int(parts[0]), int(parts[1]), birth_year)
            except Exception:
                age = None
            if age is not None:
                lines.append(f"🎂 Current age: {age}")
        else:
            lines.append(f"Birth date: {month_name} *(year unknown)*")
    else:
        lines.append("Birth date: N/A")

    lines.append("")  # separator after birth date block

    # Pre-alert line
    next_dt = _get_next_dt(alert)
    ordered_tokens = _ordered_pre_alerts(alert, next_dt)
    if ordered_tokens:
        pre_labels = [
            format_pre_alert_display(alert, token, due_dt=next_dt, user_prefs=user_prefs)
            for token in ordered_tokens
        ]
        pre_labels = [lbl for lbl in pre_labels if isinstance(lbl, str) and lbl.strip()]
        if pre_labels:
            lines.append(f"🔔 Pre-alert: {_md_escape(', '.join(pre_labels))}")
            lines.append("")

    # Additional info block
    info = (alert.get("additional_info") or "").strip()
    if info:
        lines.append(f"Additional info:\n{_md_escape_multiline_text(info)}")
        lines.append("")

    # Zodiac block
    zodiac = append_zodiac_block(alert, user_prefs)
    if zodiac:
        lines.append(zodiac.lstrip("\n"))
        lines.append("")

    lines.append(format_tags_line(alert.get("tags") or []))
    return "\n".join(lines)
