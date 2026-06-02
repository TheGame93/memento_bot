"""Route settings callbacks and render top-level settings views."""

import asyncio
import html
import os
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.handlers.birthday_flow.bulk_birthdays import (
    build_bulk_export_lines,
    build_import_final_confirmation_blocks,
    chunk_text_blocks,
)
from modules.handlers.export_import import (
    handle_settings_backup_import_cancel,
    handle_settings_backup_import_confirm,
)
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.callback_codec import extract_callback_token
from modules.shared.runtime_context import get_runtime_storage
from modules.timezone_utils import validate_tz_name

from .settings_bday import (
    _ZODIAC_MODE_MAP,
    build_birthday_bulk_export_mode_keyboard,
    build_birthday_bulk_export_mode_status,
    build_birthday_bulk_import_decision_keyboard,
    build_birthday_bulk_import_prompt_keyboard,
    build_birthday_time_status,
    build_birthday_zodiac_status,
)
from .settings_mail import (
    _format_backup_size_label,
    _get_backup_size_bytes,
    _normalized_email_address,
    build_backup_email_sent_notification,
    build_mail_backup_status,
    build_mail_set_prompt_keyboard,
    build_mail_set_prompt_message,
)
from .settings_backup import (
    handle_settings_backup,
    handle_settings_backup_export,
    handle_settings_backup_import,
    handle_settings_backup_mail,
    handle_settings_backup_restore,
)
from .settings_tz import (
    TZ_PICK_PREFIX,
    _reschedule_user_timezones,
    _update_timezone_prefs,
    build_location_request_keyboard,
    build_timezone_status,
)

SETTINGS_BUTTONS = [
    [{"label": "🗄️ Backups", "callback": "settings_backup"}],
    [
        {"label": "🎂 Birthdays", "callback": "settings_bdays"},
        {"label": "🔔 Alerts", "callback": "settings_alerts"},
    ],
    [
        {"label": "🕒 Timezone", "callback": "settings_timezone"},
    ],
]


def build_settings_keyboard():
    """Build the top-level settings dashboard keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn["label"], callback_data=btn["callback"]) for btn in row]
        for row in SETTINGS_BUTTONS
    ])


def build_settings_placeholder_keyboard():
    """Build a back-only keyboard for placeholder settings sections."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="settings_back")],
    ])


def build_settings_placeholder_status(section):
    """Build placeholder text and keyboard for unimplemented settings sections."""
    section_name = (section or "").strip().lower()
    if section_name == "alerts":
        title = "🔔 <b>Alert Settings</b>"
    else:
        title = "⚙️ <b>Settings Section</b>"

    message = (
        f"{title}\n\n"
        "This section is currently empty.\n"
        "Feature options will be added in future updates."
    )
    return message, build_settings_placeholder_keyboard()


def _has_active_text_flow(user_data):
    keys = (
        "temp_alert",
        "expecting_tag_name",
        "expecting_tag_rename",
        "expecting_custom_postpone",
        "expecting_edit_text",
        "expecting_alert_search",
        "expecting_birthday_search",
        "expecting_backup_email",
        "expecting_birthday_time",
        "expecting_birthday_evening_time",
        "expecting_timezone_query",
        "expecting_timezone_location",
        "expecting_admin_add_user",
        "expecting_start_request_message",
        "expecting_bday_bulk_import_message",
        "bday_bulk_import_session",
    )
    for key in keys:
        if key not in user_data:
            continue
        value = user_data.get(key)
        # Explicit False means inactive, but key presence with empty containers
        # still counts as an active flow to prevent overlap regressions.
        if isinstance(value, bool):
            if value:
                return True
            continue
        return True
    return False


