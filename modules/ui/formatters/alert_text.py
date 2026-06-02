"""
alert_text.py — Text formatters for non-birthday alert notifications.

Covers PA (pre-alert of alert), AA (alert notification), and the
missed-alert startup-recovery messages.  Birthday-specific renderers
live in birthday_text.py.

Layout for PA:
    🔔 UPCOMING ALERT

    ⚠️ This alert is due in <countdown>
    📅 Scheduled: `Mon 27 Mar - 10:00`

    📅 ─ `TITLE ALL IN CAPS`
    📑 Type: <type_name>

    [Additional info: <text>  ← only when non-empty]

    <tags line>

Layout for AA:
    📅 ─ `TITLE ALL IN CAPS`
    📑 Type: <type_name>

    [Additional info: <text>  ← only when non-empty]

    <tags line>
"""

from datetime import datetime

from modules.scheduler_mathlogic import format_datetime_human
from modules.shared.markdown_utils import (
    md_escape as _md_escape,
    md_escape_inline_code as _md_escape_inline_code,
    md_escape_multiline_text as _md_escape_multiline_text,
)
from modules.tags_logic import parse_tag
from modules.ui.formatters.shared import (
    format_next_occurrence_line,
    format_tags_line,
    format_time_until,
)


# =============================================================================
# PRE-ALERT NOTIFICATION (PA)
# =============================================================================

def format_pa(alert: dict, main_trigger_time, scheduled_time=None) -> str:
    """Render the pre-alert notification text for a non-birthday alert (PA).

    Opens with the UPCOMING ALERT header, countdown line, and main trigger
    datetime.  Follows with the title block (📅 ─ prefix), type line,
    additional_info when non-empty, and tags line.
    scheduled_time is accepted for API symmetry but is not rendered; the
    📅 Scheduled line always shows main_trigger_time (when the alert fires).
    """
    title = _md_escape_inline_code((alert.get("title") or "Untitled Alert").upper())
    type_name = _md_escape(alert.get("type_name") or "Unknown")
    time_until = format_time_until(main_trigger_time)
    main_time_str = _md_escape_inline_code(
        format_datetime_human(main_trigger_time) if main_trigger_time else "Unknown"
    )

    lines = [
        "🔔 UPCOMING ALERT",
        "",
        f"⚠️ This alert is due in {time_until}",
        f"📅 Scheduled: `{main_time_str}`",
        "",
        f"📅 ─ `{title}`",
        f"📑 Type: {type_name}",
        "",
    ]

    info = (alert.get("additional_info") or "").strip()
    if info:
        lines.append(f"Additional info:\n{_md_escape_multiline_text(info)}")
        lines.append("")

    lines.append(format_tags_line(alert.get("tags") or []))
    return "\n".join(lines)


# =============================================================================
# MAIN ALERT NOTIFICATION (AA)
# =============================================================================

def format_aa(alert: dict, scheduled_time=None, user_prefs=None) -> str:
    """Render the main alert notification text (AA).

    Contains the title block (📅 ─ prefix), type line, additional_info when
    non-empty, and tags line.  No header line — the notification itself
    is the delivery signal.  user_prefs is accepted for API symmetry with
    birthday formatters but is unused for non-birthday alerts.
    """
    title = _md_escape_inline_code((alert.get("title") or "Untitled Alert").upper())
    type_name = _md_escape(alert.get("type_name") or "Unknown")

    lines = [
        f"📅 ─ `{title}`",
        f"📑 Type: {type_name}",
        "",
    ]

    info = (alert.get("additional_info") or "").strip()
    if info:
        lines.append(f"Additional info:\n{_md_escape_multiline_text(info)}")
        lines.append("")

    lines.append(format_tags_line(alert.get("tags") or []))
    return "\n".join(lines)


def format_ghost_alert(alert: dict, trigger_time) -> str:
    """Render a ghost-reminder notification message."""
    raw_title = alert.get("title") or "Untitled Alert"
    if raw_title.startswith("👻 "):
        raw_title = raw_title[2:]
    title = _md_escape(raw_title)
    trigger_str = _md_escape_inline_code(format_datetime_human(trigger_time) if trigger_time else "Unknown")
    return (
        "👻 *Ghost Reminder*\n\n"
        f"📌 *{title}*\n"
        f"🕐 Scheduled: `{trigger_str}`\n\n"
        "_This is a ghost copy of a missed alert._"
    )


# =============================================================================
# MISSED-ALERT STARTUP RECOVERY (layout unchanged from scheduler_messagelogic)
# =============================================================================

