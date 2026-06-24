from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.handlers.birthday_flow.message_suggestions.callbacks import (
    build_bday_msg_callback,
    decode_bday_msg_callback,
    decode_bday_noted_callback,
)
from modules.handlers.birthday_flow.message_suggestions.catalog import (
    ArchiveValidationError,
    load_archive,
)
from modules.handlers.birthday_flow.message_suggestions.inference import (
    infer_message_context,
    infer_turning_age,
    infer_zodiac_context,
)
from modules.handlers.birthday_flow.message_suggestions.zodiac_assembler import (
    assemble_zodiac_message,
)
from modules.handlers.birthday_flow.message_suggestions.selector import select_template
from modules.shared.runtime_context import get_runtime_storage

logger = logging.getLogger(__name__)

_STYLE_OPTIONS = ("polite", "boomer", "cringe", "zodiac")
_STYLE_BUTTONS = (
    ("Yes, very polite", "polite"),
    ("Yes, very boomer", "boomer"),
    ("Yes, very cringe", "cringe"),
    ("Yes, with the stars", "zodiac"),
    ("No, I'll do it myself", "no"),
)


def _build_prompt_keyboard(alert_id: str, occurrence_time) -> InlineKeyboardMarkup:
    buttons = []
    for label, style in _STYLE_BUTTONS:
        callback_data = build_bday_msg_callback(style, alert_id, occurrence_time)
        buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])
    return InlineKeyboardMarkup(buttons)


def _log_generation_failure(storage, user_id: int, alert_id: str | None, style: str | None, reason_code: str) -> None:
    storage.log_user_event(
        user_id,
        "bday_msg_generation_failed",
        {
            "alert_id": alert_id,
            "alert_type": 6,
            "style": style,
            "reason_code": reason_code,
        },
    )


def _log_bday_noted_pressed(
    storage,
    user_id: int,
    *,
    alert_id: str | None,
    occurrence_time,
    payload_source: str | None,
    reason_code: str | None = None,
) -> None:
    payload = {
        "alert_id": alert_id,
        "alert_type": 6,
        "occ_ts_present": occurrence_time is not None,
        "occ_iso": occurrence_time.isoformat() if occurrence_time is not None else None,
        "payload_source": payload_source,
    }
    if reason_code is not None:
        payload["reason_code"] = reason_code
    storage.log_user_event(user_id, "bday_noted_pressed", payload)


def _log_style_selection(
    storage,
    user_id: int,
    *,
    alert_id: str | None,
    style: str | None,
    selection_result: str,
    fallback_stage: str | None = None,
    template_id: str | None = None,
    reason_code: str | None = None,
) -> None:
    storage.log_user_event(
        user_id,
        "bday_msg_style_selected",
        {
            "alert_id": alert_id,
            "alert_type": 6,
            "style": style,
            "selection_result": selection_result,
            "fallback_stage": fallback_stage,
            "template_id": template_id,
            "reason_code": reason_code,
        },
    )


async def _handle_zodiac_style(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query,
    alert: dict,
    alert_id: str | None,
    user_id: int,
    storage,
    occurrence_time,
) -> None:
    """Handle the 'zodiac' style selection: assemble and send an Italian zodiac message."""
    try:
        user_prefs = storage.get_user_prefs(user_id)
    except Exception:
        user_prefs = None

    zodiac_ctx = infer_zodiac_context(alert, user_prefs)
    western_info = zodiac_ctx.get("western_info")
    eastern_info = zodiac_ctx.get("eastern_info")
    use_western = zodiac_ctx.get("use_western", True)
    use_eastern = zodiac_ctx.get("use_eastern", False)
    eastern_missing_year = zodiac_ctx.get("eastern_missing_year", False)
    zodiac_mode = zodiac_ctx.get("zodiac_mode", "none")

    turning_age = infer_turning_age(alert, occurrence_time=occurrence_time)
    title = alert.get("title") if isinstance(alert, dict) else None

    result = assemble_zodiac_message(
        western_info,
        eastern_info,
        turning_age=turning_age,
        title=title,
        use_western=use_western,
        use_eastern=use_eastern,
    )

    if result is None:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ I could not generate a zodiac message right now.",
            )
        except Exception as exc:
            logger.warning("Failed to send zodiac error message: %s", exc)
        _log_style_selection(
            storage, user_id,
            alert_id=alert_id, style="zodiac",
            selection_result="failed",
            reason_code="zodiac_assemble_failed",
        )
        _log_generation_failure(storage, user_id, alert_id, "zodiac", "zodiac_assemble_failed")
        return

    if zodiac_mode == C.BIRTHDAY_ZODIAC_MODE_NONE and eastern_info is not None:
        result = "(zodiac randomly picked between eastern and wester — set a preference in /settings)\n\n" + result

    if use_western and use_eastern:
        zodiac_used = "both"
    elif use_eastern:
        zodiac_used = "eastern"
    else:
        zodiac_used = "western"

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=result,
        )
    except Exception as exc:
        logger.warning("Failed to send zodiac birthday message: %s", exc)
        _log_style_selection(
            storage, user_id,
            alert_id=alert_id, style="zodiac",
            selection_result="failed",
            reason_code="send_failed",
        )
        _log_generation_failure(storage, user_id, alert_id, "zodiac", "send_failed")
        return

    _log_style_selection(
        storage, user_id,
        alert_id=alert_id, style="zodiac",
        selection_result="selected",
    )
    storage.log_user_event(
        user_id,
        "bday_msg_generated",
        {
            "alert_id": alert_id,
            "alert_type": 6,
            "style": "zodiac",
            "zodiac_used": zodiac_used,
            "zodiac_mode_setting": zodiac_mode,
            "zodiac_eastern_fallback_to_western": eastern_missing_year,
            "turning_age_known": turning_age is not None,
        },
    )


