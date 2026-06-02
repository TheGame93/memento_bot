"""Handle /start onboarding and access-request callback flows."""

import html
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.runtime_context import get_runtime_storage
from modules.systemlog import log_system

START_REQUEST_MAX_MESSAGE_CHARS = C.START_REQUEST_MAX_MESSAGE_CHARS
START_REQUEST_PROCEED_CB = "startreq_proceed"
START_REQUEST_CANCEL_CB = "startreq_cancel"
START_REQUEST_EDIT_YES_CB = "startreq_edit_yes"
START_REQUEST_EDIT_NO_CB = "startreq_edit_no"


def _start_request_prompt_text():
    return (
        "I'm going to send an approval request for using the bot. "
        "Add a message for identification."
    )


def _start_request_default_message(user_id, username=None, display_name=None):
    uname = (str(username).strip() if username else "")
    if uname and not uname.startswith("@"):
        uname = f"@{uname}"
    uname = uname or "n/a"
    dname = (str(display_name).strip() if display_name else "") or "n/a"
    return f"Auto /start request. User ID: {user_id}. Username: {uname}. Full name: {dname}."


def _start_request_pending_text(message_text):
    safe = html.escape(message_text or "n/a")
    return (
        "⏳ <b>Waiting for approval</b>\n\n"
        f"The message to admins is:\n<code>{safe}</code>\n\n"
        "Do you want to modify it?"
    )


def _start_request_pending_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes", callback_data=START_REQUEST_EDIT_YES_CB),
            InlineKeyboardButton("No", callback_data=START_REQUEST_EDIT_NO_CB),
        ]
    ])


def _start_request_confirm_text(message_text):
    safe = html.escape(message_text or "")
    return (
        "📝 <b>Access Request Recap</b>\n\n"
        f"<code>{safe}</code>\n\n"
        "Send this request to admins?"
    )


def _start_request_confirm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Proceed", callback_data=START_REQUEST_PROCEED_CB),
            InlineKeyboardButton("Cancel", callback_data=START_REQUEST_CANCEL_CB),
        ]
    ])


def clear_start_request_context(user_data):
    """Clear temporary /start access-request fields from user context."""
    user_data.pop("expecting_start_request_message", None)
    user_data.pop("start_request_message_draft", None)
    user_data.pop("start_request_confirm_pending", None)