def format_missed_alert(alert: dict, missed_time) -> str:
    """Render a missed-alert startup-recovery notification.

    Layout unchanged from scheduler_messagelogic.format_missed_alert;
    migrated here without restyling.
    """
    title = _md_escape((alert.get("title") or "Untitled Alert").upper())
    missed_str = _md_escape(format_datetime_human(missed_time))

    header = "🎂 **MISSED BIRTHDAY**" if alert.get("type") == 6 else "⚠️ **MISSED ALERT**"
    message = (
        f"{header}\n\n"
        f"📌 **{title}**\n\n"
        f"❌ Was scheduled for: `{missed_str}`\n"
        f"📱 Delivered now during startup recovery."
    )

    if alert.get("type") not in (5, 6):
        next_line = format_next_occurrence_line(alert, datetime.now())
        if next_line:
            message += f"\n\n📅 {next_line}"

    return message


def format_missed_alerts_summary(
    standard_items: list,
    missed_ghost_items: list | None = None,
    pending_ghost_alerts: list | None = None,
) -> str | None:
    """Render startup missed-alert summary sections for standard and ghost items.

    Return None when there are no standard items and no missed ghost items,
    so pending-only ghost reminders do not trigger a standalone summary.
    """
    missed_ghost_items = missed_ghost_items or []
    pending_ghost_alerts = pending_ghost_alerts or []
    if not standard_items and not missed_ghost_items:
        return None

    count = len(standard_items)
    message = (
        f"⚠️ **MISSED ALERTS SUMMARY**\n\n"
        f"Startup recovery found **{count}** alert(s) needing attention:\n\n"
    )

    now = datetime.now()

    def _fmt_pre(dt):
        if not dt:
            return "Unknown"
        date_str = dt.strftime("%a %d %b")
        time_str = dt.strftime("%H:%M")
        year_str = dt.strftime("%Y") if dt.year != now.year else ""
        if year_str:
            date_str = f"{date_str} ({year_str})"
        return f"{date_str} - {time_str}"

    def _fmt_due(dt):
        if not dt:
            return "Unknown"
        date_str = dt.strftime("%a %d/%m")
        time_str = dt.strftime("%H:%M")
        year_str = dt.strftime("%Y") if dt.year != now.year else ""
        if year_str:
            date_str = f"{date_str} ({year_str})"
        return f"{date_str} {time_str}"

    for item in standard_items[:20]:
        alert = item.get("alert") if isinstance(item, dict) else None
        if not alert:
            continue
        title = _md_escape(alert.get("title") or "Untitled")
        tags = alert.get("tags") or []
        tag_icons = "".join(_md_escape(parse_tag(t)[0]) for t in tags) if tags else ""
        title_line = f"{tag_icons} {title}".strip()
        message += f"{title_line}\n"

        missed_pre = item.get("missed_pre") or []
        missed_due = item.get("missed_due") or []
        upcoming_pre = item.get("upcoming_pre") or []
        upcoming_due = item.get("upcoming_due") or []

        for pre_time in sorted(missed_pre):
            message += f"❌ (🔔) `{_fmt_pre(pre_time)}`\n"
        for due_time in sorted(missed_due):
            message += f"❌ `{_fmt_due(due_time)}`\n"
        for pre_time in sorted(upcoming_pre):
            message += f"— (🔔) `{_fmt_pre(pre_time)}`\n"
        for due_time in sorted(upcoming_due):
            message += f"⟶ `{_fmt_due(due_time)}`\n"

        message += "\n"

    if count > 20:
        message += f"\n_...and {count - 20} more_"

    if missed_ghost_items or pending_ghost_alerts:
        message += "\n---\n👻 *Ghost reminders*\n\n"
        if missed_ghost_items:
            message += "Missed ghost copies (no action):\n"
            for item in missed_ghost_items[:20]:
                alert = item.get("alert") if isinstance(item, dict) else item
                if not isinstance(alert, dict):
                    continue
                title = _md_escape(alert.get("title") or "Untitled")
                message += f"• {title}\n"
            if len(missed_ghost_items) > 20:
                message += f"_...and {len(missed_ghost_items) - 20} more_\n"
            message += "\n"
        if pending_ghost_alerts:
            message += "Pending ghost copies (scheduled):\n"
            for alert in pending_ghost_alerts[:20]:
                if not isinstance(alert, dict):
                    continue
                title = _md_escape(alert.get("title") or "Untitled")
                next_scheduled = alert.get("next_scheduled")
                fire_text = "Unknown"
                if next_scheduled:
                    try:
                        fire_dt = datetime.fromisoformat(next_scheduled)
                        fire_text = _fmt_due(fire_dt)
                    except Exception:
                        fire_text = _md_escape(str(next_scheduled))
                message += f"• {title} — `{_md_escape(fire_text)}`\n"
            if len(pending_ghost_alerts) > 20:
                message += f"_...and {len(pending_ghost_alerts) - 20} more_\n"

    if len(message) > 4096:
        suffix = "\n_...and more_"
        message = message[: 4096 - len(suffix)].rstrip() + suffix

    return message
