"""Provide whitelist-request list and shortcut rendering helpers for admin flows."""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.security.whitelist_store import list_whitelist_requests
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.shared.runtime_context import get_runtime_storage
from modules.shared.user_identity import format_label_order, format_user_label


def _is_admin_role(role):
    return role in {"admin", "developer"}


def _back_only_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="mgmt_menu")]])


def _find_request_record(user_id):
    if user_id is None:
        return None
    uid = str(user_id)
    for record in list_whitelist_requests():
        if str(record.get("user_id")) == uid:
            return record
    return None


def _requests_text(requests):
    if not requests:
        return "📝 **Pending Requests**\nNo pending requests."
    lines = ["📝 **Pending Requests**"]
    for record in requests[:10]:
        uid = record.get("user_id")
        count = record.get("request_count", 1)
        label = format_user_label(
            uid,
            record.get("username"),
            record.get("display_name"),
            custom_name=record.get("custom_name"),
            label_order=record.get("label_order"),
            escape_markdown=True,
        )
        lines.append(f"• {label} (x{count})")
    if len(requests) > 10:
        lines.append(f"\nShowing 10 of {len(requests)} requests.")
    return "\n".join(lines)


def _build_requests_list(requests):
    if not requests:
        return "📝 **Pending Requests**\nNo pending requests.", {}
    lines = ["📝 **Pending Requests**"]
    alias_map = {}
    for idx, record in enumerate(requests[:20], start=1):
        alias = f"{idx:02d}"
        uid = record.get("user_id")
        identity = format_user_label(
            uid,
            record.get("username"),
            record.get("display_name"),
            custom_name=record.get("custom_name"),
            label_order=record.get("label_order"),
            escape_markdown=True,
        )
        count = record.get("request_count", 1)
        alias_map[alias] = str(uid)
        lines.append(f"/{alias} {identity} (x{count})")
    if len(requests) > 20:
        lines.append(f"\nShowing 20 of {len(requests)} requests.")
    lines.append("\nType a /NN command to review the request.")
    return "\n".join(lines), alias_map


def _request_action_text(record):
    uid = record.get("user_id")
    identity = format_user_label(
        uid,
        record.get("username"),
        record.get("display_name"),
        custom_name=record.get("custom_name"),
        label_order=record.get("label_order"),
        escape_markdown=True,
    )
    count = record.get("request_count", 1)
    first = record.get("first_requested_at")
    last = record.get("last_requested_at")
    lines = [
        "**Whitelist Request**",
        f"User: {identity}",
        f"Requests: `{count}`",
    ]
    request_message = (record.get("request_message") or "").strip()
    if request_message:
        lines.append(f"Message: `{_md_escape(request_message)}`")
    else:
        lines.append("Message: `n/a`")
    custom_name = record.get("custom_name")
    if custom_name:
        lines.append(f"Custom name: `{_md_escape(custom_name)}`")
    label_order = record.get("label_order")
    if label_order:
        lines.append(f"Label order: `{_md_escape(format_label_order(label_order))}`")
    if first:
        lines.append(f"First: `{_md_escape(first)}`")
    if last:
        lines.append(f"Last: `{_md_escape(last)}`")
    return "\n".join(lines)


def _request_action_keyboard(uid):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"admin_req_approve:{uid}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"admin_req_reject:{uid}"),
        ],
        [
            InlineKeyboardButton("✏️ Set Name", callback_data=f"admin_req_set_name:{uid}"),
            InlineKeyboardButton("🔀 Set Label Order", callback_data=f"admin_req_set_order:{uid}"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_requests")],
    ])


async def show_admin_requests_list(query, context):
    """Render pending whitelist requests and store shortcut alias context."""
    requests = list_whitelist_requests()
    text, alias_map = _build_requests_list(requests)
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "admin_requests",
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=_back_only_keyboard(),
    )


async def handle_admin_shortcut_request(update: Update, context: ContextTypes.DEFAULT_TYPE, target_id: str) -> None:
    """Handle admin request shortcut commands and open request actions."""
    storage = get_runtime_storage(context)
    actor_id = update.effective_user.id if update.effective_user else None
    role = storage.get_user_role(actor_id)
    if not _is_admin_role(role):
        await update.message.reply_text("🚫 Unauthorized.")
        return
    record = _find_request_record(target_id)
    if not record:
        await update.message.reply_text("⚠️ Request not found or already resolved.")
        return
    text = _request_action_text(record)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_request_action_keyboard(target_id))
