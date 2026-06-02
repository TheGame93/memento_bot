from __future__ import annotations

from typing import Any, Optional

from modules.shared.acting_as import build_acting_as_payload, get_target_user_id
from modules.telegram_resilience import (
    is_message_not_modified_error as _is_message_not_modified_error_strict,
)
from telegram.constants import ParseMode

FEATURE_NOT_IMPLEMENTED_TEXT = "Feature still not implemented, sorry for the inconvenience."


def is_message_not_modified_error(exc: Exception) -> bool:
    """Return whether an exception is Telegram's benign message-not-modified edit outcome."""
    if _is_message_not_modified_error_strict(exc):
        return True
    try:
        message = str(exc or "").strip().lower()
    except Exception:
        return False
    return "message is not modified" in message


async def edit_callback_message_media_aware(
    query,
    text,
    *,
    reply_markup=None,
    parse_mode=ParseMode.MARKDOWN,
):
    """Edit a callback message as caption for photo cards and text otherwise, treating no-op edits as benign."""
    if query is None:
        return None

    message = getattr(query, "message", None)
    is_photo_message = bool(message and getattr(message, "photo", None))
    try:
        if is_photo_message:
            return await query.edit_message_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        return await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as exc:
        if is_message_not_modified_error(exc):
            return message
        raise


async def send_feature_not_implemented(
    update: Any,
    context: Any,
    storage: Any,
    *,
    feature_label: Optional[str] = None,
    reply_markup: Any = None,
) -> str:
    """Send the standard not-implemented response and emit optional user telemetry."""
    target_id = get_target_user_id(update, context)
    payload = {}
    if feature_label:
        payload["feature"] = str(feature_label)
    payload.update(build_acting_as_payload(update, context))
    if target_id is not None and storage is not None:
        storage.log_user_event(target_id, "feature_not_implemented", payload)

    message = FEATURE_NOT_IMPLEMENTED_TEXT
    if update is None:
        return message

    query = getattr(update, "callback_query", None)
    if query is not None:
        delivered = False
        msg = getattr(query, "message", None)
        if msg is not None and getattr(msg, "photo", None) and getattr(msg, "caption", None) is not None:
            try:
                await query.edit_message_caption(caption=message, reply_markup=reply_markup)
                delivered = True
            except Exception:
                delivered = False
        if not delivered:
            try:
                await query.edit_message_text(message, reply_markup=reply_markup)
                delivered = True
            except Exception:
                delivered = False
        if delivered:
            return message

    target = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if target is not None:
        try:
            await target.reply_text(message, reply_markup=reply_markup)
        except Exception:
            pass
    return message
