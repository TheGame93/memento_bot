from datetime import datetime

from modules import constants as C
from modules import zodiac as _zodiac
from modules.shared.markdown_utils import (
    md_escape as _md_escape,
    md_escape_fence_content as _md_escape_fence_content,
    md_escape_inline_code as _md_escape_inline_code,
)

from modules.birthday_utils import calculate_current_age, calculate_turning_age
from modules.scheduler_mathlogic import (
    format_pre_alert_display,
    get_next_occurrence,
    resolve_pre_alert_fire_time,
)


def format_compact_date(dt):
    """Return a compact date label and include year only when needed."""
    if not dt:
        return "N/A"
    same_year = dt.year == datetime.now().year
    base = dt.strftime("%d %b").lower()
    return base if same_year else f"{base} {dt.strftime('%y')}"


def _normalize_time(value):
    text = "" if value is None else str(value).strip()
    try:
        dt = datetime.strptime(text, "%H:%M")
    except ValueError:
        return None
    return dt.strftime("%H:%M")


def _with_default_time(alert, default_time):
    if not isinstance(alert, dict):
        return alert
    schedule = alert.get("schedule") or {}
    time_str = _normalize_time(schedule.get("time"))
    fallback = _normalize_time(default_time) or _normalize_time(C.BIRTHDAY_DEFAULT_TIME)
    if time_str is None:
        time_str = fallback
    if schedule.get("time") == time_str:
        return alert
    cloned = dict(alert)
    cloned_schedule = dict(schedule)
    cloned_schedule["time"] = time_str
    cloned["schedule"] = cloned_schedule
    return cloned


def _resolve_compact_pre_alert_dates(alert, due_dt, user_prefs=None):
    """Resolve, deduplicate, and sort pre-alert fire datetimes for compact birthday list rows."""
    if due_dt is None or not isinstance(alert, dict):
        return []
    resolved_dates = []
    for token in alert.get("pre_alerts", []) or []:
        pre_dt, _kind = resolve_pre_alert_fire_time(
            alert,
            token,
            due_dt,
            user_prefs=user_prefs,
        )
        if pre_dt is not None:
            resolved_dates.append(pre_dt)
    return sorted({dt for dt in resolved_dates})


def build_compact_birthday_lines(page_items, default_time=None, user_prefs=None):
    """Build compact birthday list rows using resolved pre-alert datetime labels when due context exists."""
    lines = []
    alias_map = {}
    for idx, alert in enumerate(page_items, start=1):
        alias = f"{idx:02d}"
        alias_map[alias] = alert.get("id")
        status = "🟢" if alert.get("active", True) else "🔴"
        title = (alert.get("title") or "Untitled").strip().upper()
        effective_alert = _with_default_time(alert, default_time)
        due_dt = get_next_occurrence(effective_alert)
        lines.append(f"[/{alias}] {status} {title}")

        pre_dates = _resolve_compact_pre_alert_dates(
            effective_alert,
            due_dt,
            user_prefs=user_prefs,
        )
        pre_labels = [format_compact_date(pre_dt) for pre_dt in pre_dates]
        detail_parts = []
        if pre_labels:
            pre_str = ", ".join(pre_labels)
            detail_parts.append(f"🔔 {pre_str}")

        detail_parts.append(f"⏰ {format_compact_date(due_dt)}")
        if due_dt is not None and alert.get("birth_year") is not None:
            turning = calculate_turning_age(alert["birth_year"], due_dt.year)
            if turning is not None:
                detail_parts.append(f"(turns {turning})")
        lines.append(f"_____ {' '.join(detail_parts)}")
    return lines, alias_map


def format_bday_pre_alerts(data, *, due_dt=None, user_prefs=None):
    """Render birthday pre-alert labels and fallback to `None` when nothing is renderable."""
    pre_list = (data or {}).get("pre_alerts", [])
    if not pre_list:
        return "None"
    payload = data or {}
    resolved_due = due_dt
    if resolved_due is None:
        try:
            resolved_due = get_next_occurrence(payload)
        except Exception:
            resolved_due = None
    labels = [
        format_pre_alert_display(payload, token, due_dt=resolved_due, user_prefs=user_prefs)
        for token in pre_list
    ]
    labels = [label for label in labels if isinstance(label, str) and label.strip()]
    return ", ".join(labels) if labels else "None"


