from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from modules import constants as C
from modules.handlers.add_flow.keyboards import build_change_type_keyboard
from modules.handlers.add_flow.state_helpers import _delete_additional_info_copy_message
from modules.handlers.add_flow.summary_flow import (
    ensure_default_settings,
    format_additional_info,
    format_interval,
    format_photo_choice,
    format_pre_alerts,
    format_repetition,
)
from modules.shared.acting_as import get_target_user_id
from modules.shared.messages import edit_callback_message_media_aware as _edit_callback_message
from modules.shared.runtime_context import get_runtime_storage

_CHANGE_TYPE_ALLOWED_IDS = {1, 2, 3, 4, 5, 7}


def settings_return_target(context):
    """Return the settings destination key for alert, birthday, or edit flows."""
    value = context.user_data.get("settings_return", "alert")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"alert", "birthday", "edit"}:
            return normalized
    return "alert"


async def return_to_settings(
    update,
    context,
    show_alert_settings_menu,
    show_birthday_settings_menu,
    show_edit_dashboard=None,
):
    """Route back to the settings dashboard that matches current flow context."""
    target = settings_return_target(context)
    if target == "birthday":
        return await show_birthday_settings_menu(update, context)
    if target == "edit" and show_edit_dashboard is not None:
        return await show_edit_dashboard(update, context)
    return await show_alert_settings_menu(update, context)


async def show_multi_setting_menu(update, context):
    """Render the add-flow settings menu with pre-alert labels resolved against the current schedule context."""
    data = context.user_data.get("temp_alert", {})
    ensure_default_settings(data)
    context.user_data["settings_return"] = "alert"
    repetition_supported = data.get("type") in C.REPETITION_SUPPORTED_TYPES
    user_prefs = None
    try:
        storage = get_runtime_storage(context)
        user_id = get_target_user_id(update, context)
        if user_id is not None and hasattr(storage, "get_user_prefs"):
            user_prefs = storage.get_user_prefs(user_id)
    except Exception:
        user_prefs = None

    text = (
        "⚙️ **Alert Settings**\n\n"
        f"• Interval: `{format_interval(data)}`\n"
        f"• Time: `{data.get('schedule', {}).get('time', '10:00')}`\n"
    )
    if repetition_supported:
        text += f"• Repetition: `{format_repetition(data)}`\n"
    text += (
        f"• Pre-alert: `{format_pre_alerts(data, user_prefs=user_prefs)}`\n"
        f"• Photo: `{format_photo_choice(data)}`\n"
        f"• Additional Info: `{format_additional_info(data)}`\n\n"
        "Choose what to change:"
    )

    keyboard = []
    keyboard.append([InlineKeyboardButton("🔄 Change alert type", callback_data="ms_change_type")])
    if repetition_supported:
        keyboard.append([
            InlineKeyboardButton("Set interval", callback_data="ms_interval"),
            InlineKeyboardButton("Set time", callback_data="ms_time"),
        ])
        keyboard.append([
            InlineKeyboardButton("Set pre-alert", callback_data="ms_pre"),
            InlineKeyboardButton("Set repetition", callback_data="ms_repetition"),
        ])
        keyboard.append([
            InlineKeyboardButton("Set picture", callback_data="ms_photo"),
            InlineKeyboardButton("Additional INFO", callback_data="ms_info"),
        ])
    else:
        keyboard.append([InlineKeyboardButton("Set time", callback_data="ms_time")])
        keyboard.append([InlineKeyboardButton("Set pre-alert", callback_data="ms_pre")])
        keyboard.append([
            InlineKeyboardButton("Set picture", callback_data="ms_photo"),
            InlineKeyboardButton("Additional INFO", callback_data="ms_info"),
        ])
    keyboard.append([InlineKeyboardButton("✅ DONE", callback_data="ms_done")])

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
    return C.MULTI_SETTINGS


