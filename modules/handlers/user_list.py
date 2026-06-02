from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from modules import constants as C
from modules.handlers.list_alerts import LIST_CONTEXT_KEY
from modules.security.whitelist_store import list_whitelist_users
from modules.shared.acting_as import get_actor_user_id
from modules.shared.logging_utils import text_meta
from modules.shared.runtime_context import get_runtime_storage
from modules.shared.whitelist_users import (
    build_whitelist_users_chunks,
    build_whitelist_users_empty_text,
    build_whitelist_users_text,
)
from modules.systemlog import log_system


ROLE_ADMIN = "admin"
ROLE_DEVELOPER = "developer"
ROLE_USER = "user"
USER_LIST_TOO_LONG_TEXT = (
    "⚠️ User list is too long for a single Telegram message.\n"
    "The list could not be rendered in one message."
)


def _normalize_role(role):
    text = str(role).strip().lower() if role is not None else ""
    if text in {ROLE_ADMIN, ROLE_DEVELOPER, ROLE_USER}:
        return text
    return ROLE_USER


def resolve_user_detail_back_cb(context, actor_role):
    """Resolve the back callback target for user-detail views."""
    source = None
    if context is not None:
        data = context.user_data.get(LIST_CONTEXT_KEY)
        if isinstance(data, dict):
            source = data.get("source")
    if source == "developer_users":
        return "developer_users"
    if source == "admin_users":
        return "admin_list"
    if actor_role == ROLE_DEVELOPER:
        return "developer_users"
    if actor_role in {ROLE_ADMIN, ROLE_DEVELOPER}:
        return "admin_list"
    return None


def build_user_detail_keyboard(
    *,
    actor_role,
    target_role,
    target_id,
    actor_id=None,
    back_cb=None,
):
    """Build role-aware user detail action keyboard for admin/developer flows."""
    actor_role = _normalize_role(actor_role)
    target_role = _normalize_role(target_role)
    rows = []

    if actor_role in {ROLE_ADMIN, ROLE_DEVELOPER}:
        rows.append([
            InlineKeyboardButton("✏️ Set Name", callback_data=f"admin_user_set_name:{target_id}"),
            InlineKeyboardButton("🔀 Set Label Order", callback_data=f"admin_user_set_order:{target_id}"),
        ])
        if target_role == ROLE_USER:
            rows.append([InlineKeyboardButton("🗑️ Remove User", callback_data=f"admin_remove:{target_id}")])

    if actor_role == ROLE_DEVELOPER:
        role_buttons = []
        if target_role != ROLE_USER:
            role_buttons.append(InlineKeyboardButton("Set User", callback_data=f"developer_role:{target_id}:user"))
        if target_role != ROLE_ADMIN:
            role_buttons.append(InlineKeyboardButton("Set Admin", callback_data=f"developer_role:{target_id}:admin"))
        if target_role != ROLE_DEVELOPER:
            role_buttons.append(InlineKeyboardButton("Set Developer", callback_data=f"developer_role:{target_id}:developer"))
        if role_buttons:
            rows.append(role_buttons)
        if actor_id is None or str(actor_id) != str(target_id):
            rows.append([InlineKeyboardButton("🧑‍💻 Act As", callback_data=f"developer_actas_set:{target_id}")])

    if back_cb:
        rows.append([InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])

    return InlineKeyboardMarkup(rows)


def summarize_user_data(data):
    """Summarize alert, birthday, and tag counts from user data payloads."""
    if not isinstance(data, dict):
        return {"alerts": 0, "birthdays": 0, "tags": 0}
    alerts = data.get("alerts")
    if not isinstance(alerts, list):
        alerts = []
    alerts_count = 0
    birthdays_count = 0
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        if alert.get("type") == 6:
            birthdays_count += 1
        else:
            alerts_count += 1
    tags = data.get("tags")
    tags_count = len(tags) if isinstance(tags, list) else 0
    return {
        "alerts": alerts_count,
        "birthdays": birthdays_count,
        "tags": tags_count,
    }


