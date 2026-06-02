import asyncio
import logging
import os
import tempfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ApplicationHandlerStop

from modules.backup_core.archive_preview import build_archive_preview_text
from modules.backup_core.export_import import export_user_archive, import_user_archive
from modules.backup_core.user_backup import diff_archive_vs_current, inspect_archive
from modules.shared.acting_as import (
    build_acting_as_payload,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage

logger = logging.getLogger(__name__)
IMPORT_PENDING_KEY = "expecting_import_archive"

ALLOWED_ZIP_MIME_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "multipart/x-zip",
}
from modules import constants as C
USER_IMPORT_MAX_BYTES = min(
    45 * 1024 * 1024,
    getattr(C, "IMPORT_DOWNLOAD_MAX_BYTES", 45 * 1024 * 1024),
)


def _extract_document_path(update: Update):
    message = update.effective_message or update.message
    doc = message.document if message else None
    if not doc:
        return None
    return doc


def _size_to_mb_string(size_bytes):
    if not isinstance(size_bytes, int) or size_bytes < 0:
        return "unknown"
    return f"{size_bytes / (1024 * 1024):.1f}"


def _validate_import_document(doc, *, max_bytes):
    file_name = (getattr(doc, "file_name", None) or "").strip()
    mime_type = (getattr(doc, "mime_type", None) or "").strip().lower()
    file_size = getattr(doc, "file_size", None)

    is_zip_by_name = file_name.lower().endswith(".zip") if file_name else False
    is_zip_by_mime = mime_type in ALLOWED_ZIP_MIME_TYPES if mime_type else False
    if not (is_zip_by_name or is_zip_by_mime):
        return False, "invalid_type", "❌ Only .zip archives are allowed."

    if isinstance(file_size, int) and file_size > max_bytes:
        return (
            False,
            "file_too_large",
            "❌ Archive too large "
            f"({_size_to_mb_string(file_size)} MB). "
            f"Max allowed: {_size_to_mb_string(max_bytes)} MB.",
        )

    return True, None, None


def _delete_temp_path(path):
    """Remove one temporary archive path best-effort."""
    if not isinstance(path, str) or not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def discard_backup_import_session(user_data) -> dict | None:
    """Clear a pending backup import session and remove its staged archive best-effort."""
    if not isinstance(user_data, dict):
        return None
    session = user_data.pop("backup_import_session", None)
    if not isinstance(session, dict):
        return None
    temp_path = session.get("temp_path")
    if isinstance(temp_path, str) and temp_path:
        _delete_temp_path(temp_path)
    return session


async def _run_import_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, *, source: str):
    """Stage a user import archive, render a preview, and wait for explicit confirmation."""
    storage = get_runtime_storage(context)

    message = update.effective_message or update.message
    if not message:
        return
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    doc = _extract_document_path(update)

    if not doc:
        context.user_data[IMPORT_PENDING_KEY] = True
        payload = {"source": source}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_import_prompted", payload)
        await message.reply_text("⚠️ Send a backup archive as a document now or /cancel.")
        return

    valid_doc, invalid_reason, invalid_text = _validate_import_document(
        doc,
        max_bytes=USER_IMPORT_MAX_BYTES,
    )
    if not valid_doc:
        context.user_data[IMPORT_PENDING_KEY] = True
        payload = {"source": source, "error": f"invalid_document:{invalid_reason}"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_import_failed", payload)
        await message.reply_text(
            f"{invalid_text}\nSend a backup .zip archive now or /cancel."
        )
        return

    discard_backup_import_session(context.user_data)
    context.user_data.pop(IMPORT_PENDING_KEY, None)
    payload = {"source": source}
    payload.update(acting_payload)
    storage.log_user_event(user_id, "backup_import_requested", payload)

    tmp_handle = tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".zip",
        prefix=f"import_{user_id}_",
        dir="/tmp",
        delete=False,
    )
    tmp_path = tmp_handle.name
    tmp_handle.close()
    tmp_stored_in_session = False

    try:
        await message.reply_text("📥 Downloading archive...")
        try:
            file = await doc.get_file()
            await file.download_to_drive(tmp_path)
        except Exception as exc:
            payload = {
                "source": source,
                "error": f"download_failed: {exc}",
            }
            payload.update(acting_payload)
            storage.log_user_event(user_id, "backup_import_failed", payload)
            await message.reply_text("❌ Import failed while downloading the archive.")
            return

        # Post-download size check against IMPORT_DOWNLOAD_MAX_BYTES
        import_max = getattr(C, "IMPORT_DOWNLOAD_MAX_BYTES", 0)
        if import_max > 0:
            try:
                actual_size = os.path.getsize(tmp_path)
                if actual_size > import_max:
                    payload = {
                        "source": source,
                        "error": f"download_too_large:{actual_size}",
                    }
                    payload.update(acting_payload)
                    storage.log_user_event(user_id, "backup_import_failed", payload)
                    await message.reply_text(
                        f"❌ Archive too large after download "
                        f"({actual_size / (1024*1024):.1f} MB). "
                        f"Max allowed: {import_max / (1024*1024):.0f} MB."
                    )
                    return
            except OSError:
                pass

        await message.reply_text("🔄 Checking archive...")
        inspect_data = await asyncio.to_thread(inspect_archive, tmp_path, user_id)
        if not inspect_data.get("ok"):
            storage.log_user_event(user_id, "backup_import_failed", {
                "source": source,
                "error": "inspect_failed",
                "details": inspect_data.get("errors"),
                **acting_payload,
            })
            await message.reply_text("❌ Could not read backup archive.")
            return

        try:
            diff_data = await asyncio.to_thread(diff_archive_vs_current, storage, user_id, tmp_path)
        except Exception as exc:
            diff_data = {"ok": False, "errors": [str(exc)]}
        if not diff_data.get("ok"):
            storage.log_user_event(user_id, "backup_import_failed", {
                "source": source,
                "error": "diff_failed",
                "details": diff_data.get("errors"),
                **acting_payload,
            })
            await message.reply_text("❌ Could not compare the archive with your current backup data.")
            return

        size_bytes = inspect_data.get("size_bytes")
        summary = build_archive_preview_text(
            inspect_data,
            diff_data,
            title="📄 **Backup Import Preview**",
            target_user_id=str(user_id),
            size_bytes=size_bytes,
        )
        confirm_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Import", callback_data="settings_backup_import_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="settings_backup_import_cancel")],
        ])
        context.user_data["backup_import_session"] = {
            "temp_path": tmp_path,
            "source": source,
            "target_user_id": str(user_id),
        }
        tmp_stored_in_session = True
        storage.log_user_event(user_id, "backup_import_preview_shown", {"source": source, **acting_payload})
        await message.reply_text(summary, parse_mode="Markdown", reply_markup=confirm_keyboard)
    finally:
        if not tmp_stored_in_session:
            _delete_temp_path(tmp_path)


