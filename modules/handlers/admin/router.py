"""Route admin dashboard callbacks across request, invite, and user actions."""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules.handlers.user_list import show_user_list
from modules.security.whitelist_notifications import (
    build_request_admin_text,
    update_request_messages,
)
from modules.security.whitelist_store import (
    add_whitelist_user,
    resolve_whitelist_request,
    update_whitelist_request,
)
from modules.shared.context_cleanup import clear_transient_context
from modules.shared.runtime_context import get_runtime_storage
from modules.shared.user_identity import format_user_label_from_meta
from modules.systemlog import log_system

from .invites import (
    _find_invite_by_token,
    _invite_detail_keyboard,
    _invite_detail_text,
    _invite_identity_label,
    _invite_revoke_confirm_keyboard,
    _invite_token_from_record,
    _remove_invite_record,
    show_admin_invites_list,
)
from .requests import (
    _find_request_record,
    _request_action_keyboard,
    _request_action_text,
    show_admin_requests_list,
)
from .users import (
    LABEL_ORDER_PRESETS,
    _handle_admin_remove_callback,
    _handle_admin_remove_confirm_callback,
    _handle_admin_user_clear_name_callback,
    _handle_admin_user_detail_callback,
    _handle_admin_user_set_name_callback,
    _handle_admin_user_set_order_callback,
    _is_target_whitelisted,
    _label_order_keyboard,
    start_admin_add_user,
)


def _is_admin_role(role) -> bool:
    """Return whether a role has access to the admin dashboard callbacks."""
    return role in {"admin", "developer"}