async def _edit_or_reply(query, text, *, parse_mode=None, reply_markup=None):
    message = getattr(query, "message", None)
    if message:
        try:
            await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return
        except Exception:
            pass
    await query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Settings entrypoint."""
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    storage.log_user_event(user_id, "command_settings", build_acting_as_payload(update, context))
    keyboard = build_settings_keyboard()
    banner = build_acting_as_banner(update, context, parse_mode="HTML")
    message = (
        f"{banner}"
        "⚙️ <b>Settings</b>\n\n"
        "Use the buttons below to manage preferences and backups."
    )
    target = update.effective_message or update.message
    if not target:
        return
    await target.reply_text(message, parse_mode="HTML", reply_markup=keyboard)


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route settings callbacks across backup, birthday, and timezone subflows.

    Handle section navigation, birthday bulk import/export decisions, mail-backup
    configuration and sends, birthday time/zodiac updates, and timezone mode/manual/auto
    flows while preserving active-flow guards and single callback-answer semantics.
    """
    query = update.callback_query
    if not query:
        return
    callback_data = query.data or ""
    if (
        callback_data not in {"settings_mail_toggle", "settings_home"}
        and not callback_data.startswith("settings_backup")
    ):
        await query.answer()

    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)

    if query.data in {"settings_back", "settings_home"}:
        banner = build_acting_as_banner(update, context, parse_mode="HTML")
        message = (
            f"{banner}"
            "⚙️ <b>Settings</b>\n\n"
            "Use the buttons below to manage preferences and backups."
        )
        await _edit_or_reply(
            query,
            message,
            parse_mode="HTML",
            reply_markup=build_settings_keyboard(),
        )
        return

    if callback_data == "settings_backup":
        await handle_settings_backup(update, context)
        return

    if callback_data == "settings_backup_export":
        await handle_settings_backup_export(update, context)
        return

    if callback_data == "settings_backup_import":
        await handle_settings_backup_import(update, context)
        return

    if callback_data == "settings_backup_import_confirm":
        await handle_settings_backup_import_confirm(update, context)
        return

    if callback_data == "settings_backup_import_cancel":
        await handle_settings_backup_import_cancel(update, context)
        return

    if callback_data == "settings_backup_mail":
        await handle_settings_backup_mail(update, context)
        return

    if callback_data == "settings_backup_restore":
        await handle_settings_backup_restore(update, context)
        return

    if query.data == "settings_bdays":
        # Entering the Birthdays panel should not keep stale bulk-import capture state.
        context.user_data.pop("expecting_bday_bulk_import_message", None)
        context.user_data.pop("bday_bulk_import_session", None)
        payload = {
            "source": "settings",
            "section": "bdays",
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "settings_section_opened", payload)
        view_payload = {"source": "settings", "entrypoint": "settings_bdays"}
        view_payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_default_time_view", view_payload)
        prefs = storage.get_user_prefs(user_id)
        message, keyboard = build_birthday_time_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_bday_bulk_export":
        payload = {
            "source": "settings",
            "entrypoint": "settings_bdays",
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_bulk_export_mode_opened", payload)
        message, keyboard = build_birthday_bulk_export_mode_status()
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data in {"settings_bday_bulk_export_everything", "settings_bday_bulk_export_bytag"}:
        export_mode = "everything" if query.data.endswith("_everything") else "by_tag"
        user_data = storage.get_all_alerts(user_id) or {}
        all_alerts = user_data.get("alerts", []) if isinstance(user_data, dict) else []
        birthdays = [alert for alert in all_alerts if isinstance(alert, dict) and alert.get("type") == 6]
        rendered = build_bulk_export_lines(birthdays, mode=export_mode)
        blocks = rendered.get("blocks") or []
        chunks = []
        if export_mode == "by_tag":
            # Keep one logical message per tag block; chunk only within each tag block.
            for block in blocks:
                chunks.extend(chunk_text_blocks([block], safe_limit=3900))
        else:
            chunks = chunk_text_blocks(blocks, safe_limit=3900)
        if not chunks:
            chunks = ["Birthday bulk export\n\nNo birthdays found for export."]

        sent_messages = 0
        for chunk in chunks:
            await query.message.reply_text(chunk)
            sent_messages += 1

        payload = {
            "source": "settings",
            "mode": export_mode,
            "birthdays_count": int(rendered.get("birthdays_count") or 0),
            "tags_nonempty_count": int(rendered.get("tags_nonempty_count") or 0),
            "rows_count": int(rendered.get("rows_count") or 0),
            "messages_sent": sent_messages,
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_bulk_export_sent", payload)

        summary = (
            "✅ <b>Bulk export completed.</b>\n\n"
            f"Mode: <b>{html.escape(export_mode)}</b>\n"
            f"Birthdays exported: <b>{payload['birthdays_count']}</b>\n"
            f"Messages sent: <b>{sent_messages}</b>"
        )
        await _edit_or_reply(
            query,
            summary,
            parse_mode="HTML",
            reply_markup=build_birthday_bulk_export_mode_keyboard(),
        )
        return

    if query.data == "settings_bday_bulk_import":
        if _has_active_text_flow(context.user_data):
            await query.message.reply_text(
                "⚠️ Finish the current flow (or /cancel) before starting birthday bulk import."
            )
            return
        context.user_data["expecting_bday_bulk_import_message"] = True
        context.user_data.pop("bday_bulk_import_session", None)
        payload = {
            "source": "settings",
            "entrypoint": "settings_bdays",
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_bulk_import_prompted", payload)
        await query.message.reply_text(
            "📥 Birthday bulk import\n\n"
            "Send a multi-line message using this format:\n"
            "<code>Name :: DD/MM[/YYYY] :: Tag</code>\n\n"
            "Rules:\n"
            "• one birthday per line\n"
            "• exactly two separators <code>::</code> per line\n"
            "• max 300 non-empty lines\n"
            "• max name length 80",
            parse_mode="HTML",
            reply_markup=build_birthday_bulk_import_prompt_keyboard(),
        )
        return

    if query.data == "settings_bday_bulk_import_edit":
        session = context.user_data.get("bday_bulk_import_session") or {}
        session_summary = session.get("summary") if isinstance(session, dict) else {}
        context.user_data["expecting_bday_bulk_import_message"] = True
        context.user_data.pop("bday_bulk_import_session", None)
        payload = {
            "decision": "edit",
            "valid_lines": int((session_summary or {}).get("valid_lines") or 0),
            "unresolved_tags": int((session_summary or {}).get("unresolved_tags") or 0),
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_bulk_import_decision", payload)
        await query.message.reply_text(
            "✏️ Send the revised bulk import message now.\n"
            "Tip: /cancel stops this flow.",
            parse_mode="HTML",
            reply_markup=build_birthday_bulk_import_prompt_keyboard(),
        )
        return

    if query.data == "settings_bday_bulk_import_gototags":
        session = context.user_data.get("bday_bulk_import_session") or {}
        session_summary = session.get("summary") if isinstance(session, dict) else {}
        context.user_data.pop("expecting_bday_bulk_import_message", None)
        context.user_data.pop("bday_bulk_import_session", None)
        payload = {
            "decision": "gototags",
            "valid_lines": int((session_summary or {}).get("valid_lines") or 0),
            "unresolved_tags": int((session_summary or {}).get("unresolved_tags") or 0),
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_bulk_import_decision", payload)
        from modules.handlers.tags_dashboard import tags_dashboard_start
        await tags_dashboard_start(update, context)
        return

    if query.data == "settings_bday_bulk_import_continue":
        session = context.user_data.get("bday_bulk_import_session")
        if not isinstance(session, dict) or not session:
            context.user_data.pop("expecting_bday_bulk_import_message", None)
            context.user_data.pop("bday_bulk_import_session", None)
            payload = {
                "decision": "continue",
                "reason_code": "session_missing_or_expired",
                "valid_lines": 0,
                "unresolved_tags": 0,
            }
            payload.update(acting_payload)
            storage.log_user_event(user_id, "birthday_bulk_import_decision", payload)
            await query.message.reply_text(
                "⚠️ Import session missing or expired.\n"
                "Start again from Birthdays settings and resend your bulk message."
            )
            return

        session_summary = session.get("summary") if isinstance(session, dict) else {}
        valid_lines = int((session_summary or {}).get("valid_lines") or 0)
        unresolved_tags = int((session_summary or {}).get("unresolved_tags") or 0)

        payload = {
            "decision": "continue",
            "valid_lines": valid_lines,
            "unresolved_tags": unresolved_tags,
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_bulk_import_decision", payload)

        entries = session.get("entries")
        if not isinstance(entries, list) or not entries:
            context.user_data.pop("expecting_bday_bulk_import_message", None)
            context.user_data.pop("bday_bulk_import_session", None)
            fail_payload = {
                "reason_code": "session_entries_missing",
                "valid_lines": valid_lines,
                "unresolved_tags": unresolved_tags,
            }
            fail_payload.update(acting_payload)
            storage.log_user_event(user_id, "birthday_bulk_import_commit_failed", fail_payload)
            await query.message.reply_text(
                "⚠️ Import session has no valid entries.\n"
                "Use Edit Message and resend your bulk import payload."
            )
            return

        source = (session.get("source") if isinstance(session.get("source"), str) else "") or "settings_bulk_import"
        result = storage.save_birthdays_bulk(user_id, entries, source=source)

        context.user_data.pop("expecting_bday_bulk_import_message", None)
        context.user_data.pop("bday_bulk_import_session", None)

        if not result.get("ok"):
            reason_code = str(result.get("failure_reason") or "unknown")
            fail_payload = {
                "reason_code": reason_code,
                "valid_lines": valid_lines,
                "unresolved_tags": unresolved_tags,
                "saved_count": int(result.get("saved_count") or 0),
            }
            fail_payload.update(acting_payload)
            storage.log_user_event(user_id, "birthday_bulk_import_commit_failed", fail_payload)

            message = "❌ Birthday bulk import failed. Please retry."
            if reason_code == "limit_reached":
                message = "❌ Birthday bulk import failed: alert limit reached."
            elif reason_code == "entries_empty":
                message = "❌ Birthday bulk import failed: no valid entries to import."

            await query.message.reply_text(message)
            return

        final_blocks = build_import_final_confirmation_blocks(entries, safe_limit=3900)
        if not final_blocks:
            final_blocks = ["<b>Birthday Bulk Import - Final Confirmation</b>\n\nNo entries imported."]

        for block in final_blocks:
            await query.message.reply_text(block, parse_mode="HTML")

        def _has_resolved_import_tags(row):
            item = row or {}
            raw_tags = item.get("resolved_tags")
            if isinstance(raw_tags, (list, tuple)):
                for raw_tag in raw_tags:
                    if str(raw_tag or "").strip():
                        return True
                return False
            return bool(str(item.get("resolved_tag") or "").strip())

        untagged_count = sum(1 for row in entries if not _has_resolved_import_tags(row))
        committed_payload = {
            "imported_count": int(result.get("saved_count") or 0),
            "untagged_count": int(untagged_count),
            "duplicates_possible": True,
            "valid_lines": valid_lines,
            "unresolved_tags": unresolved_tags,
        }
        committed_payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_bulk_import_committed", committed_payload)
        await query.message.reply_text("✅ Birthday bulk import completed.")
        return

    if query.data == "settings_bday_zodiac":
        payload = {"source": "settings", "section": "bday_zodiac"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_zodiac_view", payload)
        prefs = storage.get_user_prefs(user_id)
        message, keyboard = build_birthday_zodiac_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data in _ZODIAC_MODE_MAP:
        new_mode = _ZODIAC_MODE_MAP[query.data]
        storage.update_user_prefs(user_id, {"birthday_zodiac_mode": new_mode})
        payload = {"mode": new_mode}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_zodiac_mode_set", payload)
        prefs = storage.get_user_prefs(user_id)
        message, keyboard = build_birthday_zodiac_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_alerts":
        payload = {
            "source": "settings",
            "section": "alerts",
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "settings_section_opened", payload)
        message, keyboard = build_settings_placeholder_status("alerts")
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_export":
        await handle_settings_backup_export(update, context)
        return

    if query.data == "settings_import":
        await handle_settings_backup_import(update, context)
        return

    if query.data == "settings_mail":
        await handle_settings_backup_mail(update, context)
        return

    if query.data == "settings_mail_toggle":
        from modules.backup_core.email_backup import smtp_service_status as _svc_status
        if not _svc_status().get("configured"):
            await query.answer("⚠️ Email service unavailable", show_alert=True)
            return
        prefs = storage.get_backup_prefs(user_id)
        if prefs.get("email_enabled"):
            storage.update_backup_prefs(user_id, {"email_enabled": False})
            payload = {"source": "settings", "enabled": False}
            payload.update(acting_payload)
            storage.log_user_event(user_id, "backup_email_toggle", payload)
            prefs = storage.get_backup_prefs(user_id)
            size_bytes = _get_backup_size_bytes(storage, user_id)
            message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
            await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
            return
        if not _normalized_email_address(prefs):
            if _has_active_text_flow(context.user_data):
                await query.message.reply_text(
                    "⚠️ Finish the current flow (or /cancel) before setting your email."
                )
                return
            context.user_data["expecting_backup_email"] = True
            context.user_data["backup_email_enable_after_set"] = True
            payload = {"source": "settings", "redirected_to_set_mail": True}
            payload.update(acting_payload)
            storage.log_user_event(user_id, "backup_email_enable_prompt", payload)
            await query.message.reply_text(
                build_mail_set_prompt_message(prefs),
                reply_markup=build_mail_set_prompt_keyboard(prefs),
            )
            return
        storage.update_backup_prefs(user_id, {"email_enabled": True})
        payload = {"source": "settings", "enabled": True}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_email_toggle", payload)
        prefs = storage.get_backup_prefs(user_id)
        size_bytes = _get_backup_size_bytes(storage, user_id)
        message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_mail_set":
        if _has_active_text_flow(context.user_data):
            await query.message.reply_text(
                "⚠️ Finish the current flow (or /cancel) before setting your email."
            )
            return
        context.user_data["expecting_backup_email"] = True
        context.user_data.pop("backup_email_enable_after_set", None)
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_email_set_prompt", payload)
        prefs = storage.get_backup_prefs(user_id)
        await query.message.reply_text(
            build_mail_set_prompt_message(prefs),
            reply_markup=build_mail_set_prompt_keyboard(prefs),
        )
        return

    if query.data == "settings_mail_clear":
        context.user_data.pop("expecting_backup_email", None)
        context.user_data.pop("backup_email_enable_after_set", None)
        storage.update_backup_prefs(user_id, {
            "email_enabled": False,
            "email_address": None,
        })
        payload = {"source": "settings", "cleared": True}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_email_cleared", payload)
        prefs = storage.get_backup_prefs(user_id)
        size_bytes = _get_backup_size_bytes(storage, user_id)
        message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_mail_set_cancel":
        context.user_data.pop("expecting_backup_email", None)
        context.user_data.pop("backup_email_enable_after_set", None)
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_email_set_cancelled", payload)
        prefs = storage.get_backup_prefs(user_id)
        size_bytes = _get_backup_size_bytes(storage, user_id)
        message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_birthday_time_set":
        if _has_active_text_flow(context.user_data):
            await query.message.reply_text(
                "⚠️ Finish the current flow (or /cancel) before changing birthday time."
            )
            return
        context.user_data.pop("expecting_birthday_evening_time", None)
        context.user_data["expecting_birthday_time"] = True
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_default_time_prompt", payload)
        await query.message.reply_text(
            "✍️ Send the default birthday time as HH:MM (24h).\n"
            "Tip: /cancel will stop this step and keep your current time.",
            parse_mode="HTML",
        )
        return

    if query.data == "settings_birthday_evening_time_set":
        if _has_active_text_flow(context.user_data):
            await query.message.reply_text(
                "⚠️ Finish the current flow (or /cancel) before changing birthday evening time."
            )
            return
        context.user_data.pop("expecting_birthday_time", None)
        context.user_data["expecting_birthday_evening_time"] = True
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_evening_time_prompt", payload)
        await query.message.reply_text(
            "✍️ Send the birthday evening-before time as HH:MM (24h).\n"
            "Tip: /cancel will stop this step and keep your current time.",
            parse_mode="HTML",
        )
        return

    if query.data == "settings_mail_send":
        from modules.backup_core.email_backup import send_backup_email, smtp_service_status as _svc_status2
        if not _svc_status2().get("configured"):
            notice_text = (
                "⚠️ Email service unavailable.\n"
                "Contact the bot administrator and try again later."
            )
            callback_message = getattr(query, "message", None)
            if callback_message:
                await callback_message.reply_text(notice_text, parse_mode="HTML")
            else:
                actor_id = get_actor_user_id(update)
                if actor_id:
                    await context.bot.send_message(chat_id=actor_id, text=notice_text, parse_mode="HTML")
            return
        prefs = storage.get_backup_prefs(user_id)
        to_email = _normalized_email_address(prefs)
        if not to_email:
            await query.message.reply_text(
                "⚠️ Email not set. Use Set Mail before sending a backup.",
                parse_mode="HTML",
            )
            return
        size_bytes = _get_backup_size_bytes(storage, user_id)
        size_label = _format_backup_size_label(size_bytes)
        await query.message.reply_text(
            "📤 Sending backup email...\n\n"
            f"Data size: {size_label}\n\n"
            "If you don't find the backup email,\n"
            "check the SPAM folder!!"
        )
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_email_send_requested", payload)
        result = await asyncio.to_thread(send_backup_email, storage, user_id, to_email, reason="manual")
        if result.get("sent"):
            payload = {"source": "settings", "sent": True}
            payload.update(acting_payload)
            storage.log_user_event(user_id, "backup_email_send_result", payload)
            notif = build_backup_email_sent_notification(
                from_email=result.get("from_email", ""),
                to_email=result.get("to_email", to_email),
                size_bytes=result.get("bytes"),
                reason="manual",
                sent_at_iso=result.get("sent_at", datetime.now().isoformat()),
            )
            await query.message.reply_text(notif, parse_mode="HTML")
        else:
            payload = {
                "source": "settings",
                "sent": False,
                "error": result.get("error", "unknown_error"),
            }
            payload.update(acting_payload)
            storage.log_user_event(user_id, "backup_email_send_result", payload)
        prefs = storage.get_backup_prefs(user_id)
        size_bytes = _get_backup_size_bytes(storage, user_id)
        message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_birthday_time_reset":
        default_time = C.BIRTHDAY_DEFAULT_TIME
        storage.update_user_prefs(user_id, {"birthday_default_time": default_time})
        updated = storage.update_birthday_schedule_time(user_id, default_time, user_prefs=storage.get_user_prefs(user_id))
        payload = {
            "source": "settings",
            "time": default_time,
            "updated_birthdays": updated.get("updated", 0),
            "total_birthdays": updated.get("total", 0),
            "reset": True,
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_default_time_reset", payload)
        prefs = storage.get_user_prefs(user_id)
        message, keyboard = build_birthday_time_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_birthday_evening_time_reset":
        evening_default = C.BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME
        storage.update_user_prefs(user_id, {"birthday_evening_before_time": evening_default})
        payload = {
            "source": "settings",
            "time": evening_default,
            "reset": True,
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "birthday_evening_time_reset", payload)
        prefs = storage.get_user_prefs(user_id)
        message, keyboard = build_birthday_time_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_mail_enable":
        storage.update_backup_prefs(user_id, {
            "email_reminder_disabled": False,
        })
        payload = {"source": "settings", "enabled": True}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_email_reminder_enabled", payload)
        prefs = storage.get_backup_prefs(user_id)
        size_bytes = _get_backup_size_bytes(storage, user_id)
        message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_mail_disable":
        storage.update_backup_prefs(user_id, {
            "email_reminder_disabled": True,
        })
        payload = {"source": "settings", "disabled": True}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_email_reminder_disabled", payload)
        prefs = storage.get_backup_prefs(user_id)
        size_bytes = _get_backup_size_bytes(storage, user_id)
        message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_timezone":
        prefs = storage.get_user_prefs(user_id) or {}
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "timezone_status_view", payload)
        message, keyboard = build_timezone_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_timezone_mode_server":
        _update_timezone_prefs(storage, user_id, mode=C.TIMEZONE_MODE_SERVER)
        updated = _reschedule_user_timezones(user_id, reason="timezone_mode_server")
        payload = {
            "source": "settings",
            "mode": C.TIMEZONE_MODE_SERVER,
            "updated_alerts": updated,
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "timezone_mode_changed", payload)
        prefs = storage.get_user_prefs(user_id) or {}
        message, keyboard = build_timezone_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_timezone_mode_user":
        prefs = storage.get_user_prefs(user_id) or {}
        tz_block = prefs.get("timezone") if isinstance(prefs, dict) else {}
        tz_name = tz_block.get("name") if isinstance(tz_block, dict) else None
        if not validate_tz_name(tz_name):
            await query.message.reply_text(
                "⚠️ Set your timezone first. Tap “Set timezone”.",
                parse_mode="HTML",
            )
            return
        _update_timezone_prefs(storage, user_id, mode=C.TIMEZONE_MODE_USER)
        updated = _reschedule_user_timezones(user_id, reason="timezone_mode_user")
        payload = {
            "source": "settings",
            "mode": C.TIMEZONE_MODE_USER,
            "updated_alerts": updated,
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "timezone_mode_changed", payload)
        prefs = storage.get_user_prefs(user_id) or {}
        message, keyboard = build_timezone_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return

    if query.data == "settings_timezone_auto":
        if _has_active_text_flow(context.user_data):
            await query.message.reply_text(
                "⚠️ Finish the current flow (or /cancel) before sharing location."
            )
            return
        context.user_data["expecting_timezone_location"] = True
        context.user_data.pop("expecting_timezone_query", None)
        context.user_data.pop("timezone_pick_token_map", None)
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "timezone_auto_prompt", payload)
        await query.message.reply_text(
            "📍 Share your location to auto-detect the timezone.\n"
            "Tip: /cancel will stop this step and keep your current timezone.",
            reply_markup=build_location_request_keyboard(),
        )
        return

    if query.data == "settings_timezone_set":
        if _has_active_text_flow(context.user_data):
            await query.message.reply_text(
                "⚠️ Finish the current flow (or /cancel) before setting timezone."
            )
            return
        context.user_data["expecting_timezone_query"] = True
        context.user_data.pop("timezone_pick_token_map", None)
        payload = {"source": "settings"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "timezone_manual_prompt", payload)
        await query.message.reply_text(
            "✍️ Send a city, state, or IANA timezone (e.g., Europe/Rome).\n"
            "Tip: /cancel will stop this step and keep your current timezone.",
            parse_mode="HTML",
        )
        return

    if query.data and query.data.startswith(TZ_PICK_PREFIX):
        token = extract_callback_token(query.data, TZ_PICK_PREFIX)
        token_map = context.user_data.get("timezone_pick_token_map") or {}
        tz_name = token_map.get(token)
        if not tz_name:
            await query.message.reply_text(
                "⚠️ This selection expired. Please set your timezone again.",
                parse_mode="HTML",
            )
            return
        context.user_data.pop("expecting_timezone_query", None)
        context.user_data.pop("timezone_pick_token_map", None)
        _update_timezone_prefs(
            storage,
            user_id,
            tz_name=tz_name,
            source=C.TIMEZONE_SOURCE_MANUAL,
            state=context.user_data.pop("timezone_query_value", None),
            mode=C.TIMEZONE_MODE_USER,
        )
        updated = _reschedule_user_timezones(user_id, reason="timezone_manual")
        payload = {
            "source": "settings",
            "timezone": tz_name,
            "updated_alerts": updated,
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "timezone_manual_set", payload)
        prefs = storage.get_user_prefs(user_id) or {}
        message, keyboard = build_timezone_status(prefs)
        await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)
        return
