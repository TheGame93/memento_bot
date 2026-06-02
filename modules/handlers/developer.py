import logging
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.handlers.base import get_size_format
from modules.security.roles import VALID_ROLES
from modules.security.whitelist_store import add_whitelist_user, list_whitelist_users
from modules.shared.acting_as import (
    build_acting_as_payload,
    build_acting_as_payload_for,
    clear_acting_as,
    get_actor_user_id,
    set_acting_as,
)
from modules.shared.runtime_context import (
    get_runtime_api_failure_tracker,
    get_runtime_storage,
)
from modules.systemlog import log_system
from modules.shared.context_cleanup import clear_transient_context
from modules.shared.user_identity import format_user_label_from_meta
from modules.shared.user_status import build_user_status_message
from modules.shared.markdown_utils import (
    md_escape_inline_code as _md_escape_inline_code,
)
from modules.shared.storage_metrics import (
    get_backup_root_bytes,
    get_data_root_bytes,
    get_system_log_root_bytes,
    get_user_backup_dir_bytes,
    get_user_data_dir_bytes,
    get_user_event_logs_bytes,
    get_user_log_root_bytes,
)
from modules.shared.messages import send_feature_not_implemented
from modules.handlers.user_list import (
    build_users_text,
    summarize_user_data,
    show_user_list,
    build_user_detail_keyboard,
    resolve_user_detail_back_cb,
    log_user_detail_render,
    is_message_not_modified_error,
)
from modules.shared.whitelist_users import build_whitelist_users_empty_text
from modules.handlers.manage import build_manage_keyboard, build_manage_text
from modules import constants as C

logger = logging.getLogger(__name__)


def _is_developer(role):
    return role == "developer"


def _dashboard_text(target_id, target_label=None):
    return build_manage_text("developer", target_id, target_label)


def _current_target_id(context):
    if context is None:
        return None
    return context.user_data.get("acting_as_user_id")


def _dashboard_keyboard(target_id):
    return build_manage_keyboard("developer", target_id)

def _parse_iso(ts):
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _get_active_acting_lock(storage, target_id):
    if target_id is None:
        return None
    meta = storage.get_user_meta(target_id) or {}
    lock = meta.get("acting_as_lock")
    if not isinstance(lock, dict):
        return None
    expires_at = _parse_iso(lock.get("expires_at"))
    if expires_at and expires_at <= datetime.now():
        storage.update_user_meta(target_id, {"acting_as_lock": None})
        return None
    return lock


