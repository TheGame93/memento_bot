import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, 
    MessageHandler, filters, CallbackQueryHandler
)
from modules import constants as C
from modules.handlers.add_flow.state_helpers import (
    _delete_additional_info_copy_message,
    cleanup_add_flow_messages as _cleanup_add_flow_messages,
    track_add_flow_callback_message as _track_add_flow_callback_message,
)
from modules.handlers.add_flow.summary_flow import (
    format_alert_summary,
)
from modules.handlers.add_flow.media_flow import (
    get_photo as _get_photo_impl,
    photo_back as _photo_back_impl,
    reject_document as _reject_document_impl,
    remove_photo as _remove_photo_impl,
    show_photo_menu as _show_photo_menu_impl,
)
from modules.handlers.add_flow.settings_flow import (
    _change_type_callback_impl,
    handle_additional_info_clear as _handle_additional_info_clear_impl,
    handle_additional_info_input as _handle_additional_info_input_impl,
    handle_additional_info_skip as _handle_additional_info_skip_impl,
    handle_multi_setting_choice as _handle_multi_setting_choice_impl,
    prompt_additional_info as _prompt_additional_info_impl,
    return_to_settings as _return_to_settings_impl,
    show_multi_setting_menu as _show_multi_setting_menu_impl,
)
from modules.handlers.add_flow.repetition_flow import (
    handle_repetition_choice as _handle_repetition_choice_impl,
    handle_repetition_count_input as _handle_repetition_count_input_impl,
    handle_repetition_until_date_input as _handle_repetition_until_date_input_impl,
    prompt_repetition_count as _prompt_repetition_count_impl,
    prompt_repetition_until_date as _prompt_repetition_until_date_impl,
    show_repetition_menu as _show_repetition_menu_impl,
)
from modules.handlers.add_flow.flow_start import (
    get_title as _get_title_impl,
    prompt_type_specific as _prompt_type_specific_impl,
    select_type as _select_type_impl,
    start_add as _start_add_impl,
    start_add_from_menu as _start_add_from_menu_impl,
)
from modules.handlers.add_flow.type_flow import (
    ask_time as _ask_time_impl,
    calculate_suggested_start as _calculate_suggested_start_impl,
    confirm_custom_pre_alert as _confirm_custom_pre_alert_impl,
    daily_interval_confirm_callback as _daily_interval_confirm_callback_impl,
    fuzzy_mean_std_input as _fuzzy_mean_std_input_impl,
    get_custom_pre_alert_input as _get_custom_pre_alert_input_impl,
    get_interval_callback as _get_interval_callback_impl,
    get_interval_input as _get_interval_input_impl,
    get_interval_prompt as _get_interval_prompt_impl,
    get_pre_alert_callback as _get_pre_alert_callback_impl,
    get_start_date_callback as _get_start_date_callback_impl,
    get_start_date_input as _get_start_date_input_impl,
    get_time_callback as _get_time_callback_impl,
    get_time_input as _get_time_input_impl,
    interval_mode_choice_callback as _interval_mode_choice_callback_impl,
    show_pre_alert_menu as _show_pre_alert_menu_impl,
    show_tags_menu as _show_tags_menu_impl,
    tags_toggle as _tags_toggle_impl,
    toggle_handler as _toggle_handler_impl,
    type_1_days as _type_1_days_impl,
    type_2_fifth_policy as _type_2_fifth_policy_impl,
    type_2_ordinal as _type_2_ordinal_impl,
    type_2_weekday as _type_2_weekday_impl,
    type_3_weekdays as _type_3_weekdays_impl,
    type_4_dates as _type_4_dates_impl,
    type_5_date as _type_5_date_impl,
    type_6_date as _type_6_date_impl,
)
from modules.shared.context_cleanup import clear_transient_context, require_temp_alert
from modules.shared.acting_as import get_actor_user_id, get_target_user_id
from modules.shared.runtime_context import get_runtime_storage
from modules.handlers.base.conversation_fallbacks import (
    build_implicit_cancel_fallbacks,
    end_registered_conversations,
)

logger = logging.getLogger(__name__)
LEGACY_REVIEW_CALLBACK_PATTERN = r"^(save|discard|bday_save|bday_discard)$"

async def ask_time(update: Update, context: ContextTypes.DEFAULT_TYPE): # FIXED: Added context
    """Delegate the legacy `ask_time` add-flow handler to the modular implementation."""
    return await _ask_time_impl(update, context)