def _activity_state(last_seen_raw, *, first_start_raw=None):
    """Classifies user activity and returns (bucket, icon_or_none)."""
    icon_purple = getattr(C, "ACTIVITY_ICON_PURPLE", "\U0001f7e3")  # 🟣
    icon_green = getattr(C, "ACTIVITY_ICON_GREEN", "\U0001f7e2")  # 🟢
    icon_orange = getattr(C, "ACTIVITY_ICON_ORANGE", "\U0001f7e0")  # 🟠
    icon_red = getattr(C, "ACTIVITY_ICON_RED", "\U0001f534")  # 🔴

    has_last_seen = bool(str(last_seen_raw).strip()) if last_seen_raw is not None else False
    has_first_start = bool(str(first_start_raw).strip()) if first_start_raw is not None else False
    if not has_last_seen:
        if has_first_start:
            return "inconsistent", icon_red
        return "never_active", None

    try:
        last_seen_dt = datetime.fromisoformat(str(last_seen_raw))
    except Exception:
        return "inconsistent", icon_red

    if last_seen_dt.tzinfo is None:
        elapsed = (datetime.now() - last_seen_dt).total_seconds()
    else:
        elapsed = (datetime.now(timezone.utc) - last_seen_dt.astimezone(timezone.utc)).total_seconds()
    if elapsed < 0:
        elapsed = 0

    purple = getattr(C, "ACTIVITY_PURPLE_SECONDS", getattr(C, "ACTIVITY_GREEN_SECONDS", 600))
    green = getattr(C, "ACTIVITY_GREEN_SECONDS", 86400)
    orange = getattr(C, "ACTIVITY_ORANGE_SECONDS", 7 * 86400)
    if elapsed <= purple:
        return "purple", icon_purple
    if elapsed <= green:
        return "green", icon_green
    if elapsed <= orange:
        return "orange", icon_orange
    return "red", icon_red


def _build_activity_counts(meta_map):
    counts = {
        "activity_never_active": 0,
        "activity_purple": 0,
        "activity_green": 0,
        "activity_orange": 0,
        "activity_red": 0,
        "activity_inconsistent": 0,
    }
    for meta in (meta_map or {}).values():
        safe_meta = meta if isinstance(meta, dict) else {}
        bucket, _icon = _activity_state(
            safe_meta.get("last_seen"),
            first_start_raw=safe_meta.get("first_start"),
        )
        key = f"activity_{bucket}"
        if key in counts:
            counts[key] += 1
    return counts


def format_user_summary(summary, *, last_seen=None, first_start=None):
    """Format compact whitelist stats triplets with an activity icon for one user row."""
    summary = summary or {}
    alerts_count = int(summary.get("alerts", 0) or 0)
    birthdays_count = int(summary.get("birthdays", 0) or 0)
    tags_count = int(summary.get("tags", 0) or 0)
    _bucket, icon = _activity_state(last_seen, first_start_raw=first_start)
    stats = f"{alerts_count}-{birthdays_count}-{tags_count}"
    return (icon, stats)


def build_users_text(entries, meta_map, summary_map=None, *, include_alias, empty_text):
    """Build whitelist user list text using summary and activity metadata."""
    def _format_with_activity(summary_data, *, meta=None):
        last_seen = meta.get("last_seen") if isinstance(meta, dict) else None
        first_start = meta.get("first_start") if isinstance(meta, dict) else None
        return format_user_summary(summary_data, last_seen=last_seen, first_start=first_start)

    return build_whitelist_users_text(
        entries,
        meta_map,
        summary_map or {},
        _format_with_activity,
        include_alias=include_alias,
        empty_text=empty_text,
    )