async def handle_multi_setting_choice(
    update,
    context,
    get_interval_prompt,
    ask_time,
    show_pre_alert_menu,
    show_photo_menu,
    prompt_additional_info,
    show_tags_menu,
    show_repetition_menu=None,
):
    """Route settings-menu actions to the selected add-flow substep."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ms_interval":
        return await get_interval_prompt(update, context)
    if data == "ms_time":
        return await ask_time(update, context)
    if data == "ms_pre":
        return await show_pre_alert_menu(update, context)
    if data == "ms_photo":
        return await show_photo_menu(update, context)
    if data == "ms_info":
        return await prompt_additional_info(update, context)
    if data == "ms_repetition" and callable(show_repetition_menu):
        return await show_repetition_menu(update, context)
    if data == "ms_change_type":
        return await show_change_type_menu(update, context)
    if data == "ms_done":
        return await show_tags_menu(update, context)

    return C.MULTI_SETTINGS


async def show_change_type_menu(update, context):
    """Show the inline menu for changing alert type mid-flow."""
    query = update.callback_query
    if query:
        await _edit_callback_message(
            query,
            "🔄 **Change alert type**\nSelect the new type:",
            reply_markup=build_change_type_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    return C.CHANGE_ALERT_TYPE


async def _change_type_callback_impl(update, context, return_fn, prompt_type_specific_fn):
    query = update.callback_query
    data = query.data or ""
    if data == "ct_back":
        await query.answer()
        return await return_fn(update, context)
    if not data.startswith("ct_"):
        await query.answer("Invalid type option.", show_alert=True)
        return C.CHANGE_ALERT_TYPE

    try:
        next_type = int(data.replace("ct_", "", 1))
    except Exception:
        await query.answer("Invalid type option.", show_alert=True)
        return C.CHANGE_ALERT_TYPE

    if next_type not in _CHANGE_TYPE_ALLOWED_IDS:
        await query.answer("This type cannot be selected here.", show_alert=True)
        return C.CHANGE_ALERT_TYPE

    temp_alert = context.user_data.get("temp_alert")
    if not isinstance(temp_alert, dict):
        await query.answer("Session expired.", show_alert=True)
        return C.CHANGE_ALERT_TYPE

    current_type = temp_alert.get("type")
    await query.answer()
    if current_type == next_type:
        context.user_data["temp_selection"] = []
        return await prompt_type_specific_fn(update, context)

    schedule = temp_alert.get("schedule")
    if not isinstance(schedule, dict):
        schedule = {}
        temp_alert["schedule"] = schedule
    for key in ("days", "ordinals", "weekdays", "fifth_policy", "dates", "date", "interval", "start_marker"):
        schedule.pop(key, None)

    context.user_data["temp_selection"] = []
    temp_alert["type"] = next_type
    temp_alert["type_name"] = C.ALERT_TYPES.get(next_type, str(next_type))
    return await prompt_type_specific_fn(update, context)


async def prompt_additional_info(update, context):
    """Prompt for optional additional info; send a raw copy of the current text when non-empty.

    Sends the keyboard prompt first, then — when additional_info is already
    stored and non-blank — sends a plain copy message (no parse_mode) so the
    user can copy-paste the existing text.  The copy message_id is stored in
    context.user_data["additional_info_copy_msg_id"] for cleanup on exit.
    On the callback path the copy is skipped silently when callback_query.message
    is None; no message_id is stored in that case.
    """
    text = (
        "📝 **Additional Info**\n"
        "Send any extra details for this alert."
    )
    keyboard = [[
        InlineKeyboardButton("❌ Cancel this operation", callback_data="info_skip"),
        InlineKeyboardButton("🗑️ Clear present text", callback_data="info_clear"),
    ]]
    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
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

    raw_existing = ((context.user_data.get("temp_alert") or {}).get("additional_info") or "")
    if raw_existing.strip():
        copy_msg = None
        if update.callback_query:
            if update.callback_query.message is not None:
                copy_msg = await update.callback_query.message.reply_text(
                    f"Current text:\n{raw_existing}"
                )
        else:
            copy_msg = await update.message.reply_text(
                f"Current text:\n{raw_existing}"
            )
        if copy_msg is not None:
            context.user_data["additional_info_copy_msg_id"] = copy_msg.message_id

    return C.GET_ADDITIONAL_INFO


async def handle_additional_info_input(update, context, return_to_settings):
    """Validate and store additional information before returning to settings."""
    raw_text = update.message.text or ""
    if raw_text.strip() == "":
        raw_text = ""
    if len(raw_text) > C.ADDITIONAL_INFO_MAX_LEN:
        try:
            storage = get_runtime_storage(context)
            target_id = get_target_user_id(update, context)
            storage.log_user_event(
                target_id,
                "additional_info_input_too_long",
                {"text_len": len(raw_text)},
            )
        except Exception:
            pass
        await update.message.reply_text(
            f"⚠️ Text too long (max {C.ADDITIONAL_INFO_MAX_LEN} characters). Try again."
        )
        return C.GET_ADDITIONAL_INFO
    context.user_data["temp_alert"]["additional_info"] = raw_text
    await _delete_additional_info_copy_message(update, context)
    return await return_to_settings(update, context)


async def handle_additional_info_clear(update, context, return_to_settings):
    """Clear staged additional info explicitly and route back through the active settings destination."""
    query = update.callback_query
    if query:
        await query.answer()
    temp_alert = context.user_data.get("temp_alert")
    if not isinstance(temp_alert, dict):
        temp_alert = {}
        context.user_data["temp_alert"] = temp_alert
    temp_alert["additional_info"] = ""
    await _delete_additional_info_copy_message(update, context)
    return await return_to_settings(update, context)


async def handle_additional_info_skip(update, context, return_to_settings):
    """Skip additional information and return to settings."""
    query = update.callback_query
    if query:
        await query.answer()
    await _delete_additional_info_copy_message(update, context)
    return await return_to_settings(update, context)
