from datetime import datetime

from modules import constants as C
from modules.scheduler_mathlogic import format_pre_alert_display
from modules.repetition_utils import (
    format_repetition_human,
    is_repetition_supported,
    normalize_repetition_payload,
)
from modules.shared.markdown_utils import md_escape_fence_content, md_escape_inline_code
from modules.timezone_utils import (
    compute_next_occurrence,
    now_server_naive,
    normalize_one_time_date,
    resolve_user_timezone,
    to_server_naive_from_user,
    to_user_naive_from_server,
)

def ensure_default_settings(data):
    """Populate missing alert defaults and normalize daily/repetition schedule invariants."""
    if data is None:
        return
    schedule = data.get("schedule")
    if not isinstance(schedule, dict):
        schedule = {}
        data["schedule"] = schedule
    if not schedule.get("time"):
        schedule["time"] = "10:00"
    if data.get("pre_alerts") is None:
        data["pre_alerts"] = []
    if data.get("additional_info") is None:
        data["additional_info"] = ""
    alert_type = data.get("type")
    if alert_type in [1, 2, 3, 4, 7]:
        if not schedule.get("interval"):
            schedule["interval"] = 1
    if alert_type == 7 and "interval_mode" not in schedule:
        schedule["interval_mode"] = "fixed"
    if is_repetition_supported(alert_type):
        data["repetition"] = normalize_repetition_payload(alert_type, data.get("repetition"))
    else:
        data.pop("repetition", None)


def format_interval(data):
    """Return a human-readable interval label for recurring alert types."""
    alert_type = data.get("type")
    schedule = data.get("schedule") or {}
    interval = schedule.get("interval", 1)
    if alert_type in [1, 2]:
        unit = "month" if interval == 1 else "months"
        return f"Every {interval} {unit}"
    if alert_type == 3:
        unit = "week" if interval == 1 else "weeks"
        return f"Every {interval} {unit}"
    if alert_type == 4:
        unit = "year" if interval == 1 else "years"
        return f"Every {interval} {unit}"
    if alert_type == 7:
        if schedule.get("interval_mode") == "fuzzy":
            try:
                mean_val = int(round(float(schedule.get("fuzzy_mean", interval))))
            except Exception:
                mean_val = int(interval) if str(interval).isdigit() else 1
            try:
                std_val = int(round(float(schedule.get("fuzzy_std", 0))))
            except Exception:
                std_val = 0
            return f"Fuzzy ({mean_val}±{std_val}) days"
        unit = "day" if interval == 1 else "days"
        return f"Every {interval} {unit}"
    return "N/A"


def format_pre_alerts(data, *, due_dt=None, user_prefs=None, reference_time=None):
    """Render pre-alert entries using resolved datetime labels when due context is available."""
    payload = data or {}
    pre_list = list(payload.get("pre_alerts") or [])
    if not pre_list:
        return "None"

    resolved_due = due_dt
    schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
    is_fuzzy_daily = payload.get("type") == 7 and schedule.get("interval_mode") == "fuzzy"
    if resolved_due is None and is_fuzzy_daily:
        raw_next = payload.get("next_scheduled")
        if isinstance(raw_next, str) and raw_next.strip():
            try:
                resolved_due = datetime.fromisoformat(raw_next)
            except Exception:
                resolved_due = None

    if resolved_due is None and not is_fuzzy_daily:
        server_ref = _resolve_reference_server_time(reference_time, user_prefs)
        try:
            resolved_due, _shifted = compute_next_occurrence(payload, server_ref, user_prefs)
        except Exception:
            resolved_due = None

    labels = [
        format_pre_alert_display(payload, token, due_dt=resolved_due, user_prefs=user_prefs)
        for token in pre_list
    ]
    cleaned = [label for label in labels if isinstance(label, str) and label.strip()]
    return ", ".join(cleaned) if cleaned else "None"


def format_repetition(data):
    """Return the repetition summary label for the current alert payload."""
    payload = data or {}
    return format_repetition_human(payload.get("type"), payload.get("repetition"))


def format_photo_choice(data):
    """Return whether the alert currently has an image attachment."""
    return "Yes" if data.get("image_id") else "No"


def format_additional_info(data):
    """Return a compact additional-info preview, or `None` when empty."""
    info = data.get("additional_info") or ""
    if not info:
        return "None"
    preview = info.replace("\n", " ⏎ ")
    if len(preview) > 60:
        preview = preview[:57] + "..."
    return preview


