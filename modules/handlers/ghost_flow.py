"""Handle ghost-reminder picker callbacks from missed-alert summary messages."""

from __future__ import annotations

import logging
import json
import os
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from modules import constants as C
from modules.ghost_utils import create_ghost_alert, find_existing_ghost
from modules.handlers.list_alerts.detail import send_alert_detail_by_id
from modules.scheduler_mathlogic import format_datetime_human, parse_pre_alert_string
from modules.shared.markdown_utils import md_escape
from modules.shared.messages import is_message_not_modified_error
from modules.shared.runtime_context import get_runtime_storage
from modules.shared.storage_metrics import get_user_event_log_paths
from modules.timezone_utils import (
    get_server_tz,
    now_server_naive,
    parse_user_datetime_expression,
)

logger = logging.getLogger(__name__)


def _truncated_title(title: str, max_len: int = 28) -> str:
    return title[:max_len] + "…" if len(title) > max_len else title


def _serialize_markup(reply_markup) -> list[list[dict]]:
    keyboard = getattr(reply_markup, "inline_keyboard", None)
    if not isinstance(keyboard, (list, tuple)):
        return []
    serialized = []
    for row in keyboard:
        if not isinstance(row, (list, tuple)):
            continue
        out_row = []
        for button in row:
            out_row.append({
                "text": getattr(button, "text", ""),
                "callback_data": getattr(button, "callback_data", None),
            })
        serialized.append(out_row)
    return serialized


def _rebuild_markup(snapshot) -> InlineKeyboardMarkup | None:
    if not isinstance(snapshot, list):
        return None
    rows = []
    for row in snapshot:
        if not isinstance(row, list):
            return None
        out_row = []
        for item in row:
            if not isinstance(item, dict):
                return None
            out_row.append(
                InlineKeyboardButton(
                    text=item.get("text") or "",
                    callback_data=item.get("callback_data"),
                )
            )
        rows.append(out_row)
    return InlineKeyboardMarkup(rows)


def _build_picker_keyboard(source_alert_id: str) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(label, callback_data=f"ghost_set_{token}_{source_alert_id}")
        for label, token in C.QUICK_DURATION_OPTIONS
    ]
    return InlineKeyboardMarkup(
        [
            row,
            [InlineKeyboardButton("⚙️ Custom", callback_data=f"ghost_set_cust_{source_alert_id}")],
        ]
    )


def _build_dedup_keyboard(source_alert_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Create another", callback_data=f"ghost_dedup_ok_{source_alert_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"ghost_dedup_no_{source_alert_id}"),
        ]]
    )


def _resolve_missed_date_str(missed_ts: str | None) -> str:
    if not missed_ts:
        return "recently"
    try:
        raw = int(missed_ts)
        if raw <= 0:
            return "recently"
        dt = datetime.fromtimestamp(raw, tz=get_server_tz()).replace(tzinfo=None)
        return format_datetime_human(dt)
    except Exception:
        return "recently"


def _ghost_summary_markup_reason_code(exc: Exception) -> str:
    """Map summary-markup edit failures to stable reason codes without exposing raw exception text."""
    if is_message_not_modified_error(exc):
        return "message_not_modified"
    if isinstance(exc, BadRequest):
        try:
            text = str(exc or "").lower()
        except Exception:
            return "bad_request"
        if "message to edit not found" in text:
            return "message_not_found"
        if "chat not found" in text:
            return "chat_not_found"
        if "forbidden" in text or "bot was blocked by the user" in text:
            return "forbidden"
        return "bad_request"
    return "unexpected_exception"


def _replace_summary_button(snapshot, source_alert_id: str, source_title: str) -> tuple[list[list[dict]] | None, bool]:
    if not isinstance(snapshot, list):
        return None, False
    needle = f"missed_dtl_{source_alert_id}"
    updated = []
    replaced = False
    for row in snapshot:
        if not isinstance(row, list):
            return None, False
        out_row = []
        for item in row:
            if not isinstance(item, dict):
                return None, False
            callback_data = str(item.get("callback_data") or "")
            if callback_data.startswith(needle):
                out_row.append({
                    "text": f"✅ {_truncated_title(source_title)}",
                    "callback_data": f"ghost_noop_{source_alert_id[:8]}",
                })
                replaced = True
            else:
                out_row.append({
                    "text": item.get("text") or "",
                    "callback_data": item.get("callback_data"),
                })
        updated.append(out_row)
    return updated, replaced


