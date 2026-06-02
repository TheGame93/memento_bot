"""Build timezone settings UI and handle timezone text/location inputs."""

import html
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import ContextTypes

from modules import constants as C
from modules.shared.acting_as import build_acting_as_payload, get_target_user_id
from modules.shared.callback_codec import (
    build_value_token_map,
    ensure_callback_fits,
)
from modules.shared.runtime_context import get_runtime_storage
from modules.systemlog import log_system
from modules.timezone_catalog import describe_timezone, suggest_timezones
from modules.timezone_geo import resolve_timezone_from_location
from modules.timezone_utils import (
    format_tz_offset,
    get_server_tz,
    get_server_tz_name,
    now_server_naive,
    resolve_user_timezone,
    validate_tz_name,
)

TZ_PICK_PREFIX = "settings_timezone_pick_"


def _format_timezone_line(tz_name, reference):
    try:
        tz = get_server_tz() if tz_name == get_server_tz_name() else resolve_user_timezone({
            "timezone_mode": C.TIMEZONE_MODE_USER,
            "timezone": {"name": tz_name},
        })
    except Exception:
        tz = get_server_tz()
    ref = reference
    try:
        if isinstance(ref, datetime) and ref.tzinfo is None:
            ref = ref.replace(tzinfo=get_server_tz())
    except Exception:
        ref = reference
    offset = format_tz_offset(ref, tz)
    return f"{tz_name} ({offset})"


def build_timezone_keyboard(prefs):
    """Build timezone settings controls for mode and source selection."""
    mode = prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    tz_block = prefs.get("timezone") if isinstance(prefs, dict) else {}
    source = tz_block.get("source") if isinstance(tz_block, dict) else None
    source = source or C.TIMEZONE_SOURCE_DEFAULT

    server_label = "✅ Use Server Time" if mode == C.TIMEZONE_MODE_SERVER else "Use Server Time"
    user_label = "✅ Use my timezone" if mode == C.TIMEZONE_MODE_USER else "Use my timezone"
    auto_label = "✅ Auto timezone set" if source == C.TIMEZONE_SOURCE_AUTO else "Auto timezone set"
    manual_label = "✅ Manual timezone set" if source == C.TIMEZONE_SOURCE_MANUAL else "Manual timezone set"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(server_label, callback_data="settings_timezone_mode_server"),
            InlineKeyboardButton(user_label, callback_data="settings_timezone_mode_user"),
        ],
        [
            InlineKeyboardButton(manual_label, callback_data="settings_timezone_set"),
            InlineKeyboardButton(auto_label, callback_data="settings_timezone_auto"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="settings_back")],
    ])