def _resolve_reference_time(reference_time, user_prefs):
    if reference_time is not None:
        return reference_time
    if not isinstance(user_prefs, dict):
        return now_server_naive()
    mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    if mode != C.TIMEZONE_MODE_USER:
        return now_server_naive()
    user_tz = resolve_user_timezone(user_prefs)
    return to_user_naive_from_server(now_server_naive(), user_tz)


def _resolve_reference_server_time(reference_time, user_prefs):
    if reference_time is None:
        return now_server_naive()
    if not isinstance(user_prefs, dict):
        return reference_time
    mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    if mode != C.TIMEZONE_MODE_USER:
        return reference_time
    user_tz = resolve_user_timezone(user_prefs)
    server_dt, _ = to_server_naive_from_user(reference_time, user_tz)
    return server_dt


def is_one_time_past(data, reference_time=None, user_prefs=None):
    """Check whether a one-time alert resolves to a past-or-now datetime."""
    if (data or {}).get("type") != 5:
        return False
    schedule = (data or {}).get("schedule", {})
    date_str = schedule.get("date")
    time_str = schedule.get("time") or "10:00"
    if not date_str:
        return False
    now = _resolve_reference_time(reference_time, user_prefs)
    server_ref = _resolve_reference_server_time(reference_time, user_prefs)
    status, normalized, _assumed, _reason = normalize_one_time_date(
        date_str,
        reference_server_dt=server_ref,
        user_prefs=user_prefs,
        require_year_if_today=False,
        time_str=time_str,
    )
    if status != "ok" or not normalized:
        return False
    try:
        date_part = datetime.strptime(normalized, "%d/%m/%Y")
        time_part = datetime.strptime(time_str, "%H:%M").time()
        candidate = date_part.replace(hour=time_part.hour, minute=time_part.minute, second=0, microsecond=0)
    except Exception:
        return False
    return candidate <= now


def format_alert_summary(data, alert_id=None, user_prefs=None, reference_time=None):
    """Build a Markdown-safe detailed alert summary for preview and save flows."""
    payload = data or {}
    schedule = payload.get("schedule") or {}
    shortcode_line = ""
    if payload.get("shortcode"):
        shortcode_line = f"**Shortcut:** `/{md_escape_inline_code(payload.get('shortcode'))}`\n"
    summary = (
        f"{'✅ **Alert Saved Successfully!**' if alert_id else '📋 **Review Alert**'}\n"
        f"{f'ID: `{alert_id}`' if alert_id else ''}\n"
        f"{shortcode_line}"
        f"**Title:** `{md_escape_inline_code(payload.get('title'))}`\n"
        f"**Type:** `{md_escape_inline_code(payload.get('type_name'))}`\n"
        f"**Time:** `{md_escape_inline_code(schedule.get('time'))}`\n"
        f"**Interval:** `{md_escape_inline_code(format_interval(payload))}`\n"
    )
    if is_repetition_supported(payload.get("type")):
        summary += f"**Repetition:** `{md_escape_inline_code(format_repetition(payload))}`\n"
    summary += (
        f"**Pre-Alerts:** "
        f"`{md_escape_inline_code(format_pre_alerts(payload, user_prefs=user_prefs, reference_time=reference_time))}`\n"
    )
    fifth_policy = schedule.get("fifth_policy")
    if payload.get("type") == 2 and fifth_policy:
        policy_label = "Skip that month" if fifth_policy == "skip" else "Alert on the 4th instead"
        summary += f"**5th day policy:** `{md_escape_inline_code(policy_label)}`\n"
    info = payload.get("additional_info") or ""
    if info:
        safe_info = md_escape_fence_content(info)
        summary += f"**Additional Info:**\n```\n{safe_info}\n```\n"
    else:
        summary += "**Additional Info:** `None`\n"
    tags_list = payload.get("tags", []) or []
    if tags_list:
        summary += f"**Tags:** `{md_escape_inline_code(', '.join(tags_list))}`\n"
    summary += f"**Image:** `{md_escape_inline_code(format_photo_choice(payload))}`"
    if is_one_time_past(payload, reference_time=reference_time, user_prefs=user_prefs):
        summary += (
            "\n\n⚠️ **Past one-time date detected.**\n"
            "After saving, this alert will be delivered immediately (one time only)."
        )
    if alert_id:
        summary += "\n\n🚀 I will now start tracking this for you."
    return summary