async def _edit_or_reply(query, text, *, parse_mode=None, reply_markup=None):
    message = getattr(query, "message", None)
    if message:
        try:
            await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return
        except Exception:
            pass
    await query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point with whitelist check and user space setup."""
    storage = get_runtime_storage(context)
    target = update.effective_message or update.message
    if not target:
        return
    user = update.effective_user
    actor_id = get_actor_user_id(update)
    user_id = get_target_user_id(update, context)
    same_identity = str(actor_id) == str(user_id)

    # Whitelist Check
    authorized = storage.is_user_whitelisted(user_id)
    if not authorized:
        from modules.security.whitelist_store import (
            add_whitelist_user,
            ensure_whitelist_request,
            find_whitelist_invite,
            find_whitelist_request,
            get_whitelist_request_state,
            remove_whitelist_invite,
            remove_whitelist_request,
            update_whitelist_request_message,
        )
        from modules.security.whitelist_notifications import notify_admins_for_request

        now_iso = datetime.now().isoformat()
        username = getattr(user, "username", None) if same_identity else None
        display_name = None
        if same_identity:
            display_name = getattr(user, "full_name", None) or " ".join(
                [
                    part
                    for part in [
                        getattr(user, "first_name", None),
                        getattr(user, "last_name", None),
                    ]
                    if part
                ]
            )
        invite_record = find_whitelist_invite(user_id=user_id, username=username)
        if invite_record:
            invite_role = invite_record.get("role") or "user"
            invite_by = invite_record.get("invited_by")
            ok_invite = add_whitelist_user(user_id, role=invite_role)
            if ok_invite:
                remove_whitelist_invite(user_id=user_id, username=username)
                remove_whitelist_request(user_id)
                storage.setup_user_space(user_id)
                current_meta = storage.get_user_meta(user_id) or {}
                updates = {}
                if not current_meta.get("added_at"):
                    updates["added_at"] = now_iso
                if invite_by and not current_meta.get("added_by"):
                    updates["added_by"] = str(invite_by)
                if not current_meta.get("added_via"):
                    updates["added_via"] = "admin_invite"
                if username:
                    updates["username"] = username
                if display_name:
                    updates["display_name"] = display_name
                if updates:
                    storage.update_user_meta(user_id, updates)
                log_system(
                    "security",
                    "whitelist_invite_consumed",
                    {
                        "user_id": str(user_id),
                        "username": username,
                        "role": invite_role,
                        "invited_by": invite_by,
                    },
                )
                authorized = True
        if not authorized:
            clear_start_request_context(context.user_data)
            state = get_whitelist_request_state(user_id) or {}
            pending_record = find_whitelist_request(user_id)
            state_status = str((state or {}).get("status") or "").strip().lower()

            # Fail-safe cleanup: stale pending records must not block users
            # after an already-resolved request cycle.
            if pending_record and state_status in {"approved", "rejected"}:
                removed = remove_whitelist_request(user_id)
                log_system(
                    "security",
                    "whitelist_request_stale_removed",
                    {
                        "user_id": str(user_id),
                        "state_status": state_status,
                        "removed": bool(removed),
                    },
                    level="WARNING",
                )
                pending_record = None
                state = {}

            created = False
            if not pending_record:
                auto_message = _start_request_default_message(
                    user_id=user_id,
                    username=username,
                    display_name=display_name,
                )
                result = ensure_whitelist_request(
                    user_id=user_id,
                    username=username,
                    display_name=display_name,
                    request_message=auto_message,
                    now_iso=now_iso,
                )
                if not bool(result.get("ok")):
                    log_system(
                        "errors",
                        "whitelist_request_store_failed",
                        {
                            "actor_id": str(actor_id),
                            "user_id": str(user_id),
                            "source": "start_auto",
                        },
                        level="ERROR",
                    )
                    await target.reply_text(
                        "⚠️ Could not record your access request. Please try again later."
                    )
                    return
                pending_record = result.get("record") or {}
                state = result.get("state") or {}
                created = bool(result.get("created"))
            elif not isinstance(state, dict) or state_status != "pending":
                # Repair pending-state snapshot without bumping request counters.
                heal = update_whitelist_request_message(
                    user_id=user_id,
                    request_message=pending_record.get("request_message"),
                    now_iso=now_iso,
                )
                if heal.get("status") in {"updated", "updated_partial"}:
                    pending_record = heal.get("record") or pending_record
                    state = heal.get("state") or {}
                else:
                    state = get_whitelist_request_state(user_id) or {}

            message_text = (pending_record or {}).get(
                "request_message"
            ) or _start_request_default_message(
                user_id=user_id,
                username=username,
                display_name=display_name,
            )
            should_notify_admins = bool(created) or not (state or {}).get(
                "first_notified_at"
            )
            if should_notify_admins:
                try:
                    await notify_admins_for_request(
                        context.bot, storage, pending_record or {}, state or {}
                    )
                except Exception as exc:
                    log_system(
                        "errors",
                        "whitelist_request_notify_failed",
                        {
                            "user_id": str(user_id),
                            "error": str(exc),
                            "source": "start_auto",
                        },
                        level="ERROR",
                    )

            log_system(
                "security",
                "whitelist_request_received",
                {
                    "actor_id": str(actor_id),
                    "user_id": str(user_id),
                    "username": username,
                    "display_name": display_name,
                    "message_length": len(message_text),
                    "created": bool(created),
                    "source": "start_auto",
                },
            )
            await target.reply_text(
                _start_request_pending_text(message_text),
                parse_mode="HTML",
                reply_markup=_start_request_pending_keyboard(),
            )
            return

    # Defensive cleanup for stale onboarding flags after approval.
    clear_start_request_context(context.user_data)

    # Setup directories
    storage.setup_user_space(user_id)
    acting_payload = build_acting_as_payload(update, context)
    storage.log_user_event(user_id, "command_start", {"authorized": True, **acting_payload})
    now_iso = datetime.now().isoformat()
    meta = storage.get_user_meta(user_id) or {}
    updates = {
        "last_seen": now_iso,
    }
    if same_identity:
        updates["username"] = getattr(user, "username", None)
        updates["display_name"] = getattr(user, "full_name", None)
    if same_identity and not meta.get("first_start"):
        updates["first_start"] = now_iso
    storage.update_user_meta(user_id, updates)

    await target.reply_text(
        f"{build_acting_as_banner(update, context, parse_mode='Markdown')}"
        f"✅ **Bot Started.**\n"
        f"User ID: `{user_id}`\n"
        f"Role: `{storage.get_user_role(user_id)}`\n"
        f"Data folder: Initialized",
        parse_mode="Markdown",
    )


async def handle_start_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle onboarding access-request callbacks with fail-closed semantics."""
    query = update.callback_query
    valid_callbacks = {
        START_REQUEST_PROCEED_CB,
        START_REQUEST_CANCEL_CB,
        START_REQUEST_EDIT_YES_CB,
        START_REQUEST_EDIT_NO_CB,
    }
    if not query or query.data not in valid_callbacks:
        return
    await query.answer()

    storage = get_runtime_storage(context)
    user_id = get_target_user_id(update, context)

    if storage.is_user_whitelisted(user_id):
        clear_start_request_context(context.user_data)
        await _edit_or_reply(query, "✅ Access already granted. Use /help to get started.")
        return

    # Legacy callbacks from previous inline keyboards must fail closed and never mutate state.
    if query.data in {START_REQUEST_PROCEED_CB, START_REQUEST_CANCEL_CB}:
        clear_start_request_context(context.user_data)
        await _edit_or_reply(query, "⚠️ This action is no longer valid. Use /start to continue.")
        return

    from modules.security.whitelist_store import (
        find_whitelist_request,
        get_whitelist_request_state,
        remove_whitelist_request,
    )

    pending_record = find_whitelist_request(user_id)
    state = get_whitelist_request_state(user_id) or {}
    state_status = str(state.get("status") or "").strip().lower()
    if pending_record and state_status in {"approved", "rejected"}:
        remove_whitelist_request(user_id)
        pending_record = None

    if not pending_record:
        clear_start_request_context(context.user_data)
        await _edit_or_reply(query, "⚠️ Request recap expired. Send /start again.")
        return

    if query.data == START_REQUEST_EDIT_NO_CB:
        clear_start_request_context(context.user_data)
        message_text = pending_record.get("request_message") or _start_request_default_message(
            user_id=user_id,
            username=pending_record.get("username"),
            display_name=pending_record.get("display_name"),
        )
        await _edit_or_reply(
            query,
            _start_request_pending_text(message_text),
            parse_mode="HTML",
            reply_markup=_start_request_pending_keyboard(),
        )
        return

    if query.data == START_REQUEST_EDIT_YES_CB:
        clear_start_request_context(context.user_data)
        context.user_data["expecting_start_request_message"] = True
        await _edit_or_reply(
            query,
            "✏️ Send the new message for admins now.\nUse /cancel to stop.",
        )
        return

    clear_start_request_context(context.user_data)
    await _edit_or_reply(query, "⚠️ Request action unavailable. Send /start again.")
