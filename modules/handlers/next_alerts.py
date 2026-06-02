import logging
import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from modules.scheduler_mathlogic import get_next_occurrence, parse_pre_alert_string
from modules.tags_logic import parse_tag
from modules import constants as C
from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.shared.acting_as import build_acting_as_banner, build_acting_as_payload, get_actor_user_id, get_target_user_id
from modules.shared.runtime_context import get_runtime_storage

logger = logging.getLogger(__name__)

def _parse_threshold(raw_value):
    if not raw_value:
        return None, None
    text = raw_value.strip().lower()
    match = re.match(r"^(\d+)\s*([a-z]+)$", text)
    if not match:
        return None, None
    value = int(match.group(1))
    unit_raw = match.group(2)
    unit_map = {
        "h": "h", "hour": "h", "hours": "h",
        "d": "d", "day": "d", "days": "d",
        "w": "w", "week": "w", "weeks": "w",
        "m": "m", "month": "m", "months": "m",
        "y": "y", "year": "y", "years": "y",
    }
    return value, unit_map.get(unit_raw)


def _is_priority(now, event_time, threshold_str):
    value, unit = _parse_threshold(threshold_str)
    if not value or not unit:
        # Fallback to legacy logic
        return (event_time - now).days < 2

    if unit == "h":
        return event_time <= now + timedelta(hours=value)
    if unit == "w":
        return event_time <= now + timedelta(weeks=value)
    if unit == "d":
        # Calendar-day rounding (date-based)
        day_diff = (event_time.date() - now.date()).days
        return day_diff <= value
    if unit == "m":
        return event_time <= now + relativedelta(months=value)
    if unit == "y":
        return event_time <= now + relativedelta(years=value)

    return (event_time - now).days < 2

