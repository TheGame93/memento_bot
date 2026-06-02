from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from modules.tags_logic import get_tag_stats, parse_tag
from modules import constants as C
from modules.scheduler_mathlogic import get_next_occurrence
from modules.shared.logging_utils import hash_text, text_meta
from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.systemlog import log_system
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage


def _is_markdown_parse_error(exc):
    if not isinstance(exc, BadRequest):
        return False
    raw = str(exc or "")
    text = raw.strip().lower()
    if not text:
        return False
    return "can't parse entities" in text


async def alerts_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the alerts home menu with tag statistics and markdown fallback handling."""
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)
    user_data = storage.get_all_alerts(user_id)
    if not user_data:
        storage.setup_user_space(user_id)
        user_data = storage.get_all_alerts(user_id)

    storage.log_user_event(user_id, "command_alerts", acting_payload)

    stats, untagged = get_tag_stats(user_data)
    tags_list = user_data.get("tags", [])

    lines = [
        "🔔 **Alerts**",
        "",
        "Your Tags:",
    ]
    tag_lines_budget = 3600 - sum(len(l) for l in lines)
    tag_lines_len = 0
    shown = 0
    for tag in tags_list:
        emoji, name = parse_tag(tag)
        safe_name = _md_escape(name)
        count = stats.get(tag, 0)
        line = f"• {emoji} {safe_name}: {count} alerts"
        if tag_lines_len + len(line) > tag_lines_budget:
            lines.append(f"_… and {len(tags_list) - shown} more tags_")
            break
        lines.append(line)
        tag_lines_len += len(line)
        shown += 1
    lines.append(f"• ⚪ Untagged alerts: {untagged}")
    lines.append("")
    lines.append("Choose an action:")

    keyboard = [
        [
            InlineKeyboardButton("➕ Add Alert", callback_data="alert_add"),
            InlineKeyboardButton("⏩ Next Alerts", callback_data="alert_next")
        ],
        [
            InlineKeyboardButton("🔎 Search Alerts", callback_data="alert_search"),
            InlineKeyboardButton("📋 Show ALL Alerts", callback_data="alert_list")
        ]
    ]
    text = "\n".join(lines)
    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    render_text = f"{banner}{text}"
    target_message = update.message or update.effective_message
    if target_message is None:
        return

    try:
        await target_message.reply_text(
            render_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    except BadRequest as exc:
        if not _is_markdown_parse_error(exc):
            raise

        text_signal = text_meta(render_text)
        fallback_payload = {
            "source": "callback" if update.callback_query else "command",
            "reason_code": "markdown_parse_error",
            "fallback_mode": "plain_text",
            "message_text_len": text_signal["len"],
            "message_text_hash": text_signal["hash"],
        }
        fallback_payload.update(acting_payload)
        storage.log_user_event(user_id, "alerts_menu_markdown_fallback", fallback_payload)
        log_system("api", "menu_markdown_parse_failed", {
            "menu": "alerts",
            "user_id": str(user_id),
            "reason_code": "markdown_parse_error",
            "message_text_len": text_signal["len"],
            "message_text_hash": text_signal["hash"],
        }, level="WARNING")

        try:
            await target_message.reply_text(
                render_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as fallback_exc:
            fallback_failed_payload = {
                "source": "callback" if update.callback_query else "command",
                "reason_code": "fallback_send_failed",
                "error_type": fallback_exc.__class__.__name__,
            }
            fallback_failed_payload.update(acting_payload)
            storage.log_user_event(user_id, "alerts_menu_markdown_fallback_failed", fallback_failed_payload)
            log_system("api", "menu_markdown_fallback_failed", {
                "menu": "alerts",
                "user_id": str(user_id),
                "reason_code": "fallback_send_failed",
                "error_type": fallback_exc.__class__.__name__,
            }, level="ERROR")
            raise

        fallback_sent_payload = {
            "source": "callback" if update.callback_query else "command",
            "reason_code": "fallback_plain_text_ok",
        }
        fallback_sent_payload.update(acting_payload)
        storage.log_user_event(user_id, "alerts_menu_markdown_fallback_sent", fallback_sent_payload)
        log_system("api", "menu_markdown_fallback_sent", {
            "menu": "alerts",
            "user_id": str(user_id),
            "reason_code": "fallback_plain_text_ok",
        })


def _get_alerts(storage, user_id, include_inactive=False):
    data = storage.get_all_alerts(user_id) or {}
    alerts = [a for a in data.get("alerts", []) if a.get("type") != 6]
    if not include_inactive:
        alerts = [a for a in alerts if a.get("active", True)]
    return alerts


def rank_alerts_by_name(query_text, alerts):
    """Ranks only non-birthday alerts by title similarity."""
    from modules.handlers.birthdays import rank_birthdays_by_name
    filtered = [a for a in (alerts or []) if a.get("type") != 6]
    return rank_birthdays_by_name(query_text, filtered)


def _format_search_due(dt):
    if not dt:
        return "Not scheduled"
    return dt.strftime("%d/%m/%Y at %H:%M")


async def alert_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables free-text alert search mode from /alerts menu button."""
    query = update.callback_query
    await query.answer()
    context.user_data["expecting_alert_search"] = True
    context.user_data.pop("expecting_birthday_search", None)
    try:
        await query.message.delete()
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=get_actor_user_id(update),
        text=(
            f"{build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)}"
            "🔎 **Search Alerts**\n\n"
            "Send one or more words to search by alert title.\n"
            "Examples:\n"
            "• dentist\n"
            "• pay bills\n"
            "• month report\n\n"
            "Type /cancel to stop."
        ),
        parse_mode=ParseMode.MARKDOWN
    )