async def handle_missed_dtl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open the ghost picker for one missed-summary alert button."""
    query = update.callback_query
    if query is None:
        return

    match = re.fullmatch(r"missed_dtl_([^_]+)(?:_(\d+))?", query.data or "")
    if not match:
        await query.answer("Invalid summary button", show_alert=True)
        return

    source_alert_id, missed_ts = match.group(1), match.group(2)
    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    source_alert = storage.get_alert_by_id(user_id, source_alert_id)
    if not source_alert:
        await query.answer("Source alert not found", show_alert=True)
        return

    summary_msg_id = getattr(query.message, "message_id", None)
    summary_markup_key = f"ghost_summary_markup_{summary_msg_id}" if summary_msg_id is not None else None
    if summary_markup_key:
        context.user_data.setdefault(
            summary_markup_key,
            _serialize_markup(getattr(query.message, "reply_markup", None)),
        )

    title = source_alert.get("title") or "Untitled"
    missed_date_str = _resolve_missed_date_str(missed_ts)
    picker_text = (
        "👻 Ghost Reminder\n"
        f"For: *{md_escape(title)}*\n"
        f"Missed: {md_escape(missed_date_str)}\n\n"
        "When should I remind you?"
    )

    picker_msg = await context.bot.send_message(
        chat_id=user_id,
        text=picker_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_build_picker_keyboard(source_alert_id),
    )

    context.user_data[f"ghost_picker_{source_alert_id}"] = {
        "summary_msg_id": summary_msg_id,
        "summary_markup_key": summary_markup_key,
        "source_title": title,
        "missed_date_str": missed_date_str,
        "source_alert": source_alert,
        "picker_msg_id": getattr(picker_msg, "message_id", None),
    }

    await query.answer()


async def handle_ghost_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a ghost reminder with one quick-duration picker token."""
    query = update.callback_query
    if query is None:
        return

    match = re.fullmatch(r"ghost_set_([^_]+)_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid picker button", show_alert=True)
        return

    token, source_alert_id = match.group(1), match.group(2)
    if token not in {"1h", "1d", "1w"}:
        await query.answer("Invalid duration", show_alert=True)
        return

    delta = parse_pre_alert_string(token)
    now_dt = now_server_naive()
    if not delta:
        await query.answer("Invalid duration", show_alert=True)
        return
    fire_at = now_dt + delta
    if fire_at <= now_server_naive():
        await query.answer("Time must be in the future", show_alert=True)
        return

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    picker_key = f"ghost_picker_{source_alert_id}"
    picker_state = context.user_data.get(picker_key)

    if not isinstance(picker_state, dict):
        source_alert = storage.get_alert_by_id(user_id, source_alert_id)
        if not source_alert:
            await query.answer("Session expired, press the summary button again", show_alert=True)
            return
        picker_state = {
            "summary_msg_id": None,
            "summary_markup_key": None,
            "source_title": source_alert.get("title") or "Untitled",
            "missed_date_str": "recently",
            "source_alert": source_alert,
            "picker_msg_id": getattr(query.message, "message_id", None),
        }
        context.user_data[picker_key] = picker_state

    source_alert = picker_state.get("source_alert")
    if not isinstance(source_alert, dict):
        source_alert = storage.get_alert_by_id(user_id, source_alert_id)
        if not source_alert:
            await query.answer("Session expired, press the summary button again", show_alert=True)
            return
        picker_state["source_alert"] = source_alert

    existing = find_existing_ghost(storage, user_id, source_alert_id)
    if existing:
        context.user_data[f"ghost_dedup_{source_alert_id}"] = fire_at.isoformat()
        await context.bot.send_message(
            chat_id=user_id,
            text="A ghost reminder already exists for this alert. Create another?",
            reply_markup=_build_dedup_keyboard(source_alert_id),
        )
        await query.answer()
        return

    await _do_create_ghost(
        context,
        storage,
        user_id,
        source_alert,
        fire_at,
        picker_state,
        query=query,
    )