def _build_users_chunks(entries, meta_map, summary_map=None, *, include_alias, empty_text):
    def _format_with_activity(summary_data, *, meta=None):
        last_seen = meta.get("last_seen") if isinstance(meta, dict) else None
        first_start = meta.get("first_start") if isinstance(meta, dict) else None
        return format_user_summary(summary_data, last_seen=last_seen, first_start=first_start)

    return build_whitelist_users_chunks(
        entries,
        meta_map,
        summary_map or {},
        _format_with_activity,
        include_alias=include_alias,
        empty_text=empty_text,
    )


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
            summary_map[str(uid)] = summarize_user_data(storage.get_all_alerts(uid))
        except Exception:
            summary_map[str(uid)] = {"alerts": 0, "birthdays": 0, "tags": 0}
    return summary_map


def _back_keyboard(back_cb):
    if not back_cb:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=back_cb)]])


def _role_source(role):
    return "developer_users" if role == ROLE_DEVELOPER else "admin_users"


def _normalize_role_filter(role_filter):
    """Normalize optional role-filter input into a lowercase role allowlist set."""
    if role_filter is None:
        return None
    if isinstance(role_filter, str):
        return {str(role_filter).strip().lower()}
    if isinstance(role_filter, (set, list, tuple)):
        values = {str(item).strip().lower() for item in role_filter if str(item).strip()}
        return values or None
    return None


def _filter_entries_by_role(entries, role_filter):
    """Filter whitelist entries by normalized role names when a filter is configured."""
    normalized = _normalize_role_filter(role_filter)
    if normalized is None:
        return list(entries or [])
    filtered = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("role") or "").strip().lower() in normalized:
            filtered.append(entry)
    return filtered


def _origin_back_callback(origin, role):
    if origin in {"manage", "developer", "admin"}:
        return "mgmt_menu"
    if origin is None and role in {ROLE_ADMIN, ROLE_DEVELOPER}:
        return "mgmt_menu"
    return None


def _resolve_target(update):
    if update.callback_query:
        return update.callback_query
    return update.effective_message or update.message


def _send_text(target, text, *, reply_markup):
    if hasattr(target, "edit_message_text"):
        return target.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    return target.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


def _aggregate_chunks_text(chunks):
    safe_chunks = [str(chunk or "") for chunk in (chunks or []) if str(chunk or "").strip()]
    if not safe_chunks:
        return ""
    return "\n\n".join(safe_chunks)


def _is_message_too_long_error(error: Exception) -> bool:
    message = str(error or "").lower()
    return (
        "message is too long" in message
        or "text is too long" in message
        or "entities too long" in message
        or "entity is too long" in message
    )


def is_message_not_modified_error(error: Exception) -> bool:
    """Return whether an error represents Telegram message-not-modified no-op."""
    message = str(error or "").lower()
    return "message is not modified" in message


_ALLOWED_RENDER_REASONS = {
    "unauthorized",
    "target_missing",
    "missing_delivery_target",
    "message_not_modified",
    "telegram_message_too_long",
    "bad_request",
}


def normalize_render_reason(reason) -> str | None:
    """Normalize render failure reasons to the allowed audit reason set."""
    if reason is None:
        return None
    text = str(reason).strip().lower()
    if not text:
        return None
    if text in _ALLOWED_RENDER_REASONS:
        return text
    if text.startswith("bad_request"):
        return "bad_request"
    return "other"


def _normalize_detail_role(role):
    text = str(role).strip().lower() if role is not None else ""
    if text in {ROLE_ADMIN, ROLE_DEVELOPER, ROLE_USER}:
        return text
    return "unknown"


