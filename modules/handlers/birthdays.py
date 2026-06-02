from datetime import datetime
from telegram import Update
from telegram.error import BadRequest
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import constants as C
from modules.scheduler_mathlogic import get_next_occurrence
from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.handlers.birthday_flow.flow import (
    birthday_add_handler,
    show_birthday_settings_menu,
)
from modules.handlers.birthday_flow.list_view import (
    BDAY_ORPHAN_FILTER_CALLBACK_DATA as BDAY_ORPHAN_FILTER_CALLBACK_DATA_FLOW,
    _decode_birthday_filter_value,
    _get_birthdays,
    birthday_list_start,
    show_birthdays_list,
    show_next_birthdays,
)
from modules.handlers.birthday_flow.menu import (
    build_birthday_home_keyboard,
    build_birthday_home_text,
    get_birthday_tag_stats,
)
from modules.handlers.birthday_flow.search import (
    _normalize_search_text,
    rank_birthdays_by_name,
)
from modules.handlers.birthday_flow.render import (
    format_search_due,
)
from modules.shared.logging_utils import hash_text, text_meta
from modules.systemlog import log_system
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage

CB_BDAY_TAG = "btag_"
CB_BDAY_ACTION = "bday_"
BDAY_FILTER_TOKEN_PREFIX = "bday_filter_t"
BDAY_ORPHAN_FILTER_CALLBACK_DATA = BDAY_ORPHAN_FILTER_CALLBACK_DATA_FLOW


def _is_markdown_parse_error(exc):
    if not isinstance(exc, BadRequest):
        return False
    raw = str(exc or "")
    text = raw.strip().lower()
    if not text:
        return False
    return "can't parse entities" in text


