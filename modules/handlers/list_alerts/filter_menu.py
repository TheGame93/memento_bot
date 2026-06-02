"""Build /list tag-filter menus and resolve filter callback payloads."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.callback_codec import (
    build_value_token_map,
    ensure_callback_fits,
    extract_callback_token,
    is_token_candidate,
)
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.shared.runtime_context import get_runtime_storage
from modules.tags_logic import partition_used_tags_by_master_order

logger = logging.getLogger(__name__)

LIST_CONTEXT_KEY = "compact_list_context"
FILTER_TOKEN_PREFIX = "filter_t"
ORPHAN_FILTER_CALLBACK_VALUE = "ORPHAN"
ORPHAN_FILTER_VALUE = ("__orphan_filter_state__",)
ORPHAN_FILTER_BUTTON_LABEL = "🧩 Orphan tag"
ORPHAN_FILTER_CALLBACK_DATA = f"filter_{ORPHAN_FILTER_CALLBACK_VALUE}"
UNTAGGED_FILTER_CALLBACK_VALUE = "UNTAGGED"
UNTAGGED_FILTER_VALUE = ("__untagged_filter_state__",)
UNTAGGED_FILTER_BUTTON_LABEL = "🏷️ Untagged"
UNTAGGED_FILTER_CALLBACK_DATA = f"filter_{UNTAGGED_FILTER_CALLBACK_VALUE}"


def _resolve_ids(update, context):
    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    return actor_id, target_id, acting_payload


def _collect_alert_tags(alerts, master_tags):
    used_known_tags, _orphan_tags = partition_used_tags_by_master_order(alerts, master_tags)
    return used_known_tags


def _collect_orphan_alert_tags(alerts, master_tags):
    _used_known_tags, orphan_tags = partition_used_tags_by_master_order(alerts, master_tags)
    return orphan_tags


def _build_filter_tag_token_map(alerts, master_tags):
    return build_value_token_map(_collect_alert_tags(alerts, master_tags))


def _is_orphan_filter_callback(callback_data):
    return callback_data == ORPHAN_FILTER_CALLBACK_DATA


def _is_untagged_filter_callback(callback_data):
    return callback_data == UNTAGGED_FILTER_CALLBACK_DATA


def _render_filter_label(tag_filter):
    if tag_filter == ORPHAN_FILTER_VALUE:
        return ORPHAN_FILTER_BUTTON_LABEL
    if tag_filter == UNTAGGED_FILTER_VALUE:
        return UNTAGGED_FILTER_BUTTON_LABEL
    return tag_filter


def _coerce_filter_tag_value(raw_tag):
    if raw_tag is None:
        return None
    if isinstance(raw_tag, str):
        return raw_tag
    return str(raw_tag)


def _alert_matches_known_tag_filter(alert, tag_filter):
    expected = _coerce_filter_tag_value(tag_filter)
    if expected is None or not isinstance(alert, dict):
        return False
    raw_tags = alert.get("tags")
    if not isinstance(raw_tags, list):
        return False
    for raw_tag in raw_tags:
        if _coerce_filter_tag_value(raw_tag) == expected:
            return True
    return False


def _alert_is_untagged(alert) -> bool:
    """Return whether an alert has no usable tags for tag-filter purposes."""
    if not isinstance(alert, dict):
        return True
    raw_tags = alert.get("tags")
    if not isinstance(raw_tags, list):
        return True
    for raw_tag in raw_tags:
        normalized = _coerce_filter_tag_value(raw_tag)
        if isinstance(normalized, str) and normalized.strip():
            return False
    return True


def _build_orphan_warning_text(orphan_tags, max_chars=3900):
    intro = (
        "⚠️ *Orphan tags found*\n"
        "Some alerts use tags that are missing from your master tag list (/tags).\n"
        "Use *🧩 Orphan tag* to review those alerts.\n\n"
        "*Orphan tags in use:*\n"
    )
    safe_tags = [_md_escape(tag) for tag in orphan_tags]
    limit = max(512, int(max_chars))
    lines = []

    for idx, tag in enumerate(safe_tags):
        line = f"• {tag}"
        remaining = len(safe_tags) - idx - 1
        suffix = (
            f"\n… and {remaining} more orphan tag(s)."
            if remaining > 0
            else ""
        )
        candidate = intro + "\n".join(lines + [line]) + suffix
        if len(candidate) > limit:
            omitted = remaining + 1
            if not lines:
                return intro + f"… and {omitted} orphan tag(s). Open /list and filter to inspect them."
            return intro + "\n".join(lines) + f"\n… and {omitted} more orphan tag(s)."
        lines.append(line)

    return intro + "\n".join(lines)


async def _send_orphan_warning_message(context, update, actor_id, orphan_tags):
    if not orphan_tags:
        return

    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    available_chars = max(512, 4096 - len(banner) - 16)
    warning_text = _build_orphan_warning_text(orphan_tags, max_chars=available_chars)
    await context.bot.send_message(
        chat_id=actor_id,
        text=f"{banner}{warning_text}",
        parse_mode=ParseMode.MARKDOWN,
    )


def _decode_filter_value(callback_data, token_map):
    if not isinstance(callback_data, str) or not callback_data.startswith("filter_"):
        return None
    raw = callback_data.replace("filter_", "", 1)
    if raw == "ALL":
        return "ALL"
    if raw == ORPHAN_FILTER_CALLBACK_VALUE:
        return ORPHAN_FILTER_VALUE
    if raw == UNTAGGED_FILTER_CALLBACK_VALUE:
        return UNTAGGED_FILTER_VALUE

    token = extract_callback_token(callback_data, FILTER_TOKEN_PREFIX)
    if token and is_token_candidate(token):
        resolved = token_map.get(token)
        if resolved is None:
            return None
        return resolved
    return raw


async def list_alerts_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the /list filter menu with known tags and optional orphan-tag warning."""
    storage = get_runtime_storage(context)
    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)
    query = update.callback_query
    if query:
        await query.answer()

    user_data = storage.get_all_alerts(user_id)
    source = "callback" if query else "command"
    total_alerts = 0
    if user_data and isinstance(user_data.get("alerts"), list):
        total_alerts = len([a for a in user_data.get("alerts", []) if a.get("type") != 6])
    payload = {"source": source, "count": total_alerts}
    payload.update(acting_payload)
    storage.log_user_event(user_id, "alerts_list_view", payload)
    if not user_data or not user_data.get("alerts"):
        target = query.message if query else update.message
        await target.reply_text("📭 You don't have any alerts yet. Use /alerts to create one!")
        return
    alerts_all = [a for a in user_data.get("alerts", []) if a.get("type") != 6]
    if not alerts_all:
        target = query.message if query else update.message
        await target.reply_text(
            "📭 You don't have any non-birthday alerts yet.\n"
            "Birthdays are shown with /birthdays."
        )
        return

    master_tags = storage.get_user_tags(user_id)
    used_known_tags = _collect_alert_tags(alerts_all, master_tags)
    orphan_tags = _collect_orphan_alert_tags(alerts_all, master_tags)
    has_untagged_alerts = any(_alert_is_untagged(alert) for alert in alerts_all)

    keyboard = [[InlineKeyboardButton("📋 ALL TAGS", callback_data="filter_ALL")]]
    tag_token_map = _build_filter_tag_token_map(alerts_all, master_tags)
    context.user_data["alerts_filter_token_map"] = tag_token_map

    tag_buttons = []
    tag_to_token = {tag: token for token, tag in tag_token_map.items()}
    for tag in used_known_tags:
        token = tag_to_token.get(tag)
        if not token:
            continue
        callback_data = f"{FILTER_TOKEN_PREFIX}{token}"
        if not ensure_callback_fits(callback_data):
            logger.warning("Skipping oversized callback payload for tag filter: %s", tag)
            continue
        tag_buttons.append(InlineKeyboardButton(tag, callback_data=callback_data))
    for i in range(0, len(tag_buttons), 2):
        keyboard.append(tag_buttons[i : i + 2])
    if orphan_tags:
        if ensure_callback_fits(ORPHAN_FILTER_CALLBACK_DATA):
            keyboard.append([
                InlineKeyboardButton(
                    ORPHAN_FILTER_BUTTON_LABEL,
                    callback_data=ORPHAN_FILTER_CALLBACK_DATA,
                )
            ])
        else:
            logger.warning("Skipping orphan filter button due oversized callback payload")
    if has_untagged_alerts:
        if ensure_callback_fits(UNTAGGED_FILTER_CALLBACK_DATA):
            keyboard.append([
                InlineKeyboardButton(
                    UNTAGGED_FILTER_BUTTON_LABEL,
                    callback_data=UNTAGGED_FILTER_CALLBACK_DATA,
                )
            ])
        else:
            logger.warning("Skipping untagged filter button due oversized callback payload")

    if query:
        if query.data in {"alert_list", "alert_filter_back"}:
            try:
                await query.message.delete()
            except Exception:
                pass
        await context.bot.send_message(
            chat_id=actor_id,
            text=f"{build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)}"
            "🔍 **Filter by Tag:**\nSelect a category to view:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
        await _send_orphan_warning_message(context, update, actor_id, orphan_tags)
    else:
        await update.message.reply_text(
            f"{build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)}"
            "🔍 **Filter by Tag:**\nSelect a category to view:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
        await _send_orphan_warning_message(context, update, actor_id, orphan_tags)
    return
