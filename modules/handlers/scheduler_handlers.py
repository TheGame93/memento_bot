"""
scheduler_handlers.py - Alert Action Handlers

Handles callback queries for:
- Postpone (quick + custom)
- Snooze toggle (ON/OFF)
- Delete confirmation
- Legacy Done / pre-alert ack (older messages)
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode

from modules import constants as C
from modules.scheduler_mathlogic import (
    parse_pre_alert_string,
    format_datetime_human,
    get_next_occurrence,
)
from modules.handlers.notification_actions import (
    _clear_custom_postpone_context,
    _resolve_custom_postpone_fire_at,
    _upsert_postpone_instance,
    _validate_postpone,
)
from modules.handlers.notification_presenter import (
    _build_notification_keyboard,
    _build_postpone_options_keyboard,
    _build_toggle_keyboard_for_message,
    _build_toggle_keyboard_from_context,
    _restore_failure_reason_code,
    _restore_notification_message_view,
    _restore_notification_message_view_with_result,
    _ts,
)
from modules.handlers.notification_context import (
    NotificationContext,
    _extract_back_tag_filter,
    _parse_alert_callback_with_prefix,
    _parse_alert_info_data,
    _parse_iso,
    _parse_notif_back_data,
    _parse_postpone_data,
    _parse_prealert_info_data,
    _parse_ts,
)
from modules.scheduler import mark_alert_done, queue_single_alert
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.shared.runtime_context import get_runtime_storage
from modules.handlers.birthday_flow.message_suggestions.handlers import (
    handle_bday_msg_style as _handle_bday_msg_style_impl,
    handle_bday_noted as _handle_bday_noted_impl,
)
from modules.telegram_resilience import is_message_not_modified_error
from modules.timezone_utils import now_server_naive
from modules.ui.formatters.info_text import format_ia as _format_ia, format_ib as _format_ib
from modules.ui.keyboards.detail_kb import build_detail_keyboard
from modules.ui.keyboards.notification_kb import build_prealert_notification_keyboard

logger = logging.getLogger(__name__)
# =============================================================================
# HELPERS
# =============================================================================

def _callback_answer_reason_code(exc):
    text = str(exc or "").lower()
    if "query is too old" in text or "query id is invalid" in text:
        return "query_too_old_or_invalid"
    return "callback_answer_failed"


def _format_detail_card(alert, user_prefs=None):
    """Render the detail card text for alerts and birthdays via the UI formatter layer."""
    if alert.get("type") == 6:
        return _format_ib(alert, user_prefs=user_prefs)
    return _format_ia(alert, user_prefs=user_prefs)


# =============================================================================
# POSTPONE HANDLERS
# =============================================================================

async def handle_postpone_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open postpone options keyboard for a parsed notification callback payload."""
    query = update.callback_query

    data = _parse_postpone_data(query.data)
    if not data:
        await query.answer("❌ Invalid postpone data", show_alert=True)
        return
    await query.answer()

    kind = data["kind"]
    alert_id = data["alert_id"]
    original_time = data["original_time"]
    occurrence_time = data["occurrence_time"]
    postpone_count = data.get("postpone_count", 0)

    kb = _build_postpone_options_keyboard(
        kind,
        alert_id,
        _ts(original_time),
        _ts(occurrence_time or original_time),
        postpone_count,
    )

    try:
        await query.edit_message_reply_markup(reply_markup=kb)
    except Exception as exc:
        logger.error(f"Error opening postpone menu: {exc}")