async def handle_ghost_set_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch ghost creation to custom datetime input mode."""
    query = update.callback_query
    if query is None:
        return

    match = re.fullmatch(r"ghost_set_cust_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid custom picker", show_alert=True)
        return

    source_alert_id = match.group(1)
    picker_state = context.user_data.get(f"ghost_picker_{source_alert_id}")
    if not isinstance(picker_state, dict):
        await query.answer("Session expired, press the summary button again", show_alert=True)
        return

    context.user_data["expecting_ghost_custom"] = {
        "source_alert_id": source_alert_id,
        "summary_msg_id": picker_state.get("summary_msg_id"),
        "picker_msg_id": getattr(query.message, "message_id", None),
    }

    await query.edit_message_text(
        "✏️ Send me the time/date (e.g. `tomorrow at 9`, `in 3 hours`):",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=None,
    )
    await query.answer()


async def handle_ghost_custom_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse custom ghost time text and create or deduplicate the reminder."""
    state = context.user_data.get("expecting_ghost_custom")
    if not isinstance(state, dict):
        return

    message = update.message
    if message is None:
        return

    source_alert_id = state.get("source_alert_id")
    if not source_alert_id:
        context.user_data.pop("expecting_ghost_custom", None)
        await message.reply_text("Session expired, press the summary button again.")
        return

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    picker_state = context.user_data.get(f"ghost_picker_{source_alert_id}")
    source_alert = None
    if isinstance(picker_state, dict):
        source_alert = picker_state.get("source_alert")
    if not isinstance(source_alert, dict):
        source_alert = storage.get_alert_by_id(user_id, source_alert_id)

    if not isinstance(source_alert, dict):
        context.user_data.pop("expecting_ghost_custom", None)
        await message.reply_text("Session expired, press the summary button again.")
        return

    now_dt = now_server_naive()
    user_prefs = storage.get_user_prefs(user_id)
    status, fire_at, _meta = parse_user_datetime_expression(
        (message.text or "").strip(),
        reference_server_dt=now_dt,
        user_prefs=user_prefs,
        default_time=now_dt.strftime("%H:%M"),
        allow_relative_tokens=True,
        allow_day_only=False,
        boundary_mode="future",
        now_server_dt=now_dt,
    )
    if status != "ok" or fire_at is None:
        await message.reply_text(
            "I couldn't parse that date/time. Try examples like: tomorrow at 9, in 3 hours."
        )
        return

    if fire_at <= now_server_naive():
        await message.reply_text("Time must be in the future.")
        return

    if find_existing_ghost(storage, user_id, source_alert_id):
        context.user_data[f"ghost_dedup_{source_alert_id}"] = fire_at.isoformat()
        context.user_data.pop("expecting_ghost_custom", None)
        await context.bot.send_message(
            chat_id=user_id,
            text="A ghost reminder already exists for this alert. Create another?",
            reply_markup=_build_dedup_keyboard(source_alert_id),
        )
        return

    if not isinstance(picker_state, dict):
        picker_state = {
            "summary_msg_id": state.get("summary_msg_id"),
            "summary_markup_key": f"ghost_summary_markup_{state.get('summary_msg_id')}"
            if state.get("summary_msg_id") is not None
            else None,
            "source_title": source_alert.get("title") or "Untitled",
            "missed_date_str": "recently",
            "source_alert": source_alert,
            "picker_msg_id": state.get("picker_msg_id"),
        }
        context.user_data[f"ghost_picker_{source_alert_id}"] = picker_state

    await _do_create_ghost(
        context,
        storage,
        user_id,
        source_alert,
        fire_at,
        picker_state,
        message_update=message,
    )


async def handle_ghost_dedup_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm duplicate ghost creation after explicit user approval."""
    query = update.callback_query
    if query is None:
        return

    match = re.fullmatch(r"ghost_dedup_ok_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid action", show_alert=True)
        return

    source_alert_id = match.group(1)
    fire_at_iso = context.user_data.pop(f"ghost_dedup_{source_alert_id}", None)
    if not fire_at_iso:
        await query.answer("Session expired, press the summary button again", show_alert=True)
        return

    try:
        fire_at = datetime.fromisoformat(fire_at_iso)
    except Exception:
        await query.answer("Session expired, press the summary button again", show_alert=True)
        return

    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    picker_state = context.user_data.get(f"ghost_picker_{source_alert_id}")
    source_alert = picker_state.get("source_alert") if isinstance(picker_state, dict) else None
    if not isinstance(source_alert, dict):
        source_alert = storage.get_alert_by_id(user_id, source_alert_id)
    if not isinstance(source_alert, dict):
        await query.answer("Source alert not found", show_alert=True)
        return

    if not isinstance(picker_state, dict):
        picker_state = {
            "summary_msg_id": None,
            "summary_markup_key": None,
            "source_title": source_alert.get("title") or "Untitled",
            "missed_date_str": "recently",
            "source_alert": source_alert,
            "picker_msg_id": None,
        }

    await _do_create_ghost(
        context,
        storage,
        user_id,
        source_alert,
        fire_at,
        picker_state,
        query=query,
    )


async def handle_ghost_dedup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel duplicate ghost creation and clear in-memory picker state."""
    query = update.callback_query
    if query is None:
        return

    match = re.fullmatch(r"ghost_dedup_no_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid action", show_alert=True)
        return

    source_alert_id = match.group(1)
    context.user_data.pop(f"ghost_picker_{source_alert_id}", None)
    context.user_data.pop(f"ghost_dedup_{source_alert_id}", None)
    context.user_data.pop("expecting_ghost_custom", None)
    await query.answer("Ghost creation cancelled.")


