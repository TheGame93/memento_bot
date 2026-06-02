from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from modules import constants as C
from modules.repetition_utils import (
    default_repetition_payload,
    format_repetition_human,
    is_repetition_supported,
    normalize_repetition_payload,
    parse_until_date_input,
)
from modules.shared.acting_as import build_acting_as_payload, get_target_user_id
from modules.shared.logging_utils import text_meta
from modules.shared.messages import edit_callback_message_media_aware as _edit_callback_message
from modules.shared.runtime_context import get_runtime_storage
from modules.timezone_utils import (
    now_server_naive,
    resolve_user_timezone,
    to_user_naive_from_server,
)


def _source_label(context):
    value = None
    if context is not None:
        user_data = getattr(context, "user_data", None)
        if isinstance(user_data, dict):
            value = user_data.get("settings_return")
    if isinstance(value, str) and value.strip().lower() == "edit":
        return "edit_flow"
    return "add_flow"


def _log_repetition_event(update, context, event_type, payload=None):
    try:
        storage = get_runtime_storage(context)
    except Exception:
        return

    user_id = get_target_user_id(update, context)
    if user_id is None:
        return

    meta = {"source": _source_label(context)}
    meta.update(build_acting_as_payload(update, context))
    if isinstance(payload, dict):
        meta.update(payload)
    try:
        storage.log_user_event(user_id, event_type, meta)
    except Exception:
        pass


def _current_alert(context):
    user_data = getattr(context, "user_data", None)
    if not isinstance(user_data, dict):
        return {}
    alert = user_data.get("temp_alert")
    if not isinstance(alert, dict):
        alert = {}
        user_data["temp_alert"] = alert
    return alert


def _load_user_prefs(update, context):
    user_id = get_target_user_id(update, context)
    if user_id is None:
        return None
    try:
        storage = get_runtime_storage(context)
    except Exception:
        return None
    if not hasattr(storage, "get_user_prefs"):
        return None
    try:
        return storage.get_user_prefs(user_id)
    except Exception:
        return None


def _local_today_for_repetition(update, context):
    now_local = now_server_naive()
    user_prefs = _load_user_prefs(update, context)
    if isinstance(user_prefs, dict):
        mode = user_prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
        if mode == C.TIMEZONE_MODE_USER:
            try:
                user_tz = resolve_user_timezone(user_prefs)
                now_local = to_user_naive_from_server(now_local, user_tz)
            except Exception:
                pass
    return now_local.date()


async def show_repetition_menu(update, context):
    """Show repetition mode options for repetition-capable alert types."""
    alert = _current_alert(context)
    alert_type = alert.get("type")
    if not is_repetition_supported(alert_type):
        return C.MULTI_SETTINGS

    normalized = normalize_repetition_payload(alert_type, alert.get("repetition"))
    alert["repetition"] = normalized
    current = format_repetition_human(alert_type, normalized)
    _log_repetition_event(update, context, "repetition_menu_opened", {
        "current_mode": (normalized or {}).get("mode"),
    })

    text = (
        "🔁 **Set Repetition**\n\n"
        f"Current: `{current}`\n\n"
        "Choose repetition mode:"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Forever", callback_data="rep_forever")],
        [InlineKeyboardButton("Until date", callback_data="rep_until")],
        [InlineKeyboardButton("Total events", callback_data="rep_count")],
        [InlineKeyboardButton("⬅️ Back", callback_data="rep_back")],
    ])

    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    return C.GET_REPETITION_MENU


async def handle_repetition_choice(update, context, return_to_settings, prompt_until, prompt_count):
    """Handle repetition mode selection and route to the next repetition step."""
    query = update.callback_query
    data = (query.data or "").strip()
    alert = _current_alert(context)
    alert_type = alert.get("type")

    if data not in {"rep_forever", "rep_until", "rep_count", "rep_back"}:
        await query.answer("Invalid repetition option.", show_alert=True)
        return C.GET_REPETITION_MENU

    await query.answer()

    if data == "rep_back":
        return await return_to_settings(update, context)

    if not is_repetition_supported(alert_type):
        return await return_to_settings(update, context)

    if data == "rep_forever":
        alert["repetition"] = default_repetition_payload(alert_type)
        _log_repetition_event(update, context, "repetition_mode_selected", {"mode": C.REPETITION_MODE_FOREVER})
        _log_repetition_event(update, context, "repetition_forever_set", {"mode": C.REPETITION_MODE_FOREVER})
        return await return_to_settings(update, context)

    if data == "rep_until":
        _log_repetition_event(update, context, "repetition_mode_selected", {"mode": C.REPETITION_MODE_UNTIL_DATE})
        return await prompt_until(update, context)

    _log_repetition_event(update, context, "repetition_mode_selected", {"mode": C.REPETITION_MODE_COUNT})
    return await prompt_count(update, context)


