"""Provide edit-flow origin capture and origin-view restoration helpers."""

from datetime import datetime

from telegram.constants import ParseMode

from modules.handlers.add_flow.state_helpers import (
    cleanup_add_flow_messages,
    track_add_flow_callback_message,
    track_add_flow_incoming,
    track_add_flow_outgoing,
)
from modules.shared.context_cleanup import clear_transient_context
from modules.shared.runtime_context import get_runtime_storage


def _parse_iso_datetime(raw_text):
    """Parse an ISO datetime string and return `None` on invalid input."""
    try:
        return datetime.fromisoformat(raw_text) if raw_text else None
    except Exception:
        return None


def _log_edit_flow_event(storage, user_id, event_type, payload=None):
    """Emit metadata-only edit-flow telemetry when storage and target user are available."""
    if storage is None or user_id is None:
        return
    try:
        storage.log_user_event(user_id, event_type, dict(payload or {}))
    except Exception:
        pass


def _restore_reason_code_from_exception(exc):
    """Map restore failures to stable reason codes without exposing raw exception text."""
    try:
        text = str(exc or "").lower()
    except Exception:
        return "restore_exception"
    if "message is not modified" in text:
        return "message_not_modified"
    if "message to edit not found" in text:
        return "message_not_found"
    if "chat not found" in text:
        return "chat_not_found"
    if "forbidden" in text or "bot was blocked by the user" in text:
        return "forbidden"
    return "restore_exception"


def _build_edit_origin_context(update, alert_id):
    """Capture metadata needed to restore notification or list/detail origin cards after edit."""
    context = {
        "source": "unknown",
        "source_hint": None,
        "alert_id": str(alert_id or ""),
        "chat_id": None,
        "message_id": None,
        "origin_chat_id": None,
        "origin_message_id": None,
        "is_photo": False,
        "include_back": False,
        "kind": "due",
        "original_time": None,
        "occurrence_time": None,
        "postpone_count": 0,
    }
    query = getattr(update, "callback_query", None)
    message = getattr(query, "message", None)
    if message is None:
        return context

    context["message_id"] = getattr(message, "message_id", None)
    context["origin_message_id"] = context["message_id"]
    context["is_photo"] = bool(getattr(message, "photo", None))

    chat = getattr(message, "chat", None)
    chat_id = getattr(chat, "id", None)
    if chat_id is None:
        effective_chat = getattr(update, "effective_chat", None)
        chat_id = getattr(effective_chat, "id", None)
    context["chat_id"] = chat_id
    context["origin_chat_id"] = chat_id

    try:
        from modules.handlers.notification_context import _derive_detail_origin_context

        derived = _derive_detail_origin_context(message, alert_id) or {}
    except Exception:
        derived = {}

    if derived.get("detail_from_notification"):
        context["source"] = "notification"
    elif derived.get("detail_from_list"):
        context["source"] = "list"
    context["include_back"] = bool(derived.get("include_back"))

    kind = str(derived.get("kind") or "due").strip().lower()
    context["kind"] = kind if kind in {"pre", "due"} else "due"

    try:
        parsed_count = int(derived.get("postpone_count") or 0)
    except (TypeError, ValueError):
        parsed_count = 0
    context["postpone_count"] = parsed_count if parsed_count > 0 else 0

    original_time = derived.get("original_time")
    occurrence_time = derived.get("occurrence_time")
    if original_time is not None:
        try:
            context["original_time"] = original_time.isoformat()
        except Exception:
            context["original_time"] = None
    if occurrence_time is not None:
        try:
            context["occurrence_time"] = occurrence_time.isoformat()
        except Exception:
            context["occurrence_time"] = None
    return context


def _normalize_origin_source_hint(raw_source):
    """Normalize manage-source hints into stable list/detail source labels."""
    source = str(raw_source or "").strip().lower()
    if not source:
        return None
    if source == "next_alerts":
        return "alerts"
    if source == "next_birthdays":
        return "birthdays"
    return source


def _track_edit_incoming_message(update, context):
    """Register incoming edit-flow user messages for later artifact cleanup."""
    track_add_flow_incoming(update, context)


def _track_edit_callback_message(update, context):
    """Register callback-origin edit-flow message ids for later artifact cleanup."""
    track_add_flow_callback_message(update, context)


def _track_edit_outgoing_message(context, message):
    """Register outgoing edit-flow messages for later artifact cleanup."""
    track_add_flow_outgoing(context, message)


def _capture_origin_tag_filter(context, source_hint):
    """Capture the active list filter so restored detail cards keep source-aware Back labels."""
    user_data = getattr(context, "user_data", None)
    source = _normalize_origin_source_hint(source_hint)
    if not isinstance(user_data, dict) or source not in {"alerts", "birthdays"}:
        return None
    if source == "birthdays":
        return user_data.get("birthday_current_filter", "ALL")
    return user_data.get("current_filter", "ALL")