def _back_only_keyboard() -> InlineKeyboardMarkup:
    """Build a one-button keyboard that routes back to the management dashboard."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="mgmt_menu")]])


def _build_meta_updates(admin_id, current_meta, *, username=None, display_name=None):
    """Build whitelist-meta updates for approved requests while preserving existing fields."""
    now_iso = datetime.now().isoformat()
    meta = current_meta or {}
    updates = {}
    if not meta.get("added_at"):
        updates["added_at"] = now_iso
    if not meta.get("added_by"):
        updates["added_by"] = str(admin_id)
    if not meta.get("added_via"):
        updates["added_via"] = "admin_dashboard"
    if username:
        updates["username"] = username
    if display_name:
        updates["display_name"] = display_name
    return updates


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route admin dashboard callbacks for requests, invites, and user operations."""
    storage = get_runtime_storage(context)
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_id = update.effective_user.id
    role = storage.get_user_role(user_id)
    if not _is_admin_role(role):
        await query.edit_message_text("🚫 Unauthorized.")
        return

    data = query.data or ""
    if data == "admin_menu":
        clear_transient_context(context.user_data, include_navigation=True)
        from modules.handlers.manage import _send_manage_dashboard

        await _send_manage_dashboard(update, context, storage, role=role, source="callback")
        return

    if data == "admin_add_user":
        await start_admin_add_user(query, context)
        return

    if data == "admin_requests":
        await show_admin_requests_list(query, context)
        return

    if data == "admin_invites":
        await show_admin_invites_list(query, context, storage, user_id)
        return

    if data == "admin_list":
        await show_user_list(update, context, storage, role=role, origin="admin")
        return

    if data.startswith("admin_invite_revoke_confirm:"):
        token = data.split(":", 1)[1]
        record = _find_invite_by_token(token)
        if not record:
            await query.edit_message_text(
                "⚠️ Invite not found or already resolved.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return
        removed = _remove_invite_record(record)
        target_token = _invite_token_from_record(record) or token
        log_system(
            "security",
            "admin_invite_revoked",
            {
                "actor_id": str(user_id),
                "invite_token": target_token,
                "removed": bool(removed),
            },
        )
        log_system(
            "admin_audit",
            "invite_revoked",
            {
                "actor_id": str(user_id),
                "invite_token": target_token,
                "removed": bool(removed),
            },
        )
        if removed:
            await query.edit_message_text(
                "🗑️ Invite revoked.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
        else:
            await query.edit_message_text(
                "⚠️ Invite already removed or missing.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
        return

    if data.startswith("admin_invite_revoke:"):
        token = data.split(":", 1)[1]
        record = _find_invite_by_token(token)
        if not record:
            await query.edit_message_text(
                "⚠️ Invite not found or already resolved.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return
        label = _invite_identity_label(record, escape_markdown=True)
        await query.edit_message_text(
            f"⚠️ Revoke pending invite for {label}?",
            parse_mode="Markdown",
            reply_markup=_invite_revoke_confirm_keyboard(token),
        )
        return

    if data.startswith("admin_invite:"):
        token = data.split(":", 1)[1]
        record = _find_invite_by_token(token)
        if not record:
            await query.edit_message_text(
                "⚠️ Invite not found or already resolved.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return
        await query.edit_message_text(
            _invite_detail_text(record, storage=storage),
            parse_mode="Markdown",
            reply_markup=_invite_detail_keyboard(token),
        )
        return

    if data.startswith("admin_req_approve:"):
        target_id = data.split(":", 1)[1]
        actor_meta = storage.get_user_meta(user_id) or {}
        actor_label = format_user_label_from_meta(user_id, actor_meta, escape_markdown=True)
        result = resolve_whitelist_request(
            target_id,
            action="approved",
            actor_id=user_id,
            actor_role=role,
            actor_label=actor_label,
        )
        status = result.get("status")
        record = result.get("record")
        state = result.get("state") or {}

        if status in {"not_found", "invalid"}:
            await query.edit_message_text(
                "Request not found or already resolved.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return

        if status == "already_resolved":
            text = build_request_admin_text(record, state, status=state.get("status", "resolved"))
            try:
                await update_request_messages(context.bot, target_id, text)
            except Exception:
                pass
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_back_only_keyboard())
            return

        ok = add_whitelist_user(target_id, role="user")
        if ok:
            storage.setup_user_space(target_id)
            current_meta = storage.get_user_meta(target_id) or {}
            updates = _build_meta_updates(
                user_id,
                current_meta,
                username=(record or {}).get("username"),
                display_name=(record or {}).get("display_name"),
            )
            custom_name = (record or {}).get("custom_name")
            label_order = (record or {}).get("label_order")
            if custom_name:
                updates["custom_name"] = custom_name
            if label_order:
                updates["label_order"] = label_order
            if updates:
                storage.update_user_meta(target_id, updates)

        log_system(
            "security",
            "admin_request_approved",
            {
                "admin_id": str(user_id),
                "target_id": str(target_id),
                "ok": bool(ok),
                "status": status,
            },
        )
        log_system(
            "admin_audit",
            "request_approved",
            {
                "admin_id": str(user_id),
                "target_id": str(target_id),
                "ok": bool(ok),
                "status": status,
            },
        )

        text = build_request_admin_text(record, state, status="approved")
        try:
            await update_request_messages(context.bot, target_id, text)
        except Exception:
            pass

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="Your access request has been approved. Use /help to get started.",
            )
        except Exception:
            pass

        if ok:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_back_only_keyboard())
        else:
            await query.edit_message_text(
                "Approval recorded, but whitelist update failed. Check storage/logs.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
        return

    if data.startswith("admin_req_reject:"):
        target_id = data.split(":", 1)[1]
        actor_meta = storage.get_user_meta(user_id) or {}
        actor_label = format_user_label_from_meta(user_id, actor_meta, escape_markdown=True)
        result = resolve_whitelist_request(
            target_id,
            action="rejected",
            actor_id=user_id,
            actor_role=role,
            actor_label=actor_label,
        )
        status = result.get("status")
        record = result.get("record")
        state = result.get("state") or {}

        if status in {"not_found", "invalid"}:
            await query.edit_message_text(
                "Request not found or already resolved.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return

        if status == "already_resolved":
            text = build_request_admin_text(record, state, status=state.get("status", "resolved"))
            try:
                await update_request_messages(context.bot, target_id, text)
            except Exception:
                pass
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_back_only_keyboard())
            return

        log_system(
            "security",
            "admin_request_rejected",
            {
                "admin_id": str(user_id),
                "target_id": str(target_id),
                "status": status,
            },
        )
        log_system(
            "admin_audit",
            "request_rejected",
            {
                "admin_id": str(user_id),
                "target_id": str(target_id),
                "status": status,
            },
        )

        text = build_request_admin_text(record, state, status="rejected")
        try:
            await update_request_messages(context.bot, target_id, text)
        except Exception:
            pass

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="Your access request has been rejected.",
            )
        except Exception:
            pass

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_back_only_keyboard())
        return

    if data.startswith("admin_req_set_name:"):
        target_id = data.split(":", 1)[1]
        request_record = _find_request_record(target_id)
        if not request_record:
            await query.edit_message_text(
                "⚠️ Request already resolved.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return
        context.user_data["expecting_admin_custom_name"] = True
        context.user_data["admin_custom_name_target_id"] = str(target_id)
        context.user_data["admin_custom_name_target_kind"] = "req"
        await query.edit_message_text(
            "✏️ **Custom Name**\nSend the custom name for this request.\n"
            "Send `-` to clear or /cancel to stop.",
            parse_mode="Markdown",
            reply_markup=_back_only_keyboard(),
        )
        return

    if data.startswith("admin_user_set_name:"):
        target_id = data.split(":", 1)[1]
        await _handle_admin_user_set_name_callback(query, context, storage, target_id=target_id)
        return

    if data.startswith("admin_user_clear_name:"):
        target_id = data.split(":", 1)[1]
        await _handle_admin_user_clear_name_callback(
            query,
            context,
            storage,
            actor_id=user_id,
            role=role,
            target_id=target_id,
        )
        return

    if data.startswith("admin_req_set_order:"):
        target_id = data.split(":", 1)[1]
        request_record = _find_request_record(target_id)
        if not request_record:
            await query.edit_message_text(
                "⚠️ Request already resolved.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return
        await query.edit_message_text(
            "🔀 **Label Order**\nChoose the label fallback order:",
            parse_mode="Markdown",
            reply_markup=_label_order_keyboard("req", target_id),
        )
        return

    if data.startswith("admin_user_set_order:"):
        target_id = data.split(":", 1)[1]
        await _handle_admin_user_set_order_callback(query, storage, target_id=target_id)
        return

    if data.startswith("admin_label_order:"):
        _, kind, target_id, idx_text = data.split(":", 3)
        try:
            idx = int(idx_text)
        except Exception:
            await query.edit_message_text(
                "⚠️ Invalid label order selection.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return
        if idx < 1 or idx > len(LABEL_ORDER_PRESETS):
            await query.edit_message_text(
                "⚠️ Invalid label order selection.",
                parse_mode="Markdown",
                reply_markup=_back_only_keyboard(),
            )
            return
        order = LABEL_ORDER_PRESETS[idx - 1][1]
        if kind == "req":
            ok = update_whitelist_request(target_id, label_order=order)
            record = _find_request_record(target_id)
            if not ok or not record:
                await query.edit_message_text(
                    "⚠️ Request already resolved.",
                    parse_mode="Markdown",
                    reply_markup=_back_only_keyboard(),
                )
                return
            text = _request_action_text(record)
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=_request_action_keyboard(target_id),
            )
            return
        if kind == "user":
            if not _is_target_whitelisted(storage, target_id):
                await query.edit_message_text(
                    "⚠️ User not found or no longer whitelisted.",
                    reply_markup=_back_only_keyboard(),
                )
                return
            storage.update_user_meta(target_id, {"label_order": order})
            await _handle_admin_user_detail_callback(
                query,
                context,
                storage,
                actor_id=user_id,
                role=role,
                target_id=target_id,
            )
            return

    if data.startswith("admin_user:"):
        target_id = data.split(":", 1)[1]
        await _handle_admin_user_detail_callback(
            query,
            context,
            storage,
            actor_id=user_id,
            role=role,
            target_id=target_id,
        )
        return

    if data.startswith("admin_remove:"):
        target_id = data.split(":", 1)[1]
        await _handle_admin_remove_callback(query, storage, target_id=target_id)
        return

    if data.startswith("admin_remove_confirm:"):
        target_id = data.split(":", 1)[1]
        await _handle_admin_remove_confirm_callback(query, storage, actor_id=user_id, target_id=target_id)
        return
