"""Handle /manage -> Backups callbacks and restore navigation flows."""

import os
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules.backup_core.archive_preview import build_archive_preview_text
from modules.backup_core.retention import retention_bucket_for_timestamp
from modules.backup_core import system_backup
from modules.backup_core.constants import LOCAL_BACKUP_HOUR, LOCAL_BACKUP_MINUTE
from modules.backup_core.user_backup import (
    diff_archive_vs_current,
    inspect_archive,
    list_user_backups,
)
from modules.backup_core.user_restore import apply_user_restore
from modules.handlers.birthday_flow.bulk_birthdays import chunk_text_blocks
from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.handlers.user_list import build_scoped_user_alias_chunks
from modules.shared.acting_as import get_actor_user_id
from modules.shared.runtime_context import get_runtime_storage
from modules.timezone_utils import get_server_tz, resolve_user_timezone

ROLE_ADMIN = "admin"
ROLE_DEVELOPER = "developer"
ELEVATED_ROLES = {ROLE_ADMIN, ROLE_DEVELOPER}
BACKUP_LIST_LINES_PER_CHUNK = 25
SYSTEM_BACKUP_LIST_LINES_PER_CHUNK = 25


def _normalize_role(role):
    text = str(role or "").strip().lower()
    if text in ELEVATED_ROLES:
        return text
    return "user"


def _is_developer(role):
    return _normalize_role(role) == ROLE_DEVELOPER


def _is_admin_or_developer(role):
    return _normalize_role(role) in ELEVATED_ROLES


def _fmt_size(size_bytes):
    """Format byte counts into human-readable MB strings for restore UI rows."""
    try:
        raw = int(size_bytes or 0)
    except Exception:
        raw = 0
    return f"{raw / (1024 * 1024):.2f} MB"


def _infer_system_backup_type(ts):
    """Return 'scheduled' if ts matches the daily cron slot, otherwise 'manual'."""
    scheduled_minute = (LOCAL_BACKUP_MINUTE + 5) % 60
    if ts and ts.hour == LOCAL_BACKUP_HOUR and ts.minute == scheduled_minute:
        return "scheduled"
    return "manual"


def _format_timestamp_for_actor(storage, actor_id, dt):
    """Format one server-naive timestamp into the actor timezone label."""
    if not isinstance(dt, datetime):
        return "n/a"
    prefs = storage.get_user_prefs(actor_id) if actor_id is not None else {}
    user_tz = resolve_user_timezone(prefs or {})
    server_tz = get_server_tz()
    server_aware = dt.replace(tzinfo=server_tz)
    return server_aware.astimezone(user_tz).strftime("%Y-%m-%d %H:%M")


def _build_backups_panel_keyboard(role):
    """Build the /manage Backups panel keyboard for admin/developer roles."""
    rows = [[InlineKeyboardButton("🔄 Restore User Backup", callback_data="mgmt_restore_users")]]
    if _is_developer(role):
        rows.append([InlineKeyboardButton("🧰 System Backup", callback_data="mgmt_system_backup")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="mgmt_menu")])
    return InlineKeyboardMarkup(rows)


def _build_system_backup_panel_keyboard():
    """Build developer-only system backup action keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Export System Backup", callback_data="mgmt_system_backup_export")],
        [InlineKeyboardButton("🔄 Restore System Backup", callback_data="mgmt_system_backup_restore")],
        [InlineKeyboardButton("⬅️ Back", callback_data="mgmt_backups")],
    ])


def _build_system_restore_confirm_keyboard():
    """Build confirmation keyboard for system restore execution."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm System Restore", callback_data="mgmt_system_backup_restore_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="mgmt_system_backup")],
    ])