async def handle_ghost_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Acknowledge no-op ghost summary buttons after creation."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()


def _find_deletion_ts(storage, user_id: int, source_id: str) -> str | None:
    paths = get_user_event_log_paths(storage, user_id)
    for path in sorted(
        paths,
        key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
        reverse=True,
    ):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except Exception:
            continue
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except Exception:
                continue
            if record.get("event") != "alert_deleted":
                continue
            payload = record.get("payload") or {}
            if str(payload.get("alert_id")) == str(source_id):
                ts = record.get("ts")
                if isinstance(ts, str) and ts.strip():
                    return ts.strip()
    return None


async def handle_ghost_noted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Acknowledge ghost notification noted action without mutating storage."""
    query = update.callback_query
    if query is None:
        return
    await query.answer("✅ Noted")


async def handle_ghost_dtl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open source alert details or explain source deletion for a ghost notification."""
    query = update.callback_query
    if query is None:
        return
    match = re.fullmatch(r"ghost_dtl_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid action", show_alert=True)
        return
    ghost_id = match.group(1)
    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    ghost = storage.get_alert_by_id(user_id, ghost_id)
    if not ghost:
        await query.answer("Ghost reminder not found", show_alert=True)
        return
    source_id = ghost.get("ghost_source_id")
    source = storage.get_alert_by_id(user_id, source_id) if source_id else None
    if source:
        await query.answer()
        await send_alert_detail_by_id(update, context, source_id, include_back=False)
        return
    deletion_ts = _find_deletion_ts(storage, user_id, str(source_id or ""))
    if deletion_ts:
        text = (
            "ℹ️ *Original alert was deleted*\n"
            f"_Deleted on: {md_escape(deletion_ts)}_"
        )
    else:
        text = (
            "ℹ️ *Original alert was deleted*\n"
            "_Deletion date not recorded._"
        )
    await query.answer()
    await context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.MARKDOWN)


async def handle_ghost_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show delete-confirmation prompt for a ghost notification."""
    query = update.callback_query
    if query is None:
        return
    match = re.fullmatch(r"ghost_del_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid action", show_alert=True)
        return
    ghost_id = match.group(1)
    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    ghost = storage.get_alert_by_id(user_id, ghost_id)
    if not ghost:
        await query.answer("Ghost already deleted", show_alert=True)
        return
    context.user_data[f"ghost_delete_markup_{ghost_id}"] = _serialize_markup(
        getattr(query.message, "reply_markup", None)
    )
    title = md_escape(ghost.get("title") or "Untitled")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, delete", callback_data=f"ghost_del_ok_{ghost_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"ghost_del_no_{ghost_id}"),
    ]])
    try:
        await query.edit_message_text(
            f"🗑️ Delete this ghost reminder?\n_{title}_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
    except BadRequest as exc:
        logger.debug("Ghost del prompt edit failed: %s", exc)
    await query.answer()


async def handle_ghost_del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete ghost alert after explicit confirmation and remove confirmation state."""
    query = update.callback_query
    if query is None:
        return
    match = re.fullmatch(r"ghost_del_ok_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid action", show_alert=True)
        return
    ghost_id = match.group(1)
    storage = get_runtime_storage(context)
    user_id = update.effective_user.id
    ghost = storage.get_alert_by_id(user_id, ghost_id)
    if not ghost:
        await query.answer("Already deleted")
        return
    storage.delete_alert(user_id, ghost_id)
    storage.log_user_event(user_id, "ghost_deleted", {
        "ghost_id": ghost_id,
        "source_id": ghost.get("ghost_source_id"),
    })
    context.user_data.pop(f"ghost_delete_markup_{ghost_id}", None)
    await query.edit_message_text("🗑️ Ghost reminder deleted.", reply_markup=None)
    await query.answer("Deleted")