def _apply_origin_tag_filter(context, source_hint, tag_filter):
    """Apply stored filter metadata before list-origin card restoration."""
    if tag_filter is None:
        return
    user_data = getattr(context, "user_data", None)
    source = _normalize_origin_source_hint(source_hint)
    if not isinstance(user_data, dict) or source not in {"alerts", "birthdays"}:
        return
    if source == "birthdays":
        user_data["birthday_current_filter"] = tag_filter
    else:
        user_data["current_filter"] = tag_filter


async def _restore_notification_origin_message_view(
    context,
    *,
    user_id,
    alert_id,
    origin_context,
):
    """Restore notification-origin cards and emit stable telemetry for restore outcomes."""
    try:
        storage = get_runtime_storage(context)
    except Exception:
        storage = None

    origin = origin_context if isinstance(origin_context, dict) else {}
    chat_id = origin.get("chat_id")
    message_id = origin.get("message_id")
    has_chat_id_ref = chat_id is not None
    has_message_id_ref = message_id is not None
    is_photo_hint = bool(origin.get("is_photo"))
    kind = str(origin.get("kind") or "due").strip().lower()
    if kind not in {"pre", "due"}:
        kind = "due"

    try:
        postpone_count = int(origin.get("postpone_count") or 0)
    except (TypeError, ValueError):
        postpone_count = 0
    if postpone_count < 0:
        postpone_count = 0

    if chat_id is None:
        chat_id = user_id

    original_time = _parse_iso_datetime(origin.get("original_time"))
    occurrence_time = _parse_iso_datetime(origin.get("occurrence_time"))
    base_payload = {
        "source": "edit_flow",
        "alert_id": str(alert_id or ""),
        "kind": kind,
        "postpone_count": postpone_count,
        "has_chat_id_ref": bool(has_chat_id_ref),
        "has_message_id_ref": bool(has_message_id_ref),
        "is_photo_hint": bool(is_photo_hint),
        "has_original_time": original_time is not None,
        "has_occurrence_time": occurrence_time is not None,
    }
    _log_edit_flow_event(
        storage,
        user_id,
        "edit_notification_restore_attempted",
        base_payload,
    )

    restored = False
    reason_code = "ok"
    if not alert_id:
        reason_code = "missing_alert_id"
    elif message_id is None:
        reason_code = "missing_message_id"
    else:
        try:
            from modules.handlers.scheduler_handlers import _restore_notification_message_view

            restore_outcome = await _restore_notification_message_view(
                context,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                alert_id=alert_id,
                kind=kind,
                original_time=original_time,
                occurrence_time=occurrence_time,
                postpone_count=postpone_count,
                is_photo_hint=is_photo_hint,
                return_result=True,
            )
            if isinstance(restore_outcome, dict):
                restored = bool(restore_outcome.get("success"))
                if restored:
                    reason_code = str(restore_outcome.get("reason_code") or "ok")
                else:
                    reason_code = str(restore_outcome.get("reason_code") or "restore_failed")
            else:
                restored = bool(restore_outcome)
                reason_code = "ok" if restored else "restore_failed"
        except Exception as exc:
            reason_code = _restore_reason_code_from_exception(exc)
            restored = reason_code == "message_not_modified"

    _log_edit_flow_event(
        storage,
        user_id,
        "edit_notification_restore_result",
        {
            **base_payload,
            "success": bool(restored),
            "reason_code": reason_code,
        },
    )
    return {"success": bool(restored), "reason_code": str(reason_code)}


async def _restore_list_origin_message_view(
    context,
    *,
    user_id,
    chat_id,
    message_id,
    alert_id,
    include_back,
    source_hint,
):
    """Rebuild and render list/detail-origin info card in-place after edit completion."""
    if chat_id is None:
        chat_id = user_id
    if chat_id is None or message_id is None:
        return {"success": False, "reason_code": "restore_failed"}

    storage = get_runtime_storage(context)

    alert = storage.get_alert_by_id(user_id, alert_id)
    if not isinstance(alert, dict):
        return {"success": False, "reason_code": "alert_not_found"}

    try:
        user_prefs = storage.get_user_prefs(user_id) or {}
    except Exception:
        user_prefs = {}

    from modules.handlers.list_alerts import build_info_keyboard, format_detailed_card

    normalized_source = _normalize_origin_source_hint(source_hint) or "alerts"
    text = format_detailed_card(alert, user_prefs=user_prefs)
    kb = build_info_keyboard(
        alert_id,
        context,
        source=normalized_source,
        include_back=bool(include_back),
        alert=alert,
    )

    attempted_modes = set()
    last_reason_code = "restore_failed"
    for use_caption in (True, False):
        if use_caption in attempted_modes:
            continue
        attempted_modes.add(use_caption)
        try:
            if use_caption:
                await context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )
            return {"success": True, "reason_code": "ok"}
        except Exception as exc:
            reason_code = _restore_reason_code_from_exception(exc)
            if reason_code == "message_not_modified":
                return {"success": True, "reason_code": "message_not_modified"}
            last_reason_code = reason_code
            if reason_code in {"message_not_found", "chat_not_found", "forbidden"}:
                break
            continue

    return {"success": False, "reason_code": str(last_reason_code)}