async def handle_settings_backup_import_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run a pending user import from the stored session archive and clean up session state."""
    query = update.callback_query
    if not query:
        return
    storage = get_runtime_storage(context)
    acting_payload = build_acting_as_payload(update, context)
    session = context.user_data.pop("backup_import_session", None)
    context.user_data.pop(IMPORT_PENDING_KEY, None)

    if not isinstance(session, dict):
        await query.answer("⚠️ Import session expired. Please send the archive again.", show_alert=True)
        return

    tmp_path = session.get("temp_path")
    source = session.get("source", "settings") if isinstance(session.get("source"), str) else "settings"
    user_id = session.get("target_user_id") or get_target_user_id(update, context)

    if not isinstance(tmp_path, str) or not tmp_path or not os.path.exists(tmp_path):
        _delete_temp_path(tmp_path)
        await query.answer("⚠️ Import session expired. Please send the archive again.", show_alert=True)
        return

    await query.answer()
    try:
        result = await asyncio.to_thread(import_user_archive, storage, user_id, tmp_path)
    except Exception as exc:
        result = {"ok": False, "error": f"import_exception: {exc}"}
    finally:
        _delete_temp_path(tmp_path)

    if result.get("ok"):
        storage.log_user_event(user_id, "backup_import_completed", {"source": source, **acting_payload})
        await query.message.reply_text("✅ Import completed.")
    else:
        error = result.get("error", "unknown_error")
        storage.log_user_event(user_id, "backup_import_failed", {
            "source": source,
            "error": error,
            "details": result.get("details"),
            **acting_payload,
        })
        await query.message.reply_text(f"❌ Import failed: {error}")


async def handle_settings_backup_import_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel a pending user import, discard the staged archive, and clear session state."""
    query = update.callback_query
    if not query:
        return
    session = discard_backup_import_session(context.user_data)
    context.user_data.pop(IMPORT_PENDING_KEY, None)
    user_id = (
        session.get("target_user_id")
        if isinstance(session, dict) and session.get("target_user_id")
        else get_target_user_id(update, context)
    )
    source = (
        session.get("source")
        if isinstance(session, dict) and isinstance(session.get("source"), str)
        else "settings"
    )
    acting_payload = build_acting_as_payload(update, context)
    storage = get_runtime_storage(context)
    storage.log_user_event(user_id, "backup_import_cancelled", {"source": source, **acting_payload})
    await query.answer()
    await query.message.reply_text("❌ Import cancelled.")


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export user data as a zip archive."""
    storage = get_runtime_storage(context)

    message = update.effective_message or update.message
    if not message:
        return

    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    payload = {"source": "command"}
    payload.update(acting_payload)
    storage.log_user_event(user_id, "backup_export_requested", payload)
    await message.reply_text("📦 Preparing your export archive...")

    try:
        result = await asyncio.to_thread(export_user_archive, storage, user_id)
    except Exception as exc:
        payload = {"source": "command", "error": str(exc)}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_export_failed", payload)
        await message.reply_text("❌ Export failed. Please try again.")
        return

    path = result.get("path")
    if not path or not os.path.isfile(path):
        payload = {"source": "command"}
        payload.update(acting_payload)
        storage.log_user_event(user_id, "backup_export_failed", payload)
        await message.reply_text("❌ Export failed. Please try again.")
        return

    with open(path, "rb") as handle:
        await message.reply_document(handle, filename=os.path.basename(path))
    payload = {"source": "command", "files_count": len(result.get("files") or [])}
    payload.update(acting_payload)
    storage.log_user_event(user_id, "backup_export_completed", payload)


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Import user data from a previously exported archive."""
    await _run_import_flow(update, context, source="command")


async def handle_import_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consumes a pending /import flow when the next document is uploaded."""
    if not context.user_data.get(IMPORT_PENDING_KEY):
        return
    if not _extract_document_path(update):
        return
    await _run_import_flow(update, context, source="followup")
    raise ApplicationHandlerStop