async def handle_ghost_del_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restore original ghost notification keyboard after delete cancellation."""
    query = update.callback_query
    if query is None:
        return
    match = re.fullmatch(r"ghost_del_no_(.+)", query.data or "")
    if not match:
        await query.answer("Invalid action", show_alert=True)
        return
    ghost_id = match.group(1)
    snapshot = context.user_data.pop(f"ghost_delete_markup_{ghost_id}", None)
    markup = _rebuild_markup(snapshot)
    try:
        if markup is None:
            await query.edit_message_text("Deletion cancelled.", reply_markup=None)
        else:
            await query.edit_message_reply_markup(reply_markup=markup)
    except BadRequest as exc:
        logger.debug("Ghost del cancel restore failed: %s", exc)
    await query.answer()


async def _do_create_ghost(
    context: ContextTypes.DEFAULT_TYPE,
    storage,
    user_id: int,
    source_alert: dict,
    fire_at: datetime,
    picker_state: dict,
    *,
    query=None,
    message_update=None,
):
    source_alert_id = str(source_alert.get("id") or "")
    missed_date_str = picker_state.get("missed_date_str") or "recently"
    ghost_id = create_ghost_alert(storage, user_id, source_alert, fire_at, missed_date_str)
    if ghost_id is None:
        if query is not None:
            await query.answer("Failed to create ghost reminder", show_alert=True)
        elif message_update is not None:
            await message_update.reply_text("Failed to create ghost reminder.")
        return

    context.user_data.pop(f"ghost_picker_{source_alert_id}", None)
    context.user_data.pop(f"ghost_dedup_{source_alert_id}", None)
    context.user_data.pop("expecting_ghost_custom", None)

    summary_msg_id = picker_state.get("summary_msg_id")
    summary_key = picker_state.get("summary_markup_key")
    snapshot = context.user_data.get(summary_key) if summary_key else None
    if summary_msg_id and summary_key:
        updated_snapshot, replaced = _replace_summary_button(
            snapshot,
            source_alert_id,
            source_alert.get("title") or "Untitled",
        )
        if updated_snapshot is None:
            logger.warning(
                "ghost_summary_snapshot_invalid",
                extra={"user_id": user_id, "source_alert_id": source_alert_id, "summary_msg_id": summary_msg_id},
            )
        elif replaced:
            context.user_data[summary_key] = updated_snapshot
            markup = _rebuild_markup(updated_snapshot)
            if markup is not None:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=user_id,
                        message_id=summary_msg_id,
                        reply_markup=markup,
                    )
                except BadRequest as exc:
                    reason_code = _ghost_summary_markup_reason_code(exc)
                    payload = {
                        "reason_code": reason_code,
                        "error_class": type(exc).__name__,
                        "summary_msg_id": summary_msg_id,
                        "snapshot_is_none": snapshot is None,
                        "replaced": replaced,
                        "markup_is_none": markup is None,
                    }
                    if reason_code == "message_not_modified":
                        logger.debug("ghost_summary_markup_update_noop", extra=payload)
                    else:
                        logger.warning(
                            "ghost_summary_markup_update_failed",
                            extra=payload,
                        )
                except Exception as exc:
                    reason_code = _ghost_summary_markup_reason_code(exc)
                    logger.warning(
                        "ghost_summary_markup_update_failed",
                        extra={
                            "reason_code": reason_code,
                            "error_class": type(exc).__name__,
                            "summary_msg_id": summary_msg_id,
                            "snapshot_is_none": snapshot is None,
                            "replaced": replaced,
                            "markup_is_none": markup is None,
                        },
                    )

    picker_msg_id = picker_state.get("picker_msg_id")
    if picker_msg_id:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=picker_msg_id)
        except Exception as exc:
            logger.warning("Ghost picker delete failed: %s", exc)

    fire_text = format_datetime_human(fire_at)
    if query is not None:
        query_msg_id = getattr(query.message, "message_id", None)
        is_from_dedup_dialog = (
            query_msg_id is not None and query_msg_id != picker_msg_id
        )
        if is_from_dedup_dialog:
            try:
                await query.edit_message_text(
                    f"✅ Ghost reminder set for {fire_text}",
                    reply_markup=None,
                )
            except BadRequest as exc:
                logger.debug("Ghost dedup confirm edit failed: %s", exc)
        await query.answer(f"✅ Ghost reminder set for {fire_text}")
    elif message_update is not None:
        await message_update.reply_text(
            f"✅ Ghost reminder set for `{md_escape(fire_text)}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    storage.log_user_event(
        user_id,
        "ghost_created",
        {
            "ghost_id": ghost_id,
            "source_alert_id": source_alert_id,
            "fire_at": fire_at.isoformat(),
        },
    )
