"""Provide whitelist-invite list and shortcut rendering helpers for admin flows."""

from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.security.whitelist_store import (
    find_whitelist_invite,
    list_whitelist_invites,
    remove_whitelist_invite,
)
from modules.shared.markdown_utils import md_escape as _md_escape
from modules.shared.runtime_context import get_runtime_storage
from modules.shared.user_identity import format_user_label, format_user_label_from_meta
from modules.systemlog import log_system


def _is_admin_role(role):
    return role in {"admin", "developer"}


def _back_only_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="mgmt_menu")]])


def _normalize_invite_username(value):
    text = (str(value).strip() if value is not None else "")
    if text.startswith("@"):
        text = text[1:]
    return text.lower()


def _invite_token_from_record(record):
    if not isinstance(record, dict):
        return None
    uid_raw = record.get("user_id")
    if uid_raw is not None:
        uid = str(uid_raw).strip()
        if uid and uid.lstrip("-").isdigit() and len(uid) <= 32:
            return f"id:{uid}"
    uname = _normalize_invite_username(record.get("username"))
    if uname and len(uname) <= 32:
        return f"u:{uname}"
    return None


def _callback_data_safe(text):
    if not isinstance(text, str):
        return False
    return len(text.encode("utf-8")) <= 64


def _invite_identity_label(record, *, escape_markdown=True):
    record = record or {}
    uid = record.get("user_id")
    uname = record.get("username")
    dname = record.get("display_name")
    return format_user_label(uid, uname, dname, escape_markdown=escape_markdown)


def _resolve_inviter_label(invited_by, storage=None, *, escape_markdown=True):
    invited_by_text = str(invited_by).strip() if invited_by is not None else ""
    if not invited_by_text:
        return "n/a"
    meta = {}
    if storage is not None:
        candidates = [invited_by]
        if invited_by_text not in candidates:
            candidates.append(invited_by_text)
        if invited_by_text.lstrip("-").isdigit():
            try:
                candidates.append(int(invited_by_text))
            except Exception:
                pass
        for candidate in candidates:
            try:
                found = storage.get_user_meta(candidate) or {}
            except Exception:
                found = {}
            if isinstance(found, dict) and found:
                meta = found
                break
    return format_user_label_from_meta(invited_by_text, meta, escape_markdown=escape_markdown)


def _build_invite_message(username=None, display_name=None, bot_username=None):
    uname = (username or "").strip()
    if uname and not uname.startswith("@"):
        uname = f"@{uname}"
    target_label = uname or (display_name or "").strip() or "there"
    bot_label = f"@{bot_username}" if bot_username else "this bot"
    return (
        f"Hi {target_label}, you are pre-approved to access {bot_label}. "
        "Press /start to run the bot and then /help to learn how to use it."
    )


def _build_invites_list(invites, storage=None):
    invites = [r for r in (invites or []) if isinstance(r, dict)]
    if not invites:
        return "📨 **Pending Invites**\nNo pending invites.", {}

    safe_records = []
    skipped = 0
    for record in invites:
        token = _invite_token_from_record(record)
        if not token:
            skipped += 1
            continue
        if not _callback_data_safe(f"admin_invite_revoke_confirm:{token}"):
            skipped += 1
            continue
        safe_records.append((record, token))

    if not safe_records:
        return "📨 **Pending Invites**\nNo valid pending invites.", {}

    safe_records.sort(
        key=lambda item: (
            str(item[0].get("invited_at") or ""),
            str(item[0].get("user_id") or ""),
            str(item[0].get("username") or ""),
        ),
        reverse=True,
    )

    lines = ["📨 **Pending Invites**"]
    alias_map = {}
    for idx, (record, token) in enumerate(safe_records[:20], start=1):
        alias = f"{idx:02d}"
        alias_map[alias] = token
        label = _invite_identity_label(record, escape_markdown=True)
        invited_by = str(record.get("invited_by") or "n/a")
        inviter_label = _resolve_inviter_label(invited_by, storage=storage, escape_markdown=True)
        invited_at = str(record.get("invited_at") or "n/a")
        lines.append(f"/{alias} {label}")
        lines.append(f"    by {inviter_label} at `{_md_escape(invited_at)}`")

    if len(safe_records) > 20:
        lines.append(f"\nShowing 20 of {len(safe_records)} invites.")
    if skipped:
        lines.append(f"Skipped malformed/oversized invite records: `{skipped}`")
    lines.append("\nType a /NN command to review the invite.")
    return "\n".join(lines), alias_map


def _find_invite_by_token(token):
    """Resolve an invite record from a compact token using package-level store lookups."""
    if not isinstance(token, str) or ":" not in token:
        return None
    kind, value = token.split(":", 1)
    value = str(value).strip()
    if not value:
        return None
    if kind == "id":
        return find_whitelist_invite(user_id=value)
    if kind == "u":
        return find_whitelist_invite(username=_normalize_invite_username(value))
    return None