def calculate_suggested_start(data):
    """Return a suggested first-occurrence datetime for interval prompts."""
    return _calculate_suggested_start_impl(data)

# --- FLOW START ---

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `start_add` add-flow handler to the modular implementation."""
    return await _start_add_impl(update, context)


async def start_add_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `start_add_from_menu` add-flow handler to the modular implementation."""
    return await _start_add_from_menu_impl(update, context)


@require_temp_alert
async def select_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `select_type` add-flow handler to the modular implementation."""
    return await _select_type_impl(update, context)

@require_temp_alert
async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_title` add-flow handler to the modular implementation."""
    return await _get_title_impl(update, context, prompt_type_specific)

async def prompt_type_specific(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `prompt_type_specific` add-flow handler to the modular implementation."""
    return await _prompt_type_specific_impl(
        update,
        context,
        get_interval_prompt=get_interval_prompt,
    )

# --- DATA ENTRY & VALIDATION ---

@require_temp_alert
async def type_1_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_1_days` add-flow handler to the modular implementation."""
    return await _type_1_days_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def type_4_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_4_dates` add-flow handler to the modular implementation."""
    return await _type_4_dates_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def type_5_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_5_date` add-flow handler to the modular implementation."""
    return await _type_5_date_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def type_6_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_6_date` add-flow handler to the modular implementation."""
    return await _type_6_date_impl(update, context, show_tags_menu)

# --- TOGGLES ---

async def toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                         data_list, cb_prefix, next_state, next_msg, next_kb_func=None, next_func=None):
    """Delegate the legacy `toggle_handler` add-flow handler to the modular implementation."""
    return await _toggle_handler_impl(
        update,
        context,
        data_list,
        cb_prefix,
        next_state,
        next_msg,
        next_kb_func=next_kb_func,
        next_func=next_func,
        get_interval_prompt=get_interval_prompt,
    )

@require_temp_alert
async def type_2_ordinal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_2_ordinal` add-flow handler to the modular implementation."""
    return await _type_2_ordinal_impl(update, context, get_interval_prompt)

@require_temp_alert
async def type_2_fifth_policy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_2_fifth_policy` add-flow handler to the modular implementation."""
    return await _type_2_fifth_policy_impl(update, context)

@require_temp_alert
async def type_2_weekday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_2_weekday` add-flow handler to the modular implementation."""
    return await _type_2_weekday_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def type_3_weekdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `type_3_weekdays` add-flow handler to the modular implementation."""
    return await _type_3_weekdays_impl(update, context, show_multi_setting_menu)

# --- INTERVALS & TIME ---

async def get_interval_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_interval_prompt` add-flow handler to the modular implementation."""
    return await _get_interval_prompt_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def get_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_interval_callback` add-flow handler to the modular implementation."""
    return await _get_interval_callback_impl(update, context, _return_to_settings)

@require_temp_alert
async def get_interval_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_interval_input` add-flow handler to the modular implementation."""
    return await _get_interval_input_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def daily_interval_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `daily_interval_confirm_callback` add-flow handler to the modular implementation."""
    return await _daily_interval_confirm_callback_impl(
        update,
        context,
        _return_to_settings,
        show_multi_setting_menu,
    )


@require_temp_alert
async def interval_mode_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate daily interval mode choice callbacks to the modular implementation."""
    return await _interval_mode_choice_callback_impl(update, context)


@require_temp_alert
async def fuzzy_mean_std_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate daily fuzzy mean/std parsing to the modular implementation."""
    return await _fuzzy_mean_std_input_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def get_start_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_start_date_callback` add-flow handler to the modular implementation."""
    return await _get_start_date_callback_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def get_start_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_start_date_input` add-flow handler to the modular implementation."""
    return await _get_start_date_input_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def get_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_time_input` add-flow handler to the modular implementation."""
    return await _get_time_input_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def get_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_time_callback` add-flow handler to the modular implementation."""
    return await _get_time_callback_impl(update, context, show_multi_setting_menu)

async def show_pre_alert_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `show_pre_alert_menu` add-flow handler to the modular implementation."""
    return await _show_pre_alert_menu_impl(update, context)

@require_temp_alert
async def get_pre_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_pre_alert_callback` add-flow handler to the modular implementation."""
    return await _get_pre_alert_callback_impl(update, context, _return_to_settings)

@require_temp_alert
async def get_custom_pre_alert_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_custom_pre_alert_input` add-flow handler to the modular implementation."""
    return await _get_custom_pre_alert_input_impl(update, context)