def build_location_request_keyboard():
    """Build a one-tap reply keyboard that requests location sharing."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Share location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_timezone_status(prefs):
    """Build timezone status text and settings keyboard from user preferences."""
    mode = prefs.get("timezone_mode") or C.TIMEZONE_DEFAULT_MODE
    tz_block = prefs.get("timezone") if isinstance(prefs, dict) else {}
    tz_name = tz_block.get("name") if isinstance(tz_block, dict) else None
    source = tz_block.get("source") if isinstance(tz_block, dict) else None
    source = source or C.TIMEZONE_SOURCE_DEFAULT

    server_tz_name = get_server_tz_name()
    server_now = now_server_naive()
    server_line = _format_timezone_line(server_tz_name, server_now)

    if validate_tz_name(tz_name):
        user_tz_name = tz_name
    else:
        user_tz_name = server_tz_name

    user_line = _format_timezone_line(user_tz_name, server_now)
    mode_label = "Server time" if mode == C.TIMEZONE_MODE_SERVER else "Your timezone"
    source_label = source.capitalize()
    if source == C.TIMEZONE_SOURCE_AUTO and user_tz_name == server_tz_name:
        source_label = "Auto (fallback to server)"

    message = (
        "🕒 <b>Timezone Settings</b>\n\n"
        f"Mode: <b>{mode_label}</b>\n"
        f"Source: <b>{html.escape(source_label)}</b>\n"
        f"Server TZ: <code>{html.escape(server_line)}</code>\n"
        f"User TZ: <code>{html.escape(user_line)}</code>\n\n"
        "Select how the bot should interpret your alert times."
    )
    keyboard = build_timezone_keyboard(prefs)
    return message, keyboard


async def handle_timezone_query_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle manual timezone query input and persist a selected timezone."""
    if not context.user_data.get("expecting_timezone_query"):
        return False
    user_id = get_target_user_id(update, context)
    storage = get_runtime_storage(context)

    raw_query = (update.message.text or "").strip()
    if not raw_query:
        await update.message.reply_text("⚠️ Send a timezone name or /cancel.")
        return True

    context.user_data["timezone_query_value"] = raw_query
    matches = suggest_timezones(raw_query, limit=C.TIMEZONE_SUGGESTION_LIMIT)

    if not matches:
        await update.message.reply_text(
            "❌ No timezone found. Try a city or an IANA name like Europe/Rome."
        )
        return True

    if len(matches) == 1:
        tz_name = matches[0]
        _update_timezone_prefs(
            storage,
            user_id,
            tz_name=tz_name,
            source=C.TIMEZONE_SOURCE_MANUAL,
            state=raw_query,
            mode=C.TIMEZONE_MODE_USER,
        )
        updated = _reschedule_user_timezones(user_id, reason="timezone_manual")
        payload = {
            "source": "settings",
            "timezone": tz_name,
            "updated_alerts": updated,
        }
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "timezone_manual_set", payload)
        context.user_data.pop("expecting_timezone_query", None)
        context.user_data.pop("timezone_pick_token_map", None)
        prefs = storage.get_user_prefs(user_id) or {}
        message, keyboard = build_timezone_status(prefs)
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
        return True

    token_map = build_value_token_map(matches)
    context.user_data["timezone_pick_token_map"] = token_map
    keyboard = []
    for token, tz_name in token_map.items():
        callback_data = f"{TZ_PICK_PREFIX}{token}"
        if not ensure_callback_fits(callback_data):
            continue
        keyboard.append([InlineKeyboardButton(describe_timezone(tz_name), callback_data=callback_data)])
    if not keyboard:
        await update.message.reply_text(
            "❌ Timezone selection failed. Please try again."
        )
        return True
    await update.message.reply_text(
        "🌍 Multiple matches found. Choose your timezone:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return True


async def handle_timezone_location_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle shared-location timezone detection and persist auto timezone."""
    if not context.user_data.get("expecting_timezone_location"):
        return False
    message = update.effective_message or update.message
    if not message or not getattr(message, "location", None):
        return False

    user_id = get_target_user_id(update, context)
    storage = get_runtime_storage(context)
    location = message.location
    tz_name = resolve_timezone_from_location(location.latitude, location.longitude)

    context.user_data.pop("expecting_timezone_location", None)
    context.user_data.pop("timezone_pick_token_map", None)

    if not tz_name:
        payload = {"source": "settings"}
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "timezone_auto_failed", payload)
        await message.reply_text(
            "❌ Could not detect your timezone.",
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.reply_text(
            "Choose a manual timezone instead:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Manual timezone set", callback_data="settings_timezone_set")],
            ]),
        )
        return True

    _update_timezone_prefs(
        storage,
        user_id,
        tz_name=tz_name,
        source=C.TIMEZONE_SOURCE_AUTO,
        state="location",
        mode=C.TIMEZONE_MODE_USER,
    )
    updated = _reschedule_user_timezones(user_id, reason="timezone_auto")
    payload = {
        "source": "settings",
        "timezone": tz_name,
        "updated_alerts": updated,
    }
    payload.update(build_acting_as_payload(update, context))
    storage.log_user_event(user_id, "timezone_auto_set", payload)
    prefs = storage.get_user_prefs(user_id) or {}
    message_text, keyboard = build_timezone_status(prefs)
    await message.reply_text(
        message_text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await message.reply_text("✅ Timezone updated.", reply_markup=ReplyKeyboardRemove())
    return True


def _update_timezone_prefs(storage, user_id, *, tz_name=None, source=None, state=None, mode=None):
    prefs = storage.get_user_prefs(user_id) or {}
    tz_block = prefs.get("timezone") if isinstance(prefs, dict) else {}
    if not isinstance(tz_block, dict):
        tz_block = {}
    if tz_name is not None:
        tz_block["name"] = tz_name
    if source is not None:
        tz_block["source"] = source
    if state is not None:
        tz_block["state"] = state
    tz_block["updated_at"] = now_server_naive().isoformat()
    updates = {"timezone": tz_block}
    if mode is not None:
        updates["timezone_mode"] = mode
    return storage.update_user_prefs(user_id, updates)


def _reschedule_user_timezones(user_id, reason):
    from modules.scheduler_core.coordinator import reschedule_user_alerts
    try:
        updated = reschedule_user_alerts(user_id, reason=reason)
    except Exception as exc:
        log_system("scheduler", "timezone_reschedule_failed", {
            "user_id": str(user_id),
            "error": str(exc),
            "reason": reason,
        }, level="ERROR")
        return 0
    return updated