def log_user_detail_render(
    storage,
    *,
    actor_id,
    actor_role,
    target_id,
    target_role,
    source,
    delivery,
    text,
    ok,
    reason=None,
):
    """Log user-detail render outcomes to user events and admin audit stream."""
    meta = text_meta(text)
    payload = {
        "actor_role": _normalize_detail_role(actor_role),
        "target_id": str(target_id) if target_id is not None else None,
        "target_role": _normalize_detail_role(target_role),
        "source": str(source or "unknown"),
        "delivery": str(delivery or "unknown"),
        "text_len": int(meta.get("len") or 0),
        "text_hash": meta.get("hash"),
        "ok": bool(ok),
    }
    reason_code = normalize_render_reason(reason)
    if reason_code:
        payload["reason"] = reason_code

    event_name = "manage_user_detail_rendered" if ok else "manage_user_detail_render_failed"
    actor_text = str(actor_id) if actor_id is not None else None
    if actor_id is not None:
        try:
            storage.log_user_event(actor_id, event_name, payload)
        except Exception:
            pass

    audit_payload = {"actor_id": actor_text}
    audit_payload.update(payload)
    level = "INFO" if ok else "WARNING"
    log_system("admin_audit", event_name, audit_payload, level=level)


def _log_user_list_render(
    storage,
    *,
    actor_id,
    role,
    origin,
    users_total,
    aliases_total,
    text,
    ok,
    reason=None,
    activity_counts=None,
    delivery=None,
    chunks_total=1,
    continuation_messages_sent=0,
):
    meta = text_meta(text)
    payload = {
        "role": role,
        "origin": origin,
        "users_total": int(users_total),
        "aliases_total": int(aliases_total),
        "text_len": int(meta.get("len") or 0),
        "text_hash": meta.get("hash"),
        "ok": bool(ok),
        "delivery": str(delivery or "unknown"),
        "chunks_total": int(chunks_total or 0),
        "continuation_messages_sent": int(continuation_messages_sent or 0),
    }
    if reason:
        payload["reason"] = normalize_render_reason(reason) or "other"
    if isinstance(activity_counts, dict):
        payload.update({
            "activity_never_active": int(activity_counts.get("activity_never_active", 0) or 0),
            "activity_purple": int(activity_counts.get("activity_purple", 0) or 0),
            "activity_green": int(activity_counts.get("activity_green", 0) or 0),
            "activity_orange": int(activity_counts.get("activity_orange", 0) or 0),
            "activity_red": int(activity_counts.get("activity_red", 0) or 0),
            "activity_inconsistent": int(activity_counts.get("activity_inconsistent", 0) or 0),
        })
        payload["anomaly_activity_meta_inconsistent"] = bool(payload.get("activity_inconsistent", 0) > 0)

    event_name = "manage_user_list_rendered" if ok else "manage_user_list_render_failed"
    actor_text = str(actor_id) if actor_id is not None else None
    if actor_id is not None:
        try:
            storage.log_user_event(actor_id, event_name, payload)
        except Exception:
            pass

    audit_payload = {"actor_id": actor_text}
    audit_payload.update(payload)
    level = "INFO" if ok else "WARNING"
    log_system("admin_audit", event_name, audit_payload, level=level)


def _back_markup_for_chunk(back_markup, *, idx, total):
    if back_markup is None:
        return None
    if total <= 1:
        return back_markup
    return back_markup if idx == total - 1 else None


def _classify_bad_request(exc: Exception) -> str:
    if _is_message_too_long_error(exc):
        return "telegram_message_too_long"
    return "bad_request"


def _classify_delivery_error(exc: Exception) -> str:
    """Classify chunk-delivery exceptions into metadata-safe reason codes."""
    if isinstance(exc, BadRequest):
        return _classify_bad_request(exc)
    if isinstance(exc, TelegramError):
        return "bad_request"
    return "other"