@require_temp_alert
async def confirm_custom_pre_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `confirm_custom_pre_alert` add-flow handler to the modular implementation."""
    return await _confirm_custom_pre_alert_impl(update, context, _return_to_settings)

async def show_tags_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `show_tags_menu` add-flow handler to the modular implementation."""
    return await _show_tags_menu_impl(update, context)

@require_temp_alert
async def tags_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `tags_toggle` add-flow handler to the modular implementation."""
    return await _tags_toggle_impl(update, context, save_after_tags)

async def _return_to_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modules.handlers.birthdays import show_birthday_settings_menu
    return await _return_to_settings_impl(
        update,
        context,
        show_multi_setting_menu,
        show_birthday_settings_menu,
    )

async def show_multi_setting_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `show_multi_setting_menu` add-flow handler to the modular implementation."""
    return await _show_multi_setting_menu_impl(update, context)

@require_temp_alert
async def show_repetition_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `show_repetition_menu` add-flow handler to the modular implementation."""
    return await _show_repetition_menu_impl(update, context)

async def prompt_repetition_until_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `prompt_repetition_until_date` add-flow handler to the modular implementation."""
    return await _prompt_repetition_until_date_impl(update, context)

async def prompt_repetition_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `prompt_repetition_count` add-flow handler to the modular implementation."""
    return await _prompt_repetition_count_impl(update, context)

@require_temp_alert
async def handle_repetition_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `handle_repetition_choice` add-flow handler to the modular implementation."""
    return await _handle_repetition_choice_impl(
        update,
        context,
        _return_to_settings,
        prompt_repetition_until_date,
        prompt_repetition_count,
    )

@require_temp_alert
async def handle_repetition_until_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `handle_repetition_until_date_input` add-flow handler to the modular implementation."""
    return await _handle_repetition_until_date_input_impl(update, context, _return_to_settings)

@require_temp_alert
async def handle_repetition_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `handle_repetition_count_input` add-flow handler to the modular implementation."""
    return await _handle_repetition_count_input_impl(update, context, _return_to_settings)

@require_temp_alert
async def handle_multi_setting_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `handle_multi_setting_choice` add-flow handler to the modular implementation."""
    return await _handle_multi_setting_choice_impl(
        update,
        context,
        get_interval_prompt,
        ask_time,
        show_pre_alert_menu,
        show_photo_menu,
        prompt_additional_info,
        show_tags_menu,
        show_repetition_menu,
    )


@require_temp_alert
async def handle_change_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `handle_change_type_callback` add-flow handler to the modular implementation."""
    return await _change_type_callback_impl(
        update,
        context,
        _return_to_settings,
        prompt_type_specific,
    )

async def show_photo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `show_photo_menu` add-flow handler to the modular implementation."""
    return await _show_photo_menu_impl(update, context)

async def prompt_additional_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `prompt_additional_info` add-flow handler to the modular implementation."""
    return await _prompt_additional_info_impl(update, context)

@require_temp_alert
async def handle_additional_info_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `handle_additional_info_input` add-flow handler to the modular implementation."""
    return await _handle_additional_info_input_impl(update, context, _return_to_settings)

@require_temp_alert
async def handle_additional_info_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `handle_additional_info_skip` add-flow handler to the modular implementation."""
    return await _handle_additional_info_skip_impl(update, context, _return_to_settings)


@require_temp_alert
async def handle_additional_info_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate explicit Additional Info clear action to shared add-flow settings logic."""
    return await _handle_additional_info_clear_impl(update, context, _return_to_settings)


@require_temp_alert
async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `get_photo` add-flow handler to the modular implementation."""
    return await _get_photo_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def reject_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `reject_document` add-flow handler to the modular implementation."""
    return await _reject_document_impl(update, context)

@require_temp_alert
async def photo_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `photo_back` add-flow handler to the modular implementation."""
    return await _photo_back_impl(update, context, show_multi_setting_menu)

