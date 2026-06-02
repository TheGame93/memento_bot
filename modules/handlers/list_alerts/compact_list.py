"""Render paginated compact alert lists and persist list navigation context."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.scheduler_mathlogic import get_next_occurrence, resolve_pre_alert_fire_time
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage
from modules.tags_logic import alert_has_any_orphan_tag

from .filter_menu import (
    FILTER_TOKEN_PREFIX,
    LIST_CONTEXT_KEY,
    ORPHAN_FILTER_VALUE,
    UNTAGGED_FILTER_VALUE,
    _alert_is_untagged,
    _alert_matches_known_tag_filter,
    _build_filter_tag_token_map,
    _collect_orphan_alert_tags,
    _decode_filter_value,
    _is_orphan_filter_callback,
    _is_untagged_filter_callback,
    _render_filter_label,
)

logger = logging.getLogger(__name__)


def _resolve_ids(update, context):
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    return actor_id, target_id, acting_payload


def _format_dt_for_list(dt, include_time=True):
    if not dt:
        return "Not scheduled"
    same_year = dt.year == datetime.now().year
    if include_time:
        return dt.strftime("%d %b - %H:%M") if same_year else dt.strftime("%d %b %Y - %H:%M")
    return dt.strftime("%d %b") if same_year else dt.strftime("%d %b %Y")


def _parse_iso_dt(raw):
    try:
        return datetime.fromisoformat(raw) if raw else None
    except Exception:
        return None


def _format_compact_date(dt):
    if not dt:
        return "N/A"
    same_year = dt.year == datetime.now().year
    base = dt.strftime("%d %b").lower()
    return base if same_year else f"{base} {dt.strftime('%y')}"


def _compact_title(alert):
    return (alert.get("title") or "Untitled").strip().upper()


def _compute_pre_alert_dates(alert, due_dt, user_prefs=None):
    dates = []
    if not due_dt:
        return dates
    for token in alert.get("pre_alerts", []) or []:
        pre_dt, _kind = resolve_pre_alert_fire_time(
            alert,
            token,
            due_dt,
            user_prefs=user_prefs,
        )
        if not pre_dt:
            continue
        dates.append(pre_dt)
    unique_sorted = sorted({d for d in dates})
    return unique_sorted


def _get_next_dt(alert):
    next_dt = _parse_iso_dt(alert.get("next_scheduled"))
    if next_dt:
        return next_dt
    return get_next_occurrence(alert)


def _build_compact_lines(page_items, show_due_time=False, user_prefs=None):
    lines = []
    alias_map = {}
    for idx, alert in enumerate(page_items, start=1):
        alias = f"{idx:02d}"
        alias_map[alias] = alert.get("id")
        due_dt = _get_next_dt(alert)
        status = "🟢" if alert.get("active", True) else "🔴"
        has_picture = bool(alert.get("image_id") or alert.get("local_image_path"))
        picture_icon = " 🖼️" if has_picture else ""
        lines.append(f"[/{alias}] {status} {_compact_title(alert)}{picture_icon}")

        detail_parts = []
        pre_dates = _compute_pre_alert_dates(alert, due_dt, user_prefs=user_prefs)
        if pre_dates:
            pre_labels = list(dict.fromkeys(_format_compact_date(pre_dt) for pre_dt in pre_dates))
            if pre_labels:
                pre_str = ", ".join(pre_labels)
                detail_parts.append(f"🔔 {pre_str}")

        due_str = _format_compact_date(due_dt)
        if show_due_time and due_dt:
            due_str = f"{due_str} {due_dt.strftime('%H:%M')}"
        detail_parts.append(f"⏰ {due_str}")
        lines.append(f"_____ {' '.join(detail_parts)}")
    return lines, alias_map


def _save_compact_context(context, source, tag_filter, page, alias_map):
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": source,
        "tag_filter": tag_filter,
        "page": page,
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }


def _get_compact_context(context):
    data = context.user_data.get(LIST_CONTEXT_KEY)
    if isinstance(data, dict):
        return data
    return {}


async def show_alerts_list(update: Update, context: ContextTypes.DEFAULT_TYPE, manual_tag=None, manual_page=None):
    """Show a paginated alert list for the selected tag filter, including orphan mode."""
    query = update.callback_query
    if query and isinstance(query.data, str) and (
        query.data.startswith("filter_") or query.data.startswith("alpage_")
    ):
        await query.answer()

    current_page = int(manual_page or 1)
    if query and query.data.startswith("alpage_"):
        if query.data == "alpage_noop":
            return
        current_page = context.user_data.get("alerts_current_page", 1)
        if query.data.endswith("next"):
            current_page += 1
        elif query.data.endswith("prev"):
            current_page -= 1

    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    storage = get_runtime_storage(context)
    data = storage.get_all_alerts(user_id) or {"alerts": []}
    user_prefs = storage.get_user_prefs(user_id) or {}
    alerts_all = [a for a in data.get("alerts", []) if a.get("type") != 6]
    master_tags = storage.get_user_tags(user_id)
    orphan_tags = _collect_orphan_alert_tags(alerts_all, master_tags)
    has_untagged_alerts = any(_alert_is_untagged(alert) for alert in alerts_all)
    tag_token_map = _build_filter_tag_token_map(alerts_all, master_tags)
    context.user_data["alerts_filter_token_map"] = tag_token_map

    if manual_tag is not None:
        tag_filter = manual_tag
    elif query and query.data.startswith("filter_"):
        decoded = _decode_filter_value(query.data, tag_token_map)
        if decoded is None:
            stale_text = "⚠️ This filter is no longer available. Open /list and try again."
            if _is_orphan_filter_callback(query.data):
                stale_text = "⚠️ Orphan filter is no longer available. Open /list and try again."
            elif _is_untagged_filter_callback(query.data):
                stale_text = "⚠️ Untagged filter is no longer available. Open /list and try again."
            await context.bot.send_message(
                chat_id=actor_id,
                text=stale_text,
            )
            return
        tag_filter = decoded
    else:
        tag_filter = context.user_data.get("current_filter", "ALL")

    if tag_filter == ORPHAN_FILTER_VALUE and not orphan_tags:
        await context.bot.send_message(
            chat_id=actor_id,
            text="⚠️ Orphan filter is no longer available. Open /list and try again.",
        )
        return
    if tag_filter == UNTAGGED_FILTER_VALUE and not has_untagged_alerts:
        await context.bot.send_message(
            chat_id=actor_id,
            text="⚠️ Untagged filter is no longer available. Open /list and try again.",
        )
        return

    context.user_data["current_filter"] = tag_filter
    context.user_data["manage_source"] = "alerts"

    alerts = list(alerts_all)
    if tag_filter == ORPHAN_FILTER_VALUE:
        alerts = [a for a in alerts if alert_has_any_orphan_tag(a, master_tags)]
    elif tag_filter == UNTAGGED_FILTER_VALUE:
        alerts = [a for a in alerts if _alert_is_untagged(a)]
    elif tag_filter != "ALL":
        alerts = [
            a
            for a in alerts
            if _alert_matches_known_tag_filter(a, tag_filter)
        ]
    filter_label = _render_filter_label(tag_filter)

    if not alerts:
        await context.bot.send_message(
            chat_id=actor_id,
            text=f"📭 No alerts found for: {filter_label}\nBirthdays are shown with /birthdays.",
        )
        return

    alerts.sort(key=lambda a: (_get_next_dt(a) or datetime.max, a.get("created_at", "")))
    per_page = int(getattr(C, "LIST_PAGE_SIZE", 20))
    total_pages = max(1, (len(alerts) + per_page - 1) // per_page)
    current_page = max(1, min(total_pages, current_page))
    context.user_data["alerts_current_page"] = current_page

    start = (current_page - 1) * per_page
    end = start + per_page
    page_items = alerts[start:end]

    compact_lines, alias_map = _build_compact_lines(page_items, show_due_time=False, user_prefs=user_prefs)
    _save_compact_context(context, "alerts", tag_filter, current_page, alias_map)

    header = f"📂 Alerts | Tag: {filter_label} | Page {current_page}/{total_pages}"
    text = header + "\n(press the number for INFO)\n\n" + "\n".join(compact_lines)
    banner = build_acting_as_banner(update, context, parse_mode="Markdown")
    if banner:
        text = f"{banner}{text}"

    nav_row = [
        InlineKeyboardButton("⬅️ Prev", callback_data="alpage_prev"),
        InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="alpage_noop"),
        InlineKeyboardButton("Next ➡️", callback_data="alpage_next"),
    ]
    footer_row = [InlineKeyboardButton("⬅️ Back to tag search", callback_data="alert_filter_back")]

    if current_page <= 1:
        nav_row[0] = InlineKeyboardButton("·", callback_data="alpage_noop")
    if current_page >= total_pages:
        nav_row[2] = InlineKeyboardButton("·", callback_data="alpage_noop")

    keyboard = InlineKeyboardMarkup([nav_row, footer_row])
    if query:
        try:
            await query.message.delete()
        except Exception:
            pass
    await context.bot.send_message(chat_id=actor_id, text=text, reply_markup=keyboard)
