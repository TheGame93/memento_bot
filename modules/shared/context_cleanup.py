import functools
import os

from telegram.ext import ConversationHandler

from modules.shared import context_keys as K

EXPIRED_FLOW_TEXT = (
    "⏹️ Session expired or interrupted. "
    "Use /alerts or /birthdays to restart, or /cancel."
)


def require_temp_alert(func):
    """Guard: ends conversation gracefully if temp_alert is missing from user_data."""
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if "temp_alert" not in context.user_data:
            clear_transient_context(context.user_data)
            delivered = False
            if update.callback_query:
                try:
                    await update.callback_query.answer("Session expired.", show_alert=True)
                except Exception:
                    pass
                try:
                    message = update.callback_query.message
                    if message and getattr(message, "photo", None):
                        await update.callback_query.edit_message_caption(
                            caption=EXPIRED_FLOW_TEXT,
                            reply_markup=None,
                        )
                    else:
                        await update.callback_query.edit_message_text(
                            EXPIRED_FLOW_TEXT,
                            reply_markup=None,
                        )
                    delivered = True
                except Exception:
                    pass
                if not delivered:
                    chat = getattr(update, "effective_chat", None)
                    chat_id = getattr(chat, "id", None)
                    if chat_id is not None:
                        try:
                            await context.bot.send_message(chat_id=chat_id, text=EXPIRED_FLOW_TEXT)
                            delivered = True
                        except Exception:
                            pass
            elif update.message:
                try:
                    await update.message.reply_text(EXPIRED_FLOW_TEXT)
                    delivered = True
                except Exception:
                    pass
            if not delivered:
                try:
                    message = getattr(update, "effective_message", None)
                    if message:
                        await message.reply_text(EXPIRED_FLOW_TEXT)
                except Exception:
                    pass
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapper


def _pop_keys(user_data, keys):
    for key in keys:
        user_data.pop(key, None)


def _pop_dynamic_prefixes(user_data, prefixes):
    for key in list(user_data.keys()):
        if any(key.startswith(prefix) for prefix in prefixes):
            user_data.pop(key, None)


def has_transient_context(user_data):
    """
    Returns True when user_data contains any transient flow state.

    Rule: presence of a key counts as active unless the value is the
    boolean False. This avoids false-negatives for empty lists/dicts
    while allowing explicit False flags to mean "inactive".
    """
    if not isinstance(user_data, dict):
        return False
    key_groups = (
        K.ADD_FLOW_KEYS,
        K.SEARCH_KEYS,
        K.TAG_KEYS,
        K.BACKUP_KEYS,
        K.TIMEZONE_KEYS,
        K.SETTINGS_KEYS,
        K.EDIT_TEXT_KEYS,
        K.EDIT_FLOW_KEYS,
        K.POSTPONE_KEYS,
        K.GHOST_KEYS,
        K.FILTER_KEYS,
        K.ADMIN_KEYS,
        K.ONBOARDING_KEYS,
    )
    for group in key_groups:
        for key in group:
            if key in user_data:
                value = user_data.get(key)
                if isinstance(value, bool):
                    if value:
                        return True
                    continue
                return True
    for key in user_data.keys():
        if any(key.startswith(prefix) for prefix in K.DYNAMIC_PREFIXES):
            return True
    return False


def clear_transient_context(user_data, include_navigation=False):
    """
    Removes temporary runtime state while keeping persistent/user preference data.
    """
    session = user_data.get("backup_import_session") if isinstance(user_data, dict) else None
    if isinstance(session, dict):
        temp_path = session.get("temp_path")
        if isinstance(temp_path, str) and temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    _pop_keys(user_data, K.ADD_FLOW_KEYS)
    _pop_keys(user_data, K.SEARCH_KEYS)
    _pop_keys(user_data, K.TAG_KEYS)
    _pop_keys(user_data, K.BACKUP_KEYS)
    _pop_keys(user_data, K.TIMEZONE_KEYS)
    _pop_keys(user_data, K.SETTINGS_KEYS)
    _pop_keys(user_data, K.EDIT_TEXT_KEYS)
    _pop_keys(user_data, K.EDIT_FLOW_KEYS)
    _pop_keys(user_data, K.POSTPONE_KEYS)
    _pop_keys(user_data, K.GHOST_KEYS)
    _pop_keys(user_data, K.FILTER_KEYS)
    _pop_keys(user_data, K.ADMIN_KEYS)
    _pop_keys(user_data, K.ONBOARDING_KEYS)
    _pop_dynamic_prefixes(user_data, K.DYNAMIC_PREFIXES)

    if include_navigation:
        _pop_keys(user_data, K.NAVIGATION_KEYS)