def _set_acting_as_lock(storage, target_id, actor_id):
    if target_id is None or actor_id is None:
        return
    now = datetime.now()
    expires_at = now + timedelta(seconds=C.ACTING_AS_LOCK_TTL_SECONDS)
    storage.update_user_meta(target_id, {
        "acting_as_lock": {
            "by": str(actor_id),
            "started_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    })


def _clear_acting_as_lock(storage, target_id):
    if target_id is None:
        return
    storage.update_user_meta(target_id, {"acting_as_lock": None})


def _compute_user_storage_parts(storage, user_id):
    if user_id is None:
        return {
            "data_bytes": 0,
            "logs_bytes": 0,
            "backups_bytes": 0,
            "total_bytes": 0,
        }
    data_bytes = get_user_data_dir_bytes(user_id)
    logs_bytes = get_user_event_logs_bytes(storage, user_id)
    backups_bytes = get_user_backup_dir_bytes(user_id)
    return {
        "data_bytes": data_bytes,
        "logs_bytes": logs_bytes,
        "backups_bytes": backups_bytes,
        "total_bytes": data_bytes + logs_bytes + backups_bytes,
    }


def _build_storage_summary_payload(storage, entries, meta_map):
    total_data_root_bytes = get_data_root_bytes()
    total_system_log_root_bytes = get_system_log_root_bytes()
    total_user_log_root_bytes = get_user_log_root_bytes()
    total_backup_root_bytes = get_backup_root_bytes()
    rows = []
    total_user_data_bytes = 0
    total_user_logs_bytes = 0
    total_user_backups_bytes = 0
    total_rows_bytes = 0
    for entry in entries:
        uid = entry.get("id")
        if uid is None:
            continue
        parts = _compute_user_storage_parts(storage, uid)
        meta = meta_map.get(str(uid)) or {}
        label = format_user_label_from_meta(uid, meta, escape_markdown=True)
        total_user_data_bytes += parts["data_bytes"]
        total_user_logs_bytes += parts["logs_bytes"]
        total_user_backups_bytes += parts["backups_bytes"]
        total_rows_bytes += parts["total_bytes"]
        rows.append({
            "label": label,
            "data_bytes": parts["data_bytes"],
            "logs_bytes": parts["logs_bytes"],
            "backups_bytes": parts["backups_bytes"],
            "total_bytes": parts["total_bytes"],
        })
    rows.sort(key=lambda item: (-item["total_bytes"], str(item["label"]).lower()))

    lines = [
        "📊 **Storage Summary**",
        "",
        f"Total space (data/): `{get_size_format(total_data_root_bytes)}`",
        f"Total space (data/systemlog.d): `{get_size_format(total_system_log_root_bytes)}`",
        f"Total space (data/userlog.d): `{get_size_format(total_user_log_root_bytes)}`",
        f"Total space (backups/): `{get_size_format(total_backup_root_bytes)}`",
    ]
    if not rows:
        lines.append("No user data found.")
        return {
            "text": "\n".join(lines),
            "rows_count": 0,
            "total_data_root_bytes": total_data_root_bytes,
            "total_system_log_root_bytes": total_system_log_root_bytes,
            "total_user_log_root_bytes": total_user_log_root_bytes,
            "total_backup_root_bytes": total_backup_root_bytes,
            "total_user_data_bytes": 0,
            "total_user_logs_bytes": 0,
            "total_user_backups_bytes": 0,
            "total_rows_bytes": 0,
        }

    lines.append("")
    lines.append("User name - Data / Logs / Backups")
    lines.append("")
    for row in rows:
        lines.append(
            f"{row['label']} - "
            f"`{get_size_format(row['data_bytes'])}` / "
            f"`{get_size_format(row['logs_bytes'])}` / "
            f"`{get_size_format(row['backups_bytes'])}`"
        )
    return {
        "text": "\n".join(lines),
        "rows_count": len(rows),
        "total_data_root_bytes": total_data_root_bytes,
        "total_system_log_root_bytes": total_system_log_root_bytes,
        "total_user_log_root_bytes": total_user_log_root_bytes,
        "total_backup_root_bytes": total_backup_root_bytes,
        "total_user_data_bytes": total_user_data_bytes,
        "total_user_logs_bytes": total_user_logs_bytes,
        "total_user_backups_bytes": total_user_backups_bytes,
        "total_rows_bytes": total_rows_bytes,
    }


def _build_storage_summary(storage, entries, meta_map):
    return _build_storage_summary_payload(storage, entries, meta_map)["text"]


def _users_text(entries, meta_map, summary_map=None):
    text, _ = build_users_text(
        entries,
        meta_map,
        summary_map,
        include_alias=False,
        empty_text=build_whitelist_users_empty_text(),
    )
    return text


def _build_users_list(entries, meta_map, summary_map=None):
    return build_users_text(
        entries,
        meta_map,
        summary_map,
        include_alias=True,
        empty_text=build_whitelist_users_empty_text(),
    )


def _back_only_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="mgmt_menu")]])