async def handle_postpone_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apply selected postpone duration and restore notification keyboard state."""
    query = update.callback_query

    data = _parse_postpone_data(query.data)
    if not data:
        await query.answer("❌ Invalid postpone data", show_alert=True)
        return

    duration = data["duration"]
    kind = data["kind"]
    alert_id = data["alert_id"]
    original_time = data["original_time"]
    occurrence_time = data["occurrence_time"]
    prior_count = data.get("postpone_count", 0)

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        await query.answer("❌ Alert not found", show_alert=True)
        return

    delta = parse_pre_alert_string(duration)
    if not delta:
        await query.answer("❌ Invalid duration", show_alert=True)
        return

    fire_at = datetime.now() + delta
    ok, reason = _validate_postpone(alert, kind, fire_at, occurrence_time)
    if not ok:
        await query.answer(f"❌ {reason}", show_alert=True)
        return
    await query.answer()

    _, _, count = _upsert_postpone_instance(
        storage,
        user_id,
        alert,
        kind,
        fire_at,
        original_time or fire_at,
        occurrence_time,
        prior_count=prior_count,
    )

    when_str = format_datetime_human(fire_at)
    kind_label = "pre-alert" if kind == "pre" else "alert"
    count_label = f"(postponed {count} time{'s' if count != 1 else ''})"
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"⏳ **Postpone set**\n\n"
            f"📌 **{_md_escape(alert.get('title', 'Alert').upper())}**\n"
            f"New {kind_label} time: `{when_str}`\n"
            f"_{count_label}_"
        ),
        parse_mode=ParseMode.MARKDOWN
    )

    # Restore original keyboard
    try:
        kb = _build_notification_keyboard(
            alert,
            kind,
            occurrence_time,
            original_time,
            count,
        )
        await query.edit_message_reply_markup(reply_markup=kb)
    except Exception as exc:
        logger.error(f"Error restoring keyboard after postpone: {exc}")


async def handle_postpone_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for custom postpone expressions while preserving cancel semantics."""
    query = update.callback_query

    data = _parse_postpone_data(query.data)
    if not data:
        await query.answer("❌ Invalid postpone data", show_alert=True)
        return
    await query.answer()

    user_id = update.effective_user.id
    context.user_data["expecting_custom_postpone"] = True
    context.user_data["postpone_alert_id"] = data["alert_id"]
    context.user_data["postpone_kind"] = data["kind"]
    context.user_data["postpone_original_time"] = data["original_time"].isoformat() if data["original_time"] else None
    context.user_data["postpone_occurrence_time"] = data["occurrence_time"].isoformat() if data["occurrence_time"] else None
    context.user_data["postpone_message_id"] = query.message.message_id
    context.user_data["postpone_count"] = data.get("postpone_count", 0)

    prompt = (
        "⏳ **Custom Postpone**\n\n"
        "Send when to postpone using one of these formats:\n"
        "• Delay: `30m`, `2h`, `1d`, `1w`, `1mo`\n"
        "• Natural: `today at 18`, `tomorrow 09:30`\n"
        "• Date/time: `25/12 14`, `25/12/26 14:30`, `25/12/2026`\n\n"
        "If time is missing, I use the current time.\n"
        "PRess (or write) `/cancel` to abort."
    )
    await context.bot.send_message(
        chat_id=user_id,
        text=prompt,
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_custom_postpone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse custom postpone expressions, validate them, and persist postpone state."""
    if not context.user_data.get("expecting_custom_postpone"):
        return

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    raw_text = (update.message.text or "").strip()
    text_lower = raw_text.lower()

    alert_id = context.user_data.get("postpone_alert_id")
    kind = context.user_data.get("postpone_kind")
    original_time_raw = context.user_data.get("postpone_original_time")
    occurrence_time_raw = context.user_data.get("postpone_occurrence_time")
    message_id = context.user_data.get("postpone_message_id")
    prior_count = context.user_data.get("postpone_count", 0) or 0
    original_time = _parse_iso(original_time_raw)
    occurrence_time = _parse_iso(occurrence_time_raw)

    if not alert_id or kind not in {"pre", "due"}:
        _clear_custom_postpone_context(context.user_data)
        await update.message.reply_text(
            "⏹️ Postpone session expired.\n"
            "Open the alert again and choose Postpone."
        )
        return

    if text_lower in {"cancel", "/cancel"}:
        _clear_custom_postpone_context(context.user_data)
        await update.message.reply_text("⏹️ Postpone cancelled.")
        try:
            alert = storage.get_alert_by_id(user_id, alert_id) if alert_id else None
            if alert and message_id:
                kb = _build_notification_keyboard(
                    alert,
                    kind,
                    occurrence_time,
                    original_time,
                    prior_count,
                )
                await context.bot.edit_message_reply_markup(
                    chat_id=user_id,
                    message_id=message_id,
                    reply_markup=kb
                )
        except Exception as exc:
            logger.error(f"Error restoring keyboard after cancel: {exc}")
        return

    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        await update.message.reply_text("❌ Alert not found.")
        _clear_custom_postpone_context(context.user_data)
        return

    try:
        user_prefs = storage.get_user_prefs(user_id)
    except Exception:
        user_prefs = None

    fire_at, parse_reason, _parse_meta = _resolve_custom_postpone_fire_at(
        raw_text,
        now_server_dt=now_server_naive(),
        user_prefs=user_prefs,
        kind=kind,
        occurrence_time=occurrence_time,
    )
    if fire_at is None:
        if parse_reason == "not_future":
            error_text = "❌ Postpone time must be in the future."
        elif parse_reason == "not_before_due":
            error_text = "❌ Pre-alert postpone must be before the due time."
        elif parse_reason == "due_time_missing":
            error_text = "❌ Cannot resolve the alert due time."
        elif parse_reason == "empty_input":
            error_text = (
                "❌ Empty input. Use `30m`, `tomorrow 09:30`, or `25/12/2026 14:00`."
            )
        else:
            error_text = (
                "❌ Invalid format/date. Use `30m`, `tomorrow 09:30`, or `25/12/2026 14:00`."
            )
        await update.message.reply_text(
            error_text,
            parse_mode=ParseMode.MARKDOWN
        )
        return

    ok, reason = _validate_postpone(alert, kind, fire_at, occurrence_time)
    if not ok:
        await update.message.reply_text(f"❌ {reason}")
        return

    _, _, count = _upsert_postpone_instance(
        storage,
        user_id,
        alert,
        kind,
        fire_at,
        original_time or fire_at,
        occurrence_time,
        prior_count=prior_count,
    )

    # Clear state
    _clear_custom_postpone_context(context.user_data)

    when_str = format_datetime_human(fire_at)
    kind_label = "pre-alert" if kind == "pre" else "alert"
    count_label = f"(postponed {count} time{'s' if count != 1 else ''})"
    await update.message.reply_text(
        f"✅ Postponed **{_md_escape(alert.get('title', 'Alert').upper())}** {kind_label} to `{when_str}`\n_{count_label}_",
        parse_mode=ParseMode.MARKDOWN
    )

    # Restore original keyboard (if message still exists)
    if message_id:
        try:
            kb = _build_notification_keyboard(
                alert,
                kind,
                occurrence_time,
                original_time,
                count,
            )
            await context.bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=message_id,
                reply_markup=kb
            )
        except Exception as exc:
            logger.error(f"Error restoring keyboard after custom postpone: {exc}")

async def handle_prealert_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the notification-origin pre-alert detail card in place."""
    query = update.callback_query

    data = _parse_prealert_info_data(query.data or "")
    if not data:
        await query.answer("❌ Invalid data", show_alert=True)
        return

    alert_id = data["alert_id"]
    original_time = data["original_time"]
    occurrence_time = data["occurrence_time"]
    postpone_count = data.get("postpone_count", 0)

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        await query.answer("❌ Item not found", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    await query.answer()
    if occurrence_time is None:
        occurrence_time = _parse_iso(alert.get("next_scheduled"))
    if original_time is None and occurrence_time is not None:
        original_time = occurrence_time

    storage.log_user_event(user_id, "alert_detail_opened", {
        "source": "pre",
        "alert_type": alert.get("type"),
    })

    info_text = _format_detail_card(alert, user_prefs=storage.get_user_prefs(user_id) or {})
    kb = build_detail_keyboard(
        alert,
        from_notification=True,
        kind="pre",
        occurrence_time=occurrence_time,
        original_time=original_time,
        postpone_count=postpone_count,
    )
    try:
        if query.message.photo:
            await query.edit_message_caption(
                caption=info_text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text(
                text=info_text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as exc:
        logger.error(f"Error showing pre-alert details: {exc}")


async def handle_alert_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the notification-origin due-alert detail card in place."""
    query = update.callback_query

    data = _parse_alert_info_data(query.data or "")
    if not data:
        await query.answer("❌ Invalid data", show_alert=True)
        return

    alert_id = data["alert_id"]
    original_time = data["original_time"]
    occurrence_time = data["occurrence_time"]
    postpone_count = data.get("postpone_count", 0)

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        await query.answer("❌ Item not found", show_alert=True)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    await query.answer()
    if occurrence_time is None:
        occurrence_time = _parse_iso(alert.get("next_scheduled"))
    if original_time is None and occurrence_time is not None:
        original_time = occurrence_time

    info_text = _format_detail_card(alert, user_prefs=storage.get_user_prefs(user_id) or {})
    kb = build_detail_keyboard(
        alert,
        from_notification=True,
        kind="due",
        occurrence_time=occurrence_time,
        original_time=original_time,
        postpone_count=postpone_count,
    )
    try:
        if query.message.photo:
            await query.edit_message_caption(
                caption=info_text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text(
                text=info_text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as exc:
        logger.error(f"Error showing alert details: {exc}")


async def handle_notif_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restore the original notification view from a notification-detail card."""
    query = update.callback_query

    data = _parse_notif_back_data(query.data or "")
    if not data:
        await query.answer("❌ Invalid data", show_alert=True)
        return

    alert_id = data["alert_id"]
    kind = data["kind"]
    original_time = data["original_time"]
    occurrence_time = data["occurrence_time"]
    postpone_count = data.get("postpone_count", 0)

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    alert = storage.get_alert_by_id(user_id, alert_id)
    if not alert:
        await query.answer("❌ Alert not found", show_alert=True)
        return
    await query.answer()

    message = getattr(query, "message", None)
    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", user_id)
    message_id = getattr(message, "message_id", None)
    is_photo_hint = bool(getattr(message, "photo", None)) if message is not None else None
    await _restore_notification_message_view(
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


# =============================================================================
# SNOOZE TOGGLE HANDLER
# =============================================================================

async def handle_alert_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle alert active state and refresh detail or notification controls."""
    query = update.callback_query

    user_id = update.effective_user.id
    alert_id = query.data.replace(C.CB_ALERT_TOGGLE, "")

    storage = get_runtime_storage(context)
    new_status = storage.toggle_alert(user_id, alert_id)

    if new_status is None:
        await query.answer("❌ Alert not found", show_alert=True)
        return
    await query.answer()

    if new_status is True:
        try:
            await queue_single_alert(user_id, alert_id)
        except Exception as exc:
            logger.warning("Could not requeue alert after activation toggle: %s", exc)

    alert = storage.get_alert_by_id(user_id, alert_id)
    status_text = "enabled" if new_status else "disabled"
    status_icon = "🟢" if new_status else "🔴"

    keyboard_updated = False
    if alert and getattr(query, "message", None):
        notif_ctx = NotificationContext.from_message(query.message, alert_id)
        ctx = vars(notif_ctx)
        include_back = bool(notif_ctx.include_back)
        tag_filter = _extract_back_tag_filter(query.message) if include_back else "ALL"
        updated_keyboard = _build_toggle_keyboard_from_context(
            alert,
            ctx,
            tag_filter=tag_filter,
        )

        if ctx.get("detail_from_notification") or ctx.get("detail_from_list"):
            if updated_keyboard is not None:
                info_text = _format_detail_card(
                    alert,
                    user_prefs=storage.get_user_prefs(user_id) or {},
                )
                try:
                    if query.message.photo:
                        await query.edit_message_caption(
                            caption=info_text,
                            reply_markup=updated_keyboard,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    else:
                        await query.edit_message_text(
                            text=info_text,
                            reply_markup=updated_keyboard,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    keyboard_updated = True
                except Exception as exc:
                    if is_message_not_modified_error(exc):
                        keyboard_updated = True
                    else:
                        logger.warning(
                            "Could not refresh detail card after alert toggle: %s", exc
                        )
        else:
            if updated_keyboard is not None:
                try:
                    await query.edit_message_reply_markup(reply_markup=updated_keyboard)
                    keyboard_updated = True
                except Exception as exc:
                    logger.warning(
                        "Could not refresh toggle keyboard after alert toggle: %s", exc
                    )

    if not keyboard_updated:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"{status_icon} **Alert {status_text}.**",
            parse_mode=ParseMode.MARKDOWN
        )


# =============================================================================
# DELETE HANDLER
# =============================================================================

async def handle_alert_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete confirmation flow for alert deletion callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id
    storage = get_runtime_storage(context)

    # alertdel_confirm_{id} / alertdel_cancel_{id} / alertdel_{id}
    if data.startswith(f"{C.CB_ALERT_DELETE}confirm_"):
        alert_id = data.replace(f"{C.CB_ALERT_DELETE}confirm_", "")
        if storage.delete_alert(user_id, alert_id):
            await query.edit_message_text("🗑️ **Alert permanently deleted.**", parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text("❌ Alert not found.")
        return

    if data.startswith(f"{C.CB_ALERT_DELETE}cancel_"):
        await query.edit_message_text("⏹️ Delete cancelled.")
        return

    alert_id = data.replace(C.CB_ALERT_DELETE, "")
    kb = [[
        InlineKeyboardButton("✅ Yes, delete", callback_data=f"{C.CB_ALERT_DELETE}confirm_{alert_id}"),
        InlineKeyboardButton("❌ No", callback_data=f"{C.CB_ALERT_DELETE}cancel_{alert_id}")
    ]]
    await context.bot.send_message(
        chat_id=user_id,
        text="⚠️ **Delete this alert?**\nThis action cannot be undone.",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )


# =============================================================================
# PLACEBO ACKNOWLEDGMENT HANDLERS
# =============================================================================

async def handle_placebo_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ✅ DONE ! button on main (non-birthday) alerts."""
    query = update.callback_query

    data = query.data[len(C.CB_PLACEBO_DONE):]
    parts = data.split("_")
    alert_id = parts[0] if parts else None

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    alert = storage.get_alert_by_id(user_id, alert_id) if alert_id else None

    if not alert:
        try:
            await query.answer("Alert not found", show_alert=True)
            storage.log_user_event(user_id, "placebo_done_feedback_sent", {
                "alert_id": alert_id,
                "alert_type": None,
                "result": "alert_not_found",
            })
        except Exception as exc:
            storage.log_user_event(user_id, "placebo_done_feedback_failed", {
                "alert_id": alert_id,
                "alert_type": None,
                "result": "alert_not_found",
                "reason_code": _callback_answer_reason_code(exc),
            })
        return

    is_one_time = alert.get("type") == 5
    result_code = "one_time_archived"
    if is_one_time:
        text = "👋 Completed and archived!"
    else:
        next_occ = get_next_occurrence(alert, datetime.now())
        if next_occ:
            date_str = next_occ.strftime("%d/%m/%Y")
            text = f"👋 See you next time on {date_str}!"
            result_code = "next_occurrence"
        else:
            text = "👋 All done!"
            result_code = "all_done"

    feedback_ok = True
    failure_reason = None
    try:
        await query.answer(text, show_alert=True)
    except Exception as exc:
        feedback_ok = False
        failure_reason = _callback_answer_reason_code(exc)

    storage.log_user_event(user_id, "placebo_done_pressed", {
        "alert_id": alert_id,
        "alert_type": alert.get("type"),
    })
    if feedback_ok:
        storage.log_user_event(user_id, "placebo_done_feedback_sent", {
            "alert_id": alert_id,
            "alert_type": alert.get("type"),
            "result": result_code,
        })
    else:
        storage.log_user_event(user_id, "placebo_done_feedback_failed", {
            "alert_id": alert_id,
            "alert_type": alert.get("type"),
            "result": result_code,
            "reason_code": failure_reason,
        })


async def handle_placebo_noted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 👀 NOTED ! button on pre-alerts (all types)."""
    query = update.callback_query

    data = query.data[len(C.CB_PLACEBO_NOTED):]
    parts = data.split("_")
    alert_id = parts[0] if parts else None
    occ_ts = parts[2] if len(parts) > 2 else None
    occ_time = _parse_ts(occ_ts) if occ_ts else None

    if occ_time:
        date_str = occ_time.strftime("%d/%m/%Y")
        text = f"📝 Be ready, {date_str} is close!"
        result_code = "prealert_date_shown"
    else:
        text = "📝 Noted!"
        result_code = "generic_noted"

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    feedback_ok = True
    failure_reason = None
    try:
        await query.answer(text, show_alert=True)
    except Exception as exc:
        feedback_ok = False
        failure_reason = _callback_answer_reason_code(exc)

    storage.log_user_event(user_id, "placebo_noted_pressed", {
        "alert_id": alert_id,
        "alert_type": None,
    })
    if feedback_ok:
        storage.log_user_event(user_id, "placebo_noted_feedback_sent", {
            "alert_id": alert_id,
            "alert_type": None,
            "result": result_code,
        })
    else:
        storage.log_user_event(user_id, "placebo_noted_feedback_failed", {
            "alert_id": alert_id,
            "alert_type": None,
            "result": result_code,
            "reason_code": failure_reason,
        })


async def handle_bday_noted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate birthday-noted callback handling to message-suggestion module."""
    return await _handle_bday_noted_impl(update, context)


async def handle_bday_msg_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delegate birthday style callback handling to message-suggestion module."""
    return await _handle_bday_msg_style_impl(update, context)


# =============================================================================
# LEGACY: DONE HANDLER (older messages)
# =============================================================================

async def handle_alert_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle legacy done callbacks and finalize alert completion messaging."""
    query = update.callback_query

    user_id = update.effective_user.id
    alert_id = query.data.replace(C.CB_ALERT_DONE, "")

    storage = get_runtime_storage(context)
    alert = storage.get_alert_by_id(user_id, alert_id)

    if not alert:
        await query.answer()
        await query.edit_message_text("❌ Alert not found.")
        return

    title = _md_escape(alert.get('title', 'Alert').upper())

    success, was_one_time, next_occ = await mark_alert_done(user_id, alert_id, storage=storage)

    if success:
        await query.answer()
        if was_one_time:
            new_text = (
                f"✅ **COMPLETED**\n\n"
                f"📌 **{title}**\n\n"
                f"This one-time alert has been archived."
            )
        else:
            next_str = format_datetime_human(next_occ) if next_occ else "Unknown"
            new_text = (
                f"✅ **DONE**\n\n"
                f"📌 **{title}**\n\n"
                f"📅 Next occurrence: `{next_str}`"
            )

        try:
            if query.message.photo:
                await query.edit_message_caption(
                    caption=new_text,
                    reply_markup=None,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text(
                    text=new_text,
                    reply_markup=None,
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as exc:
            logger.error(f"Error updating message after done: {exc}")
    else:
        await query.answer("❌ Error marking alert as done", show_alert=True)


# =============================================================================
# LEGACY: PRE-ALERT ACKNOWLEDGMENT
# =============================================================================

async def handle_pre_alert_ack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle legacy pre-alert acknowledgment by removing inline controls."""
    query = update.callback_query
    await query.answer("👍 Noted!")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as exc:
        logger.error(f"Error removing pre-alert keyboard: {exc}")


# =============================================================================
# HANDLER REGISTRATION
# =============================================================================


def get_scheduler_handlers():
    """Return callback handlers for scheduler notification actions."""
    return [
        CallbackQueryHandler(handle_placebo_done, pattern=f"^{C.CB_PLACEBO_DONE}"),
        CallbackQueryHandler(handle_placebo_noted, pattern=f"^{C.CB_PLACEBO_NOTED}"),
        CallbackQueryHandler(handle_bday_noted, pattern=f"^{C.CB_BDAY_NOTED}"),
        CallbackQueryHandler(handle_bday_msg_style, pattern=f"^{C.CB_BDAY_MSG}"),
        CallbackQueryHandler(handle_notif_back, pattern=f"^{C.CB_NOTIF_BACK}"),
        CallbackQueryHandler(handle_prealert_info, pattern=f"^{C.CB_PREALERT_INFO}"),
        CallbackQueryHandler(handle_alert_info, pattern=f"^{C.CB_ALERT_INFO}"),
        CallbackQueryHandler(handle_postpone_menu, pattern=f"^{C.CB_POSTPONE}menu_"),
        CallbackQueryHandler(handle_postpone_set, pattern=f"^{C.CB_POSTPONE}set_"),
        CallbackQueryHandler(handle_postpone_custom, pattern=f"^{C.CB_POSTPONE}custom_"),
        CallbackQueryHandler(handle_alert_toggle, pattern=f"^{C.CB_ALERT_TOGGLE}"),
        CallbackQueryHandler(handle_alert_delete, pattern=f"^{C.CB_ALERT_DELETE}"),
        CallbackQueryHandler(handle_alert_done, pattern=f"^{C.CB_ALERT_DONE}"),
        CallbackQueryHandler(handle_pre_alert_ack, pattern="^pre_ack_"),
    ]


def get_custom_postpone_text_handler():
    """Return the text handler that routes custom postpone input messages."""
    return MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_postpone_input)
