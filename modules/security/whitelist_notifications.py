import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules.security.authz import get_role_map
from modules.security.whitelist_store import (
    list_whitelist_requests,
    get_whitelist_request_state,
    get_whitelist_request_state_meta,
    update_whitelist_request_state_meta,
    register_whitelist_request_message,
    set_whitelist_request_notified,
    prune_whitelist_request_message_refs,
)
from modules.shared.user_identity import format_user_label

from modules.shared.markdown_utils import md_escape as _md_escape

logger = logging.getLogger(__name__)


def _format_username(username: Any) -> str:
    if not username:
        return "n/a"
    raw = str(username).strip()
    if not raw:
        return "n/a"
    if raw.startswith("@"):
        raw = raw[1:]
    return f"@{_md_escape(raw)}"


def _format_display_name(display_name: Any) -> str:
    if not display_name:
        return "n/a"
    return _md_escape(display_name)


def _format_request_message(request_message: Any) -> str:
    if request_message is None:
        return "n/a"
    text = str(request_message).strip()
    if not text:
        return "n/a"
    return _md_escape(text)


def _format_request_label(record: Dict[str, Any]) -> str:
    return format_user_label(
        record.get("user_id"),
        record.get("username"),
        record.get("display_name"),
        custom_name=record.get("custom_name"),
        label_order=record.get("label_order"),
        escape_markdown=True,
    )


def _request_snapshot(record: Optional[Dict[str, Any]], state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(record, dict):
        return record
    if isinstance(state, dict):
        snapshot = state.get("request")
        if isinstance(snapshot, dict):
            return snapshot
    return {}


def _status_icon(status: str) -> str:
    status = (status or "").lower()
    if status == "approved":
        return "🟢"
    if status == "rejected":
        return "🔴"
    return "🟡"


def build_request_admin_text(
    record: Optional[Dict[str, Any]],
    state: Optional[Dict[str, Any]] = None,
    *,
    status: str = "pending",
) -> str:
    """Build admin-facing Markdown text for one whitelist request state."""
    data = _request_snapshot(record, state)
    uid = data.get("user_id")
    label = _format_request_label(data) if data else _md_escape(uid) or "n/a"
    username = _format_username(data.get("username")) if data else "n/a"
    display_name = _format_display_name(data.get("display_name")) if data else "n/a"
    request_message = _format_request_message(data.get("request_message")) if data else "n/a"
    count = data.get("request_count", 1)
    first_ts = data.get("first_requested_at")
    last_ts = data.get("last_requested_at")

    lines = [
        "Whitelist Request",
        f"Status: {_status_icon(status)} {_md_escape(status.capitalize())}",
        f"User: {label}",
        f"Username: {username}",
        f"Full name: {display_name}",
        f"Message: `{request_message}`",
        f"User ID: `{_md_escape(uid)}`" if uid else "User ID: n/a",
        f"Requests: `{count}`",
    ]

    if first_ts:
        lines.append(f"First request: `{_md_escape(first_ts)}`")
    if last_ts:
        lines.append(f"Last request: `{_md_escape(last_ts)}`")

    if isinstance(state, dict) and state.get("resolved_at"):
        resolved_by = state.get("resolved_by_label")
        resolved_role = state.get("resolved_role")
        resolved_at = state.get("resolved_at")
        if resolved_by:
            if resolved_role:
                lines.append(f"Resolved by: {_md_escape(resolved_by)} (`{_md_escape(resolved_role)}`)")
            else:
                lines.append(f"Resolved by: {_md_escape(resolved_by)}")
        if resolved_at:
            lines.append(f"Resolved at: `{_md_escape(resolved_at)}`")

    return "\n".join(lines)


def build_request_action_keyboard(user_id: Any) -> InlineKeyboardMarkup:
    """Build admin action buttons for approving or editing a request."""
    uid = str(user_id)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve", callback_data=f"admin_req_approve:{uid}"),
            InlineKeyboardButton("Reject", callback_data=f"admin_req_reject:{uid}"),
        ],
        [
            InlineKeyboardButton("Set Name", callback_data=f"admin_req_set_name:{uid}"),
            InlineKeyboardButton("Set Label Order", callback_data=f"admin_req_set_order:{uid}"),
        ],
    ])


