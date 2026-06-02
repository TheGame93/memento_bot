"""Render and handle the /settings -> Backups panel callbacks."""

import asyncio
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.backup_core.user_backup import BackupQuotaError, build_user_backup
from modules.handlers.export_import import discard_backup_import_session
from modules.shared.acting_as import (
    build_acting_as_payload,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage

from .settings_mail import _get_backup_size_bytes, build_mail_backup_status


def build_settings_backup_keyboard():
    """Build the settings Backups panel keyboard with combined export/import actions."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 Export backup", callback_data="settings_backup_export"),
            InlineKeyboardButton("📥 Import backup", callback_data="settings_backup_import"),
        ],
        [InlineKeyboardButton("✉️ Mail Backup", callback_data="settings_backup_mail")],
        [InlineKeyboardButton("🔄 Restore Backup from Server", callback_data="settings_backup_restore")],
        [InlineKeyboardButton("⬅️ Back", callback_data="settings_home")],
    ])


async def _edit_or_reply(query, text, *, parse_mode=None, reply_markup=None):
    """Edit the callback message when possible and fall back to a normal reply."""
    message = getattr(query, "message", None)
    if message:
        try:
            await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return
        except Exception:
            pass
    await query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def handle_settings_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the Backups section under /settings."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    payload = {"source": "settings", "section": "backups"}
    payload.update(build_acting_as_payload(update, context))
    storage.log_user_event(user_id, "settings_section_opened", payload)
    message = (
        "🗄️ <b>Backups</b>\n\n"
        "Export your backup, import a backup ZIP, open mail backup settings,\n"
        "or use server-side restore through /manage."
    )
    await _edit_or_reply(
        query,
        message,
        parse_mode="HTML",
        reply_markup=build_settings_backup_keyboard(),
    )


async def handle_settings_backup_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Build and send one Telegram export backup from the settings Backups panel."""
    query = update.callback_query
    if not query:
        return
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    storage.log_user_event(user_id, "backup_export_requested", {"source": "settings", **acting_payload})
    try:
        result = await asyncio.to_thread(
            build_user_backup,
            storage,
            user_id,
            "exports",
            None,
            source="export",
            enforce_quota=True,
        )
    except BackupQuotaError as exc:
        storage.log_user_event(user_id, "backup_export_failed", {
            "source": "settings",
            "reason_code": "quota_exceeded",
            "quota_bytes": int(exc.quota_bytes),
            "usage_bytes": int(exc.usage_bytes),
            "overflow_bytes": int(exc.overflow_bytes),
            **acting_payload,
        })
        await query.answer("⚠️ Backup quota exceeded. Free space and retry.", show_alert=True)
        return
    except Exception:
        storage.log_user_event(user_id, "backup_export_failed", {
            "source": "settings",
            "reason_code": "archive_build_failed",
            **acting_payload,
        })
        await query.answer("❌ Export failed. Please retry.", show_alert=True)
        return

    archive_path = result.get("path")
    archive_size = int(result.get("size_bytes") or 0)
    if archive_size > int(C.TELEGRAM_EXPORT_MAX_BYTES):
        storage.log_user_event(user_id, "backup_export_failed", {
            "source": "settings",
            "reason_code": "telegram_size_limit",
            "size_bytes": archive_size,
            "limit_bytes": int(C.TELEGRAM_EXPORT_MAX_BYTES),
            **acting_payload,
        })
        await query.answer("⚠️ Backup too large for Telegram delivery.", show_alert=True)
        return
    if not archive_path or not os.path.isfile(archive_path):
        await query.answer("❌ Export file missing. Retry.", show_alert=True)
        return

    with open(archive_path, "rb") as handle:
        await query.message.reply_document(handle, filename=os.path.basename(archive_path))
    archive_id = os.path.splitext(os.path.basename(archive_path))[0]
    storage.log_user_event(user_id, "backup_exported", {
        "source": "settings",
        "target": "telegram",
        "archive_id": archive_id,
        "size_bytes": archive_size,
        **acting_payload,
    })
    await query.answer()


async def handle_settings_backup_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Arm ZIP import mode and prompt the user to send a backup archive document."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    discard_backup_import_session(context.user_data)
    context.user_data["expecting_import_archive"] = True
    storage.log_user_event(user_id, "backup_import_prompted", {"source": "settings", **acting_payload})
    await query.message.reply_text(
        "📥 Send your backup archive as a document now.\n"
        "Tip: /cancel will stop this step.",
        parse_mode="HTML",
    )


async def handle_settings_backup_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open the mail backup subpanel from settings Backups."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    payload = {"source": "settings"}
    payload.update(build_acting_as_payload(update, context))
    storage.log_user_event(user_id, "backup_email_status_view", payload)
    prefs = storage.get_backup_prefs(user_id)
    size_bytes = _get_backup_size_bytes(storage, user_id)
    message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
    await _edit_or_reply(query, message, parse_mode="HTML", reply_markup=keyboard)


async def handle_settings_backup_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show restore guidance pointing users to /manage -> Backups for server restore."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)
    payload = {"source": "settings", "entrypoint": "settings_backup_restore"}
    payload.update(build_acting_as_payload(update, context))
    storage.log_user_event(user_id, "backup_restore_info_view", payload)
    await query.message.reply_text(
        "🔄 Server restore is available under /manage → Backups for admin/developer users.\n"
        "If you are a normal user, contact an admin to restore a server backup."
    )
