import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from modules.shared.context_cleanup import clear_transient_context
from modules.shared.acting_as import get_actor_user_id
from modules.shared.runtime_context import get_runtime_storage
from modules.shared.user_identity import format_user_label_from_meta
from modules.systemlog import log_system
from modules.handlers.user_list import is_message_not_modified_error

logger = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_DEVELOPER = "developer"
ELEVATED_ROLES = {ROLE_ADMIN, ROLE_DEVELOPER}


def _normalize_role(role):
    text = str(role).strip().lower() if role is not None else ""
    if text in ELEVATED_ROLES:
        return text
    return None


def _is_elevated(role):
    return _normalize_role(role) in ELEVATED_ROLES


def _is_developer(role):
    return _normalize_role(role) == ROLE_DEVELOPER


def _current_target_id(context):
    if context is None:
        return None
    return context.user_data.get("acting_as_user_id")


def build_manage_keyboard(role, target_id=None):
    """Build manage-dashboard controls based on elevated role and acting target."""
    role = _normalize_role(role)
    rows = [
        [
            InlineKeyboardButton("👥 User List", callback_data="mgmt_users"),
            InlineKeyboardButton("📝 Pending Request", callback_data="mgmt_requests"),
        ],
        [
            InlineKeyboardButton("➕ Add User", callback_data="mgmt_add_user"),
            InlineKeyboardButton("📨 Pending Invite", callback_data="mgmt_invites"),
        ],
        [InlineKeyboardButton("🗄️ Backups", callback_data="mgmt_backups")],
    ]
    if _is_developer(role):
        rows.append([InlineKeyboardButton("📊 Storage Summary", callback_data="mgmt_storage")])
        if target_id:
            rows.append([InlineKeyboardButton("🛑 Stop Acting", callback_data="mgmt_actas_stop")])
    return InlineKeyboardMarkup(rows)


def build_manage_text(role, target_id=None, target_label=None):
    """Build manage-dashboard header text with optional acting-as context."""
    title = "⚙️ **Manage Dashboard**"
    if _is_developer(role):
        if target_id:
            label = target_label or str(target_id)
            return f"{title}\nActing as: {label}"
        return f"{title}\nActing as: `none`"
    return title


def _build_target_label(storage, target_id):
    if target_id is None or storage is None:
        return None
    meta = storage.get_user_meta(target_id) or {}
    return format_user_label_from_meta(target_id, meta, escape_markdown=True)


def _log_dashboard_opened(actor_id, role, target_id, source):
    log_system("admin_audit", "manage_dashboard_opened", {
        "actor_id": str(actor_id) if actor_id is not None else None,
        "role": role,
        "target_id": str(target_id) if target_id is not None else None,
        "source": source,
    })