def _admin_and_developer_ids(storage) -> List[str]:
    role_map = get_role_map(admin_id=getattr(storage, "admin_id", None))
    ids = []
    for uid, role in role_map.items():
        if role in {"admin", "developer"}:
            ids.append(str(uid))
    return sorted(set(ids))


async def notify_admins_for_request(bot, storage, record: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send whitelist-request notifications to all admin/developer recipients."""
    admin_ids = _admin_and_developer_ids(storage)
    if not admin_ids:
        return {"sent": 0, "skipped": 0}

    text = build_request_admin_text(record, state, status="pending")
    keyboard = build_request_action_keyboard(record.get("user_id"))
    sent = 0
    skipped = 0

    for admin_id in admin_ids:
        try:
            msg = await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            message_id = getattr(msg, "message_id", None)
            if message_id is not None:
                register_whitelist_request_message(
                    user_id=record.get("user_id"),
                    chat_id=admin_id,
                    message_id=message_id,
                )
            sent += 1
        except Exception as exc:
            skipped += 1
            logger.warning("whitelist_request_notify_failed admin_id=%s error=%s", admin_id, exc)

    if sent > 0:
        set_whitelist_request_notified(record.get("user_id"))

    return {"sent": sent, "skipped": skipped}


async def update_request_messages(
    bot,
    user_id: Any,
    text: str,
    *,
    reply_markup=None,
) -> Dict[str, Any]:
    """Edit stored request notifications, optionally preserving pending action buttons.

    Use `reply_markup` only for pending-card refreshes that must keep the action
    keyboard attached. Leave it omitted for resolved-state updates so old pending
    buttons are removed.
    """
    state = get_whitelist_request_state(user_id)
    refs = []
    if isinstance(state, dict):
        refs = state.get("message_refs") or []
    updated = 0
    kept = []

    for ref in refs:
        try:
            edit_kwargs: Dict[str, Any] = {
                "text": text,
                "parse_mode": "Markdown",
            }
            if reply_markup is not None:
                edit_kwargs["reply_markup"] = reply_markup
            await bot.edit_message_text(
                chat_id=ref.get("chat_id"),
                message_id=ref.get("message_id"),
                **edit_kwargs,
            )
            kept.append(ref)
            updated += 1
        except Exception as exc:
            error_text = str(exc).lower()
            if "message is not modified" in error_text:
                kept.append(ref)
                updated += 1
                continue
            logger.warning("whitelist_request_message_edit_failed ref=%s error=%s", ref, exc)

    if refs:
        prune_whitelist_request_message_refs(user_id, kept)

    return {"updated": updated, "failed": max(0, len(refs) - updated)}


def _build_pending_digest_text(requests: List[Dict[str, Any]], limit: int = 10) -> str:
    total = len(requests)
    lines = [f"Pending whitelist requests: `{total}`"]
    for record in requests[:limit]:
        label = _format_request_label(record)
        count = record.get("request_count", 1)
        last_ts = record.get("last_requested_at")
        if last_ts:
            lines.append(f"- {label} (x{count}) last: `{_md_escape(last_ts)}`")
        else:
            lines.append(f"- {label} (x{count})")
    if total > limit:
        lines.append(f"Showing {limit} of {total} pending requests.")
    return "\n".join(lines)


async def send_pending_requests_digest(bot, storage) -> Dict[str, Any]:
    """Send one daily digest of pending whitelist requests to privileged users."""
    pending = list_whitelist_requests()
    if not pending:
        return {"sent": 0, "reason": "no_pending"}

    meta = get_whitelist_request_state_meta()
    today = datetime.now().date().isoformat()
    if meta.get("daily_pending_notified_date") == today:
        return {"sent": 0, "reason": "already_notified"}

    admin_ids = _admin_and_developer_ids(storage)
    if not admin_ids:
        return {"sent": 0, "reason": "no_admins"}

    text = _build_pending_digest_text(pending, limit=10)
    sent = 0
    skipped = 0
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
            sent += 1
        except Exception as exc:
            skipped += 1
            logger.warning("whitelist_pending_digest_failed admin_id=%s error=%s", admin_id, exc)

    if sent > 0:
        update_whitelist_request_state_meta({
            "daily_pending_notified_date": today,
            "daily_pending_last_sent_at": datetime.now().isoformat(),
            "daily_pending_count": len(pending),
        })

    return {"sent": sent, "skipped": skipped}