def _restore_summary_keyboard():
    """Build the restore summary confirmation keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Restore", callback_data="mgmt_restore_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="mgmt_restore_cancel")],
    ])


def _build_archive_rows(storage, actor_id, target_user_id):
    """Collect restore-candidate archives across local/exports/monthly in oldest-first order."""
    rows = []
    for folder in ("local", "exports", "monthly"):
        for item in list_user_backups(target_user_id, folder):
            inspect_data = inspect_archive(item["path"], target_user_id)
            rows.append(
                {
                    "folder": folder,
                    "path": item["path"],
                    "timestamp": item["timestamp"],
                    "size_bytes": int(item.get("size_bytes") or 0),
                    "inspect": inspect_data,
                    "created_label": _format_timestamp_for_actor(storage, actor_id, item["timestamp"]),
                }
            )
    rows.sort(key=lambda entry: entry.get("timestamp") or datetime.min)
    return rows


async def _deliver_chunks(update: Update, context: ContextTypes.DEFAULT_TYPE, chunks, *, reply_markup=None):
    """Deliver chunked text through callback edit + follow-up messages or plain replies."""
    safe_chunks = [str(chunk) for chunk in (chunks or []) if str(chunk).strip()]
    if not safe_chunks:
        safe_chunks = ["No data."]

    query = update.callback_query
    if query:
        await query.edit_message_text(
            safe_chunks[0],
            parse_mode="Markdown",
            reply_markup=reply_markup if len(safe_chunks) == 1 else None,
        )
        for idx in range(1, len(safe_chunks)):
            await query.message.reply_text(
                safe_chunks[idx],
                parse_mode="Markdown",
                reply_markup=reply_markup if idx == len(safe_chunks) - 1 else None,
            )
        return

    target = update.effective_message or update.message
    if not target:
        return
    for idx, chunk in enumerate(safe_chunks):
        await target.reply_text(
            chunk,
            parse_mode="Markdown",
            reply_markup=reply_markup if idx == len(safe_chunks) - 1 else None,
        )


def _chunk_archive_lines(header, archive_lines, lines_per_chunk):
    """Split header + archive_lines into Telegram-safe chunks of <=lines_per_chunk entries each."""
    if not archive_lines:
        return chunk_text_blocks([header], safe_limit=3900)
    chunks = []
    for start in range(0, len(archive_lines), lines_per_chunk):
        block_lines = ([header] if start == 0 else []) + archive_lines[start:start + lines_per_chunk]
        chunks.extend(chunk_text_blocks(["\n".join(block_lines)], safe_limit=3900))
    return chunks


async def handle_manage_backups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the /manage Backups panel for elevated roles."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    context.user_data.pop("backup_manage_session", None)
    list_ctx = context.user_data.get(LIST_CONTEXT_KEY)
    if isinstance(list_ctx, dict) and str(list_ctx.get("source", "")).startswith("backup_"):
        context.user_data.pop(LIST_CONTEXT_KEY, None)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_admin_or_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return
    await query.edit_message_text(
        "🗄️ **Backups**\nChoose a backup management action.",
        parse_mode="Markdown",
        reply_markup=_build_backups_panel_keyboard(role),
    )


async def handle_restore_user_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render role-scoped user aliases for restore selection."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_admin_or_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return

    role_filter = "user" if role == ROLE_ADMIN else None
    render = build_scoped_user_alias_chunks(storage, role_filter=role_filter, include_alias=True)
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "backup_restore_users",
        "alias_map": render["alias_map"],
        "saved_at": datetime.now().isoformat(),
    }
    context.user_data["backup_manage_session"] = {
        "phase": "user_select",
        "role_filter": role_filter,
    }
    await _deliver_chunks(
        update,
        context,
        render["chunks"],
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_backups")]]),
    )


async def handle_restore_backup_select(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: str):
    """Render archive aliases for one restore target user."""
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_admin_or_developer(role):
        target = update.effective_message or update.message
        if target:
            await target.reply_text("🚫 Unauthorized.")
        return

    target_role = _normalize_role(storage.get_user_role(target_user_id))
    if role == ROLE_ADMIN and target_role != "user":
        target = update.effective_message or update.message
        if target:
            await target.reply_text("⚠️ Admin restore can target only regular users.")
        return

    archives = _build_archive_rows(storage, actor_id, target_user_id)
    if not archives:
        target = update.effective_message or update.message
        if target:
            await target.reply_text("⚠️ No restore archives found for this user.")
        return

    lines = [f"🗂️ **User Backups for {target_user_id}**"]
    alias_map = {}
    for idx, item in enumerate(archives, start=1):
        alias = f"{idx:02d}"
        alias_map[alias] = str(idx - 1)
        inspect_data = item.get("inspect") or {}
        source = inspect_data.get("source") or item.get("folder")
        retention_bucket = inspect_data.get("retention_bucket") or "n/a"
        alert_count = inspect_data.get("alert_count")
        image_count = inspect_data.get("image_count")
        lines.append(
            f"/{alias} {item['created_label']} | src:{source} | "
            f"alerts:{alert_count} images:{image_count} | {retention_bucket} | {_fmt_size(item['size_bytes'])}"
        )

    header = lines[0]
    archive_lines = lines[1:]
    chunks = _chunk_archive_lines(header, archive_lines, BACKUP_LIST_LINES_PER_CHUNK)
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "backup_restore_archives",
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }
    context.user_data["backup_manage_session"] = {
        "phase": "archive_select",
        "target_user_id": str(target_user_id),
        "archive_items": archives,
    }
    await _deliver_chunks(
        update,
        context,
        chunks,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_restore_users")]]),
    )


async def handle_restore_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, archive_ref: str):
    """Render one archive summary card and restore confirmation actions."""
    storage = get_runtime_storage(context)
    session = context.user_data.get("backup_manage_session") or {}
    if not isinstance(session, dict):
        return
    archives = session.get("archive_items")
    target_user_id = session.get("target_user_id")
    if not isinstance(archives, list) or target_user_id is None:
        target = update.effective_message or update.message
        if target:
            await target.reply_text("⚠️ Restore session expired. Open /manage → Backups again.")
        return

    try:
        index = int(str(archive_ref))
    except Exception:
        index = -1
    if index < 0 or index >= len(archives):
        target = update.effective_message or update.message
        if target:
            await target.reply_text("⚠️ This backup shortcut expired. Refresh the backup list.")
        return

    selected = archives[index]
    archive_path = selected.get("path")
    inspect_data = inspect_archive(archive_path, target_user_id)
    diff_data = diff_archive_vs_current(storage, target_user_id, archive_path)
    if not inspect_data.get("ok"):
        target = update.effective_message or update.message
        if target:
            await target.reply_text("❌ Failed to inspect backup archive.")
        return

    now = datetime.now()
    timestamp = selected.get("timestamp")
    age_days = None
    if isinstance(timestamp, datetime):
        age_days = max(0, (now.date() - timestamp.date()).days)

    summary = build_archive_preview_text(
        inspect_data,
        diff_data,
        title="📄 **Backup Restore Summary**",
        target_user_id=target_user_id,
        created_label=selected.get("created_label"),
        size_bytes=selected.get("size_bytes"),
        age_days=age_days,
        source_fallback=selected.get("folder"),
    )
    session["selected_archive_path"] = archive_path
    session["selected_archive_index"] = index
    session["phase"] = "summary"
    context.user_data["backup_manage_session"] = session

    target = update.effective_message or update.message
    if target:
        await target.reply_text(summary, parse_mode="Markdown", reply_markup=_restore_summary_keyboard())


async def handle_restore_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run user restore from the selected summary archive and clear restore session state."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_admin_or_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return

    session = context.user_data.get("backup_manage_session") or {}
    target_user_id = session.get("target_user_id")
    archive_path = session.get("selected_archive_path")
    if not target_user_id or not archive_path:
        await query.edit_message_text("⚠️ Restore session expired. Reopen /manage → Backups.")
        return

    import modules.scheduler_core.state as scheduler_state_module

    result = apply_user_restore(
        storage,
        target_user_id,
        archive_path,
        actor_id,
        scheduler_state_module,
        source="server_restore",
        get_role_fn=storage.get_user_role,
    )
    context.user_data.pop("backup_manage_session", None)
    context.user_data.pop(LIST_CONTEXT_KEY, None)

    if result.get("ok"):
        counts = result.get("counts_diff") or {}
        await query.edit_message_text(
            "✅ **Restore completed**\n\n"
            f"Archive: `{result.get('archive_id')}`\n"
            f"Alerts: `{counts.get('current_alert_count', 'n/a')}` → `{counts.get('archive_alert_count', 'n/a')}`\n"
            f"Birthdays: `{counts.get('current_birthday_count', 'n/a')}` → `{counts.get('archive_birthday_count', 'n/a')}`\n"
            f"Images: `{counts.get('current_image_count', 'n/a')}` → `{counts.get('archive_image_count', 'n/a')}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_backups")]]),
        )
        return

    await query.edit_message_text(
        f"❌ Restore failed: `{result.get('error', 'unknown_error')}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_backups")]]),
    )


async def handle_restore_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the in-progress restore confirmation and clear backup session state."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    context.user_data.pop("backup_manage_session", None)
    context.user_data.pop(LIST_CONTEXT_KEY, None)
    await query.edit_message_text(
        "❎ Restore cancelled.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_backups")]]),
    )


async def handle_system_backup_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE, alias_value: str):
    """Resolve numeric system-backup aliases to restore summary rendering."""
    await handle_system_backup_restore_select(update, context, alias_value)


async def handle_system_backup_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render developer-only system backup controls under /manage -> Backups."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return
    await query.edit_message_text(
        "🧰 **System Backup**\nChoose an action.",
        parse_mode="Markdown",
        reply_markup=_build_system_backup_panel_keyboard(),
    )


async def handle_system_backup_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Build one system backup archive and render export metadata for developers."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return
    built = system_backup.build_system_backup()
    archive_path = built.get("path")
    file_count = int(built.get("file_count") or 0)
    size_bytes = os.path.getsize(archive_path) if archive_path and os.path.isfile(archive_path) else 0
    await query.edit_message_text(
        "📦 **System Backup Exported**\n\n"
        f"Files: `{file_count}`\n"
        f"Size: `{_fmt_size(size_bytes)}`\n"
        f"Path: `{archive_path}`",
        parse_mode="Markdown",
        reply_markup=_build_system_backup_panel_keyboard(),
    )


async def handle_system_backup_restore_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the system-backup restore-selection list and store its alias mapping."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return

    items = system_backup.list_system_backups()
    if not items:
        await query.edit_message_text(
            "⚠️ No system backups available.",
            reply_markup=_build_system_backup_panel_keyboard(),
        )
        return

    lines = ["🗂️ **System Backups**"]
    alias_map = {}
    for idx, item in enumerate(items, start=1):
        alias = f"{idx:02d}"
        alias_map[alias] = str(idx - 1)
        created = _format_timestamp_for_actor(storage, actor_id, item.get("timestamp"))
        origin_type = _infer_system_backup_type(item.get("timestamp"))
        bucket = retention_bucket_for_timestamp(item.get("timestamp")) or "n/a"
        lines.append(
            f"/{alias} {created} | src:{origin_type} | {bucket} | {_fmt_size(item.get('size_bytes'))}"
        )

    header = lines[0]
    archive_lines = lines[1:]
    chunks = _chunk_archive_lines(header, archive_lines, SYSTEM_BACKUP_LIST_LINES_PER_CHUNK)
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "backup_system_archives",
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }
    session = context.user_data.get("backup_manage_session") or {}
    if not isinstance(session, dict):
        session = {}
    session["system_backup_items"] = items
    session["phase"] = "system_backup_list"
    context.user_data["backup_manage_session"] = session
    await _deliver_chunks(
        update,
        context,
        chunks,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_system_backup")]]),
    )


async def handle_system_backup_restore_select(update: Update, context: ContextTypes.DEFAULT_TYPE, archive_ref: str):
    """Render one system backup summary and guard-gated restore confirmation controls."""
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_developer(role):
        target = update.effective_message or update.message
        if target:
            await target.reply_text("🚫 Unauthorized.")
        return

    session = context.user_data.get("backup_manage_session") or {}
    items = session.get("system_backup_items") if isinstance(session, dict) else None
    if not isinstance(items, list):
        target = update.effective_message or update.message
        if target:
            await target.reply_text("⚠️ System backup list expired. Open it again.")
        return
    try:
        index = int(str(archive_ref))
    except Exception:
        index = -1
    if index < 0 or index >= len(items):
        target = update.effective_message or update.message
        if target:
            await target.reply_text("⚠️ This shortcut expired. Refresh system backup list.")
        return

    selected = items[index]
    archive_path = selected.get("path")
    inspected = system_backup.inspect_system_archive(archive_path)
    allowed, reason = system_backup.check_restore_guards(archive_path, actor_id, storage.get_user_role)
    created = _format_timestamp_for_actor(storage, actor_id, selected.get("timestamp"))
    summary = (
        "📄 **System Backup Restore Summary**\n\n"
        f"Created at: `{created}`\n"
        f"Size: `{_fmt_size(selected.get('size_bytes'))}`\n"
        f"Files: `{int(inspected.get('file_count') or 0)}`\n"
        f"Archive: `{archive_path}`\n"
    )
    if not allowed:
        await (update.effective_message or update.message).reply_text(
            summary + f"\n⚠️ Guard check failed: `{reason}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_system_backup")]]),
        )
        return

    session["selected_system_backup_path"] = archive_path
    session["phase"] = "system_backup_summary"
    context.user_data["backup_manage_session"] = session
    await (update.effective_message or update.message).reply_text(
        summary,
        parse_mode="Markdown",
        reply_markup=_build_system_restore_confirm_keyboard(),
    )


async def handle_system_backup_restore_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apply selected system backup restore and render success/failure outcome."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = _normalize_role(storage.get_user_role(actor_id))
    if not _is_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return
    session = context.user_data.get("backup_manage_session") or {}
    archive_path = session.get("selected_system_backup_path") if isinstance(session, dict) else None
    if not archive_path:
        await query.edit_message_text("⚠️ Restore session expired. Open System Backup list again.")
        return
    result = system_backup.apply_system_restore(archive_path, actor_id, storage.get_user_role)
    context.user_data.pop("backup_manage_session", None)
    context.user_data.pop(LIST_CONTEXT_KEY, None)
    if result.get("ok"):
        await query.edit_message_text(
            "✅ **System restore completed**\n\n"
            f"Files restored: `{int(result.get('files_restored') or 0)}`\n"
            f"Snapshot: `{result.get('snapshot_path')}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_backups")]]),
        )
        return
    await query.edit_message_text(
        f"❌ System restore failed: `{result.get('error', 'unknown_error')}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="mgmt_system_backup")]]),
    )