async def alert_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fuzzy-search non-birthday alerts by title."""
    storage = get_runtime_storage(context)

    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "🔎 Search query is empty.\n"
            "Write one or more words, e.g.:\n"
            "• dentist\n"
            "• month report",
        )
        return

    alerts = _get_alerts(storage, user_id, include_inactive=True)
    if not alerts:
        await update.message.reply_text("🔔 No alerts available yet.")
        return

    query_norm, ranked = rank_alerts_by_name(query, alerts)
    min_score = int(getattr(C, "ALERT_SEARCH_MIN_SCORE", 75))
    top_n = max(1, int(getattr(C, "ALERT_SEARCH_TOP_N", 5)))
    matched = [item for item in ranked if item["score"] >= min_score][:top_n]
    payload = {
        "query_len": len(query),
        "query_hash": hash_text(query),
        "total_alerts": len(alerts),
        "matched": len(matched),
        "min_score": min_score,
        "top_n": top_n,
    }
    payload.update(acting_payload)
    storage.log_user_event(user_id, "alert_search", payload)

    if not matched:
        hints = ranked[:3]
        lines = [
            "🔎 Alert Search",
            f"Query: {query}",
            "",
            f"No strong matches (min score: {min_score}).",
            "Send another text to retry, or /cancel to stop.",
        ]
        if hints:
            lines.append("")
            lines.append("Closest suggestions:")
            for item in hints:
                title = item["alert"].get("title", "Untitled")
                lines.append(f"• {title} (score {item['score']})")
        result_text = "\n".join(lines)
        banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
        if banner:
            result_text = f"{banner}{result_text}"
        # Bugfix: clear stale alias-map from previous successful search.
        context.user_data[LIST_CONTEXT_KEY] = {
            "source": "alerts_search",
            "tag_filter": "ALL",
            "page": 1,
            "alias_map": {},
            "search_text": result_text,
            "search_parse_mode": None,
        }
        await update.message.reply_text(result_text)
        return

    lines = [
        "🔎 Alert Search",
        f"Query: {query}",
        f"Matches: {len(matched)} (top {top_n}, min score {min_score})",
        "Send another text to search again, or /cancel to stop.",
        "",
    ]
    alias_map = {}
    for idx, item in enumerate(matched, start=1):
        alert = item["alert"]
        next_occ = get_next_occurrence(alert)
        next_str = _format_search_due(next_occ)
        status = "🟢" if alert.get("active", True) else "🔴"
        alias = f"{idx:02d}"
        alias_map[alias] = alert.get("id")
        tags = ", ".join(alert.get("tags", [])) if alert.get("tags") else "None"
        lines.append(f"/{alias} {status} {alert.get('title', 'Untitled')}")
        lines.append(f"      📅 {next_str}")
        lines.append(f"      🏷️ {tags}")
        lines.append(f"      🔍 score {item['score']}")
        if idx < len(matched):
            lines.append("")

    result_text = "\n".join(lines)
    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    if banner:
        result_text = f"{banner}{result_text}"
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "alerts_search",
        "tag_filter": "ALL",
        "page": 1,
        "alias_map": alias_map,
        "search_text": result_text,
        "search_parse_mode": None,
        "saved_at": datetime.now().isoformat(),
    }
    await update.message.reply_text(result_text)


async def alert_search_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs alert search from free-text input after pressing alert search button."""
    query_text = (update.message.text or "").strip()
    context.args = query_text.split()
    await alert_search(update, context)