@require_temp_alert
async def remove_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate the legacy `remove_photo` add-flow handler to the modular implementation."""
    return await _remove_photo_impl(update, context, show_multi_setting_menu)

def _acquire_add_flow_save_lock(context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("add_flow_save_in_progress"):
        return False
    context.user_data["add_flow_save_in_progress"] = True
    return True


def _release_add_flow_save_lock(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("add_flow_save_in_progress", None)


async def _send_add_flow_error(context: ContextTypes.DEFAULT_TYPE, chat_id, text: str) -> None:
    if chat_id is None:
        return
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception("Failed to send add-flow error to chat_id=%s", chat_id)


async def _save_temp_alert_from_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    failure_state: int,
):
    _track_add_flow_callback_message(update, context)
    query = update.callback_query
    if query is None:
        return failure_state

    if not _acquire_add_flow_save_lock(context):
        return failure_state

    actor_id = get_actor_user_id(update)
    target_id = get_target_user_id(update, context)
    if actor_id is None:
        actor_id = target_id
    chat_id = actor_id or target_id
    alert_data = context.user_data.get("temp_alert")

    if target_id is None or not isinstance(alert_data, dict):
        _release_add_flow_save_lock(context)
        await _send_add_flow_error(
            context,
            chat_id,
            "❌ **Error:** Alert session data is missing. Please restart the flow.",
        )
        return failure_state

    try:
        from modules.storage import StorageLimitError

        storage = get_runtime_storage(context)
        if "image_id" in alert_data and not alert_data.get("local_image_path"):
            local_path = await storage.download_image(context.bot, target_id, alert_data["image_id"])
            if local_path:
                alert_data["local_image_path"] = local_path

        alert_id = storage.save_alert(target_id, alert_data)
        if not alert_id:
            context.user_data["temp_selection"] = list(alert_data.get("tags", []) or [])
            await _send_add_flow_error(
                context,
                chat_id,
                "❌ **Error:** Could not write to database.\n"
                "Press `DONE` again to retry, or use /cancel.",
            )
            return failure_state

        user_prefs = None
        try:
            user_prefs = storage.get_user_prefs(target_id)
        except Exception:
            user_prefs = None

        success_text = format_alert_summary(alert_data, alert_id=alert_id, user_prefs=user_prefs)
        success_msg = await context.bot.send_message(
            chat_id=chat_id or target_id,
            text=success_text,
            parse_mode=ParseMode.MARKDOWN,
        )
        await _cleanup_add_flow_messages(
            context,
            context.bot,
            chat_id or target_id,
            end_message_id=query.message.message_id if query.message else None,
            keep_message_ids={success_msg.message_id},
        )
        clear_transient_context(context.user_data)
        return ConversationHandler.END
    except StorageLimitError as exc:
        logger.warning("Storage limit hit while saving alert: %s", exc)
        context.user_data["temp_selection"] = list((alert_data or {}).get("tags", []) or [])
        await _send_add_flow_error(
            context,
            chat_id,
            f"❌ **Storage limit reached.**\n{exc}\n"
            "Delete some alerts or images first, then try again.",
        )
        return failure_state
    except Exception:
        logger.exception("Unexpected error while saving alert in add flow")
        context.user_data["temp_selection"] = list((alert_data or {}).get("tags", []) or [])
        await _send_add_flow_error(
            context,
            chat_id,
            "❌ **Unexpected error while saving.**\n"
            "Press `DONE` again to retry, or use /cancel.",
        )
        return failure_state
    finally:
        _release_add_flow_save_lock(context)


@require_temp_alert
async def save_after_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Persist the staged alert after tag selection completes."""
    return await _save_temp_alert_from_callback(
        update,
        context,
        failure_state=C.GET_TAGS,
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel add flow, clear transient context, and force-end registered conversation state for this user."""
    await _delete_additional_info_copy_message(update, context)
    clear_transient_context(context.user_data, include_navigation=True)
    end_registered_conversations(update)
    await update.message.reply_text("⏹️ **Cancelled.**", parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


async def handle_legacy_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Global fallback for old review keyboards (save/discard) left in chat history.
    This callback must never mutate alert data.
    """
    query = update.callback_query
    if query is None:
        return

    notice = (
        "⏹️ This review action is no longer available.\n"
        "Use /alerts or /birthdays to start a new add flow."
    )
    try:
        await query.answer("This review action has expired.", show_alert=True)
    except Exception:
        pass

    edited = False
    try:
        message = query.message
        if message and getattr(message, "photo", None):
            await query.edit_message_caption(caption=notice, reply_markup=None)
            edited = True
        else:
            await query.edit_message_text(notice, reply_markup=None)
            edited = True
    except Exception:
        edited = False

    if edited:
        return

    actor_id = get_actor_user_id(update)
    if actor_id is None:
        actor_id = getattr(getattr(update, "effective_user", None), "id", None)
    if actor_id is None:
        return
    try:
        await context.bot.send_message(chat_id=actor_id, text=notice, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass

add_alert_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_add_from_menu, pattern="^alert_add$")
    ],
    states={
        C.GET_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
        C.SELECT_TYPE: [CallbackQueryHandler(select_type, pattern=f"^{C.CB_TYPE}")],
        C.TYPE_1_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_1_days)],
        C.TYPE_2_ORDINAL: [CallbackQueryHandler(type_2_ordinal, pattern=f"^{C.CB_ORDINAL}")],
        C.TYPE_2_FIFTH_POLICY: [CallbackQueryHandler(type_2_fifth_policy, pattern=f"^{C.CB_FIFTH_POLICY}")],
        C.TYPE_2_WEEKDAY: [CallbackQueryHandler(type_2_weekday, pattern=f"^{C.CB_WEEKDAY}")],
        C.TYPE_3_WEEKDAYS: [CallbackQueryHandler(type_3_weekdays, pattern=f"^{C.CB_WEEKDAY}")],
        C.TYPE_4_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_4_dates)],
        C.TYPE_5_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_5_date)],
        C.TYPE_6_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_6_date)],
        C.GET_INTERVAL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_interval_input),
            CallbackQueryHandler(get_interval_callback, pattern="^int_")
        ],
        C.FUZZY_INTERVAL_MODE_CHOICE: [
            CallbackQueryHandler(
                interval_mode_choice_callback,
                pattern=f"^({C.CB_INTERVAL_FIXED}|{C.CB_INTERVAL_FUZZY})$",
            )
        ],
        C.FUZZY_MEAN_STD_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, fuzzy_mean_std_input)
        ],
        C.DAILY_INTERVAL_CONFIRM: [
            CallbackQueryHandler(daily_interval_confirm_callback, pattern="^dint1_")
        ],
        C.GET_START_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_start_date_input),
            CallbackQueryHandler(get_start_date_callback, pattern="^start_")
        ],
        C.GET_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_time_input),
            CallbackQueryHandler(get_time_callback, pattern="^time_")
        ],
        C.GET_PRE_ALERT: [
            CallbackQueryHandler(get_pre_alert_callback, pattern="^pre_")
        ],
        C.GET_CUSTOM_PRE_ALERT: [ # <--- This matches the constants change
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_custom_pre_alert_input)
        ],
        C.GET_REPETITION_MENU: [
            CallbackQueryHandler(handle_repetition_choice, pattern="^rep_")
        ],
        C.GET_REPETITION_COUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_repetition_count_input)
        ],
        C.GET_REPETITION_UNTIL_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_repetition_until_date_input)
        ],
        C.CONFIRM_CUSTOM_PRE_ALERT: [
            CallbackQueryHandler(confirm_custom_pre_alert, pattern="^precustom_")
        ],
        C.GET_ADDITIONAL_INFO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_additional_info_input),
            CallbackQueryHandler(handle_additional_info_skip, pattern="^info_skip$"),
            CallbackQueryHandler(handle_additional_info_clear, pattern="^info_clear$"),
        ],
        C.GET_TAGS: [CallbackQueryHandler(tags_toggle, pattern=f"^{C.CB_TAG}")],
        C.CHANGE_ALERT_TYPE: [CallbackQueryHandler(handle_change_type_callback, pattern="^ct_")],
        C.GET_PHOTO: [
            # 1. The correct way (Compressed Photo)
            MessageHandler(filters.PHOTO, get_photo),
            
            # 2. The Guard (Uncompressed Document)
            MessageHandler(filters.Document.ALL, reject_document),
            
            # 3. Back / Remove buttons
            CallbackQueryHandler(photo_back, pattern="^photo_back$"),
            CallbackQueryHandler(remove_photo, pattern="^photo_remove$")
        ],
        C.MULTI_SETTINGS: [
            CallbackQueryHandler(handle_multi_setting_choice, pattern="^ms_")
        ]
    },
    fallbacks=[CommandHandler('cancel', cancel), *build_implicit_cancel_fallbacks()],
    allow_reentry=True,
    per_message=False
)
