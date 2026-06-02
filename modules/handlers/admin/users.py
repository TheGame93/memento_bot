"""Provide user-detail and user-management helpers for admin flows."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from modules.handlers.user_list import (
    build_user_detail_keyboard,
    build_users_text,
    is_message_not_modified_error,
    log_user_detail_render,
    resolve_user_detail_back_cb,
    summarize_user_data,
)
from modules.security.whitelist_store import remove_whitelist_user
from modules.shared.context_cleanup import clear_transient_context
from modules.shared.runtime_context import (
    get_runtime_api_failure_tracker,
    get_runtime_storage,
)
from modules.shared.user_identity import format_user_label_from_meta
from modules.shared.user_status import build_user_status_message
from modules.shared.whitelist_users import build_whitelist_users_empty_text
from modules.systemlog import log_system

ADMIN_USER_SET_NAME_PROMPT = "Send the custom name for this user"

LABEL_ORDER_PRESETS = [
    ("Custom > Username > Full Name > ID", ["custom_name", "username", "display_name", "user_id"]),
    ("Username > Custom > Full Name > ID", ["username", "custom_name", "display_name", "user_id"]),
    ("Full Name > Custom > Username > ID", ["display_name", "custom_name", "username", "user_id"]),
    ("Username > Full Name > Custom > ID", ["username", "display_name", "custom_name", "user_id"]),
]


def _is_admin_role(role):
    return role in {"admin", "developer"}


def _back_only_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="mgmt_menu")]])


def _label_from_meta(user_id, meta):
    meta = meta or {}
    return format_user_label_from_meta(user_id, meta, escape_markdown=True)


def _summarize_user_data(data):
    return summarize_user_data(data)


def _build_users_list(entries, user_meta_map, summary_map=None):
    return build_users_text(
        entries,
        user_meta_map,
        summary_map,
        include_alias=True,
        empty_text=build_whitelist_users_empty_text(),
    )


def _is_self_removal(actor_id, target_id) -> bool:
    if actor_id is None or target_id is None:
        return False
    return str(actor_id) == str(target_id)


def _is_target_whitelisted(storage, target_id) -> bool:
    try:
        return bool(storage.is_user_whitelisted(target_id))
    except Exception:
        return False


def _removal_result_text(target_id, removed: bool) -> str:
    return _removal_result_text_with_label(target_id, removed, None)


def _removal_result_text_with_label(target_id, removed: bool, label: str | None) -> str:
    display = label or str(target_id)
    if removed:
        return f"🗑️ Removed {display} from whitelist."
    return f"⚠️ {display} is already removed or missing."


def _admin_user_set_name_keyboard(target_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Clear Name", callback_data=f"admin_user_clear_name:{target_id}")],
        [InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="mgmt_menu")],
    ])


def _label_order_keyboard(kind, target_id):
    rows = []
    for idx, preset in enumerate(LABEL_ORDER_PRESETS, start=1):
        label = preset[0]
        rows.append([InlineKeyboardButton(label, callback_data=f"admin_label_order:{kind}:{target_id}:{idx}")])
    back_cb = "admin_requests" if kind == "req" else f"admin_user:{target_id}"
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def _user_status_keyboard(uid, target_role=None, *, actor_role=None, actor_id=None, back_cb=None):
    actor_role = actor_role or "admin"
    back_cb = back_cb or "admin_list"
    return build_user_detail_keyboard(
        actor_role=actor_role,
        target_role=target_role,
        target_id=uid,
        actor_id=actor_id,
        back_cb=back_cb,
    )


def _build_user_status(storage, user_id, *, viewer_role=None, api_failure_tracker=None):
    return build_user_status_message(
        storage,
        user_id,
        viewer_role=viewer_role,
        api_failure_tracker=api_failure_tracker,
    )


async def _handle_admin_user_detail_callback(query, context, storage, *, actor_id, role, target_id):
    if not _is_target_whitelisted(storage, target_id):
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=None,
            source="admin_users",
            delivery="callback_edit",
            text=None,
            ok=False,
            reason="target_missing",
        )
        await query.edit_message_text(
            "⚠️ User not found or no longer whitelisted.",
            reply_markup=_back_only_keyboard(),
        )
        return

    target_role = storage.get_user_role(target_id)
    status_text = _build_user_status(
        storage,
        target_id,
        viewer_role=role,
        api_failure_tracker=get_runtime_api_failure_tracker(context),
    )
    keyboard = _user_status_keyboard(
        target_id,
        target_role=target_role,
        actor_role=role,
        actor_id=actor_id,
        back_cb=resolve_user_detail_back_cb(context, role),
    )
    try:
        await query.edit_message_text(status_text, parse_mode="Markdown", reply_markup=keyboard)
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=target_role,
            source="admin_users",
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
                source="admin_users",
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
            source="admin_users",
            delivery="callback_edit",
            text=status_text,
            ok=False,
            reason="bad_request",
        )
        raise


async def _handle_admin_user_set_name_callback(query, context, storage, *, target_id):
    if not _is_target_whitelisted(storage, target_id):
        await query.edit_message_text(
            "⚠️ User not found or no longer whitelisted.",
            reply_markup=_back_only_keyboard(),
        )
        return
    context.user_data["expecting_admin_custom_name"] = True
    context.user_data["admin_custom_name_target_id"] = str(target_id)
    context.user_data["admin_custom_name_target_kind"] = "user"
    await query.edit_message_text(
        ADMIN_USER_SET_NAME_PROMPT,
        parse_mode="Markdown",
        reply_markup=_admin_user_set_name_keyboard(target_id),
    )


async def _handle_admin_user_clear_name_callback(query, context, storage, *, actor_id, role, target_id):
    if not _is_target_whitelisted(storage, target_id):
        await query.edit_message_text(
            "⚠️ User not found or no longer whitelisted.",
            reply_markup=_back_only_keyboard(),
        )
        return
    storage.update_user_meta(target_id, {"custom_name": None})
    context.user_data.pop("expecting_admin_custom_name", None)
    context.user_data.pop("admin_custom_name_target_id", None)
    context.user_data.pop("admin_custom_name_target_kind", None)
    log_system("admin_audit", "custom_name_cleared", {
        "actor_id": str(actor_id),
        "target_id": str(target_id),
    })
    log_system("security", "admin_custom_name_cleared", {
        "actor_id": str(actor_id),
        "target_id": str(target_id),
    })
    storage.log_user_event(target_id, "custom_name_cleared", {
        "actor_id": str(actor_id),
        "actor_role": role,
    })
    await _handle_admin_user_detail_callback(
        query,
        context,
        storage,
        actor_id=actor_id,
        role=role,
        target_id=target_id,
    )


async def _handle_admin_user_set_order_callback(query, storage, *, target_id):
    if not _is_target_whitelisted(storage, target_id):
        await query.edit_message_text(
            "⚠️ User not found or no longer whitelisted.",
            reply_markup=_back_only_keyboard(),
        )
        return
    await query.edit_message_text(
        "🔀 **Label Order**\nChoose the label fallback order:",
        parse_mode="Markdown",
        reply_markup=_label_order_keyboard("user", target_id),
    )


async def _handle_admin_remove_callback(query, storage, *, target_id):
    if not _is_target_whitelisted(storage, target_id):
        await query.edit_message_text(
            "⚠️ User is already removed or missing.",
            reply_markup=_back_only_keyboard(),
        )
        return
    target_role = storage.get_user_role(target_id)
    if _is_admin_role(target_role):
        await query.edit_message_text(
            "🚫 Admins and developers cannot be removed from the admin dashboard.",
            parse_mode="Markdown",
            reply_markup=_back_only_keyboard(),
        )
        return
    meta = storage.get_user_meta(target_id) or {}
    label = _label_from_meta(target_id, meta)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"admin_remove_confirm:{target_id}")],
        [InlineKeyboardButton("⬅️ Cancel", callback_data=f"admin_user:{target_id}")],
    ])
    await query.edit_message_text(
        f"⚠️ Remove {label} from whitelist?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _handle_admin_remove_confirm_callback(query, storage, *, actor_id, target_id):
    if _is_self_removal(actor_id, target_id):
        await query.edit_message_text(
            "🚫 You can't remove yourself from the whitelist.",
            parse_mode="Markdown",
            reply_markup=_back_only_keyboard(),
        )
        return
    target_role = storage.get_user_role(target_id)
    if _is_admin_role(target_role):
        await query.edit_message_text(
            "🚫 Admins and developers cannot be removed from the admin dashboard.",
            parse_mode="Markdown",
            reply_markup=_back_only_keyboard(),
        )
        return

    removed = remove_whitelist_user(target_id)
    meta = storage.get_user_meta(target_id) or {}
    label = _label_from_meta(target_id, meta)
    log_system("security", "admin_whitelist_removed", {
        "admin_id": str(actor_id),
        "target_id": str(target_id),
        "removed": bool(removed),
    })
    log_system("admin_audit", "whitelist_removed", {
        "admin_id": str(actor_id),
        "target_id": str(target_id),
        "removed": bool(removed),
    })
    await query.edit_message_text(
        _removal_result_text_with_label(target_id, removed, label),
        parse_mode="Markdown",
        reply_markup=_back_only_keyboard(),
    )


async def start_admin_add_user(query, context):
    """Start admin add-user capture flow and arm transient input state."""
    clear_transient_context(context.user_data, include_navigation=True)
    context.user_data["expecting_admin_add_user"] = True
    await query.edit_message_text(
        "➕ **Add user**\nSend an @username or forward a message from the user.\n"
        "Use /cancel to stop.",
        parse_mode="Markdown",
        reply_markup=_back_only_keyboard(),
    )


async def handle_admin_shortcut_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: str) -> None:
    """Handle admin user shortcut commands and render user detail cards."""
    storage = get_runtime_storage(context)
    api_failure_tracker = get_runtime_api_failure_tracker(context)
    actor_id = update.effective_user.id if update.effective_user else None
    role = storage.get_user_role(actor_id)
    target = update.effective_message or update.message
    if not _is_admin_role(role):
        if target:
            await target.reply_text("🚫 Unauthorized.")
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=None,
            source="admin_users",
            delivery="shortcut_reply",
            text=None,
            ok=False,
            reason="unauthorized",
        )
        return
    if not _is_target_whitelisted(storage, target_id):
        if target:
            await target.reply_text("⚠️ User not found or no longer whitelisted.")
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=None,
            source="admin_users",
            delivery="shortcut_reply",
            text=None,
            ok=False,
            reason="target_missing",
        )
        return
    target_role = storage.get_user_role(target_id)
    status_text = _build_user_status(
        storage,
        target_id,
        viewer_role=role,
        api_failure_tracker=api_failure_tracker,
    )
    back_cb = resolve_user_detail_back_cb(context, role)
    if not target:
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=target_role,
            source="admin_users",
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
            reply_markup=_user_status_keyboard(
                target_id,
                target_role=target_role,
                actor_role=role,
                actor_id=actor_id,
                back_cb=back_cb,
            ),
        )
        log_user_detail_render(
            storage,
            actor_id=actor_id,
            actor_role=role,
            target_id=target_id,
            target_role=target_role,
            source="admin_users",
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
                source="admin_users",
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
            source="admin_users",
            delivery="shortcut_reply",
            text=status_text,
            ok=False,
            reason="bad_request",
        )
        raise