def _users_keyboard(entries, back_cb, meta_map):
    rows = []
    for entry in entries[:20]:
        uid = entry.get("id")
        if uid is None:
            continue
        meta = meta_map.get(str(uid)) or {}
        label = format_user_label_from_meta(uid, meta, escape_markdown=False)
        rows.append([InlineKeyboardButton(f"{label}", callback_data=f"developer_user:{uid}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def _build_meta_map(storage, entries):
    meta_map = {}
    for entry in entries:
        uid = entry.get("id")
        if uid is None:
            continue
        meta_map[str(uid)] = storage.get_user_meta(uid) or {}
    return meta_map


def _build_summary_map(storage, entries):
    summary_map = {}
    for entry in entries:
        uid = entry.get("id")
        if uid is None:
            continue
        try:
            summary_map[str(uid)] = _summarize_user_data(storage.get_all_alerts(uid))
        except Exception:
            summary_map[str(uid)] = {"alerts": 0, "birthdays": 0, "tags": 0}
    return summary_map


def _summarize_user_data(data):
    return summarize_user_data(data)


def _user_detail_keyboard(uid, role, actor_id=None, back_cb=None):
    if not back_cb:
        back_cb = resolve_user_detail_back_cb(None, "developer") or "developer_users"
    return build_user_detail_keyboard(
        actor_role="developer",
        target_role=role,
        target_id=uid,
        actor_id=actor_id,
        back_cb=back_cb,
    )


async def handle_developer_shortcut_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: str) -> None:
    """Handle developer user shortcut commands and render user detail cards."""
    storage = get_runtime_storage(context)
    api_failure_tracker = get_runtime_api_failure_tracker(context)
    actor_id = update.effective_user.id if update.effective_user else None
    role = storage.get_user_role(actor_id)
    target = update.effective_message or update.message
    if not _is_developer(role):
        if target:
            await target.reply_text("🚫 Unauthorized.")
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=None,
            source="developer_users",
            delivery="shortcut_reply",
            text=None,
            ok=False,
            reason="unauthorized",
        )
        return
    entries = list_whitelist_users()
    entry = next((e for e in entries if str(e.get("id")) == str(target_id)), None)
    if not entry:
        if target:
            await target.reply_text("⚠️ User not found or no longer whitelisted.")
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=None,
            source="developer_users",
            delivery="shortcut_reply",
            text=None,
            ok=False,
            reason="target_missing",
        )
        return
    back_cb = resolve_user_detail_back_cb(context, role)
    status_text = build_user_status_message(
        storage,
        target_id,
        viewer_role=role,
        api_failure_tracker=api_failure_tracker,
    )
    target_role = entry.get("role")
    if not target:
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=target_role,
            source="developer_users",
            delivery="shortcut_reply",
            text=status_text,
            ok=False,
            reason="missing_delivery_target",
        )
        return
    try:
        await target.reply_text(
            status_text,
            parse_mode="Markdown",
            reply_markup=_user_detail_keyboard(target_id, target_role, actor_id=actor_id, back_cb=back_cb),
        )
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=target_role,
            source="developer_users",
            delivery="shortcut_reply",
            text=status_text,
            ok=True,
        )
    except BadRequest as exc:
        if is_message_not_modified_error(exc):
            log_user_detail_render(
                storage,
                actor_id=actor_id,
                actor_role=role,
                target_id=target_id,
                target_role=target_role,
                source="developer_users",
                delivery="shortcut_reply",
                text=status_text,
                ok=True,
                reason="message_not_modified",
            )
            return
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=target_role,
            source="developer_users",
            delivery="shortcut_reply",
            text=status_text,
            ok=False,
            reason="bad_request",
        )
        raise