def _invite_detail_text(record, storage=None):
    if not isinstance(record, dict):
        return "⚠️ Invite not found or already resolved."
    uid = str(record.get("user_id") or "n/a")
    uname = _normalize_invite_username(record.get("username"))
    uname_display = f"@{uname}" if uname else "n/a"
    dname = str(record.get("display_name") or "n/a")
    invited_by = str(record.get("invited_by") or "n/a")
    invited_by_label = _resolve_inviter_label(invited_by, storage=storage, escape_markdown=True)
    invited_at = str(record.get("invited_at") or "n/a")
    label = _invite_identity_label(record, escape_markdown=True)
    lines = [
        "📨 **Pending Invite**",
        f"Identity: {label}",
        f"User ID: `{_md_escape(uid)}`",
        f"Username: `{_md_escape(uname_display)}`",
        f"Display name: `{_md_escape(dname)}`",
        f"Invited by: {invited_by_label}",
        f"Invited at: `{_md_escape(invited_at)}`",
    ]
    return "\n".join(lines)


def _invite_detail_keyboard(token):
    rows = []
    cb = f"admin_invite_revoke:{token}"
    if _callback_data_safe(cb):
        rows.append([InlineKeyboardButton("🗑️ Revoke Invite", callback_data=cb)])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_invites")])
    return InlineKeyboardMarkup(rows)


def _invite_revoke_confirm_keyboard(token):
    rows = []
    cb = f"admin_invite_revoke_confirm:{token}"
    if _callback_data_safe(cb):
        rows.append([InlineKeyboardButton("✅ Confirm Revoke", callback_data=cb)])
    rows.append([InlineKeyboardButton("⬅️ Cancel", callback_data=f"admin_invite:{token}")])
    return InlineKeyboardMarkup(rows)


def _remove_invite_record(record):
    """Remove a pending invite by user-id first, falling back to username token."""
    if not isinstance(record, dict):
        return False
    uid = record.get("user_id")
    if uid is not None and str(uid).strip():
        return remove_whitelist_invite(user_id=uid)
    uname = _normalize_invite_username(record.get("username"))
    if uname:
        return remove_whitelist_invite(username=uname)
    return False


def _prune_stale_id_invites(storage, actor_id):
    """Delete stale id-based invites that now point to already whitelisted users."""
    invites = list_whitelist_invites()
    pruned = []
    malformed = 0
    for record in invites:
        if not isinstance(record, dict):
            malformed += 1
            continue
        token = _invite_token_from_record(record)
        if not token:
            malformed += 1
            continue
        if not token.startswith("id:"):
            continue
        uid = token.split(":", 1)[1]
        try:
            is_whitelisted = bool(storage.is_user_whitelisted(uid))
        except Exception:
            is_whitelisted = False
        if not is_whitelisted:
            continue
        removed = remove_whitelist_invite(user_id=uid)
        pruned.append({"user_id": uid, "removed": bool(removed)})

    if malformed:
        log_system("errors", "admin_invites_malformed_skipped", {
            "actor_id": str(actor_id) if actor_id is not None else None,
            "count": malformed,
        }, level="WARNING")
    if pruned:
        log_system("security", "admin_invites_stale_pruned", {
            "actor_id": str(actor_id) if actor_id is not None else None,
            "count": len(pruned),
            "sample": pruned[:5],
        })
        log_system("admin_audit", "invites_stale_pruned", {
            "actor_id": str(actor_id) if actor_id is not None else None,
            "count": len(pruned),
        })
    return len(pruned)


async def show_admin_invites_list(query, context, storage, actor_id=None):
    """Render pending invite entries after pruning stale id-based invites."""
    _prune_stale_id_invites(storage, actor_id)
    invites = list_whitelist_invites()
    text, alias_map = _build_invites_list(invites, storage=storage)
    context.user_data[LIST_CONTEXT_KEY] = {
        "source": "admin_invites",
        "alias_map": alias_map,
        "saved_at": datetime.now().isoformat(),
    }
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=_back_only_keyboard(),
    )


async def handle_admin_shortcut_invite(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    """Handle admin invite shortcut commands and render invite details."""
    storage = get_runtime_storage(context)
    actor_id = update.effective_user.id if update.effective_user else None
    role = storage.get_user_role(actor_id)
    if not _is_admin_role(role):
        await update.message.reply_text("🚫 Unauthorized.")
        return
    record = _find_invite_by_token(token)
    if not record:
        await update.message.reply_text("⚠️ Invite not found or already resolved.")
        return
    await update.message.reply_text(
        _invite_detail_text(record, storage=storage),
        parse_mode="Markdown",
        reply_markup=_invite_detail_keyboard(token),
    )
