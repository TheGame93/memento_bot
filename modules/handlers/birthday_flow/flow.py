from datetime import datetime
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from modules import constants as C
from modules.handlers.add_alert import (
    confirm_custom_pre_alert,
    get_custom_pre_alert_input,
    get_pre_alert_callback,
    handle_additional_info_clear,
    handle_additional_info_input,
    handle_additional_info_skip,
    prompt_additional_info,
    show_pre_alert_menu,
)
from modules.handlers.birthday_flow.menu import build_toggle_keyboard
from modules.handlers.birthday_flow.render import (
    format_bday_additional_info,
    format_bday_pre_alerts,
    format_birthday_summary,
)
from modules.handlers.add_flow.state_helpers import _delete_additional_info_copy_message
from modules.handlers.base import _birthday_default_time_from_prefs
from modules.shared.context_cleanup import clear_transient_context, require_temp_alert
from modules.shared.acting_as import (
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage
from modules.handlers.base.conversation_fallbacks import (
    build_implicit_cancel_fallbacks,
    end_registered_conversations,
)

CB_BDAY_TAG = "btag_"
CB_BDAY_ACTION = "bday_"
logger = logging.getLogger(__name__)


def _resolve_birthday_default_time(storage, user_id):
    prefs = storage.get_user_prefs(user_id)
    return _birthday_default_time_from_prefs(prefs)


def parse_birthday_date_input(raw_text, current_year=None):
    """Parse and validate birthday input for DD/MM and DD/MM/YYYY formats."""
    text = (raw_text or "").strip()
    try:
        year_ref = int(current_year) if current_year is not None else datetime.now().year
    except Exception:
        year_ref = datetime.now().year

    result = {
        "ok": False,
        "date_ddmm": None,
        "birth_year": None,
        "reason_code": None,
    }

    if not text:
        result["reason_code"] = "empty"
        return result

    parts = text.split("/")
    if len(parts) == 3:
        dd, mm, yy = parts
        if len(yy) == 2:
            result["reason_code"] = "year_two_digits"
            return result
        try:
            parsed = datetime.strptime(text, "%d/%m/%Y")
        except ValueError:
            result["reason_code"] = "invalid_date"
            return result

        birth_year = parsed.year
        if birth_year > year_ref:
            result["reason_code"] = "year_in_future"
            return result
        if birth_year < 1900:
            result["reason_code"] = "year_before_1900"
            return result

        result["ok"] = True
        result["date_ddmm"] = f"{dd}/{mm}"
        result["birth_year"] = birth_year
        return result

    if len(parts) != 2:
        result["reason_code"] = "invalid_format"
        return result

    try:
        datetime.strptime(f"{text}/2024", "%d/%m/%Y")
    except ValueError:
        result["reason_code"] = "invalid_date"
        return result

    result["ok"] = True
    result["date_ddmm"] = text
    return result


async def start_birthday_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start birthday creation and initialize a type-6 draft payload."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)
    context.user_data["temp_alert"] = {
        "tags": [],
        "pre_alerts": [],
        "additional_info": "",
        "schedule": {},
        "type": 6,
        "type_name": C.ALERT_TYPES.get(6, "Birthday"),
    }
    try:
        await query.message.delete()
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=get_actor_user_id(update),
        text="🎂 **New Birthday**\n\nPlease enter the **Name**:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return C.GET_TITLE


@require_temp_alert
async def birthday_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate birthday name input and route to date collection."""
    name = (update.message.text or "").strip()
    # Reject whitespace-only names; previously these passed through as empty titles.
    if not name:
        await update.message.reply_text("❌ Name cannot be empty. Try again.")
        return C.GET_TITLE
    if len(name) > C.TITLE_MAX_LEN:
        try:
            storage = get_runtime_storage(context)
            target_id = get_target_user_id(update, context)
            storage.log_user_event(target_id, "title_input_too_long", {"title_len": len(name)})
        except Exception:
            pass
        await update.message.reply_text(
            f"⚠️ Name too long (max {C.TITLE_MAX_LEN} characters). Try again."
        )
        return C.GET_TITLE
    if len(name.split()) == 1:
        context.user_data["pending_bday_name"] = name
        keyboard = [[
            InlineKeyboardButton("✅ Yes, keep it", callback_data="bdayname_yes"),
            InlineKeyboardButton("✏️ No, edit", callback_data="bdayname_no"),
        ]]
        await update.message.reply_text(
            "⚠️ You entered a single word.\n"
            "Are you sure you don’t want to add a surname or extra info?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return C.BDAY_NAME_CONFIRM

    context.user_data["temp_alert"]["title"] = name
    await update.message.reply_text(
        "📅 **Birthday Date**\nWrite date as DD/MM or DD/MM/YYYY\n(set the year, I can remind you the age!)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return C.TYPE_6_DATE


@require_temp_alert
async def birthday_confirm_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle single-word name confirmation before date entry."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "bdayname_yes":
        name = context.user_data.get("pending_bday_name", "")
        context.user_data["temp_alert"]["title"] = name
        context.user_data["pending_bday_name"] = None
        await query.edit_message_text(
            "📅 **Birthday Date**\nWrite date as DD/MM or DD/MM/YYYY\n(set the year, I can remind you the age!)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.TYPE_6_DATE

    # bdayname_no
    context.user_data["pending_bday_name"] = None
    await query.edit_message_text(
        "✏️ **Edit Name**\nPlease enter the full name:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return C.GET_TITLE


@require_temp_alert
async def birthday_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate birthday date input, persist normalized fields, and route to settings.
    
    Accept `DD/MM` or `DD/MM/YYYY`, enforce year constraints, and persist optional
    `birth_year` metadata when provided in valid four-digit form.
    """
    text = (update.message.text or "").strip()
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    default_time = _resolve_birthday_default_time(storage, user_id)
    parsed = parse_birthday_date_input(text)
    reason = parsed.get("reason_code")

    if not parsed.get("ok"):
        if reason == "year_two_digits":
            await update.message.reply_text(
                "❌ **2-digit year not allowed.** Please use 4 digits (e.g. `25/12/1990`):",
                parse_mode=ParseMode.MARKDOWN,
            )
            return C.TYPE_6_DATE
        if reason == "year_in_future":
            await update.message.reply_text(
                "❌ **Birth year cannot be in the future.**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return C.TYPE_6_DATE
        if reason == "year_before_1900":
            await update.message.reply_text(
                "❌ **Birth year must be 1900 or later.**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return C.TYPE_6_DATE

        # Keep legacy message split parity for add flow:
        # 3-part invalid year/date uses "Invalid date", all other invalids use "Invalid".
        if len(text.split("/")) == 3:
            await update.message.reply_text(
                "❌ **Invalid date.** Use format DD/MM or DD/MM/YYYY (e.g. `25/12` or `25/12/1990`):",
                parse_mode=ParseMode.MARKDOWN,
            )
            return C.TYPE_6_DATE
        await update.message.reply_text(
            "❌ **Invalid.** Use format DD/MM or DD/MM/YYYY (e.g. `25/12` or `25/12/1990`):",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.TYPE_6_DATE

    context.user_data["temp_alert"]["schedule"]["date"] = parsed.get("date_ddmm")
    context.user_data["temp_alert"]["schedule"]["time"] = default_time
    birth_year = parsed.get("birth_year")
    if birth_year is None:
        context.user_data["temp_alert"].pop("birth_year", None)
    else:
        context.user_data["temp_alert"]["birth_year"] = birth_year
    return await show_birthday_settings_menu(update, context)


async def birthday_show_tags_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available tags for birthday creation and initialize selection state."""
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    available_tags = storage.get_user_tags(user_id)
    context.user_data["temp_selection"] = []
    if available_tags:
        text = (
            "🏷️ **Select Tags** (One or more, then DONE):\n\n"
            "💡 _If your desired tag is not listed, skip this step._\n"
            "_After saving, go to /tags to create it, then edit this event's tag._"
        )
    else:
        text = (
            "🏷️ **No tags available.** Press DONE to continue without tags.\n\n"
            "💡 _After saving, go to /tags to create tags, then edit this event's tag._"
        )
    kb = build_toggle_keyboard(available_tags, [], CB_BDAY_TAG)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    return C.GET_TAGS


async def show_birthday_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render birthday-specific settings for pre-alert and additional info."""
    data = context.user_data.get("temp_alert", {})
    if data.get("pre_alerts") is None:
        data["pre_alerts"] = []
    if data.get("additional_info") is None:
        data["additional_info"] = ""
    context.user_data["settings_return"] = "birthday"

    text = (
        "⚙️ **Birthday Settings**\n\n"
        f"• Pre-alert: `{format_bday_pre_alerts(data)}`\n"
        f"• Additional Info: `{format_bday_additional_info(data)}`\n\n"
        "Choose what to change:"
    )
    keyboard = [
        [InlineKeyboardButton("Set pre-alert", callback_data="bdayset_pre")],
        [InlineKeyboardButton("Set additional info", callback_data="bdayset_info")],
        [InlineKeyboardButton("✅ DONE", callback_data="bdayset_done")],
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
    return C.BDAY_SETTINGS


@require_temp_alert
async def handle_birthday_setting_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route birthday settings actions to the selected follow-up step."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "bdayset_pre":
        context.user_data["settings_return"] = "birthday"
        return await show_pre_alert_menu(update, context)
    if data == "bdayset_info":
        context.user_data["settings_return"] = "birthday"
        return await prompt_additional_info(update, context)
    if data == "bdayset_done":
        return await birthday_show_tags_menu(update, context)

    return C.BDAY_SETTINGS


@require_temp_alert
async def birthday_tags_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle birthday tag selections and finalize when DONE is pressed."""
    query = update.callback_query
    await query.answer()
    data = query.data.replace(CB_BDAY_TAG, "")
    current = context.user_data.get("temp_selection", [])

    if data == "DONE":
        context.user_data["temp_alert"]["tags"] = current
        context.user_data["temp_selection"] = []
        return await birthday_save_after_tags(update, context)

    if data in current:
        current.remove(data)
    else:
        current.append(data)
    context.user_data["temp_selection"] = current

    storage = get_runtime_storage(context)
    available_tags = storage.get_user_tags(get_target_user_id(update, context))
    await query.edit_message_reply_markup(
        reply_markup=build_toggle_keyboard(available_tags, current, CB_BDAY_TAG)
    )
    return C.GET_TAGS


def _acquire_birthday_save_lock(context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("birthday_save_in_progress"):
        return False
    context.user_data["birthday_save_in_progress"] = True
    return True


def _release_birthday_save_lock(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("birthday_save_in_progress", None)


async def _send_birthday_error(context: ContextTypes.DEFAULT_TYPE, chat_id, text: str) -> None:
    if chat_id is None:
        return
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception("Failed to send birthday-flow error to chat_id=%s", chat_id)


async def _save_birthday_from_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    failure_state: int,
):
    from modules.storage import StorageLimitError

    query = update.callback_query
    if query is None:
        return failure_state

    if not _acquire_birthday_save_lock(context):
        return failure_state

    user_id = get_target_user_id(update, context)
    actor_id = get_actor_user_id(update) or user_id
    chat_id = actor_id or user_id
    alert_data = context.user_data.get("temp_alert")
    alert_id = None

    if user_id is None or not isinstance(alert_data, dict):
        await _send_birthday_error(
            context,
            chat_id,
            "❌ **Error:** Birthday session data is missing. Please restart the flow.",
        )
        return failure_state

    try:
        storage = get_runtime_storage(context)
        alert_id = storage.save_alert(user_id, alert_data)
        if not alert_id:
            context.user_data["temp_selection"] = list(alert_data.get("tags", []) or [])
            await _send_birthday_error(
                context,
                chat_id,
                "❌ **Error:** Could not write to database.\n"
                "Press `DONE` again to retry, or use /cancel.",
            )
            return failure_state

        try:
            _summary_prefs = storage.get_user_prefs(user_id)
        except Exception:
            _summary_prefs = None
        success_text = format_birthday_summary(alert_data, alert_id=alert_id, user_prefs=_summary_prefs)
        delivered = False
        try:
            await query.edit_message_text(success_text, parse_mode=ParseMode.MARKDOWN)
            delivered = True
        except Exception:
            try:
                await context.bot.send_message(
                    chat_id=chat_id or user_id,
                    text=success_text,
                    parse_mode=ParseMode.MARKDOWN,
                )
                delivered = True
            except Exception:
                logger.exception("Birthday saved but success message delivery failed")

        if not delivered:
            logger.warning("Birthday saved without delivery confirmation for user_id=%s alert_id=%s", user_id, alert_id)

        clear_transient_context(context.user_data)
        return ConversationHandler.END
    except StorageLimitError as exc:
        logger.warning("Storage limit hit while saving birthday: %s", exc)
        context.user_data["temp_selection"] = list((alert_data or {}).get("tags", []) or [])
        await _send_birthday_error(
            context,
            chat_id,
            f"❌ **Storage limit reached.**\n{exc}\n"
            "Delete some alerts first, then try again.",
        )
        return failure_state
    except Exception:
        if alert_id:
            # Persist succeeded; avoid retries creating duplicates even if post-save steps failed.
            clear_transient_context(context.user_data)
            return ConversationHandler.END
        logger.exception("Unexpected error while saving birthday in add flow")
        context.user_data["temp_selection"] = list((alert_data or {}).get("tags", []) or [])
        await _send_birthday_error(
            context,
            chat_id,
            "❌ **Unexpected error while saving.**\n"
            "Press `DONE` again to retry, or use /cancel.",
        )
        return failure_state
    finally:
        _release_birthday_save_lock(context)


@require_temp_alert
async def birthday_save_after_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Persist the staged birthday alert after tag selection completes."""
    return await _save_birthday_from_callback(
        update,
        context,
        failure_state=C.GET_TAGS,
    )


async def birthday_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel birthday flow, clear transient context, and end registered conversation state for this user."""
    await _delete_additional_info_copy_message(update, context)
    clear_transient_context(context.user_data, include_navigation=True)
    end_registered_conversations(update)
    await update.message.reply_text("⏹️ **Cancelled.**", parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


birthday_add_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_birthday_add, pattern=f"^{CB_BDAY_ACTION}add$")],
    states={
        C.GET_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, birthday_get_title)],
        C.BDAY_NAME_CONFIRM: [CallbackQueryHandler(birthday_confirm_name, pattern="^bdayname_")],
        C.TYPE_6_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, birthday_get_date)],
        C.BDAY_SETTINGS: [CallbackQueryHandler(handle_birthday_setting_choice, pattern="^bdayset_")],
        C.GET_PRE_ALERT: [
            CallbackQueryHandler(get_pre_alert_callback, pattern="^pre_")
        ],
        C.GET_CUSTOM_PRE_ALERT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_custom_pre_alert_input)
        ],
        C.CONFIRM_CUSTOM_PRE_ALERT: [
            CallbackQueryHandler(confirm_custom_pre_alert, pattern="^precustom_")
        ],
        C.GET_ADDITIONAL_INFO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_additional_info_input),
            CallbackQueryHandler(handle_additional_info_skip, pattern="^info_skip$"),
            CallbackQueryHandler(handle_additional_info_clear, pattern="^info_clear$"),
        ],
        C.GET_TAGS: [CallbackQueryHandler(birthday_tags_toggle, pattern=f"^{CB_BDAY_TAG}")],
    },
    fallbacks=[CommandHandler("cancel", birthday_cancel), *build_implicit_cancel_fallbacks()],
    allow_reentry=True,
    per_message=False,
)