async def show_next_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays the exactly next 7 items in the schedule.
    """
    storage = get_runtime_storage(context)
    query = update.callback_query
    if query:
        await query.answer()
        if query.data == "alert_next":
            try:
                await query.message.delete()
            except Exception:
                pass
    actor_id = get_actor_user_id(update)
    user_id = get_target_user_id(update, context)
    payload = {"source": "callback" if query else "command"}
    payload.update(build_acting_as_payload(update, context))
    storage.log_user_event(user_id, "command_next", payload)
    data = storage.get_all_alerts(user_id)
    alerts = data.get('alerts', [])
    postpone_items = data.get('postpone_queue', []) or []
    
    if not alerts:
        target = query.message if query else update.message
        await target.reply_text(
            f"{build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)}"
            "📭 No alerts found.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    now = datetime.now()
    upcoming = []
    alert_map = {a.get("id"): a for a in alerts if a.get("id")}
    postponed_pre_by_alert = {}
    postponed_due_events = []

    for item in postpone_items:
        if item.get("status") != "pending":
            continue
        try:
            fire_at = datetime.fromisoformat(item.get("fire_at"))
        except Exception:
            continue
        if fire_at < now:
            continue
        alert = alert_map.get(item.get("alert_id"))
        if not alert or not alert.get("active", True):
            continue
        if alert.get("type") == 6:
            continue
        if item.get("kind") == "pre":
            postponed_pre_by_alert.setdefault(alert.get("id"), []).append(fire_at)
        else:
            postponed_due_events.append({
                "time": fire_at,
                "title": alert.get('title', 'Untitled'),
                "tags": alert.get('tags', []),
                "pre_alerts": [],
                "alert_id": alert.get("id"),
            })

    for a in alerts:
        if not a.get('active', True):
            continue
        if a.get('type') == 6:
            continue
        
        next_run = get_next_occurrence(a, now)
        if next_run:
            upcoming.append({
                "time": next_run,
                "title": a.get('title', 'Untitled'),
                "tags": a.get('tags', []),
                "pre_alerts": a.get('pre_alerts', []),
                "alert_id": a.get("id"),
            })

    # Include postponed due instances as separate events
    upcoming.extend(postponed_due_events)

    # Sort and slice to exactly 7 items
    upcoming.sort(key=lambda x: x['time'])
    top_7 = upcoming[:7]
    if not top_7:
        source = "callback" if query else "command"
        view_payload = {
            "source": source,
            "count": 0,
            "items_with_tags": 0,
            "items_with_pre_alerts": 0,
            "items_priority": 0,
            "postponed_pre_alerts_merged": 0,
        }
        view_payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "alerts_next_view", view_payload)
        target = query.message if query else update.message
        await target.reply_text(
            f"{build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)}"
            "📅 No future occurrences scheduled.\nBirthdays are shown with /birthdays.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = "⏩ Next 7 Alerts\n━━━━━━━━━━━━━━\n(press the number for INFO)\n\n"
    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    if banner:
        msg = f"{banner}{msg}"
    alias_map = {}
    alias_idx = 0
    items_with_tags = 0
    items_with_pre_alerts = 0
    items_priority = 0
    postponed_pre_alerts_merged = 0
    for item in top_7:
        alias_idx += 1
        alias = f"{alias_idx:02d}"
        if item.get("alert_id"):
            alias_map[alias] = item.get("alert_id")
        tags = item.get("tags", [])
        tag_icons = "".join([parse_tag(t)[0] for t in tags]) if tags else ""
        safe_title = _md_escape(item.get("title") or "Untitled")
        if tag_icons:
            items_with_tags += 1
        if tag_icons:
            msg += f"/{alias} `:` {tag_icons} `:` {safe_title}\n"
        else:
            msg += f"/{alias} `:` {safe_title}\n"

        pre_alerts = item.get("pre_alerts", [])
        extra_pre = postponed_pre_by_alert.get(item.get("alert_id"), []) if item.get("alert_id") else []
        base_pre_times = []
        for pre_alert in pre_alerts:
            delta = parse_pre_alert_string(pre_alert)
            if not delta:
                continue
            pre_time = item["time"] - delta
            if pre_time >= now:
                base_pre_times.append(pre_time.replace(second=0, microsecond=0))

        base_pre_set = set(base_pre_times)
        extra_pre_valid = [pre_time.replace(second=0, microsecond=0) for pre_time in extra_pre if pre_time >= now]
        extra_pre_set = set(extra_pre_valid)
        merged_extra = sorted(extra_pre_set - base_pre_set)
        if merged_extra:
            postponed_pre_alerts_merged += len(merged_extra)

        pre_times = sorted(base_pre_set | extra_pre_set)
        if pre_times:
            items_with_pre_alerts += 1
            for pre_time in pre_times:
                pre_date = pre_time.strftime("%a %d %b")
                pre_time_str = pre_time.strftime("%H:%M")
                pre_year = pre_time.strftime("%Y") if pre_time.year != now.year else ""
                if pre_year:
                    pre_date = f"{pre_date} ({pre_year})"
                msg += f"├─ 🔔 `{pre_date} — {pre_time_str}`\n"

        date_str = item['time'].strftime("%a %d %b")
        time_str = item['time'].strftime("%H:%M")
        year_str = item['time'].strftime("%Y") if item['time'].year != now.year else ""
        if year_str:
            date_str = f"{date_str} ({year_str})"
        due_icon = "🔥" if _is_priority(now, item['time'], C.NEXT_PRIORITY_THRESHOLD) else "🗓"
        if due_icon == "🔥":
            items_priority += 1
        msg += f"╰─ {due_icon} `{date_str} — {time_str}`\n"
        msg += "\n"

    source = "callback" if query else "command"
    view_payload = {
        "source": source,
        "count": len(top_7),
        "items_with_tags": items_with_tags,
        "items_with_pre_alerts": items_with_pre_alerts,
        "items_priority": items_priority,
        "postponed_pre_alerts_merged": postponed_pre_alerts_merged,
    }
    view_payload.update(build_acting_as_payload(update, context))
    storage.log_user_event(user_id, "alerts_next_view", view_payload)

    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "next_alerts",
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }

    target_chat = actor_id or user_id
    if query:
        await context.bot.send_message(chat_id=target_chat, text=msg, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