async def handle_developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route developer dashboard callbacks for roles, acting-as, and system actions."""
    storage = get_runtime_storage(context)
    api_failure_tracker = get_runtime_api_failure_tracker(context)
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    is_legacy_backup_action = (
        data.startswith("developer_export")
        or data.startswith("developer_import")
        or data.startswith("developer_rollback")
    )
    if not is_legacy_backup_action:
        await query.answer()

    actor_id = get_actor_user_id(update)
    role = storage.get_user_role(actor_id)
    if not _is_developer(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return

    clear_transient_context(context.user_data, include_navigation=True)
    current_target = _current_target_id(context)

    if data == "developer_menu":
        target_id = _current_target_id(context)
        target_label = None
        if target_id:
            meta = storage.get_user_meta(target_id) or {}
            target_label = format_user_label_from_meta(target_id, meta, escape_markdown=True)
        await query.edit_message_text(
            _dashboard_text(target_id, target_label),
            parse_mode="Markdown",
            reply_markup=_dashboard_keyboard(target_id),
        )
        return

    if data == "developer_users":
        await show_user_list(update, context, storage, role=role, origin="developer")
        return

    if data == "developer_storage_summary":
        entries = list_whitelist_users()
        meta_map = _build_meta_map(storage, entries)
        summary_payload = _build_storage_summary_payload(storage, entries, meta_map)
        text = summary_payload.get("text") or "📊 **Storage Summary**\nNo user data found."
        event_payload = {
            "actor_id": str(actor_id) if actor_id is not None else None,
            "actor_role": role,
            "source": "developer_storage_summary",
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
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
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

    # Stub: handle stale cached "Usage Analysis" buttons gracefully.
    if data == "developer_usage" or data.startswith("developer_usage:"):
        await send_feature_not_implemented(
            update,
            context,
            storage,
            feature_label="usage_analysis",
            reply_markup=_dashboard_keyboard(_current_target_id(context)),
        )
        return

    if data.startswith("developer_user:"):
        target_id = data.split(":", 1)[1]
        entries = list_whitelist_users()
        entry = next((e for e in entries if str(e.get("id")) == str(target_id)), None)
        if not entry:
            log_user_detail_render(
                storage,
                actor_id=actor_id,
                actor_role=role,
                target_id=target_id,
                target_role=None,
                source="developer_users",
                delivery="callback_edit",
                text=None,
                ok=False,
                reason="target_missing",
            )
            await query.edit_message_text(
                "⚠️ User not found or no longer whitelisted.",
                reply_markup=_dashboard_keyboard(current_target),
            )
            return
        back_cb = resolve_user_detail_back_cb(context, role)
        status_text = build_user_status_message(
            storage,
            target_id,
            viewer_role=role,
            api_failure_tracker=api_failure_tracker,
        )
        target_role = entry.get("role")
        try:
            await query.edit_message_text(
                status_text,
                parse_mode="Markdown",
                reply_markup=_user_detail_keyboard(target_id, target_role, actor_id=actor_id, back_cb=back_cb),
            )
            log_user_detail_render(
                storage,
                actor_id=actor_id,
                actor_role=role,
                target_id=target_id,
                target_role=target_role,
                source="developer_users",
                delivery="callback_edit",
                text=status_text,
                ok=True,
            )
        except BadRequest as exc:
            if is_message_not_modified_error(exc):
                log_user_detail_render(
                    storage,
                    actor_id=actor_id,
                    actor_role=role,
                    target_id=target_id,
                    target_role=target_role,
                    source="developer_users",
                    delivery="callback_edit",
                    text=status_text,
                    ok=True,
                    reason="message_not_modified",
                )
                return
            log_user_detail_render(
                storage,
                actor_id=actor_id,
                actor_role=role,
                target_id=target_id,
                target_role=target_role,
                source="developer_users",
                delivery="callback_edit",
                text=status_text,
                ok=False,
                reason="bad_request",
            )
            raise
        return

    if data.startswith("developer_role:"):
        _, target_id, new_role = data.split(":", 2)
        if new_role not in VALID_ROLES:
            await query.edit_message_text(
                f"⚠️ Invalid role: `{_md_escape_inline_code(new_role)}`.",
                parse_mode="Markdown",
                reply_markup=_dashboard_keyboard(current_target),
            )
            return
        if str(target_id) == str(actor_id) and new_role != "developer":
            await query.edit_message_text(
                "⚠️ You cannot change your own role.",
                reply_markup=_dashboard_keyboard(current_target),
            )
            return
        ok = add_whitelist_user(target_id, role=new_role, force=True)
        meta = storage.get_user_meta(target_id) or {}
        label = format_user_label_from_meta(target_id, meta, escape_markdown=True)
        log_system("security", "developer_role_changed", {
            "actor_id": str(actor_id),
            "target_id": str(target_id),
            "role": new_role,
            "ok": bool(ok),
        })
        log_system("admin_audit", "role_changed", {
            "actor_id": str(actor_id),
            "target_id": str(target_id),
            "role": new_role,
            "ok": bool(ok),
        })
        if ok:
            await query.edit_message_text(
                f"✅ Role updated: {label} → `{_md_escape_inline_code(new_role)}`",
                parse_mode="Markdown",
                reply_markup=_dashboard_keyboard(_current_target_id(context)),
            )
        else:
            await query.edit_message_text(
                f"❌ Failed to update {label}.",
                parse_mode="Markdown",
                reply_markup=_dashboard_keyboard(_current_target_id(context)),
            )
        return

    if data == "developer_actas":
        # Backward compatibility for stale callbacks from old messages.
        await show_user_list(update, context, storage, role=role, origin="developer")
        return

    if data == "developer_actas_stop":
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
        await query.edit_message_text(
            _dashboard_text(None),
            parse_mode="Markdown",
            reply_markup=_dashboard_keyboard(None),
        )
        return

    if data.startswith("developer_actas_set:"):
        target_id = data.split(":", 1)[1]
        if str(target_id) == str(actor_id):
            await query.edit_message_text(
                "⚠️ You are already yourself.",
                reply_markup=_dashboard_keyboard(current_target),
            )
            return
        if not storage.is_user_whitelisted(target_id):
            await query.edit_message_text(
                "⚠️ User is no longer whitelisted.",
                reply_markup=_dashboard_keyboard(current_target),
            )
            return
        lock = _get_active_acting_lock(storage, target_id)
        if lock and str(lock.get("by")) != str(actor_id):
            lock_by = lock.get("by") or "unknown"
            started_at = lock.get("started_at") or "unknown"
            expires_at = lock.get("expires_at") or "unknown"
            await query.edit_message_text(
                "⚠️ Another developer is already acting as this user.\n"
                f"By: `{_md_escape_inline_code(lock_by)}`\n"
                f"Started: `{_md_escape_inline_code(started_at)}`\n"
                f"Expires: `{_md_escape_inline_code(expires_at)}`",
                parse_mode="Markdown",
                reply_markup=_dashboard_keyboard(current_target),
            )
            return
        previous_target = _current_target_id(context)
        if previous_target and str(previous_target) != str(target_id):
            _clear_acting_as_lock(storage, previous_target)
        set_acting_as(context, target_id)
        _set_acting_as_lock(storage, target_id, actor_id)
        log_system("security", "developer_acting_as_start", {
            "actor_id": str(actor_id),
            "target_id": str(target_id),
        })
        log_system("admin_audit", "acting_as_start", {
            "actor_id": str(actor_id),
            "target_id": str(target_id),
        })
        payload = build_acting_as_payload(update, context)
        storage.log_user_event(target_id, "developer_acting_as_start", payload)
        meta = storage.get_user_meta(target_id) or {}
        target_label = format_user_label_from_meta(target_id, meta, escape_markdown=True)
        await query.edit_message_text(
            _dashboard_text(target_id, target_label),
            parse_mode="Markdown",
            reply_markup=_dashboard_keyboard(target_id),
        )
        return

    if (
        data.startswith("developer_export")
        or data.startswith("developer_import")
        or data.startswith("developer_rollback")
    ):
        await query.answer("Backup actions moved to /manage → Backups.", show_alert=True)
        try:
            await query.edit_message_text(
                "⚠️ Backup actions moved to /manage → Backups.",
                reply_markup=_back_only_keyboard(),
            )
        except BadRequest as exc:
            if not is_message_not_modified_error(exc):
                raise
        return
