"""Build notification/detail keyboards and restore notification message views."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import constants as C
from modules.handlers.notification_context import (
    NotificationContext,
    _extract_back_tag_filter,
    _parse_iso,
)
from modules.telegram_resilience import is_message_not_modified_error
from modules.ui.formatters.alert_text import format_aa, format_pa
from modules.ui.formatters.birthday_text import format_bb, format_pb
from modules.ui.keyboards.detail_kb import build_detail_keyboard
from modules.ui.keyboards.notification_kb import (
    build_alert_notification_keyboard,
    build_birthday_notification_keyboard,
    build_prealert_notification_keyboard,
)

logger = logging.getLogger(__name__)


def _build_notification_keyboard(
    alert,
    kind,
    occurrence_time,
    original_time,
    postpone_count,
):
    if kind == "pre":
        return build_prealert_notification_keyboard(
            alert,
            occurrence_time,
            original_time,
            postpone_count=postpone_count,
        )
    if alert.get("type") == 6:
        return build_birthday_notification_keyboard(
            alert,
            occurrence_time,
            original_time,
            postpone_count=postpone_count,
        )
    return build_alert_notification_keyboard(
        alert,
        occurrence_time,
        original_time,
        postpone_count=postpone_count,
    )


def _build_toggle_keyboard_from_context(alert, ctx, *, tag_filter="ALL"):
    """Build the toggle keyboard from a pre-derived toggle context dict."""
    kind = ctx.get("kind", "due")
    detail_from_notification = bool(ctx.get("detail_from_notification"))
    detail_from_list = bool(ctx.get("detail_from_list"))
    original_time = ctx.get("original_time")
    occurrence_time = ctx.get("occurrence_time")
    postpone_count = ctx.get("postpone_count", 0)

    if occurrence_time is None:
        occurrence_time = _parse_iso(alert.get("next_scheduled"))
    if original_time is None and occurrence_time is not None:
        original_time = occurrence_time

    if detail_from_notification:
        return build_detail_keyboard(
            alert,
            from_notification=True,
            kind=kind,
            occurrence_time=occurrence_time,
            original_time=original_time,
            postpone_count=postpone_count,
            include_back=True,
        )

    if detail_from_list:
        return build_detail_keyboard(
            alert,
            source="alerts",
            from_notification=False,
            occurrence_time=occurrence_time,
            original_time=original_time,
            postpone_count=postpone_count,
            include_back=bool(ctx.get("include_back")),
            tag_filter=tag_filter,
        )

    return _build_notification_keyboard(
        alert,
        kind,
        occurrence_time,
        original_time,
        postpone_count,
    )


def _build_toggle_keyboard_for_message(alert, message, alert_id):
    notif_ctx = NotificationContext.from_message(message, alert_id)
    ctx = vars(notif_ctx)
    include_back = bool(notif_ctx.include_back)
    tag_filter = _extract_back_tag_filter(message) if include_back else "ALL"
    return _build_toggle_keyboard_from_context(alert, ctx, tag_filter=tag_filter)


def _build_postpone_options_keyboard(kind, alert_id, orig_ts, occ_ts, postpone_count=0):
    base = f"{kind}_{alert_id}_{orig_ts}_{occ_ts}"
    count_suffix = f"_{postpone_count}" if postpone_count and postpone_count > 0 else ""
    quick_buttons = [
        InlineKeyboardButton(
            label,
            callback_data=f"{C.CB_POSTPONE}set_{duration}_{base}{count_suffix}",
        )
        for label, duration in C.QUICK_DURATION_OPTIONS
    ]
    keyboard = [
        quick_buttons,
        [
            InlineKeyboardButton("⚙️ Custom", callback_data=f"{C.CB_POSTPONE}custom_{base}{count_suffix}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def _ts(dt):
    if not dt:
        return "0"
    return str(int(dt.timestamp()))


def _restore_failure_reason_code(exc):
    """Map restore-edit exceptions to stable metadata-only reason codes."""
    if is_message_not_modified_error(exc):
        return "message_not_modified"
    try:
        text = str(exc or "").lower()
    except Exception:
        return "restore_exception"
    if "message to edit not found" in text:
        return "message_not_found"
    if "chat not found" in text:
        return "chat_not_found"
    if "forbidden" in text or "bot was blocked by the user" in text:
        return "forbidden"
    return "restore_exception"


async def _restore_notification_message_view_with_result(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    storage,
    user_id,
    chat_id,
    message_id,
    alert_id,
    kind,
    original_time,
    occurrence_time,
    postpone_count,
    is_photo_hint=None,
):
    """Restore a notification card and return structured success and reason-code metadata."""
    if chat_id is None or message_id is None:
        return {"success": False, "reason_code": "restore_failed"}

    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        return {"success": False, "reason_code": "restore_failed"}

    if occurrence_time is None:
        occurrence_time = _parse_iso(alert.get("next_scheduled"))
    if original_time is None and occurrence_time is not None:
        original_time = occurrence_time

    user_prefs = storage.get_user_prefs(user_id) or {}
    if kind == "pre":
        if alert.get("type") == 6:
            text = format_pb(
                alert,
                main_trigger_time=original_time,
                scheduled_time=occurrence_time,
                user_prefs=user_prefs,
            )
        else:
            text = format_pa(
                alert,
                main_trigger_time=original_time,
                scheduled_time=occurrence_time,
            )
        kb = build_prealert_notification_keyboard(
            alert,
            occurrence_time,
            original_time,
            postpone_count=postpone_count,
        )
    else:
        if alert.get("type") == 6:
            text = format_bb(alert, scheduled_time=occurrence_time, user_prefs=user_prefs)
        else:
            text = format_aa(alert, scheduled_time=occurrence_time, user_prefs=user_prefs)
        kb = _build_notification_keyboard(
            alert,
            "due",
            occurrence_time,
            original_time,
            postpone_count,
        )

    use_caption_first = bool(is_photo_hint)
    attempts = [use_caption_first, not use_caption_first]
    if is_photo_hint is None:
        attempts = [False, True]

    attempted_modes = set()
    last_exc = None
    last_reason_code = None
    for use_caption in attempts:
        if use_caption in attempted_modes:
            continue
        attempted_modes.add(use_caption)
        try:
            if use_caption:
                await context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
            return {"success": True, "reason_code": "ok"}
        except Exception as exc:
            reason_code = _restore_failure_reason_code(exc)
            if reason_code == "message_not_modified":
                return {"success": True, "reason_code": "message_not_modified"}
            last_exc = exc
            last_reason_code = reason_code

    logger.error("Error restoring notification view: %s", last_exc)
    return {"success": False, "reason_code": str(last_reason_code or "restore_failed")}


async def _restore_notification_message_view(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    storage,
    user_id,
    chat_id,
    message_id,
    alert_id,
    kind,
    original_time,
    occurrence_time,
    postpone_count,
    is_photo_hint=None,
    return_result=False,
):
    """Render and restore a notification card with optional structured restore metadata."""
    outcome = await _restore_notification_message_view_with_result(
        context,
        storage=storage,
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        alert_id=alert_id,
        kind=kind,
        original_time=original_time,
        occurrence_time=occurrence_time,
        postpone_count=postpone_count,
        is_photo_hint=is_photo_hint,
    )
    if return_result:
        return outcome
    return bool((outcome or {}).get("success"))
