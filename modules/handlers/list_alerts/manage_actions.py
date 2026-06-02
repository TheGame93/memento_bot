"""Handle list/detail management callbacks, toggles, delete, and edit-text flows."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import constants as C
from modules.scheduler import queue_single_alert
from modules.shared.runtime_context import get_runtime_storage

from .compact_list import _get_compact_context, show_alerts_list
from .detail import (
    _format_standard_card,
    _log_alert_detail_event,
    _normalize_back_source,
    _resolve_ids,
    _send_alert_detail_with_media_fallback,
    get_info_text_and_kb,
)
from .filter_menu import LIST_CONTEXT_KEY

logger = logging.getLogger(__name__)


def _clear_edit_text_context(user_data):
    user_data.pop("expecting_edit_text", None)
    user_data.pop("edit_text_alert_id", None)
    user_data.pop("edit_text_source", None)
    user_data.pop("edit_text_message_id", None)
    user_data.pop("edit_text_is_photo", None)
    user_data.pop("edit_text_include_back", None)


def _message_has_back_button(message):
    try:
        markup = message.reply_markup
        if not markup or not getattr(markup, "inline_keyboard", None):
            return False
        for row in markup.inline_keyboard:
            for btn in row:
                if getattr(btn, "callback_data", None) == "manage_backtolist":
                    return True
    except Exception:
        return False
    return False


def _message_has_callback_prefix(message, prefix):
    try:
        markup = message.reply_markup
        if not markup or not getattr(markup, "inline_keyboard", None):
            return False
        for row in markup.inline_keyboard:
            for btn in row:
                cb = getattr(btn, "callback_data", None)
                if isinstance(cb, str) and cb.startswith(prefix):
                    return True
    except Exception:
        return False
    return False


def _message_is_detail_view(message):
    """Return whether message keyboard matches detail-view action callbacks."""
    return (
        _message_has_callback_prefix(message, "manage_fulledit_")
        or _message_has_callback_prefix(message, "manage_edittext_")
    )


def _parse_ts_seconds(raw):
    try:
        return datetime.fromtimestamp(int(raw))
    except Exception:
        return None


def _parse_detail_edittext_data(data):
    if not isinstance(data, str) or not data.startswith("manage_edittext_"):
        return None
    parts = data.split("_")
    if len(parts) < 6:
        return None
    kind = parts[2]
    if kind not in {"pre", "due"}:
        return None
    alert_id = parts[3]
    orig_ts = parts[4]
    occ_ts = parts[5]
    return {
        "kind": kind,
        "alert_id": alert_id,
        "original_time": _parse_ts_seconds(orig_ts),
        "occurrence_time": _parse_ts_seconds(occ_ts),
    }


def build_manage_list_keyboard(alert_id):
    """Build manage-list action keyboard for a specific alert id."""
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("ℹ️ INFO", callback_data=f"manage_info_{alert_id}"),
            InlineKeyboardButton("🔄 Snooze", callback_data=f"manage_toggle_{alert_id}"),
            InlineKeyboardButton("🗑️ DELETE", callback_data=f"manage_del_{alert_id}"),
        ]]
    )


async def handle_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle alert-management callbacks for list/detail cards."""
    query = update.callback_query
    await query.answer()

    detail_ctx = _parse_detail_edittext_data(query.data)
    if detail_ctx:
        action = "edittext"
        alert_id = detail_ctx["alert_id"]
    else:
        data_parts = query.data.split("_")
        action = data_parts[1]
        alert_id = data_parts[-1]

    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    source = context.user_data.get("manage_source", "alerts")
    storage = get_runtime_storage(context)

    if action == "del":
        context.user_data[f"manage_del_ctx_{alert_id}"] = "info" if _message_is_detail_view(query.message) else "list"
        context.user_data[f"manage_del_back_{alert_id}"] = _message_has_back_button(query.message)
        kb = [[
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"manage_confirmdel_{alert_id}"),
            InlineKeyboardButton("❌ No, Keep it", callback_data=f"manage_cancel_{alert_id}"),
        ]]
        confirm_text = "⚠️ **Are you sure?**\nThis action cannot be undone."

        if query.message.photo:
            await query.edit_message_caption(
                caption=confirm_text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await query.edit_message_text(
                text=confirm_text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode=ParseMode.MARKDOWN,
            )

    elif action == "confirmdel":
        context.user_data.pop(f"manage_del_ctx_{alert_id}", None)
        context.user_data.pop(f"manage_del_back_{alert_id}", None)
        if storage.delete_alert(user_id, alert_id):
            result_text = "🗑️ **Alert permanently deleted.**"
            if query.message.photo:
                await query.edit_message_caption(caption=result_text, reply_markup=None)
            else:
                await query.edit_message_text(result_text, reply_markup=None)
        else:
            await query.answer("❌ Error: Alert not found.")

    elif action == "cancel":
        del_ctx = context.user_data.pop(f"manage_del_ctx_{alert_id}", "list")
        del_back = bool(context.user_data.pop(f"manage_del_back_{alert_id}", False))
        data = storage.get_all_alerts(user_id)
        alert = next((a for a in data["alerts"] if a["id"] == alert_id), None) if data else None
        if not alert:
            await query.message.delete()
            return
        if del_ctx == "info":
            info_text, kb = get_info_text_and_kb(
                alert,
                context,
                source=source,
                include_back=del_back,
                user_prefs=storage.get_user_prefs(user_id) or {},
            )
            if query.message.photo:
                await query.edit_message_caption(caption=info_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.edit_message_text(text=info_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await refresh_alert_message(query, user_id, alert_id, storage=storage)

    elif action == "edittext":
        context.user_data["expecting_edit_text"] = True
        context.user_data["edit_text_alert_id"] = alert_id
        context.user_data["edit_text_source"] = source
        context.user_data["edit_text_message_id"] = query.message.message_id
        context.user_data["edit_text_is_photo"] = bool(query.message.photo)
        context.user_data["edit_text_include_back"] = _message_has_back_button(query.message)
        cancel_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ Cancel this operation", callback_data=f"manage_canceledit_{alert_id}"),
                InlineKeyboardButton("🗑️ Clear present text", callback_data=f"manage_cleartext_{alert_id}"),
            ]
        ])
        await context.bot.send_message(
            chat_id=actor_id,
            text="✏️ Send the new custom text now.",
            reply_markup=cancel_kb,
        )

    elif action == "canceledit":
        _clear_edit_text_context(context.user_data)
        await query.edit_message_text("⏹️ Edit text cancelled.")

    elif action == "cleartext":
        target_alert_id = context.user_data.get("edit_text_alert_id") or alert_id
        target_source = context.user_data.get("edit_text_source", source)
        message_id = context.user_data.get("edit_text_message_id")
        is_photo = bool(context.user_data.get("edit_text_is_photo"))
        include_back = bool(context.user_data.get("edit_text_include_back"))

        ok = storage.update_alert_fields(user_id, target_alert_id, {"additional_info": ""})
        if not ok:
            await query.edit_message_text("❌ Alert not found.")
        else:
            await query.edit_message_text("✅ Custom text cleared.")
            alert = storage.get_alert_by_id(user_id, target_alert_id)
            if alert and message_id:
                info_text, kb = get_info_text_and_kb(
                    alert,
                    context,
                    source=target_source,
                    include_back=include_back,
                    user_prefs=storage.get_user_prefs(user_id) or {},
                )
                try:
                    if is_photo:
                        await context.bot.edit_message_caption(
                            chat_id=actor_id,
                            message_id=message_id,
                            caption=info_text,
                            reply_markup=kb,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    else:
                        await context.bot.edit_message_text(
                            chat_id=actor_id,
                            message_id=message_id,
                            text=info_text,
                            reply_markup=kb,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                except Exception as exc:
                    logger.warning("Could not refresh info message after clear text: %s", exc)

        _clear_edit_text_context(context.user_data)

    elif action == "toggle":
        new_status = storage.toggle_alert(user_id, alert_id)
        if new_status is True:
            try:
                await queue_single_alert(user_id, alert_id)
            except Exception as exc:
                logger.warning("Could not requeue alert after activation toggle: %s", exc)
        is_photo = bool(query.message.photo)

        if _message_is_detail_view(query.message):
            data = storage.get_all_alerts(user_id)
            alert = next((a for a in data["alerts"] if a["id"] == alert_id), None)
            include_back = _message_has_back_button(query.message)
            info_text, kb = get_info_text_and_kb(
                alert,
                context,
                source=source,
                include_back=include_back,
                user_prefs=storage.get_user_prefs(user_id) or {},
            )

            if is_photo:
                await query.edit_message_caption(caption=info_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.edit_message_text(text=info_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await refresh_alert_message(query, user_id, alert_id, storage=storage)

    elif action == "info":
        data = storage.get_all_alerts(user_id)
        alert = next((a for a in data["alerts"] if a["id"] == alert_id), None)
        if not alert:
            await query.answer("❌ Alert not found.")
            return

        has_media = bool(alert.get("image_id") or alert.get("local_image_path")) and alert.get("type") != 6
        if query.message.photo:
            include_back = _message_has_back_button(query.message)
            info_text, kb = get_info_text_and_kb(
                alert,
                context,
                source=source,
                include_back=include_back,
                user_prefs=storage.get_user_prefs(user_id) or {},
            )
            _log_alert_detail_event(
                storage,
                user_id,
                "alert_detail_open_attempt",
                {
                    "alert_id": alert_id,
                    "source": source,
                    "origin": "manage_info",
                    "has_image_id": bool(alert.get("image_id")),
                    "has_local_image_path": bool(alert.get("local_image_path")),
                    "include_back": include_back,
                },
                acting_payload=acting_payload,
            )
            try:
                await query.edit_message_caption(
                    caption=info_text,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
                _log_alert_detail_event(
                    storage,
                    user_id,
                    "alert_detail_open_result",
                    {
                        "alert_id": alert_id,
                        "source": source,
                        "origin": "manage_info",
                        "delivery_mode": "caption_edit",
                        "reason_code": "caption_edit_ok",
                        "autoheal_image_id": False,
                    },
                    acting_payload=acting_payload,
                )
            except Exception:
                _log_alert_detail_event(
                    storage,
                    user_id,
                    "alert_detail_open_result",
                    {
                        "alert_id": alert_id,
                        "source": source,
                        "origin": "manage_info",
                        "delivery_mode": "failed",
                        "reason_code": "caption_edit_failed",
                        "autoheal_image_id": False,
                    },
                    acting_payload=acting_payload,
                )
                await query.answer("⚠️ Could not open detailed info now.", show_alert=True)
            return

        if has_media:
            result = await _send_alert_detail_with_media_fallback(
                context=context,
                storage=storage,
                actor_id=actor_id,
                user_id=user_id,
                alert=alert,
                source=source,
                include_back=True,
                open_origin="manage_info",
                acting_payload=acting_payload,
                user_prefs=storage.get_user_prefs(user_id) or {},
            )
            if result.get("delivered"):
                try:
                    await query.message.delete()
                except Exception:
                    pass
            else:
                await query.answer("⚠️ Could not open detailed info now.", show_alert=True)
            return

        info_text, kb = get_info_text_and_kb(
            alert,
            context,
            source=source,
            include_back=False,
            user_prefs=storage.get_user_prefs(user_id) or {},
        )
        _log_alert_detail_event(
            storage,
            user_id,
            "alert_detail_open_attempt",
            {
                "alert_id": alert_id,
                "source": source,
                "origin": "manage_info",
                "has_image_id": False,
                "has_local_image_path": False,
                "include_back": False,
            },
            acting_payload=acting_payload,
        )
        try:
            await query.edit_message_text(
                text=info_text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN,
            )
            _log_alert_detail_event(
                storage,
                user_id,
                "alert_detail_open_result",
                {
                    "alert_id": alert_id,
                    "source": source,
                    "origin": "manage_info",
                    "delivery_mode": "text_edit",
                    "reason_code": "text_edit_ok",
                    "autoheal_image_id": False,
                },
                acting_payload=acting_payload,
            )
        except Exception:
            _log_alert_detail_event(
                storage,
                user_id,
                "alert_detail_open_result",
                {
                    "alert_id": alert_id,
                    "source": source,
                    "origin": "manage_info",
                    "delivery_mode": "failed",
                    "reason_code": "text_edit_failed",
                    "autoheal_image_id": False,
                },
                acting_payload=acting_payload,
            )
            await query.answer("⚠️ Could not open detailed info now.", show_alert=True)

    elif action == "backtolist":
        await query.message.delete()
        list_ctx = _get_compact_context(context)
        source = _normalize_back_source(source)
        if source in {"alerts_search", "birthdays_search"}:
            search_text = list_ctx.get("search_text")
            parse_mode = list_ctx.get("search_parse_mode")
            if source == "birthdays_search":
                context.user_data["expecting_birthday_search"] = True
                context.user_data.pop("expecting_alert_search", None)
            else:
                context.user_data["expecting_alert_search"] = True
                context.user_data.pop("expecting_birthday_search", None)
            if search_text:
                await context.bot.send_message(
                    chat_id=actor_id,
                    text=search_text,
                    parse_mode=parse_mode,
                )
                return
            if source == "birthdays_search":
                from modules.handlers.birthdays import birthday_start

                return await birthday_start(update, context)
            from modules.handlers.alerts import alerts_start

            return await alerts_start(update, context)
        if source == "birthdays":
            from modules.handlers.birthdays import show_birthdays_list

            saved_filter = (
                list_ctx.get("tag_filter")
                if list_ctx.get("source") == "birthdays"
                else context.user_data.get("birthday_current_filter", "ALL")
            )
            saved_page = list_ctx.get("page", context.user_data.get("birthdays_current_page", 1))
            return await show_birthdays_list(update, context, manual_tag=saved_filter, manual_page=saved_page)
        saved_filter = context.user_data.get("current_filter", "ALL")
        if list_ctx.get("source") == "alerts":
            saved_filter = list_ctx.get("tag_filter", saved_filter)
        saved_page = list_ctx.get("page", context.user_data.get("alerts_current_page", 1))
        return await show_alerts_list(update, context, manual_tag=saved_filter, manual_page=saved_page)


async def refresh_alert_message(query, user_id, alert_id, *, storage):
    """Refresh an alert list card after mutations with resolved pre-alert labels."""
    data = storage.get_all_alerts(user_id)
    alert = next((a for a in data["alerts"] if a["id"] == alert_id), None)

    if not alert:
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    user_prefs = storage.get_user_prefs(user_id) or {}
    text = _format_standard_card(alert, user_prefs=user_prefs)

    kb = build_manage_list_keyboard(alert_id)

    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def handle_edit_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text updates for additional_info from list or birthday detail views."""
    if not context.user_data.get("expecting_edit_text"):
        return

    actor_id, user_id, acting_payload = _resolve_ids(update, context)
    alert_id = context.user_data.get("edit_text_alert_id")
    source = context.user_data.get("edit_text_source", "alerts")
    message_id = context.user_data.get("edit_text_message_id")
    is_photo = bool(context.user_data.get("edit_text_is_photo"))
    include_back = bool(context.user_data.get("edit_text_include_back"))

    if not alert_id:
        _clear_edit_text_context(context.user_data)
        await update.message.reply_text(
            "⏹️ Edit-text session expired.\n"
            "Open alert details and use Edit text again."
        )
        return

    storage = get_runtime_storage(context)
    raw_text = update.message.text or ""
    if raw_text.strip() == "":
        raw_text = ""

    if len(raw_text) > C.ADDITIONAL_INFO_MAX_LEN:
        try:
            storage.log_user_event(user_id, "additional_info_input_too_long", {"text_len": len(raw_text)})
        except Exception:
            pass
        await update.message.reply_text(
            f"⚠️ Text too long (max {C.ADDITIONAL_INFO_MAX_LEN} characters). Try again."
        )
        return

    ok = storage.update_alert_fields(user_id, alert_id, {"additional_info": raw_text})
    if not ok:
        await update.message.reply_text("❌ Alert not found.")
    else:
        if raw_text:
            await update.message.reply_text("✅ Custom text updated.")
        else:
            await update.message.reply_text("✅ Custom text cleared.")

        alert = storage.get_alert_by_id(user_id, alert_id)
        if alert and message_id:
            info_text, kb = get_info_text_and_kb(
                alert,
                context,
                source=source,
                include_back=include_back,
                user_prefs=storage.get_user_prefs(user_id) or {},
            )
            try:
                if is_photo:
                    await context.bot.edit_message_caption(
                        chat_id=actor_id,
                        message_id=message_id,
                        caption=info_text,
                        reply_markup=kb,
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=actor_id,
                        message_id=message_id,
                        text=info_text,
                        reply_markup=kb,
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception as exc:
                logger.warning("Could not refresh info message after edit text: %s", exc)

    _clear_edit_text_context(context.user_data)