async def prompt_repetition_until_date(update, context):
    """Prompt for an inclusive repetition end date."""
    text = (
        "📅 **Until Date**\n"
        "Send the final (included) date as `DD/MM/YYYY`.\n"
    )
    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return C.GET_REPETITION_UNTIL_DATE


async def prompt_repetition_count(update, context):
    """Prompt for a repetition occurrence-count limit."""
    text = (
        "🔢 **Total Events**\n"
        "Send how many future events should be allowed."
    )
    if update.callback_query:
        await _edit_callback_message(
            update.callback_query,
            text,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return C.GET_REPETITION_COUNT


async def handle_repetition_until_date_input(update, context, return_to_settings):
    """Validate until-date input, log reasoned failures, and persist normalized repetition limits.
    
    Accept `D/M/(YY|YYYY)` formats, enforce local-date non-past boundaries, and return
    to settings only after normalization succeeds for supported alert types.
    """
    raw_text = (getattr(update.message, "text", "") or "").strip()
    parsed, _used_two_digit_year = parse_until_date_input(raw_text)
    alert = _current_alert(context)
    alert_type = alert.get("type")

    if parsed is None:
        reason_code = "empty" if raw_text == "" else "invalid_format_or_date"
        _log_repetition_event(update, context, "repetition_until_invalid", {
            "reason_code": reason_code,
            "until_input_meta": text_meta(raw_text),
        })
        await update.message.reply_text(
            "❌ Invalid date. Use `D/M/YY`, `DD/MM/YY`, `D/M/YYYY`, or `DD/MM/YYYY` (for example `3/4/27` or `03/04/2027`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_REPETITION_UNTIL_DATE
    local_today = _local_today_for_repetition(update, context)
    if parsed < local_today:
        _log_repetition_event(update, context, "repetition_until_invalid", {
            "reason_code": "past_date",
            "until_input_meta": text_meta(raw_text),
        })
        await update.message.reply_text(
            "❌ Invalid date. The repetition limit cannot be in the past for your local time.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_REPETITION_UNTIL_DATE

    normalized = normalize_repetition_payload(alert_type, {
        "mode": C.REPETITION_MODE_UNTIL_DATE,
        "until_date": parsed.strftime("%d/%m/%Y"),
    })
    if normalized is None:
        _log_repetition_event(update, context, "repetition_until_invalid", {
            "reason_code": "unsupported_type",
            "until_input_meta": text_meta(raw_text),
        })
        return await return_to_settings(update, context)

    alert["repetition"] = normalized
    _log_repetition_event(update, context, "repetition_until_set", {
        "mode": C.REPETITION_MODE_UNTIL_DATE,
        "until_date": normalized.get("until_date"),
    })
    return await return_to_settings(update, context)


async def handle_repetition_count_input(update, context, return_to_settings):
    """Validate count input, log reasoned failures, and persist normalized repetition limits.
    
    Reject empty, non-numeric, and less-than-one values while preserving unsupported-type
    fail-soft behavior that returns to settings without mutating repetition state.
    """
    raw_text = (getattr(update.message, "text", "") or "").strip()
    alert = _current_alert(context)
    alert_type = alert.get("type")

    count_value = None
    reason_code = None
    if raw_text == "":
        reason_code = "empty"
    else:
        try:
            count_value = int(raw_text)
        except Exception:
            reason_code = "invalid_number"
        else:
            if count_value < 1:
                reason_code = "less_than_one"

    if reason_code is not None:
        _log_repetition_event(update, context, "repetition_count_invalid", {
            "reason_code": reason_code,
            "count_input_meta": text_meta(raw_text),
        })
        await update.message.reply_text(
            "❌ Invalid count. Send an integer greater than or equal to `1`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return C.GET_REPETITION_COUNT

    normalized = normalize_repetition_payload(alert_type, {
        "mode": C.REPETITION_MODE_COUNT,
        "count_remaining": count_value,
    })
    if normalized is None:
        _log_repetition_event(update, context, "repetition_count_invalid", {
            "reason_code": "unsupported_type",
            "count_input_meta": text_meta(raw_text),
        })
        return await return_to_settings(update, context)

    alert["repetition"] = normalized
    _log_repetition_event(update, context, "repetition_count_set", {
        "mode": C.REPETITION_MODE_COUNT,
        "count_remaining": int(normalized.get("count_remaining") or 0),
    })
    return await return_to_settings(update, context)