async def _cleanup_edit_flow_artifacts(
    context,
    *,
    chat_id,
    keep_message_ids,
    end_message_id=None,
):
    """Delete tracked edit artifacts while preserving required terminal/origin messages."""
    keep_ids = set()
    for raw_id in (keep_message_ids or []):
        try:
            keep_ids.add(int(raw_id))
        except Exception:
            continue

    bot = getattr(context, "bot", None)
    if chat_id is None or bot is None:
        context.user_data["add_flow_message_ids"] = []
        context.user_data["add_flow_start_message_id"] = None
        return

    try:
        await cleanup_add_flow_messages(
            context,
            bot,
            chat_id,
            end_message_id=end_message_id,
            keep_message_ids=keep_ids,
        )
    except Exception:
        context.user_data["add_flow_message_ids"] = []
        context.user_data["add_flow_start_message_id"] = None


async def _finalize_edit_success(
    update,
    context,
    *,
    user_id,
    alert_id,
    origin_context,
    ack_text,
):
    """Finalize edit success by restoring origin view, keeping one terminal message, and cleaning artifacts."""
    from .flow import _send_actor_message

    try:
        storage = get_runtime_storage(context)
    except Exception:
        storage = None

    origin = origin_context if isinstance(origin_context, dict) else {}
    origin_source = str(origin.get("source") or "unknown").strip().lower()
    source_hint = _normalize_origin_source_hint(origin.get("source_hint"))
    include_back = bool(origin.get("include_back"))
    origin_message_id = origin.get("message_id")
    tag_filter = origin.get("tag_filter")

    chat_id = origin.get("chat_id")
    if chat_id is None:
        chat = getattr(update, "effective_chat", None) if update else None
        chat_id = getattr(chat, "id", None)
    if chat_id is None:
        chat_id = user_id

    keep_ids = set()
    if isinstance(origin_message_id, int):
        keep_ids.add(origin_message_id)

    terminal_message = await _send_actor_message(update, context, ack_text)
    terminal_message_id = getattr(terminal_message, "message_id", None)
    if isinstance(terminal_message_id, int):
        keep_ids.add(terminal_message_id)

    if source_hint:
        context.user_data["manage_source"] = source_hint
    _apply_origin_tag_filter(context, source_hint, tag_filter)

    restore_outcome = {"success": True, "reason_code": "skipped"}
    recovery_message = None

    if origin_source == "notification":
        restore_outcome = await _restore_notification_origin_message_view(
            context,
            user_id=user_id,
            alert_id=alert_id,
            origin_context=origin,
        )
        if not restore_outcome.get("success"):
            recovery_message = await _send_actor_message(
                update,
                context,
                "⚠️ I couldn't restore the original notification card. Open the alert again from /alerts or /next.",
            )
    elif origin_source == "list":
        list_payload = {
            "source": "edit_flow",
            "alert_id": str(alert_id or ""),
            "origin_source": "list",
            "source_hint": str(source_hint or ""),
            "include_back": bool(include_back),
            "has_chat_id_ref": origin.get("chat_id") is not None,
            "has_message_id_ref": origin.get("message_id") is not None,
            "is_photo_hint": bool(origin.get("is_photo")),
            "has_tag_filter": tag_filter is not None,
        }
        _log_edit_flow_event(
            storage,
            user_id,
            "edit_list_restore_attempted",
            list_payload,
        )
        restore_outcome = await _restore_list_origin_message_view(
            context,
            user_id=user_id,
            chat_id=chat_id,
            message_id=origin_message_id,
            alert_id=alert_id,
            include_back=include_back,
            source_hint=source_hint,
        )
        _log_edit_flow_event(
            storage,
            user_id,
            "edit_list_restore_result",
            {
                **list_payload,
                "success": bool(restore_outcome.get("success")),
                "reason_code": str(restore_outcome.get("reason_code") or "restore_failed"),
            },
        )
        if not restore_outcome.get("success"):
            recovery_message = await _send_actor_message(
                update,
                context,
                "⚠️ I couldn't restore the original detail card. Open the alert again from /list or /birthdays.",
            )

    recovery_message_id = getattr(recovery_message, "message_id", None)
    if isinstance(recovery_message_id, int):
        keep_ids.add(recovery_message_id)

    await _cleanup_edit_flow_artifacts(
        context,
        chat_id=chat_id,
        keep_message_ids=keep_ids,
        end_message_id=terminal_message_id,
    )
    clear_transient_context(context.user_data)
    return restore_outcome


def _extract_alert_id_from_manage_callback(callback_data):
    prefix = "manage_fulledit_"
    if not isinstance(callback_data, str) or not callback_data.startswith(prefix):
        return None
    alert_id = callback_data.replace(prefix, "", 1).strip()
    if not alert_id:
        return None
    return alert_id