async def birthday_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the birthdays home menu with tag stats and markdown fallback handling."""
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)

    user_data = storage.get_all_alerts(user_id)
    if not user_data:
        storage.setup_user_space(user_id)
        user_data = storage.get_all_alerts(user_id)

    tags, stats, untagged = get_birthday_tag_stats(user_data)
    text = build_birthday_home_text(tags, stats, untagged)
    keyboard = build_birthday_home_keyboard(action_prefix=CB_BDAY_ACTION)
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)

    banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
    render_text = f"{banner}{text}"
    target_message = update.message or update.effective_message
    if target_message is None:
        return

    try:
        await target_message.reply_text(
            render_text,
            reply_markup=keyboard,
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
        storage.log_user_event(user_id, "birthday_menu_markdown_fallback", fallback_payload)
        log_system("api", "menu_markdown_parse_failed", {
            "menu": "birthdays",
            "user_id": str(user_id),
            "reason_code": "markdown_parse_error",
            "message_text_len": text_signal["len"],
            "message_text_hash": text_signal["hash"],
        }, level="WARNING")

        try:
            await target_message.reply_text(
                render_text,
                reply_markup=keyboard,
            )
        except Exception as fallback_exc:
            fallback_failed_payload = {
                "source": "callback" if update.callback_query else "command",
                "reason_code": "fallback_send_failed",
                "error_type": fallback_exc.__class__.__name__,
            }
            fallback_failed_payload.update(acting_payload)
            storage.log_user_event(user_id, "birthday_menu_markdown_fallback_failed", fallback_failed_payload)
            log_system("api", "menu_markdown_fallback_failed", {
                "menu": "birthdays",
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
        storage.log_user_event(user_id, "birthday_menu_markdown_fallback_sent", fallback_sent_payload)
        log_system("api", "menu_markdown_fallback_sent", {
            "menu": "birthdays",
            "user_id": str(user_id),
            "reason_code": "fallback_plain_text_ok",
        })

    payload = {"source": "callback" if update.callback_query else "command"}
    payload.update(acting_payload)
    storage.log_user_event(user_id, "birthday_menu_opened", payload)


async def handle_birthday_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route birthday menu callbacks while preserving single-answer semantics."""
    query = update.callback_query
    if query is None:
        return
    choice = query.data

    if choice == f"{CB_BDAY_ACTION}list":
        try:
            await query.message.delete()
        except Exception:
            pass
        context.user_data.pop("expecting_birthday_search", None)
        context.user_data.pop("expecting_alert_search", None)
        return await birthday_list_start(update, context)
    if choice == f"{CB_BDAY_ACTION}next":
        try:
            await query.message.delete()
        except Exception:
            pass
        context.user_data.pop("expecting_birthday_search", None)
        context.user_data.pop("expecting_alert_search", None)
        return await show_next_birthdays(update, context)
    if choice == f"{CB_BDAY_ACTION}search":
        await query.answer()
        context.user_data["expecting_birthday_search"] = True
        context.user_data.pop("expecting_alert_search", None)
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=get_actor_user_id(update),
            text=(
                f"{build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)}"
                "🔎 **Search Birthdays**\n\n"
                "Send one or more words to search by name.\n"
                "Examples:\n"
                "• Mark\n"
                "• Mak White\n"
                "• Mary Williams\n\n"
                "Type /cancel to stop."
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Defensive fail-soft for unexpected callback payloads.
    await query.answer()


async def birthday_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fuzzy-search birthdays by title/name."""
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "🔎 Search query is empty.\n"
            "Write one or more words, e.g.:\n"
            "• Mark\n"
            "• Mak White",
        )
        return

    birthdays = _get_birthdays(storage, user_id, include_inactive=True)
    if not birthdays:
        await update.message.reply_text("🎂 No birthdays available yet.")
        return

    query_norm, ranked = rank_birthdays_by_name(query, birthdays)
    min_score = int(getattr(C, "BIRTHDAY_SEARCH_MIN_SCORE", 75))
    top_n = max(1, int(getattr(C, "BIRTHDAY_SEARCH_TOP_N", 5)))
    matched = [item for item in ranked if item["score"] >= min_score][:top_n]
    payload = {
        "query_len": len(query),
        "query_hash": hash_text(query),
        "total_birthdays": len(birthdays),
        "matched": len(matched),
        "min_score": min_score,
        "top_n": top_n,
    }
    payload.update(acting_payload)
    storage.log_user_event(user_id, "birthday_search", payload)

    if not matched:
        hints = ranked[:3]
        lines = [
            "🔎 Birthday Search",
            f"Query: {query}",
            "",
            f"No strong matches (min score: {min_score}).",
            "Send another text to retry, or /cancel to stop.",
        ]
        if hints:
            lines.append("")
            lines.append("Closest suggestions:")
            for item in hints:
                alert = item["alert"]
                title = alert.get("title", "Untitled")
                lines.append(f"• {title} (score {item['score']})")
        result_text = "\n".join(lines)
        banner = build_acting_as_banner(update, context, parse_mode=ParseMode.MARKDOWN)
        if banner:
            result_text = f"{banner}{result_text}"
        # Bugfix: clear stale alias-map from previous successful search.
        context.user_data[LIST_CONTEXT_KEY] = {
            "source": "birthdays_search",
            "tag_filter": "ALL",
            "page": 1,
            "alias_map": {},
            "search_text": result_text,
            "search_parse_mode": None,
        }
        await update.message.reply_text(result_text)
        return

    lines = [
        "🔎 Birthday Search",
        f"Query: {query}",
        f"Matches: {len(matched)} (top {top_n}, min score {min_score})",
        "Send another text to search again, or /cancel to stop.",
        "",
    ]
    alias_map = {}
    for idx, item in enumerate(matched, start=1):
        alert = item["alert"]
        next_occ = get_next_occurrence(alert)
        next_str = format_search_due(next_occ)
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
        "source": "birthdays_search",
        "tag_filter": "ALL",
        "page": 1,
        "alias_map": alias_map,
        "search_text": result_text,
        "search_parse_mode": None,
        "saved_at": datetime.now().isoformat(),
    }
    await update.message.reply_text(result_text)


async def birthday_search_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs birthday search from free-text input after pressing birthday search button."""
    query_text = (update.message.text or "").strip()
    context.args = query_text.split()
    await birthday_search(update, context)