async def handle_bday_noted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle birthday-noted callbacks and send the message-style prompt."""
    query = update.callback_query
    storage = get_runtime_storage(context)

    user_id = update.effective_user.id
    decoded = decode_bday_noted_callback(query.data or "")
    if not decoded.get("ok"):
        await query.answer("⚠️ This birthday action is no longer valid.", show_alert=True)
        _log_bday_noted_pressed(
            storage,
            user_id,
            alert_id=None,
            occurrence_time=None,
            payload_source=None,
            reason_code="callback_payload_invalid",
        )
        _log_generation_failure(storage, user_id, None, None, "callback_payload_invalid")
        return

    alert_id = decoded.get("alert_id")
    occurrence_time = decoded.get("occurrence_time")
    payload_source = decoded.get("source")
    alert = storage.get_alert_by_id(user_id, alert_id) if alert_id else None

    if not alert:
        await query.answer("Alert not found", show_alert=True)
        _log_bday_noted_pressed(
            storage,
            user_id,
            alert_id=alert_id,
            occurrence_time=occurrence_time,
            payload_source=payload_source,
            reason_code="alert_not_found",
        )
        _log_generation_failure(storage, user_id, alert_id, None, "alert_not_found")
        return
    if alert.get("type") != 6:
        await query.answer("⚠️ This callback is only valid for birthdays.", show_alert=True)
        _log_bday_noted_pressed(
            storage,
            user_id,
            alert_id=alert_id,
            occurrence_time=occurrence_time,
            payload_source=payload_source,
            reason_code="alert_not_birthday",
        )
        _log_generation_failure(storage, user_id, alert_id, None, "alert_not_birthday")
        return

    try:
        prompt_keyboard = _build_prompt_keyboard(alert_id, occurrence_time)
    except Exception:
        await query.answer("⚠️ This birthday action is no longer valid.", show_alert=True)
        _log_bday_noted_pressed(
            storage,
            user_id,
            alert_id=alert_id,
            occurrence_time=occurrence_time,
            payload_source=payload_source,
            reason_code="callback_payload_invalid",
        )
        _log_generation_failure(storage, user_id, alert_id, None, "callback_payload_invalid")
        return

    callback_lengths = []
    for row in prompt_keyboard.inline_keyboard:
        for btn in row:
            callback_lengths.append(len(str(btn.callback_data).encode("utf-8")))

    await query.answer()
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="🎂 Do you want a randomly generated birthday message?",
            reply_markup=prompt_keyboard,
        )
    except Exception as exc:
        logger.warning("Failed to send birthday prompt message: %s", exc)
        _log_bday_noted_pressed(
            storage,
            user_id,
            alert_id=alert_id,
            occurrence_time=occurrence_time,
            payload_source=payload_source,
            reason_code="send_failed",
        )
        _log_generation_failure(storage, user_id, alert_id, None, "send_failed")
        return

    _log_bday_noted_pressed(
        storage,
        user_id,
        alert_id=alert_id,
        occurrence_time=occurrence_time,
        payload_source=payload_source,
    )
    storage.log_user_event(
        user_id,
        "bday_msg_prompt_shown",
        {
            "alert_id": alert_id,
            "alert_type": 6,
            "styles_count": len(_STYLE_BUTTONS),
            "max_callback_len": max(callback_lengths) if callback_lengths else 0,
            "min_callback_len": min(callback_lengths) if callback_lengths else 0,
            "payload_source": payload_source,
        },
    )


async def handle_bday_msg_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle birthday style selection and send generated style output."""
    query = update.callback_query
    storage = get_runtime_storage(context)

    user_id = update.effective_user.id
    decoded = decode_bday_msg_callback(query.data or "")
    if not decoded.get("ok"):
        await query.answer("⚠️ This birthday action is no longer valid.", show_alert=True)
        _log_style_selection(
            storage,
            user_id,
            alert_id=None,
            style=None,
            selection_result="failed",
            reason_code="callback_payload_invalid",
        )
        _log_generation_failure(storage, user_id, None, None, "callback_payload_invalid")
        return

    style = decoded.get("style")
    alert_id = decoded.get("alert_id")
    occurrence_time = decoded.get("occurrence_time")

    if style not in set(_STYLE_OPTIONS) | {"no"}:
        await query.answer("⚠️ Unsupported style.", show_alert=True)
        _log_style_selection(
            storage,
            user_id,
            alert_id=alert_id,
            style=style,
            selection_result="failed",
            reason_code="invalid_style",
        )
        _log_generation_failure(storage, user_id, alert_id, style, "invalid_style")
        return

    alert = storage.get_alert_by_id(user_id, alert_id) if alert_id else None
    if not alert:
        await query.answer("Alert not found", show_alert=True)
        _log_style_selection(
            storage,
            user_id,
            alert_id=alert_id,
            style=style,
            selection_result="failed",
            reason_code="alert_not_found",
        )
        _log_generation_failure(storage, user_id, alert_id, style, "alert_not_found")
        return
    if alert.get("type") != 6:
        await query.answer("⚠️ This callback is only valid for birthdays.", show_alert=True)
        _log_style_selection(
            storage,
            user_id,
            alert_id=alert_id,
            style=style,
            selection_result="failed",
            reason_code="alert_not_birthday",
        )
        _log_generation_failure(storage, user_id, alert_id, style, "alert_not_birthday")
        return

    await query.answer()

    if style == "no":
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="👍 No problem, good luck with the message!",
            )
            _log_style_selection(
                storage,
                user_id,
                alert_id=alert_id,
                style=style,
                selection_result="user_declined",
            )
            return
        except Exception as exc:
            logger.warning("Failed to send birthday decline message: %s", exc)
            _log_style_selection(
                storage,
                user_id,
                alert_id=alert_id,
                style=style,
                selection_result="failed",
                reason_code="send_failed",
            )
            _log_generation_failure(storage, user_id, alert_id, style, "send_failed")
            return

    if style == "zodiac":
        await _handle_zodiac_style(
            update, context, query, alert, alert_id, user_id, storage, occurrence_time
        )
        return

    try:
        archive_entries = load_archive(style, allow_empty=False, use_cache=True)
    except ArchiveValidationError:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ I cannot generate a message right now. Please try again later.",
            )
        except Exception as exc:
            logger.warning("Failed to send archive-invalid birthday message: %s", exc)
        _log_style_selection(
            storage,
            user_id,
            alert_id=alert_id,
            style=style,
            selection_result="failed",
            reason_code="archive_invalid",
        )
        _log_generation_failure(storage, user_id, alert_id, style, "archive_invalid")
        return

    context_data = infer_message_context(alert, occurrence_time=occurrence_time)
    selection = select_template(archive_entries, context_data)
    if selection.get("selection_result") != "selected":
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ I could not select a message suggestion right now.",
            )
        except Exception as exc:
            logger.warning("Failed to send selection-empty birthday message: %s", exc)
        _log_style_selection(
            storage,
            user_id,
            alert_id=alert_id,
            style=style,
            selection_result="failed",
            reason_code="selection_empty",
        )
        _log_generation_failure(storage, user_id, alert_id, style, "selection_empty")
        return

    template_id = selection.get("template_id")
    fallback_stage = selection.get("fallback_stage")
    candidate_count = int(selection.get("candidate_count", 0) or 0)
    text = selection.get("text") or ""

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✍️ {style.title()} suggestion:\n\n{text}",
        )
    except Exception as exc:
        logger.warning("Failed to send birthday suggestion: %s", exc)
        _log_style_selection(
            storage,
            user_id,
            alert_id=alert_id,
            style=style,
            selection_result="failed",
            reason_code="send_failed",
        )
        _log_generation_failure(storage, user_id, alert_id, style, "send_failed")
        return

    _log_style_selection(
        storage,
        user_id,
        alert_id=alert_id,
        style=style,
        selection_result="selected",
        fallback_stage=fallback_stage,
        template_id=template_id,
    )
    storage.log_user_event(
        user_id,
        "bday_msg_generated",
        {
            "alert_id": alert_id,
            "alert_type": 6,
            "style": style,
            "zodiac_used": None,
            "template_id": template_id,
            "fallback_stage": fallback_stage,
            "candidate_count": candidate_count,
            "turning_age_known": bool(context_data.get("turning_age_known")),
            "tag_groups": list(context_data.get("tag_groups", [])),
            "gender_hint": context_data.get("gender_hint"),
            "title_hints": list(context_data.get("title_hints", [])),
        },
    )