def format_bday_additional_info(data):
    """Return a compact birthday additional-info preview, or `None` when empty."""
    info = (data or {}).get("additional_info") or ""
    if not info:
        return "None"
    preview = info.replace("\n", " ⏎ ")
    if len(preview) > 60:
        preview = preview[:57] + "..."
    return preview


def format_birthday_summary(data, alert_id=None, user_prefs=None):
    """Build a Markdown-safe birthday summary with resolved pre-alert labels when available."""
    payload = data or {}
    schedule = payload.get("schedule") or {}
    date_label = schedule.get("date") or "N/A"
    time_label = schedule.get("time") or "N/A"

    shortcut_line = ""
    if payload.get("shortcode"):
        shortcode_safe = _md_escape_inline_code(payload.get("shortcode"))
        shortcut_line = f"**Shortcut:** `/{shortcode_safe}`\n"
    summary = (
        f"{'✅ **Birthday Saved Successfully!**' if alert_id else '📋 **Review Birthday**'}\n"
        f"{f'ID: `{alert_id}`' if alert_id else ''}\n"
        f"{shortcut_line}"
        f"**Name:** `{_md_escape_inline_code(payload.get('title'))}`\n"
        f"**Date:** `{_md_escape_inline_code(date_label)}`\n"
        f"**Time:** `{_md_escape_inline_code(time_label)}`\n"
    )
    birth_year = payload.get("birth_year")
    if birth_year is not None:
        parts = date_label.split("/") if date_label else []
        age = None
        if len(parts) == 2:
            try:
                age = calculate_current_age(int(parts[0]), int(parts[1]), birth_year)
            except (ValueError, TypeError):
                pass
        if age is not None:
            summary += f"**Current Age:** `{age}`\n"
    due_dt = None
    try:
        due_dt = get_next_occurrence(payload)
    except Exception:
        due_dt = None
    summary += (
        f"**Pre-Alerts:** "
        f"`{_md_escape_inline_code(format_bday_pre_alerts(payload, due_dt=due_dt, user_prefs=user_prefs))}`\n"
    )
    info = payload.get("additional_info") or ""
    if info:
        summary += f"**Additional Info:**\n```\n{_md_escape_fence_content(info)}\n```\n"
    else:
        summary += "**Additional Info:** `None`\n"
    tags_list = payload.get("tags", []) or []
    if tags_list:
        summary += f"**Tags:** `{_md_escape_inline_code(', '.join(tags_list))}`"

    zodiac_mode = (user_prefs or {}).get("birthday_zodiac_mode", C.BIRTHDAY_ZODIAC_MODE_NONE)
    if zodiac_mode != C.BIRTHDAY_ZODIAC_MODE_NONE:
        try:
            parts = date_label.split("/") if date_label and date_label != "N/A" else []
            day, month = int(parts[0]), int(parts[1])
            zodiac_info = _zodiac.get_zodiac_info(day, month, birth_year)
            western = zodiac_info.get("western")
            eastern = zodiac_info.get("eastern")
            if zodiac_mode in (C.BIRTHDAY_ZODIAC_MODE_WESTERN, C.BIRTHDAY_ZODIAC_MODE_BOTH):
                if western:
                    summary += f"\n**Zodiac:** {_md_escape(_zodiac.format_western_line(western))}"
            if zodiac_mode in (C.BIRTHDAY_ZODIAC_MODE_EASTERN, C.BIRTHDAY_ZODIAC_MODE_BOTH):
                if eastern:
                    summary += f"\n**Chinese Zodiac:** {_md_escape(_zodiac.format_eastern_line(eastern))}"
        except Exception:
            pass

    if alert_id:
        summary += "\n\n🚀 I will now start tracking this for you."
    return summary


def format_search_due(dt):
    """Return a search-facing due label, or `Not scheduled` when missing."""
    if not dt:
        return "Not scheduled"
    return dt.strftime("%d/%m/%Y at %H:%M")
