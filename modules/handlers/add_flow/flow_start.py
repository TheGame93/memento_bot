from telegram.constants import ParseMode
from telegram.ext import ConversationHandler

from modules import constants as C
from modules.handlers.add_flow.keyboards import build_toggle_keyboard, build_type_keyboard
from modules.handlers.add_flow.state_helpers import (
    track_add_flow_callback_message,
    track_add_flow_incoming,
    track_add_flow_outgoing,
)
from modules.shared.acting_as import get_actor_user_id, get_target_user_id
from modules.shared.messages import edit_callback_message_media_aware as _edit_callback_message
from modules.shared.runtime_context import get_runtime_storage


async def start_add(update, context):
    """Start the add-alert flow from a message entrypoint."""
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)
    # Clear stale add-flow routing/telemetry hints when restarting the wizard.
    context.user_data.pop("settings_return", None)
    context.user_data.pop("daily_interval_confirm_source", None)
    context.user_data["temp_alert"] = {"tags": [], "pre_alerts": [], "schedule": {}}
    context.user_data["add_flow_message_ids"] = []
    track_add_flow_incoming(update, context)
    sent = await update.message.reply_text(
        "📝 **New Alert** — Enter the name:",
        parse_mode=ParseMode.MARKDOWN,
    )
    track_add_flow_outgoing(context, sent)
    context.user_data["add_flow_start_message_id"] = sent.message_id
    return C.GET_TITLE


async def start_add_from_menu(update, context):
    """Start the add-alert flow from the alerts menu callback."""
    query = update.callback_query
    await query.answer()
    context.user_data.pop("expecting_birthday_search", None)
    context.user_data.pop("expecting_alert_search", None)
    # Clear stale add-flow routing/telemetry hints when restarting the wizard.
    context.user_data.pop("settings_return", None)
    context.user_data.pop("daily_interval_confirm_source", None)
    context.user_data["temp_alert"] = {"tags": [], "pre_alerts": [], "schedule": {}}
    context.user_data["add_flow_message_ids"] = []
    try:
        await query.message.delete()
    except Exception:
        pass
    actor_id = get_actor_user_id(update) or (update.effective_user.id if update.effective_user else None)
    sent = await context.bot.send_message(
        chat_id=actor_id,
        text="📝 **New Alert** — Enter the name:",
        parse_mode=ParseMode.MARKDOWN,
    )
    track_add_flow_outgoing(context, sent)
    context.user_data["add_flow_start_message_id"] = sent.message_id
    return C.GET_TITLE


async def select_type(update, context):
    """Store the selected alert type and route to type-specific prompts."""
    track_add_flow_callback_message(update, context)
    query = update.callback_query
    await query.answer()
    type_id = int(query.data.replace(C.CB_TYPE, ""))

    context.user_data["temp_alert"]["type"] = type_id
    context.user_data["temp_alert"]["type_name"] = C.ALERT_TYPES[type_id]
    return await prompt_type_specific(update, context)


async def get_title(update, context, prompt_type_specific):
    """Validate and store the alert title before opening type selection."""
    track_add_flow_incoming(update, context)
    title = (update.message.text or "").strip()
    # Prevent blank or whitespace-only titles from being saved.
    if not title:
        await update.message.reply_text("❌ Title cannot be empty. Try again.")
        return C.GET_TITLE
    if len(title) > C.TITLE_MAX_LEN:
        try:
            storage = get_runtime_storage(context)
            target_id = get_target_user_id(update, context)
            storage.log_user_event(target_id, "title_input_too_long", {"title_len": len(title)})
        except Exception:
            pass
        await update.message.reply_text(
            f"⚠️ Title too long (max {C.TITLE_MAX_LEN} characters). Try again."
        )
        return C.GET_TITLE

    context.user_data["temp_alert"]["title"] = title
    sent = await update.message.reply_text(
        "🆕 **New Alert**\n\nSelect the **Type** of alert:",
        reply_markup=build_type_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )
    track_add_flow_outgoing(context, sent)
    return C.SELECT_TYPE


async def prompt_type_specific(update, context, get_interval_prompt=None):
    """Prompt for schedule fields required by the selected alert type."""
    track_add_flow_incoming(update, context)

    async def _edit_or_send(text, reply_markup=None):
        query = update.callback_query if update else None
        if query:
            sent_message = await _edit_callback_message(
                query,
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
            )
            track_add_flow_outgoing(context, sent_message)
            return sent_message

        actor_id = get_actor_user_id(update)
        effective_user = getattr(update, "effective_user", None) if update else None
        chat_id = actor_id or (effective_user.id if effective_user else None)
        if chat_id is None:
            return None
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
        track_add_flow_outgoing(context, sent_message)
        return sent_message

    type_id = context.user_data["temp_alert"].get("type")
    if type_id == 1:
        await _edit_or_send(
            "📅 **Monthly (Days)**\nWrite days (1-31) separated by commas (e.g. `1, 15`):",
        )
        return C.TYPE_1_DAYS
    if type_id == 2:
        context.user_data["temp_selection"] = []
        await _edit_or_send(
            "📅 **Monthly (Relative)**\nSelect occurrences (Toggle):",
            reply_markup=build_toggle_keyboard(C.ORDINALS, [], C.CB_ORDINAL),
        )
        return C.TYPE_2_ORDINAL
    if type_id == 3:
        context.user_data["temp_selection"] = []
        await _edit_or_send(
            "📅 **Weekly**\nSelect Weekdays:",
            reply_markup=build_toggle_keyboard(C.WEEKDAYS, [], C.CB_WEEKDAY),
        )
        return C.TYPE_3_WEEKDAYS
    if type_id == 4:
        await _edit_or_send(
            "📅 **Yearly**\nWrite dates as DD/MM (e.g. `25/12, 01/01`):",
        )
        return C.TYPE_4_DATES
    if type_id == 5:
        await _edit_or_send(
            "📅 **One Time**\nWrite date as DD/MM, DD/MM/YY or DD/MM/YYYY:",
        )
        return C.TYPE_5_DATE
    if type_id == 6:
        await _edit_or_send(
            "🎂 **Birthday**\nBirthdays are managed with /birthdays.",
        )
        return ConversationHandler.END
    if type_id == 7:
        if get_interval_prompt is not None:
            return await get_interval_prompt(update, context)

        await _edit_or_send(
            "🔁 **Interval**\nHow many days between occurrences?\nEnter a number:",
        )
        return C.GET_INTERVAL
    return ConversationHandler.END