async def _deliver_user_list_chunks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chunks,
    back_markup,
    actor_id,
):
    """
    Deliver user-list chunks with callback-aware edit/send behavior.

    Returns a metadata dict with keys: ok, delivery, reason, continuation_messages_sent.
    """
    safe_chunks = list(chunks or [])
    if not safe_chunks:
        return {
            "ok": False,
            "delivery": "unknown",
            "reason": "missing_delivery_target",
            "continuation_messages_sent": 0,
        }

    total = len(safe_chunks)
    continuation_messages_sent = 0
    query = getattr(update, "callback_query", None)

    async def _send_all_via_bot(chat_id):
        nonlocal continuation_messages_sent
        if context is None or chat_id is None:
            return {
                "ok": False,
                "reason": "missing_delivery_target",
            }
        for idx, chunk in enumerate(safe_chunks):
            reply_markup = _back_markup_for_chunk(back_markup, idx=idx, total=total)
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
            except Exception as exc:
                return {
                    "ok": False,
                    "reason": _classify_delivery_error(exc),
                }
            if idx > 0:
                continuation_messages_sent += 1
        return {
            "ok": True,
            "reason": None,
        }

    if query is not None:
        query_message = getattr(query, "message", None)
        if query_message is None:
            send_result = await _send_all_via_bot(actor_id)
            if not send_result.get("ok"):
                return {
                    "ok": False,
                    "delivery": "chat_send",
                    "reason": send_result.get("reason") or "other",
                    "continuation_messages_sent": continuation_messages_sent,
                }
            return {
                "ok": True,
                "delivery": "chat_send",
                "reason": None,
                "continuation_messages_sent": continuation_messages_sent,
            }

        delivery = "callback_edit"
        first_markup = _back_markup_for_chunk(back_markup, idx=0, total=total)
        try:
            await query.edit_message_text(
                safe_chunks[0],
                parse_mode="Markdown",
                reply_markup=first_markup,
            )
        except BadRequest as exc:
            if is_message_not_modified_error(exc):
                delivery = "message_not_modified"
            else:
                return {
                    "ok": False,
                    "delivery": "callback_edit",
                    "reason": _classify_bad_request(exc),
                    "continuation_messages_sent": continuation_messages_sent,
                }

        chat_id = getattr(query_message, "chat_id", None)
        if chat_id is None and actor_id is not None:
            chat_id = actor_id
        if total > 1 and (context is None or chat_id is None):
            return {
                "ok": False,
                "delivery": delivery,
                "reason": "missing_delivery_target",
                "continuation_messages_sent": continuation_messages_sent,
            }
        for idx in range(1, total):
            reply_markup = _back_markup_for_chunk(back_markup, idx=idx, total=total)
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=safe_chunks[idx],
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
                continuation_messages_sent += 1
            except Exception as exc:
                return {
                    "ok": False,
                    "delivery": delivery,
                    "reason": _classify_delivery_error(exc),
                    "continuation_messages_sent": continuation_messages_sent,
                }
        return {
            "ok": True,
            "delivery": delivery,
            "reason": "message_not_modified" if delivery == "message_not_modified" else None,
            "continuation_messages_sent": continuation_messages_sent,
        }

    target = update.effective_message or update.message
    if target is not None and hasattr(target, "reply_text"):
        for idx, chunk in enumerate(safe_chunks):
            reply_markup = _back_markup_for_chunk(back_markup, idx=idx, total=total)
            try:
                await target.reply_text(chunk, parse_mode="Markdown", reply_markup=reply_markup)
                if idx > 0:
                    continuation_messages_sent += 1
            except Exception as exc:
                return {
                    "ok": False,
                    "delivery": "chat_send",
                    "reason": _classify_delivery_error(exc),
                    "continuation_messages_sent": continuation_messages_sent,
                }
        return {
            "ok": True,
            "delivery": "chat_send",
            "reason": None,
            "continuation_messages_sent": continuation_messages_sent,
        }

    send_result = await _send_all_via_bot(actor_id)
    if send_result.get("ok"):
        return {
            "ok": True,
            "delivery": "chat_send",
            "reason": None,
            "continuation_messages_sent": continuation_messages_sent,
        }
    return {
        "ok": False,
        "delivery": "chat_send",
        "reason": send_result.get("reason") or "other",
        "continuation_messages_sent": continuation_messages_sent,
    }