async def _send_manage_dashboard(update, context, storage, *, role, source):
    target_id = _current_target_id(context)
    target_label = _build_target_label(storage, target_id)
    text = build_manage_text(role, target_id, target_label)
    keyboard = build_manage_keyboard(role, target_id)

    query = update.callback_query if update else None
    if query:
        if query.message:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await context.bot.send_message(chat_id=get_actor_user_id(update), text=text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        target = update.effective_message if update else None
        if target:
            await target.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await context.bot.send_message(chat_id=get_actor_user_id(update), text=text, parse_mode="Markdown", reply_markup=keyboard)

    _log_dashboard_opened(get_actor_user_id(update), role, target_id, source)


async def manage_dashboard_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the manage dashboard for authorized elevated roles."""
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = storage.get_user_role(actor_id)
    if not _is_elevated(role):
        await update.effective_message.reply_text("🚫 Unauthorized.")
        return
    clear_transient_context(context.user_data, include_navigation=True)
    await _send_manage_dashboard(update, context, storage, role=role, source="command")


async def handle_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route manage dashboard callbacks to admin/developer feature handlers."""
    storage = get_runtime_storage(context)
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    if not (
        data == "mgmt_backups"
        or data.startswith("mgmt_restore_")
        or data.startswith("mgmt_system_backup")
        or data in {"mgmt_export", "mgmt_import"}
    ):
        await query.answer()

    actor_id = get_actor_user_id(update)
    role = storage.get_user_role(actor_id)
    if not _is_elevated(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return

    if data == "mgmt_menu":
        clear_transient_context(context.user_data, include_navigation=True)
        await _send_manage_dashboard(update, context, storage, role=role, source="callback")
        return

    if data == "mgmt_backups":
        from modules.handlers.backup_manage import handle_manage_backups
        await handle_manage_backups(update, context)
        return

    if data == "mgmt_restore_users":
        from modules.handlers.backup_manage import handle_restore_user_select
        await handle_restore_user_select(update, context)
        return

    if data == "mgmt_restore_confirm":
        from modules.handlers.backup_manage import handle_restore_confirm
        await handle_restore_confirm(update, context)
        return

    if data == "mgmt_restore_cancel":
        from modules.handlers.backup_manage import handle_restore_cancel
        await handle_restore_cancel(update, context)
        return

    if data == "mgmt_system_backup":
        from modules.handlers.backup_manage import handle_system_backup_panel
        await handle_system_backup_panel(update, context)
        return

    if data == "mgmt_system_backup_export":
        from modules.handlers.backup_manage import handle_system_backup_export
        await handle_system_backup_export(update, context)
        return

    if data == "mgmt_system_backup_list":
        from modules.handlers.backup_manage import handle_system_backup_list
        await handle_system_backup_list(update, context)
        return

    if data == "mgmt_system_backup_restore":
        from modules.handlers.backup_manage import handle_system_backup_list
        await handle_system_backup_list(update, context)
        return

    if data == "mgmt_system_backup_restore_confirm":
        from modules.handlers.backup_manage import handle_system_backup_restore_confirm
        await handle_system_backup_restore_confirm(update, context)
        return

    if data == "mgmt_users":
        from modules.handlers.user_list import show_user_list
        await show_user_list(update, context, storage, role=role, origin="manage")
        return

    if data == "mgmt_requests":
        from modules.handlers.admin import show_admin_requests_list
        await show_admin_requests_list(query, context)
        return

    if data == "mgmt_add_user":
        from modules.handlers.admin import start_admin_add_user
        await start_admin_add_user(query, context)
        return

    if data == "mgmt_invites":
        from modules.handlers.admin import show_admin_invites_list
        await show_admin_invites_list(query, context, storage, actor_id)
        return

    if data == "mgmt_storage":
        if not _is_developer(role):
            await query.edit_message_text("🚫 Unauthorized.")
            return
        from modules.handlers.developer import _build_meta_map, _build_storage_summary_payload, _back_only_keyboard
        from modules.security.whitelist_store import list_whitelist_users
        entries = list_whitelist_users()
        meta_map = _build_meta_map(storage, entries)
        summary_payload = _build_storage_summary_payload(storage, entries, meta_map)
        text = summary_payload.get("text") or "📊 **Storage Summary**\nNo user data found."
        event_payload = {
            "actor_id": str(actor_id) if actor_id is not None else None,
            "actor_role": role,
            "source": "mgmt_storage",
            "rows_count": int(summary_payload.get("rows_count", 0)),
            "total_data_root_bytes": int(summary_payload.get("total_data_root_bytes", 0)),
            "total_system_log_root_bytes": int(summary_payload.get("total_system_log_root_bytes", 0)),
            "total_user_log_root_bytes": int(summary_payload.get("total_user_log_root_bytes", 0)),
            "total_backup_root_bytes": int(summary_payload.get("total_backup_root_bytes", 0)),
            "total_user_data_bytes": int(summary_payload.get("total_user_data_bytes", 0)),
            "total_user_logs_bytes": int(summary_payload.get("total_user_logs_bytes", 0)),
            "total_user_backups_bytes": int(summary_payload.get("total_user_backups_bytes", 0)),
            "total_rows_bytes": int(summary_payload.get("total_rows_bytes", 0)),
            "delivery": "edited",
        }
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_back_only_keyboard())
        except BadRequest as exc:
            if is_message_not_modified_error(exc):
                event_payload["delivery"] = "message_not_modified"
            else:
                fail_payload = dict(event_payload)
                fail_payload["reason_code"] = "message_edit_failed"
                log_system("admin_audit", "manage_storage_summary_failed", fail_payload)
                if actor_id is not None:
                    storage.log_user_event(actor_id, "manage_storage_summary_failed", fail_payload)
                raise
        except Exception:
            fail_payload = dict(event_payload)
            fail_payload["reason_code"] = "message_edit_failed"
            log_system("admin_audit", "manage_storage_summary_failed", fail_payload)
            if actor_id is not None:
                storage.log_user_event(actor_id, "manage_storage_summary_failed", fail_payload)
            raise
        log_system("admin_audit", "manage_storage_summary_viewed", event_payload)
        if actor_id is not None:
            storage.log_user_event(actor_id, "manage_storage_summary_viewed", event_payload)
        return

    if data in {"mgmt_export", "mgmt_import"}:
        if not _is_developer(role):
            await query.edit_message_text("🚫 Unauthorized.")
            return
        await query.answer("Backup actions moved to /manage → Backups.", show_alert=True)
        await _send_manage_dashboard(update, context, storage, role=role, source="callback")
        return

    if data == "mgmt_actas_stop":
        if not _is_developer(role):
            await query.edit_message_text("🚫 Unauthorized.")
            return
        from modules.handlers.developer import _clear_acting_as_lock
        from modules.shared.acting_as import clear_acting_as, build_acting_as_payload_for
        target_id = _current_target_id(context)
        if target_id:
            payload = build_acting_as_payload_for(actor_id, target_id)
            storage.log_user_event(target_id, "developer_acting_as_stop", payload)
            _clear_acting_as_lock(storage, target_id)
        clear_acting_as(context)
        log_system("security", "developer_acting_as_stop", {
            "actor_id": str(actor_id),
            "target_id": str(target_id) if target_id is not None else None,
        })
        log_system("admin_audit", "acting_as_stop", {
            "actor_id": str(actor_id),
            "target_id": str(target_id) if target_id is not None else None,
        })
        await _send_manage_dashboard(update, context, storage, role=role, source="callback")
        return

    await query.edit_message_text("⚠️ Unknown action.")