async def _send_user_list_too_long_notice(context, actor_id):
    if context is None or actor_id is None:
        return False
    try:
        await context.bot.send_message(chat_id=actor_id, text=USER_LIST_TOO_LONG_TEXT)
        return True
    except Exception as exc:
        log_system("errors", "manage_user_list_oversize_notice_failed", {
            "actor_id": str(actor_id),
            "error": str(exc),
        }, level="ERROR")
        return False


async def show_user_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    storage,
    *,
    role: str,
    origin: str | None = None,
) -> None:
    """Render the whitelist user list, chunk oversized output, and persist alias mapping context."""
    entries = list_whitelist_users()
    meta_map = _build_meta_map(storage, entries)
    activity_counts = _build_activity_counts(meta_map)
    summary_map = _build_summary_map(storage, entries)
    chunks, alias_map, overflowed = _build_users_chunks(
        entries,
        meta_map,
        summary_map,
        include_alias=True,
        empty_text=build_whitelist_users_empty_text(),
    )
    text = _aggregate_chunks_text(chunks)
    actor_id = get_actor_user_id(update)
    chunks_total = len(chunks)

    if context is not None:
        context.user_data[LIST_CONTEXT_KEY] = {
            "source": _role_source(role),
            "alias_map": alias_map,
            "saved_at": datetime.now().isoformat(),
        }

    back_cb = _origin_back_callback(origin, role)
    reply_markup = _back_keyboard(back_cb)
    result = await _deliver_user_list_chunks(
        update,
        context,
        chunks=chunks,
        back_markup=reply_markup,
        actor_id=actor_id,
    )

    if result.get("ok"):
        _log_user_list_render(
            storage,
            actor_id=actor_id,
            role=role,
            origin=origin,
            users_total=len(entries),
            aliases_total=len(alias_map),
            text=text,
            ok=True,
            reason=result.get("reason"),
            activity_counts=activity_counts,
            delivery=result.get("delivery"),
            chunks_total=chunks_total,
            continuation_messages_sent=result.get("continuation_messages_sent", 0),
        )
        return

    reason = result.get("reason")
    _log_user_list_render(
        storage,
        actor_id=actor_id,
        role=role,
        origin=origin,
        users_total=len(entries),
        aliases_total=len(alias_map),
        text=text,
        ok=False,
        reason=reason,
        activity_counts=activity_counts,
        delivery=result.get("delivery"),
        chunks_total=chunks_total,
        continuation_messages_sent=result.get("continuation_messages_sent", 0),
    )
    if reason == "telegram_message_too_long" and overflowed:
        await _send_user_list_too_long_notice(context, actor_id)
        return
    if reason == "telegram_message_too_long":
        await _send_user_list_too_long_notice(context, actor_id)


async def userlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle `/userlist` command with elevated-role authorization checks."""
    storage = get_runtime_storage(context)
    actor_id = get_actor_user_id(update)
    role = storage.get_user_role(actor_id)
    if role not in {ROLE_ADMIN, ROLE_DEVELOPER}:
        target = update.effective_message or update.message
        if target:
            await target.reply_text("🚫 Unauthorized.")
        return
    await show_user_list(update, context, storage, role=role)


def build_scoped_user_alias_chunks(storage, *, role_filter=None, include_alias=True):
    """Build Telegram-safe user-list chunks and alias mapping for an optional role scope."""
    entries = _filter_entries_by_role(list_whitelist_users(), role_filter)
    meta_map = _build_meta_map(storage, entries)
    summary_map = _build_summary_map(storage, entries)
    chunks, alias_map, overflowed = _build_users_chunks(
        entries,
        meta_map,
        summary_map,
        include_alias=include_alias,
        empty_text=build_whitelist_users_empty_text(),
    )
    return {
        "chunks": chunks,
        "alias_map": alias_map,
        "overflowed": overflowed,
        "entries_total": len(entries),
    }
