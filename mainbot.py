import os
import logging
import time
import traceback
import fcntl
import asyncio
import inspect
from html import escape as html_escape
from types import SimpleNamespace
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, BotCommand, BotCommandScopeChat
from telegram.error import NetworkError, TimedOut, RetryAfter
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ApplicationHandlerStop,
    TypeHandler,
    filters,
)
from modules.storage import StorageManager
from modules.handlers.add_alert import (
    LEGACY_REVIEW_CALLBACK_PATTERN,
    add_alert_handler,
    handle_legacy_review_callback,
)
from modules.handlers.alerts import alerts_start, alert_search_start, alert_search_from_text
from modules.handlers.list_alerts import list_alerts_start, show_alerts_list, handle_management
from modules.handlers.list_alerts import handle_edit_text_input
from modules.handlers.edit_flow.flow import edit_alert_handler
from modules.handlers.shortcut_router import handle_dynamic_shortcut_command
from modules.handlers.base import (
    start,
    handle_start_request_callback,
    help_command,
    handle_help_callback,
    status,
    cancel,
    settings,
    START_REQUEST_MAX_MESSAGE_CHARS,
    _start_request_pending_text,
    _start_request_pending_keyboard,
    handle_settings_callback,
    build_mail_backup_status,
    build_birthday_time_status,
    build_birthday_bulk_import_decision_keyboard,
    handle_timezone_query_input,
    handle_timezone_location_input,
    normalize_time_input,
    register_conversation_handler,
)
from modules.handlers.next_alerts import show_next_alerts
from modules.handlers.birthdays import (
    birthday_start,
    handle_birthday_menu,
    birthday_add_handler,
    birthday_list_start,
    show_birthdays_list,
    birthday_search_from_text,
)
from modules.handlers.tags_dashboard import tags_dashboard_start, handle_tag_callbacks
from modules.handlers.birthday_flow.bulk_birthdays import (
    analyze_import_tags,
    build_import_preview_blocks,
    parse_bulk_birthday_message,
)
from modules.backup_core.email_backup import estimate_email_backup_size_bytes, normalize_email_address
from modules.handlers.export_import import (
    handle_import_document_upload,
)
from modules.handlers.admin import (
    handle_admin_callback,
)
from modules.handlers.developer import (
    handle_developer_callback,
)
from modules.handlers.manage import (
    manage_dashboard_start,
    handle_manage_callback,
)
from modules.tags_logic import normalize_tag_input, validate_tag_format
from modules import scheduler
from modules import constants as C
from modules.systemlog import log_system, log_downtime_summary, mark_runtime_shutdown
from modules.telegram_resilience import (
    ApiFailureTracker,
    is_message_not_modified_error,
    run_with_retry,
)
from modules.handlers.scheduler_handlers import (
    get_scheduler_handlers,
    handle_custom_postpone_input
)
from modules.handlers.ghost_flow import (
    handle_ghost_custom_text,
    handle_ghost_dedup_cancel,
    handle_ghost_dedup_confirm,
    handle_ghost_del,
    handle_ghost_del_cancel,
    handle_ghost_del_confirm,
    handle_ghost_dtl,
    handle_ghost_noop,
    handle_ghost_noted,
    handle_ghost_set,
    handle_ghost_set_custom,
    handle_missed_dtl,
)
from modules.shared.context_cleanup import has_transient_context
from modules.shared.paths import DATA_DIR, PROJECT_ROOT, SYSTEM_LOG_DIR, WHITELIST_PATH, token_global_lock_path, token_lock_hash_prefix
from modules.shared.logging_utils import text_meta
from modules.shared.acting_as import build_acting_as_payload, get_target_user_id
from modules.shared.runtime_context import BotRuntime, set_bot_runtime
from modules.security.authz import get_role_map
from modules.security.whitelist_store import reconcile_startup_whitelist


# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("TELEGRAM_USER_ID")

# 1. Initialize Storage once with Admin ID
storage = StorageManager(base_data_dir=DATA_DIR, admin_id=ADMIN_ID)

# 2. Setup System Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
BOT_LOCK_HANDLES = {}
API_FAILURE_TRACKER = ApiFailureTracker(
    window_seconds=C.API_FAILURE_WINDOW_SECONDS,
    user_threshold=C.API_FAILURE_USER_THRESHOLD,
    global_threshold=C.API_FAILURE_GLOBAL_THRESHOLD,
)
_POLLING_NETWORK_STATE = {
    "window_start_mono": None,
    "window_start_ts": None,
    "error_count": 0,
    "immediate_warning_count": 0,
    "rollup_count": 0,
    "last_rollup_mono": None,
    "last_error_mono": None,
    "last_error_ts": None,
    "last_error_type": None,
}


def _safe_positive_int(value, default):
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return parsed if parsed > 0 else int(default)


def _reset_polling_network_window(now_mono=None, now_ts=None):
    global _POLLING_NETWORK_STATE
    _POLLING_NETWORK_STATE = {
        "window_start_mono": now_mono,
        "window_start_ts": now_ts,
        "error_count": 0,
        "immediate_warning_count": 0,
        "rollup_count": 0,
        "last_rollup_mono": None,
        "last_error_mono": None,
        "last_error_ts": None,
        "last_error_type": None,
    }
    return _POLLING_NETWORK_STATE


def _emit_polling_network_rollup(now_mono, *, force=False):
    state = _POLLING_NETWORK_STATE
    if state["window_start_mono"] is None:
        return False
    suppressed_total = max(0, int(state["error_count"]) - int(state["immediate_warning_count"]))
    if suppressed_total <= 0:
        return False

    min_interval = _safe_positive_int(
        getattr(C, "POLLING_NETWORK_ROLLUP_MIN_INTERVAL_SECONDS", 60),
        60,
    )
    if not force and state["last_rollup_mono"] is not None:
        if (now_mono - state["last_rollup_mono"]) < min_interval:
            return False

    window_elapsed = max(0, int(now_mono - state["window_start_mono"]))
    log_system("api", "polling_network_error_rollup", {
        "window_start_ts": state["window_start_ts"],
        "window_elapsed_seconds": window_elapsed,
        "window_error_count": int(state["error_count"]),
        "window_immediate_warning_count": int(state["immediate_warning_count"]),
        "suppressed_total": suppressed_total,
        "rollup_index": int(state["rollup_count"]) + 1,
        "last_error_ts": state["last_error_ts"],
        "last_error_type": state["last_error_type"],
    }, level="WARNING")
    state["last_rollup_mono"] = now_mono
    state["rollup_count"] += 1
    return True


def _emit_polling_network_recovered(now_mono, quiet_seconds, *, recovery_source=None, operation=None):
    state = _POLLING_NETWORK_STATE
    if state["window_start_mono"] is None or state["error_count"] <= 0:
        return
    burst_seconds = 0
    if state["last_error_mono"] is not None:
        burst_seconds = max(0, int(state["last_error_mono"] - state["window_start_mono"]))
    log_system("api", "polling_network_recovered", {
        "quiet_seconds": max(0, int(quiet_seconds)),
        "window_start_ts": state["window_start_ts"],
        "last_error_ts": state["last_error_ts"],
        "burst_error_count": int(state["error_count"]),
        "burst_immediate_warning_count": int(state["immediate_warning_count"]),
        "burst_rollup_count": int(state["rollup_count"]),
        "burst_duration_seconds": burst_seconds,
        "last_error_type": state["last_error_type"],
        "recovery_source": recovery_source or "error_path",
        "operation": operation,
    })


def _maybe_close_polling_network_window_on_success(operation):
    state = _POLLING_NETWORK_STATE
    if state["window_start_mono"] is None or state["error_count"] <= 0:
        return False
    if state["last_error_mono"] is None:
        return False

    recovery_quiet_seconds = _safe_positive_int(
        getattr(C, "POLLING_NETWORK_RECOVERY_QUIET_SECONDS", 180),
        180,
    )
    now_mono = time.monotonic()
    quiet_seconds = now_mono - state["last_error_mono"]
    if quiet_seconds < recovery_quiet_seconds:
        return False

    _emit_polling_network_rollup(now_mono, force=True)
    _emit_polling_network_recovered(
        now_mono,
        quiet_seconds,
        recovery_source="api_success",
        operation=operation,
    )
    _reset_polling_network_window()
    return True


def _handle_polling_network_error(err):
    now_mono = time.monotonic()
    now_ts = datetime.now().isoformat()
    state = _POLLING_NETWORK_STATE

    window_seconds = _safe_positive_int(
        getattr(C, "POLLING_NETWORK_ERROR_WINDOW_SECONDS", 300),
        300,
    )
    immediate_cap = _safe_positive_int(
        getattr(C, "POLLING_NETWORK_MAX_IMMEDIATE_WARNINGS", 3),
        3,
    )
    recovery_quiet_seconds = _safe_positive_int(
        getattr(C, "POLLING_NETWORK_RECOVERY_QUIET_SECONDS", 180),
        180,
    )

    if state["window_start_mono"] is not None and state["last_error_mono"] is not None:
        quiet_seconds = now_mono - state["last_error_mono"]
        if quiet_seconds >= recovery_quiet_seconds:
            _emit_polling_network_rollup(now_mono, force=True)
            _emit_polling_network_recovered(
                now_mono,
                quiet_seconds,
                recovery_source="error_path",
                operation="polling_update",
            )
            state = _reset_polling_network_window()

    if state["window_start_mono"] is not None:
        if (now_mono - state["window_start_mono"]) >= window_seconds:
            _emit_polling_network_rollup(now_mono, force=True)
            state = _reset_polling_network_window()

    if state["window_start_mono"] is None:
        state = _reset_polling_network_window(now_mono=now_mono, now_ts=now_ts)

    state["error_count"] += 1
    state["last_error_mono"] = now_mono
    state["last_error_ts"] = now_ts
    state["last_error_type"] = err.__class__.__name__

    if state["immediate_warning_count"] < immediate_cap:
        state["immediate_warning_count"] += 1
        log_system("api", "polling_network_error", {
            "error": str(err),
            "type": err.__class__.__name__,
            "window_start_ts": state["window_start_ts"],
            "window_elapsed_seconds": max(0, int(now_mono - state["window_start_mono"])),
            "window_error_count": int(state["error_count"]),
            "immediate_warning_index": int(state["immediate_warning_count"]),
            "immediate_warning_cap": immediate_cap,
        }, level="WARNING")
        return

    _emit_polling_network_rollup(now_mono, force=False)


def _record_runtime_shutdown(clean, reason):
    payload = {
        "timestamp": datetime.now().isoformat(),
        "clean": bool(clean),
        "reason": reason,
    }
    try:
        mark_runtime_shutdown(clean=bool(clean))
    except Exception:
        pass
    try:
        log_system("lifecycle", "shutdown", payload)
    except Exception:
        pass


def _read_lock_holder_pid(lock_file):
    try:
        lock_file.seek(0)
        raw = lock_file.read().strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _acquire_named_lock(scope, lock_path, extra_payload=None):
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock_file = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        payload = {
            "scope": scope,
            "lock_file": lock_path,
            "pid": _read_lock_holder_pid(lock_file),
        }
        if extra_payload:
            payload.update(extra_payload)
        log_system("lifecycle", "mainbot_lock_conflict", payload, level="WARNING")
        try:
            lock_file.close()
        except Exception:
            pass
        return False, payload

    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    BOT_LOCK_HANDLES[scope] = lock_file
    payload = {
        "scope": scope,
        "lock_file": lock_path,
        "pid": os.getpid(),
    }
    if extra_payload:
        payload.update(extra_payload)
    log_system("lifecycle", "mainbot_lock_acquired", payload)
    return True, payload


def _release_named_lock(scope):
    lock_file = BOT_LOCK_HANDLES.pop(scope, None)
    if not lock_file:
        return
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        lock_file.close()
    except Exception:
        pass


def acquire_single_instance_lock(token):
    """Ensure only one mainbot process runs at once per worktree and per token."""
    token_hash = token_lock_hash_prefix(token)
    local_lock_path = os.path.join(SYSTEM_LOG_DIR, "mainbot.lock")
    global_lock_path = token_global_lock_path(token)

    ok_local, payload_local = _acquire_named_lock(
        "local",
        local_lock_path,
    )
    if not ok_local:
        return False, payload_local

    ok_global, payload_global = _acquire_named_lock(
        "token_global",
        global_lock_path,
        extra_payload={"token_hash_prefix": token_hash},
    )
    if not ok_global:
        _release_named_lock("local")
        return False, payload_global

    return True, {
        "token_hash_prefix": token_hash,
        "local_lock_file": local_lock_path,
        "global_lock_file": global_lock_path,
    }


def release_single_instance_lock():
    """Release both global and local process locks for this bot instance."""
    _release_named_lock("token_global")
    _release_named_lock("local")

def _compact_text(text, max_len=200):
    if text is None:
        return None
    single_line = " ".join(str(text).split())
    if len(single_line) <= max_len:
        return single_line
    return single_line[: max_len - 3] + "..."


def _parse_iso(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _get_active_acting_lock(user_id):
    if user_id is None:
        return None
    meta = storage.get_user_meta(user_id) or {}
    lock = meta.get("acting_as_lock")
    if not isinstance(lock, dict):
        return None
    expires_at = _parse_iso(lock.get("expires_at"))
    if expires_at and expires_at <= datetime.now():
        storage.update_user_meta(user_id, {"acting_as_lock": None})
        return None
    return lock


def _coerce_chat_id(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lstrip("-").isdigit():
        try:
            return int(text)
        except ValueError:
            return text
    return text


def _get_scoped_command_targets():
    try:
        from modules.security.whitelist_store import list_whitelist_users
        from modules.security.roles import normalize_role
    except Exception as exc:
        log_system("api", "set_my_commands_scoped_failed", {
            "reason": "whitelist_import_failed",
            "error": str(exc),
            "error_type": exc.__class__.__name__,
        }, level="WARNING")
        return [], []

    role_by_chat = {}
    try:
        for entry in list_whitelist_users():
            if not isinstance(entry, dict):
                continue
            role = normalize_role(entry.get("role"))
            chat_id = _coerce_chat_id(entry.get("id"))
            if chat_id is None:
                continue
            is_privileged = role in {"admin", "developer"}
            # Privileged role wins when duplicate entries exist for the same chat id.
            role_by_chat[chat_id] = bool(role_by_chat.get(chat_id, False) or is_privileged)
    except Exception as exc:
        log_system("api", "set_my_commands_scoped_failed", {
            "reason": "whitelist_load_failed",
            "error": str(exc),
            "error_type": exc.__class__.__name__,
        }, level="WARNING")
        return [], []

    privileged_targets = []
    standard_targets = []
    for chat_id, privileged in role_by_chat.items():
        if privileged:
            privileged_targets.append(chat_id)
        else:
            standard_targets.append(chat_id)
    return privileged_targets, standard_targets


def _is_read_only_command(text):
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False
    cmd = stripped.split()[0]
    cmd = cmd.split("@")[0][1:].lower()
    return cmd in {"help", "status", "start"}


def _has_active_interactive_context(user_data):
    return has_transient_context(user_data)


async def _run_implicit_cancel_if_active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Run base `/cancel` behavior only when transient context is active and return whether cancel ran."""
    if context is None:
        return False
    user_data = getattr(context, "user_data", None)
    if not _has_active_interactive_context(user_data):
        return False
    await cancel(update, context)
    return True


def _wrap_with_implicit_pre_cancel(handler):
    """Return a command handler wrapper that executes implicit pre-cancel before delegating."""

    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        await _run_implicit_cancel_if_active(update, context)
        return await handler(update, context, *args, **kwargs)

    return wrapped


def _log_startup_user_scope_telemetry(authorized_users=None):
    try:
        dataset_users_raw = storage.get_all_dataset_users(raise_on_error=True)
        authorized_users_raw = authorized_users if authorized_users is not None else storage.get_all_users()
    except Exception as exc:
        log_system("lifecycle", "startup_scope_snapshot_failed", {
            "reason_code": "user_scan_failed",
            "error": str(exc),
            "error_type": exc.__class__.__name__,
        }, level="WARNING")
        return None

    dataset_users = sorted({str(uid) for uid in (dataset_users_raw or [])})
    authorized_user_ids = sorted({str(uid) for uid in (authorized_users_raw or [])})
    authorized_set = set(authorized_user_ids)
    excluded_ids = [uid for uid in dataset_users if uid not in authorized_set]

    auth_filter_enabled = bool(getattr(storage, "admin_id", None))
    warning_threshold = _coerce_non_negative_int(
        getattr(C, "STARTUP_SCOPE_WARNING_EXCLUDED_USERS", 5),
        5,
    )
    sample_size = _safe_positive_int(
        getattr(C, "STARTUP_SCOPE_EXCLUDED_SAMPLE_SIZE", 5),
        5,
    )
    excluded_sample = excluded_ids[:sample_size]
    excluded_count = len(excluded_ids)

    warning_suppressed_reason = None
    if not auth_filter_enabled:
        warning_suppressed_reason = "auth_filter_disabled"
    elif excluded_count <= 0:
        warning_suppressed_reason = "no_excluded_users"
    elif excluded_count < warning_threshold:
        warning_suppressed_reason = "below_threshold"

    payload = {
        "dataset_users": len(dataset_users),
        "authorized_users": len(authorized_user_ids),
        "excluded_users": excluded_count,
        "excluded_user_ids_sample": excluded_sample,
        "excluded_sample_size": sample_size,
        "excluded_sample_truncated": excluded_count > len(excluded_sample),
        "warning_threshold": warning_threshold,
        "auth_filter_enabled": auth_filter_enabled,
        "warning_suppressed_reason": warning_suppressed_reason,
    }
    log_system("lifecycle", "startup_scope_snapshot", payload)

    if auth_filter_enabled and excluded_count > 0 and excluded_count >= warning_threshold:
        log_system("lifecycle", "startup_scope_warning", payload, level="WARNING")

    return payload


async def _run_api_with_retry(operation, chat_id, call_coro_factory):
    result = await run_with_retry(
        operation=operation,
        chat_id=chat_id,
        call_coro_factory=call_coro_factory,
        log_callback=log_system,
        tracker=API_FAILURE_TRACKER,
        attempts=C.TELEGRAM_RETRY_ATTEMPTS,
        max_window_seconds=C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS,
        base_delay_seconds=C.TELEGRAM_RETRY_BASE_DELAY_SECONDS,
        max_delay_seconds=C.TELEGRAM_RETRY_MAX_DELAY_SECONDS,
    )
    _maybe_close_polling_network_window_on_success(operation)
    return result


def _extract_api_context(operation, orig_method, args, kwargs):
    chat_id = kwargs.get("chat_id")
    text = kwargs.get("text")
    caption = kwargs.get("caption")
    message_id = kwargs.get("message_id")
    inline_message_id = kwargs.get("inline_message_id")

    try:
        bound = inspect.signature(orig_method).bind_partial(None, *args, **kwargs)
        chat_id = chat_id if chat_id is not None else bound.arguments.get("chat_id")
        text = text if text is not None else bound.arguments.get("text")
        caption = caption if caption is not None else bound.arguments.get("caption")
        message_id = message_id if message_id is not None else bound.arguments.get("message_id")
        inline_message_id = (
            inline_message_id
            if inline_message_id is not None
            else bound.arguments.get("inline_message_id")
        )
    except Exception:
        pass

    # Fallback compatibility for legacy positional order: (chat_id, message_id, text)
    if (
        operation == "edit_message_text"
        and "text" not in kwargs
        and "chat_id" not in kwargs
        and len(args) >= 3
        and isinstance(args[0], int)
        and isinstance(args[1], int)
        and isinstance(args[2], str)
    ):
        chat_id = args[0]
        message_id = args[1]
        text = args[2]

    # Fallback extraction for methods with optional positional caption.
    if operation == "send_document":
        if chat_id is None and len(args) >= 1:
            chat_id = args[0]
        if caption is None and len(args) >= 3 and isinstance(args[2], str):
            caption = args[2]

    # Legacy fallback: (chat_id, message_id, caption)
    if (
        operation == "edit_message_caption"
        and "caption" not in kwargs
        and "chat_id" not in kwargs
        and len(args) >= 3
        and isinstance(args[0], int)
        and isinstance(args[1], int)
        and isinstance(args[2], str)
    ):
        chat_id = args[0]
        message_id = args[1]
        caption = args[2]
    elif operation == "edit_message_caption":
        if caption is None and len(args) >= 1 and isinstance(args[0], str):
            caption = args[0]
        if chat_id is None and len(args) >= 2 and isinstance(args[1], (int, str)):
            chat_id = args[1]
        if message_id is None and len(args) >= 3 and isinstance(args[2], int):
            message_id = args[2]

    if operation == "edit_message_reply_markup":
        if chat_id is None and len(args) >= 1 and isinstance(args[0], (int, str)):
            chat_id = args[0]
        if message_id is None and len(args) >= 2 and isinstance(args[1], int):
            message_id = args[1]

    return {
        "chat_id": chat_id,
        "text": text,
        "caption": caption,
        "message_id": message_id,
        "inline_message_id": inline_message_id,
    }


def _coerce_non_negative_int(value, fallback):
    try:
        parsed = int(value)
    except Exception:
        return int(fallback)
    if parsed < 0:
        return int(fallback)
    return parsed


def _maybe_log_api_call_slow(operation, chat_id, duration_ms, *, message_id=None, inline_message_id=None):
    threshold_ms = _coerce_non_negative_int(
        getattr(C, "API_SLOW_CALL_THRESHOLD_MS", 2000),
        2000,
    )
    if duration_ms < threshold_ms:
        return

    log_system("api", "api_call_slow", {
        "operation": operation,
        "chat_id": str(chat_id) if chat_id is not None else None,
        "message_id": message_id,
        "inline_message_id": inline_message_id,
        "duration_ms": int(duration_ms),
        "threshold_ms": threshold_ms,
    }, level="WARNING")


def _resolve_original_method(bot_class, original_attr, current_method):
    stored = getattr(bot_class, original_attr, None)
    if callable(stored) and not getattr(stored, "_resilience_wrapper", False):
        return stored
    if getattr(current_method, "_resilience_wrapper", False):
        wrapped_orig = getattr(current_method, "_orig_method", None)
        if callable(wrapped_orig):
            return wrapped_orig
    return current_method


def _install_bot_api_wrappers(application):
    """
    Idempotently wraps high-volume Telegram bot methods with retry + telemetry.
    """
    bot_class = type(application.bot)
    required_methods = [
        "send_message",
        "send_photo",
        "edit_message_text",
        "send_document",
        "edit_message_caption",
        "edit_message_reply_markup",
    ]
    if getattr(bot_class, "_logging_wrapped", False):
        fully_wrapped = all(
            callable(getattr(bot_class, name, None))
            and getattr(getattr(bot_class, name), "_resilience_wrapper", False)
            for name in required_methods
        )
        if fully_wrapped:
            return

    current_send_message = bot_class.send_message
    current_send_photo = bot_class.send_photo
    current_edit_message_text = bot_class.edit_message_text
    current_send_document = bot_class.send_document
    current_edit_message_caption = bot_class.edit_message_caption
    current_edit_message_reply_markup = bot_class.edit_message_reply_markup

    orig_send_message = _resolve_original_method(
        bot_class, "_orig_send_message", current_send_message
    )
    orig_send_photo = _resolve_original_method(
        bot_class, "_orig_send_photo", current_send_photo
    )
    orig_edit_message_text = _resolve_original_method(
        bot_class, "_orig_edit_message_text", current_edit_message_text
    )
    orig_send_document = _resolve_original_method(
        bot_class, "_orig_send_document", current_send_document
    )
    orig_edit_message_caption = _resolve_original_method(
        bot_class, "_orig_edit_message_caption", current_edit_message_caption
    )
    orig_edit_message_reply_markup = _resolve_original_method(
        bot_class, "_orig_edit_message_reply_markup", current_edit_message_reply_markup
    )

    async def send_message_logged(self, *args, **kwargs):
        call_ctx = _extract_api_context("send_message", orig_send_message, args, kwargs)
        chat_id = call_ctx["chat_id"]
        text = call_ctx["text"]
        start_time = time.monotonic()
        try:
            msg = await _run_api_with_retry(
                "send_message",
                chat_id,
                lambda: orig_send_message(self, *args, **kwargs),
            )
            ok = True
            return msg
        except Exception as e:
            ok = False
            log_system("api", "send_message_failed", {
                "chat_id": str(chat_id),
                "error": str(e),
                "degraded": API_FAILURE_TRACKER.snapshot(chat_id),
            }, level="ERROR")
            raise
        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log_system("api", "send_message", {
                "chat_id": str(chat_id),
                "ok": ok,
                "duration_ms": duration_ms,
            })
            _maybe_log_api_call_slow("send_message", chat_id, duration_ms)
            try:
                if chat_id is not None and ok:
                    text_info = text_meta(text)
                    storage.log_user_event(chat_id, "bot_message_sent", {
                        "message_id": getattr(msg, "message_id", None),
                        "text_len": text_info["len"],
                        "text_hash": text_info["hash"],
                        "parse_mode": str(kwargs.get("parse_mode")),
                    })
            except Exception as e:
                logger.error(f"Failed to log bot message for {chat_id}: {e}")

    async def send_photo_logged(self, *args, **kwargs):
        call_ctx = _extract_api_context("send_photo", orig_send_photo, args, kwargs)
        chat_id = call_ctx["chat_id"]
        caption = call_ctx["caption"]
        start_time = time.monotonic()
        try:
            msg = await _run_api_with_retry(
                "send_photo",
                chat_id,
                lambda: orig_send_photo(self, *args, **kwargs),
            )
            ok = True
            return msg
        except Exception as e:
            ok = False
            log_system("api", "send_photo_failed", {
                "chat_id": str(chat_id),
                "error": str(e),
                "degraded": API_FAILURE_TRACKER.snapshot(chat_id),
            }, level="ERROR")
            raise
        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log_system("api", "send_photo", {
                "chat_id": str(chat_id),
                "ok": ok,
                "duration_ms": duration_ms,
            })
            _maybe_log_api_call_slow("send_photo", chat_id, duration_ms)
            try:
                if chat_id is not None and ok:
                    caption_info = text_meta(caption)
                    storage.log_user_event(chat_id, "bot_message_sent", {
                        "message_id": getattr(msg, "message_id", None),
                        "text_len": caption_info["len"],
                        "text_hash": caption_info["hash"],
                        "has_photo": True,
                        "parse_mode": str(kwargs.get("parse_mode")),
                    })
            except Exception as e:
                logger.error(f"Failed to log bot photo for {chat_id}: {e}")

    async def edit_message_text_logged(self, *args, **kwargs):
        call_ctx = _extract_api_context("edit_message_text", orig_edit_message_text, args, kwargs)
        chat_id = call_ctx["chat_id"]
        text = call_ctx["text"]
        message_id = call_ctx["message_id"]
        inline_message_id = call_ctx["inline_message_id"]
        start_time = time.monotonic()
        msg = None
        ok = False
        noop_not_modified = False
        try:
            msg = await _run_api_with_retry(
                "edit_message_text",
                chat_id,
                lambda: orig_edit_message_text(self, *args, **kwargs),
            )
            ok = True
            return msg
        except Exception as e:
            if is_message_not_modified_error(e):
                noop_not_modified = True
                ok = True
                msg = (
                    SimpleNamespace(message_id=message_id)
                    if message_id is not None
                    else True
                )
                _maybe_close_polling_network_window_on_success("edit_message_text")
                log_system("api", "edit_message_text_noop", {
                    "chat_id": str(chat_id),
                    "message_id": message_id,
                    "inline_message_id": inline_message_id,
                    "reason_code": "message_not_modified",
                    "degraded": API_FAILURE_TRACKER.snapshot(chat_id),
                }, level="INFO")
                return msg
            log_system("api", "edit_message_text_failed", {
                "chat_id": str(chat_id),
                "message_id": message_id,
                "inline_message_id": inline_message_id,
                "error": str(e),
                "degraded": API_FAILURE_TRACKER.snapshot(chat_id),
            }, level="ERROR")
            raise
        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            payload = {
                "chat_id": str(chat_id),
                "message_id": message_id,
                "inline_message_id": inline_message_id,
                "ok": ok,
                "duration_ms": duration_ms,
            }
            if noop_not_modified:
                payload["reason_code"] = "message_not_modified"
            log_system("api", "edit_message_text", payload)
            _maybe_log_api_call_slow(
                "edit_message_text",
                chat_id,
                duration_ms,
                message_id=message_id,
                inline_message_id=inline_message_id,
            )
            try:
                if chat_id is not None and ok:
                    text_info = text_meta(text)
                    user_event = "bot_message_edit_noop" if noop_not_modified else "bot_message_edited"
                    payload = {
                        "message_id": getattr(msg, "message_id", None),
                        "text_len": text_info["len"],
                        "text_hash": text_info["hash"],
                        "parse_mode": str(kwargs.get("parse_mode")),
                    }
                    if noop_not_modified:
                        payload["reason_code"] = "message_not_modified"
                    storage.log_user_event(chat_id, user_event, payload)
            except Exception as e:
                logger.error(f"Failed to log bot edit for {chat_id}: {e}")

    async def send_document_logged(self, *args, **kwargs):
        call_ctx = _extract_api_context("send_document", orig_send_document, args, kwargs)
        chat_id = call_ctx["chat_id"]
        caption = call_ctx["caption"]
        start_time = time.monotonic()
        try:
            msg = await _run_api_with_retry(
                "send_document",
                chat_id,
                lambda: orig_send_document(self, *args, **kwargs),
            )
            ok = True
            return msg
        except Exception as e:
            ok = False
            log_system("api", "send_document_failed", {
                "chat_id": str(chat_id),
                "error": str(e),
                "degraded": API_FAILURE_TRACKER.snapshot(chat_id),
            }, level="ERROR")
            raise
        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log_system("api", "send_document", {
                "chat_id": str(chat_id),
                "ok": ok,
                "duration_ms": duration_ms,
            })
            _maybe_log_api_call_slow("send_document", chat_id, duration_ms)
            try:
                if chat_id is not None and ok:
                    caption_info = text_meta(caption)
                    storage.log_user_event(chat_id, "bot_message_sent", {
                        "message_id": getattr(msg, "message_id", None),
                        "text_len": caption_info["len"],
                        "text_hash": caption_info["hash"],
                        "has_document": True,
                        "parse_mode": str(kwargs.get("parse_mode")),
                    })
            except Exception as e:
                logger.error(f"Failed to log bot document for {chat_id}: {e}")

    async def edit_message_caption_logged(self, *args, **kwargs):
        call_ctx = _extract_api_context("edit_message_caption", orig_edit_message_caption, args, kwargs)
        chat_id = call_ctx["chat_id"]
        caption = call_ctx["caption"]
        message_id = call_ctx["message_id"]
        inline_message_id = call_ctx["inline_message_id"]
        start_time = time.monotonic()
        try:
            msg = await _run_api_with_retry(
                "edit_message_caption",
                chat_id,
                lambda: orig_edit_message_caption(self, *args, **kwargs),
            )
            ok = True
            return msg
        except Exception as e:
            ok = False
            log_system("api", "edit_message_caption_failed", {
                "chat_id": str(chat_id),
                "message_id": message_id,
                "inline_message_id": inline_message_id,
                "error": str(e),
                "degraded": API_FAILURE_TRACKER.snapshot(chat_id),
            }, level="ERROR")
            raise
        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log_system("api", "edit_message_caption", {
                "chat_id": str(chat_id),
                "message_id": message_id,
                "inline_message_id": inline_message_id,
                "ok": ok,
                "duration_ms": duration_ms,
            })
            _maybe_log_api_call_slow(
                "edit_message_caption",
                chat_id,
                duration_ms,
                message_id=message_id,
                inline_message_id=inline_message_id,
            )
            try:
                if chat_id is not None and ok:
                    caption_info = text_meta(caption)
                    storage.log_user_event(chat_id, "bot_message_edited", {
                        "message_id": getattr(msg, "message_id", message_id),
                        "text_len": caption_info["len"],
                        "text_hash": caption_info["hash"],
                        "parse_mode": str(kwargs.get("parse_mode")),
                    })
            except Exception as e:
                logger.error(f"Failed to log bot caption edit for {chat_id}: {e}")

    async def edit_message_reply_markup_logged(self, *args, **kwargs):
        call_ctx = _extract_api_context(
            "edit_message_reply_markup",
            orig_edit_message_reply_markup,
            args,
            kwargs,
        )
        chat_id = call_ctx["chat_id"]
        message_id = call_ctx["message_id"]
        inline_message_id = call_ctx["inline_message_id"]
        start_time = time.monotonic()
        try:
            msg = await _run_api_with_retry(
                "edit_message_reply_markup",
                chat_id,
                lambda: orig_edit_message_reply_markup(self, *args, **kwargs),
            )
            ok = True
            return msg
        except Exception as e:
            ok = False
            log_system("api", "edit_message_reply_markup_failed", {
                "chat_id": str(chat_id),
                "message_id": message_id,
                "inline_message_id": inline_message_id,
                "error": str(e),
                "degraded": API_FAILURE_TRACKER.snapshot(chat_id),
            }, level="ERROR")
            raise
        finally:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            log_system("api", "edit_message_reply_markup", {
                "chat_id": str(chat_id),
                "message_id": message_id,
                "inline_message_id": inline_message_id,
                "ok": ok,
                "duration_ms": duration_ms,
            })
            _maybe_log_api_call_slow(
                "edit_message_reply_markup",
                chat_id,
                duration_ms,
                message_id=message_id,
                inline_message_id=inline_message_id,
            )

    send_message_logged._resilience_wrapper = True
    send_message_logged._orig_method = orig_send_message
    send_photo_logged._resilience_wrapper = True
    send_photo_logged._orig_method = orig_send_photo
    edit_message_text_logged._resilience_wrapper = True
    edit_message_text_logged._orig_method = orig_edit_message_text
    send_document_logged._resilience_wrapper = True
    send_document_logged._orig_method = orig_send_document
    edit_message_caption_logged._resilience_wrapper = True
    edit_message_caption_logged._orig_method = orig_edit_message_caption
    edit_message_reply_markup_logged._resilience_wrapper = True
    edit_message_reply_markup_logged._orig_method = orig_edit_message_reply_markup

    bot_class._orig_send_message = orig_send_message
    bot_class._orig_send_photo = orig_send_photo
    bot_class._orig_edit_message_text = orig_edit_message_text
    bot_class._orig_send_document = orig_send_document
    bot_class._orig_edit_message_caption = orig_edit_message_caption
    bot_class._orig_edit_message_reply_markup = orig_edit_message_reply_markup
    bot_class.send_message = send_message_logged
    bot_class.send_photo = send_photo_logged
    bot_class.edit_message_text = edit_message_text_logged
    bot_class.send_document = send_document_logged
    bot_class.edit_message_caption = edit_message_caption_logged
    bot_class.edit_message_reply_markup = edit_message_reply_markup_logged
    bot_class._logging_wrapped = True

async def post_init(application):
    """
    Setup that runs after the bot has started.
    This registers the menu button commands with Telegram
    and starts the scheduler engine.
    """
    _install_bot_api_wrappers(application)

    commands = [
        BotCommand("help", "Documentation and command guide"),
        BotCommand("alerts", "Alerts: add/next/list/search"),
        BotCommand("birthdays", "Birthdays: add/next/search/list"),
        BotCommand("tags", "Manage categories"),
        BotCommand("cancel", "Stop the current operation"),
        BotCommand("settings", "Manage preferences and backups"),
        BotCommand("status", "View bot status"),
    ]
    menu_start = time.monotonic()
    try:
        await _run_api_with_retry(
            "set_my_commands",
            None,
            lambda: application.bot.set_my_commands(commands),
        )
        log_system("api", "set_my_commands", {
            "ok": True,
            "commands_count": len(commands),
            "duration_ms": int((time.monotonic() - menu_start) * 1000),
        })
    except Exception as exc:
        retryable = isinstance(exc, (NetworkError, TimedOut, RetryAfter))
        payload = {
            "ok": False,
            "commands_count": len(commands),
            "duration_ms": int((time.monotonic() - menu_start) * 1000),
            "retryable": retryable,
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "degraded": API_FAILURE_TRACKER.snapshot(None),
        }
        log_system(
            "api",
            "set_my_commands_failed",
            payload,
            level="WARNING" if retryable else "ERROR",
        )
        if not retryable:
            raise

    privileged_targets, standard_targets = _get_scoped_command_targets()
    if privileged_targets or standard_targets:
        admin_commands = commands + [BotCommand("manage", "Admin/developer dashboard")]
        scoped_start = time.monotonic()
        privileged_failures = 0
        standard_failures = 0
        for chat_id in privileged_targets:
            scope = BotCommandScopeChat(chat_id=chat_id)
            try:
                await _run_api_with_retry(
                    "set_my_commands_scoped",
                    chat_id,
                    lambda scope=scope: application.bot.set_my_commands(admin_commands, scope=scope),
                )
            except Exception:
                privileged_failures += 1
        for chat_id in standard_targets:
            scope = BotCommandScopeChat(chat_id=chat_id)
            try:
                await _run_api_with_retry(
                    "set_my_commands_scoped",
                    chat_id,
                    lambda scope=scope: application.bot.set_my_commands(commands, scope=scope),
                )
            except Exception:
                standard_failures += 1
        log_system("api", "set_my_commands_scoped", {
            "targets": len(privileged_targets) + len(standard_targets),
            "failed": privileged_failures + standard_failures,
            "privileged_targets": len(privileged_targets),
            "standard_targets": len(standard_targets),
            "privileged_failed": privileged_failures,
            "standard_failed": standard_failures,
            "commands_count": len(admin_commands),
            "base_commands_count": len(commands),
            "duration_ms": int((time.monotonic() - scoped_start) * 1000),
        })
    
    # Start the scheduler engine
    await scheduler.start_scheduler()
    try:
        log_downtime_summary()
        users = storage.get_all_users()
        scope_payload = _log_startup_user_scope_telemetry(authorized_users=users) or {}
        active_alerts = sum(len(storage.get_active_alerts(uid)) for uid in users)
        log_system("lifecycle", "startup", {
            "users": len(users),
            "active_alerts": active_alerts,
            "scheduler_interval_seconds": C.SCHEDULER_INTERVAL_SECONDS,
            "dataset_users": scope_payload.get("dataset_users"),
            "excluded_users": scope_payload.get("excluded_users"),
            "auth_filter_enabled": scope_payload.get("auth_filter_enabled"),
        })
    except Exception as e:
        log_system("lifecycle", "startup_log_failed", {"error": str(e)}, level="ERROR")


async def touch_activity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pre-processing handler that updates last_seen for every whitelisted user interaction."""
    user = getattr(update, "effective_user", None)
    if not user:
        return
    if not storage.is_user_whitelisted(user.id):
        return
    storage.touch_user_activity(user.id)


async def log_callback_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log callback metadata and clear pending free-text search modes when needed."""
    query = update.callback_query
    if not query:
        return
    user_id = update.effective_user.id
    msg_text = None
    if query.message:
        msg_text = query.message.text or query.message.caption
    msg_meta = text_meta(msg_text)
    storage.log_user_event(user_id, "button_press", {
        "data": query.data,
        "message_id": query.message.message_id if query.message else None,
        "message_text_len": msg_meta["len"],
        "message_text_hash": msg_meta["hash"],
    })
    # Any non-search button press cancels pending birthday free-text search mode.
    if query.data != "bday_search" and context.user_data.get("expecting_birthday_search"):
        context.user_data["expecting_birthday_search"] = False
        storage.log_user_event(user_id, "birthday_search_cancelled_by_button", {
            "callback_data": query.data,
        })
    # Any non-search button press cancels pending alert free-text search mode.
    if query.data != "alert_search" and context.user_data.get("expecting_alert_search"):
        context.user_data["expecting_alert_search"] = False
        storage.log_user_event(user_id, "alert_search_cancelled_by_button", {
            "callback_data": query.data,
        })


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log unhandled exceptions and route polling network errors through rollup handling."""
    err = context.error
    # Polling-level network blips: no Update, transient infrastructure noise.
    if update is None and isinstance(err, (NetworkError, TimedOut, RetryAfter)):
        _handle_polling_network_error(err)
        return
    payload = {
        "error": str(err),
        "type": err.__class__.__name__ if err else None,
        "traceback": "".join(traceback.format_exception(type(err), err, err.__traceback__)) if err else None,
    }
    try:
        if isinstance(update, Update) and update.effective_user:
            payload["user_id"] = str(update.effective_user.id)
        if isinstance(update, Update) and update.effective_chat:
            payload["chat_id"] = str(update.effective_chat.id)
        if isinstance(update, Update) and update.callback_query:
            payload["callback_data"] = update.callback_query.data
        if isinstance(update, Update) and update.effective_message:
            payload["message_id"] = update.effective_message.message_id
    except Exception:
        pass
    log_system("errors", "unhandled_exception", payload, level="ERROR")


async def post_shutdown(application):
    """Stop scheduler services and release process locks during shutdown."""
    try:
        scheduler.stop_scheduler()
    except Exception:
        pass
    release_single_instance_lock()

async def global_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles text input for multiple features:
    - Custom snooze input
    - Add Tag feature
    """

    if update.message is None:
        return  # Not a text message (e.g. edited message, channel post)

    if context.user_data.get("start_request_confirm_pending"):
        # Legacy fail-safe: this state belongs to an old onboarding flow.
        context.user_data.pop("start_request_confirm_pending", None)
        context.user_data.pop("start_request_message_draft", None)
        await update.message.reply_text("⚠️ This request step expired. Send /start to continue.")
        raise ApplicationHandlerStop

    if context.user_data.get("expecting_start_request_message"):
        message = update.message
        raw = (message.text or "").strip() if message else ""
        if not raw:
            await update.message.reply_text("⚠️ Message cannot be empty. Send a short identification message.")
            raise ApplicationHandlerStop
        if len(raw) > START_REQUEST_MAX_MESSAGE_CHARS:
            await update.message.reply_text(
                f"⚠️ Message too long (max {START_REQUEST_MAX_MESSAGE_CHARS} characters)."
            )
            raise ApplicationHandlerStop

        user_id = get_target_user_id(update, context)
        now_iso = datetime.now().isoformat()

        from modules.security.whitelist_store import (
            update_whitelist_request_message,
            find_whitelist_request,
            get_whitelist_request_state,
        )
        from modules.security.whitelist_notifications import (
            build_request_admin_text,
            build_request_action_keyboard,
            notify_admins_for_request,
            update_request_messages,
        )

        result = update_whitelist_request_message(
            user_id=user_id,
            request_message=raw,
            now_iso=now_iso,
        )
        status = result.get("status")
        if status in {"not_found", "not_pending"}:
            context.user_data["expecting_start_request_message"] = False
            context.user_data.pop("start_request_message_draft", None)
            context.user_data.pop("start_request_confirm_pending", None)
            await update.message.reply_text("⚠️ Request is no longer pending. Send /start again.")
            raise ApplicationHandlerStop
        if status not in {"updated", "updated_partial"}:
            await update.message.reply_text("⚠️ Could not update your request message. Try again.")
            raise ApplicationHandlerStop

        record = result.get("record") or find_whitelist_request(user_id) or {}
        state = result.get("state") or get_whitelist_request_state(user_id) or {}
        try:
            if not state.get("first_notified_at"):
                await notify_admins_for_request(context.bot, storage, record, state)
            else:
                admin_text = build_request_admin_text(record, state, status="pending")
                await update_request_messages(
                    context.bot,
                    user_id,
                    admin_text,
                    reply_markup=build_request_action_keyboard(user_id),
                )
        except Exception:
            pass

        context.user_data["expecting_start_request_message"] = False
        context.user_data.pop("start_request_message_draft", None)
        context.user_data.pop("start_request_confirm_pending", None)
        await update.message.reply_text(
            _start_request_pending_text(raw),
            parse_mode="HTML",
            reply_markup=_start_request_pending_keyboard(),
        )
        raise ApplicationHandlerStop

    if context.user_data.get("expecting_admin_add_user"):
        user_id = update.effective_user.id if update.effective_user else None
        role = storage.get_user_role(user_id) if user_id is not None else None
        if role not in {"admin", "developer"}:
            context.user_data.pop("expecting_admin_add_user", None)
            raise ApplicationHandlerStop
        message = update.message
        raw = (message.text or "").strip() if message else ""
        if raw.lower() in {"cancel", "/cancel"}:
            context.user_data.pop("expecting_admin_add_user", None)
            await update.message.reply_text("✅ Add user canceled.")
            raise ApplicationHandlerStop

        from modules.shared.forward_extract import extract_forward_identity

        identity = extract_forward_identity(message)
        target_user_id = identity.get("user_id")
        target_username = identity.get("username")
        target_display_name = identity.get("display_name")

        if identity.get("error") in {"hidden_sender", "forwarded_chat"}:
            await update.message.reply_text(
                "⚠️ The forwarded message hides the sender. Ask the user to allow forwarding, "
                "or send their @username."
            )
            raise ApplicationHandlerStop

        if not target_user_id and not target_username:
            if not raw:
                await update.message.reply_text("⚠️ Send an @username or forward a message from the user.")
                raise ApplicationHandlerStop
            target_username = raw.split()[0]

        from modules.handlers.admin import _build_invite_message
        from modules.security.whitelist_store import upsert_whitelist_invite

        bot_username = getattr(context.bot, "username", None)
        ok = upsert_whitelist_invite(
            user_id=target_user_id,
            username=target_username,
            display_name=target_display_name,
            invited_by=user_id,
        )
        if not ok:
            log_system("security", "admin_invite_create_failed", {
                "admin_id": str(user_id) if user_id is not None else None,
                "target_user_id": str(target_user_id) if target_user_id is not None else None,
                "target_username": target_username,
            }, level="WARNING")
            log_system("admin_audit", "invite_create_failed", {
                "admin_id": str(user_id) if user_id is not None else None,
                "target_user_id": str(target_user_id) if target_user_id is not None else None,
                "target_username": target_username,
            })
            await update.message.reply_text("⚠️ Invalid username. Send a valid @username.")
            raise ApplicationHandlerStop
        log_system("security", "admin_invite_created", {
            "admin_id": str(user_id) if user_id is not None else None,
            "target_user_id": str(target_user_id) if target_user_id is not None else None,
            "target_username": target_username,
            "target_display_name": target_display_name,
        })
        log_system("admin_audit", "invite_created", {
            "admin_id": str(user_id) if user_id is not None else None,
            "target_user_id": str(target_user_id) if target_user_id is not None else None,
            "target_username": target_username,
        })
        text = _build_invite_message(target_username, target_display_name, bot_username)
        context.user_data.pop("expecting_admin_add_user", None)
        await update.message.reply_text(text)
        raise ApplicationHandlerStop

    if context.user_data.get("expecting_admin_custom_name"):
        user_id = update.effective_user.id if update.effective_user else None
        role = storage.get_user_role(user_id) if user_id is not None else None
        if role not in {"admin", "developer"}:
            context.user_data.pop("expecting_admin_custom_name", None)
            context.user_data.pop("admin_custom_name_target_id", None)
            context.user_data.pop("admin_custom_name_target_kind", None)
            raise ApplicationHandlerStop

        raw = (update.message.text or "").strip()
        if raw.lower() in {"cancel", "/cancel"}:
            context.user_data.pop("expecting_admin_custom_name", None)
            context.user_data.pop("admin_custom_name_target_id", None)
            context.user_data.pop("admin_custom_name_target_kind", None)
            await update.message.reply_text("✅ Custom name canceled.")
            raise ApplicationHandlerStop

        target_id = context.user_data.get("admin_custom_name_target_id")
        target_kind = context.user_data.get("admin_custom_name_target_kind")
        context.user_data.pop("expecting_admin_custom_name", None)
        context.user_data.pop("admin_custom_name_target_id", None)
        context.user_data.pop("admin_custom_name_target_kind", None)

        if not target_id or target_kind not in {"req", "user"}:
            await update.message.reply_text("⚠️ Missing target for custom name.")
            raise ApplicationHandlerStop

        if len(raw) > C.CUSTOM_NAME_MAX_LEN:
            try:
                storage.log_user_event(target_id, "custom_name_input_too_long", {
                    "name_len": len(raw),
                    "target_kind": target_kind,
                })
            except Exception:
                pass
            await update.message.reply_text(
                f"⚠️ Custom name too long (max {C.CUSTOM_NAME_MAX_LEN} characters)."
            )
            raise ApplicationHandlerStop

        if raw in {"-", "clear", "/clear"}:
            custom_name = ""
        else:
            custom_name = raw

        if target_kind == "req":
            from modules.security.whitelist_store import update_whitelist_request
            from modules.handlers.admin import _find_request_record, _request_action_keyboard, _request_action_text
            ok = update_whitelist_request(target_id, custom_name=custom_name)
            record = _find_request_record(target_id)
            if not ok or not record:
                await update.message.reply_text("⚠️ Request already resolved.")
                raise ApplicationHandlerStop
            await update.message.reply_text(
                _request_action_text(record),
                parse_mode="Markdown",
                reply_markup=_request_action_keyboard(target_id),
            )
            raise ApplicationHandlerStop

        if target_kind == "user":
            from modules.handlers.admin import _is_target_whitelisted, _user_status_keyboard, _build_user_status
            from modules.handlers.user_list import resolve_user_detail_back_cb
            if not _is_target_whitelisted(storage, target_id):
                await update.message.reply_text("⚠️ User not found or no longer whitelisted.")
                raise ApplicationHandlerStop
            storage.update_user_meta(target_id, {"custom_name": custom_name or None})
            back_cb = resolve_user_detail_back_cb(context, role)
            await update.message.reply_text(
                _build_user_status(storage, target_id, viewer_role=role),
                parse_mode="Markdown",
                reply_markup=_user_status_keyboard(
                    target_id,
                    target_role=storage.get_user_role(target_id),
                    actor_role=role,
                    actor_id=user_id,
                    back_cb=back_cb,
                ),
            )
            raise ApplicationHandlerStop

    # Handle backup email input from settings mail flow.
    if context.user_data.get("expecting_backup_email"):
        user_id = get_target_user_id(update, context)
        email = (update.message.text or "").strip()
        normalized = normalize_email_address(email)
        if not normalized:
            payload = {"source": "settings", "email_meta": text_meta(email)}
            payload.update(build_acting_as_payload(update, context))
            storage.log_user_event(user_id, "backup_email_invalid_input", payload)
            await update.message.reply_text(
                "⚠️ Invalid email. Send a valid address or /cancel."
            )
            raise ApplicationHandlerStop
        updates = {
            "email_address": normalized,
            "email_reminder_disabled": False,
        }
        enable_after_set = bool(context.user_data.pop("backup_email_enable_after_set", None))
        if enable_after_set:
            updates["email_enabled"] = True
        storage.update_backup_prefs(user_id, updates)
        context.user_data.pop("expecting_backup_email", None)
        prefs = storage.get_backup_prefs(user_id)
        payload = {
            "source": "settings",
            "enabled": bool(prefs.get("email_enabled")),
        }
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "backup_email_set", payload)
        size_bytes = estimate_email_backup_size_bytes(storage, user_id)
        message, keyboard = build_mail_backup_status(prefs, size_bytes=size_bytes)
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
        raise ApplicationHandlerStop

    if context.user_data.get("expecting_birthday_time"):
        user_id = get_target_user_id(update, context)
        raw = (update.message.text or "").strip()
        if raw.lower() in {"cancel", "/cancel"}:
            context.user_data.pop("expecting_birthday_time", None)
            context.user_data.pop("expecting_birthday_evening_time", None)
            await update.message.reply_text("✅ Birthday time update canceled.")
            raise ApplicationHandlerStop
        normalized = normalize_time_input(raw)
        if not normalized:
            await update.message.reply_text(
                "⚠️ Invalid time. Use HH:MM (24h), e.g. 07:30.",
            )
            raise ApplicationHandlerStop
        storage.update_user_prefs(user_id, {"birthday_default_time": normalized})
        updated = storage.update_birthday_schedule_time(
            user_id,
            normalized,
            user_prefs=storage.get_user_prefs(user_id),
        )
        context.user_data.pop("expecting_birthday_time", None)
        context.user_data.pop("expecting_birthday_evening_time", None)
        payload = {
            "source": "settings",
            "time": normalized,
            "updated_birthdays": updated.get("updated", 0),
            "total_birthdays": updated.get("total", 0),
        }
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "birthday_default_time_set", payload)
        prefs = storage.get_user_prefs(user_id)
        message, keyboard = build_birthday_time_status(prefs)
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
        raise ApplicationHandlerStop

    if context.user_data.get("expecting_birthday_evening_time"):
        user_id = get_target_user_id(update, context)
        raw = (update.message.text or "").strip()
        if raw.lower() in {"cancel", "/cancel"}:
            context.user_data.pop("expecting_birthday_evening_time", None)
            context.user_data.pop("expecting_birthday_time", None)
            await update.message.reply_text("✅ Birthday evening time update canceled.")
            raise ApplicationHandlerStop
        normalized = normalize_time_input(raw)
        if not normalized:
            await update.message.reply_text(
                "⚠️ Invalid time. Use HH:MM (24h), e.g. 20:00.",
            )
            raise ApplicationHandlerStop
        storage.update_user_prefs(user_id, {"birthday_evening_before_time": normalized})
        context.user_data.pop("expecting_birthday_evening_time", None)
        context.user_data.pop("expecting_birthday_time", None)
        payload = {
            "source": "settings",
            "time": normalized,
        }
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "birthday_evening_time_set", payload)
        prefs = storage.get_user_prefs(user_id)
        message, keyboard = build_birthday_time_status(prefs)
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
        raise ApplicationHandlerStop

    if context.user_data.get("expecting_bday_bulk_import_message"):
        user_id = get_target_user_id(update, context)
        raw_text = (update.message.text or "")
        text_signal = text_meta(raw_text)
        parsed = parse_bulk_birthday_message(raw_text, max_lines=300, max_name_len=80)
        tag_analysis = analyze_import_tags(
            parsed.get("valid_entries") or [],
            storage.get_user_tags(user_id),
        )
        parsed_summary = parsed.get("summary") or {}
        tag_summary = tag_analysis.get("summary") or {}
        provided_tag_items = int(tag_summary.get("provided_tag_items") or 0)
        resolved_tag_items = int(tag_summary.get("resolved_tags") or 0)
        unresolved_tags = int(tag_summary.get("unresolved_tags") or 0)
        unresolved_missing_tag_items = int(tag_summary.get("unresolved_missing_tag") or 0)
        suggestions_over_threshold = int(tag_summary.get("suggestions_over_threshold") or 0)
        entries_with_unresolved_tags = int(tag_summary.get("entries_with_unresolved_tags") or 0)
        entries_analyzed = int(tag_summary.get("entries_total") or 0)
        available_user_tags = int(tag_summary.get("available_user_tags") or 0)
        suggestion_threshold = int(tag_summary.get("suggestion_threshold") or 0)
        session_summary = {
            "nonempty_lines": int(parsed.get("nonempty_lines") or 0),
            "valid_lines": int(parsed_summary.get("valid_lines") or 0),
            "invalid_lines": int(parsed_summary.get("invalid_lines") or 0),
            "entries_analyzed": entries_analyzed,
            "provided_tag_items": provided_tag_items,
            "resolved_tag_items": resolved_tag_items,
            "unresolved_tags": unresolved_tags,
            "unresolved_missing_tag_items": unresolved_missing_tag_items,
            "suggestions_over_threshold": suggestions_over_threshold,
            "entries_with_unresolved_tags": entries_with_unresolved_tags,
            "available_user_tags": available_user_tags,
            "suggestion_threshold": suggestion_threshold,
            "reason_counts": dict(parsed_summary.get("reason_counts") or {}),
            "lines_limit_exceeded": bool(parsed.get("lines_limit_exceeded")),
        }
        context.user_data["bday_bulk_import_session"] = {
            "source": "settings_bulk_import",
            "created_at": datetime.now().isoformat(),
            "entries": list(tag_analysis.get("entries") or []),
            "summary": session_summary,
        }
        context.user_data.pop("expecting_bday_bulk_import_message", None)

        payload = {
            "input_len": text_signal["len"],
            "input_hash": text_signal["hash"],
            "nonempty_lines": int(parsed.get("nonempty_lines") or 0),
            "valid_lines": int(parsed_summary.get("valid_lines") or 0),
            "invalid_lines": int(parsed_summary.get("invalid_lines") or 0),
            "entries_analyzed": entries_analyzed,
            "provided_tag_items": provided_tag_items,
            "resolved_tag_items": resolved_tag_items,
            "unresolved_tags": unresolved_tags,
            "unresolved_missing_tag_items": unresolved_missing_tag_items,
            "suggestions_over_threshold": suggestions_over_threshold,
            "entries_with_unresolved_tags": entries_with_unresolved_tags,
            "available_user_tags": available_user_tags,
            "suggestion_threshold": suggestion_threshold,
            "reason_counts": dict(parsed_summary.get("reason_counts") or {}),
            "lines_limit_exceeded": bool(parsed.get("lines_limit_exceeded")),
        }
        payload.update(build_acting_as_payload(update, context))
        storage.log_user_event(user_id, "birthday_bulk_import_parsed", payload)

        preview_blocks = build_import_preview_blocks(parsed, tag_analysis, safe_limit=3900)
        if not preview_blocks:
            preview_blocks = ["<b>Birthday Bulk Import Preview</b>\n\nNo preview content available."]

        decision_keyboard = build_birthday_bulk_import_decision_keyboard()
        for idx, block in enumerate(preview_blocks):
            kwargs = {"parse_mode": "HTML"}
            if idx == len(preview_blocks) - 1:
                kwargs["reply_markup"] = decision_keyboard
            await update.message.reply_text(block, **kwargs)
        raise ApplicationHandlerStop

    if context.user_data.get("expecting_timezone_location"):
        await update.message.reply_text(
            "📍 Please share your location using the button or /cancel."
        )
        raise ApplicationHandlerStop

    # Handle timezone selection input from settings.
    if await handle_timezone_query_input(update, context):
        raise ApplicationHandlerStop

    # Handle custom postpone input first
    if context.user_data.get('expecting_custom_postpone'):
        await handle_custom_postpone_input(update, context)
        raise ApplicationHandlerStop

    # Handle ghost custom time input from missed-summary picker flow
    if context.user_data.get("expecting_ghost_custom"):
        await handle_ghost_custom_text(update, context)
        raise ApplicationHandlerStop

    # Handle edit-text input from /list or /birthdays info
    if context.user_data.get('expecting_edit_text'):
        await handle_edit_text_input(update, context)
        raise ApplicationHandlerStop
    
    # Handle tag rename input
    if context.user_data.get('expecting_tag_rename'):
        old_tag = context.user_data.get('tag_rename_old', '')
        user_id = get_target_user_id(update, context)
        new_tag = normalize_tag_input(update.message.text)
        new_tag_meta = text_meta(new_tag)
        old_tag_meta = text_meta(old_tag)
        acting_payload = build_acting_as_payload(update, context)

        is_valid, error_msg = validate_tag_format(new_tag)
        if not is_valid:
            payload = {
                "reason_code": "invalid_tag_format",
                "old_tag_len": old_tag_meta["len"],
                "old_tag_hash": old_tag_meta["hash"],
                "new_tag_len": new_tag_meta["len"],
                "new_tag_hash": new_tag_meta["hash"],
            }
            payload.update(acting_payload)
            storage.log_user_event(user_id, "tag_rename_invalid_format", payload)
            await update.message.reply_text(
                f"⚠️ <b>Invalid tag format</b>\n\n{error_msg}",
                parse_mode="HTML"
            )
            raise ApplicationHandlerStop

        success, error_reason = storage.rename_user_tag(user_id, old_tag, new_tag)

        if success:
            payload = {
                "old_tag_len": old_tag_meta["len"],
                "old_tag_hash": old_tag_meta["hash"],
                "new_tag_len": new_tag_meta["len"],
                "new_tag_hash": new_tag_meta["hash"],
            }
            payload.update(acting_payload)
            storage.log_user_event(user_id, "tag_rename_success", payload)
            await update.message.reply_text(
                f"✅ Tag renamed to <b>{html_escape(new_tag)}</b>.",
                parse_mode="HTML"
            )
        else:
            failed_payload = {
                "reason_code": error_reason or "unknown",
                "old_tag_len": old_tag_meta["len"],
                "old_tag_hash": old_tag_meta["hash"],
                "new_tag_len": new_tag_meta["len"],
                "new_tag_hash": new_tag_meta["hash"],
            }
            failed_payload.update(acting_payload)
            storage.log_user_event(user_id, "tag_rename_failed", failed_payload)
            if error_reason == "same_tag":
                await update.message.reply_text(
                    "⚠️ That's already the current tag name.", parse_mode="HTML"
                )
            elif error_reason == "not_found":
                await update.message.reply_text(
                    "⚠️ Tag no longer exists. Open /tags again.", parse_mode="HTML"
                )
            elif error_reason == "exact_duplicate":
                await update.message.reply_text(
                    f"⚠️ Tag <b>{html_escape(new_tag)}</b> already exists.",
                    parse_mode="HTML"
                )
            elif error_reason and error_reason.startswith("name_duplicate:"):
                existing = error_reason.replace("name_duplicate:", "")
                await update.message.reply_text(
                    f"⚠️ A tag with this name already exists:\n<b>{html_escape(existing)}</b>\n\n"
                    "Tag names must be unique (even with different emojis).",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text("⚠️ Could not rename tag. Please try again.")
            raise ApplicationHandlerStop

        context.user_data.pop('expecting_tag_rename', None)
        context.user_data.pop('tag_rename_old', None)
        context.user_data.pop('tag_edit_token_map', None)
        await tags_dashboard_start(update, context)
        raise ApplicationHandlerStop

    # Handle tag input
    if not context.user_data.get('expecting_tag_name'):
        # Handle birthday search text from /birthdays -> Search button.
        if context.user_data.get('expecting_birthday_search'):
            # If another flow is active, drop stale birthday-search mode.
            if context.user_data.get('temp_alert'):
                context.user_data['expecting_birthday_search'] = False
                await update.message.reply_text(
                    "⏹️ Search canceled — alert creation is active."
                )
                raise ApplicationHandlerStop
            await birthday_search_from_text(update, context)
            raise ApplicationHandlerStop
        # Handle alert search text from /alerts -> Search button.
        if context.user_data.get('expecting_alert_search'):
            # If another flow is active, drop stale alert-search mode.
            if context.user_data.get('temp_alert'):
                context.user_data['expecting_alert_search'] = False
                await update.message.reply_text(
                    "⏹️ Search canceled — alert creation is active."
                )
                raise ApplicationHandlerStop
            await alert_search_from_text(update, context)
            raise ApplicationHandlerStop
        if _has_active_interactive_context(context.user_data):
            return  # Let other handlers process this message
        await update.message.reply_text(
            "⚠️ No text input is pending.\n"
            "If a previous step was interrupted, use /alerts or /birthdays to restart, or /cancel."
        )
        raise ApplicationHandlerStop
    
    user_id = get_target_user_id(update, context)
    new_tag = normalize_tag_input(update.message.text)
    new_tag_meta = text_meta(new_tag)
    acting_payload = build_acting_as_payload(update, context)
    
    # Validate tag format (emoji + space + name)
    is_valid, error_msg = validate_tag_format(new_tag)
    if not is_valid:
        payload = {
            "reason_code": "invalid_tag_format",
            "tag_len": new_tag_meta["len"],
            "tag_hash": new_tag_meta["hash"],
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "tag_add_invalid_format", payload)
        await update.message.reply_text(
            f"⚠️ <b>Invalid tag format</b>\n\n{error_msg}",
            parse_mode="HTML"
        )
        # Stay in expecting mode so user can retry
        raise ApplicationHandlerStop

    # Attempt to add the tag (checks for duplicates)
    success, error_reason = storage.add_user_tag(user_id, new_tag)

    if success:
        payload = {
            "tag_len": new_tag_meta["len"],
            "tag_hash": new_tag_meta["hash"],
        }
        payload.update(acting_payload)
        storage.log_user_event(user_id, "tag_add_success", payload)
        await update.message.reply_text(
            f"✅ Tag <b>{html_escape(new_tag)}</b> added successfully!",
            parse_mode="HTML"
        )
    else:
        failed_payload = {
            "reason_code": error_reason or "unknown",
            "tag_len": new_tag_meta["len"],
            "tag_hash": new_tag_meta["hash"],
        }
        failed_payload.update(acting_payload)
        storage.log_user_event(user_id, "tag_add_failed", failed_payload)
        # Handle specific error reasons
        if error_reason == "exact_duplicate":
            await update.message.reply_text(
                f"⚠️ Tag <b>{html_escape(new_tag)}</b> already exists.",
                parse_mode="HTML"
            )
        elif error_reason and error_reason.startswith("name_duplicate:"):
            existing_tag = error_reason.replace("name_duplicate:", "")
            await update.message.reply_text(
                f"⚠️ A tag with this name already exists:\n<b>{html_escape(existing_tag)}</b>\n\n"
                "Tag names must be unique (even with different emojis).",
                parse_mode="HTML"
            )
        elif error_reason and error_reason.startswith("limit_reached:"):
            limit_msg = error_reason.replace("limit_reached:", "")
            await update.message.reply_text(
                f"⚠️ {limit_msg}",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("⚠️ Could not add tag. Please try again.")

        # Stay in expecting mode so user can retry
        raise ApplicationHandlerStop

    # Success: clear the flag and refresh dashboard
    context.user_data['expecting_tag_name'] = False
    await tags_dashboard_start(update, context)
    raise ApplicationHandlerStop


def _classify_inbound_message(message):
    if message is None:
        return None
    if getattr(message, "text", None) is not None:
        return "text"
    if getattr(message, "location", None) is not None:
        return "location"
    if getattr(message, "document", None) is not None:
        return "document"
    if getattr(message, "photo", None):
        return "photo"
    return "other"


async def authorization_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fail-closed authorization guard for all inbound user updates.
    Unauthorized updates are rejected before reaching other handlers.
    """
    user = getattr(update, "effective_user", None)
    if not user:
        return
    if getattr(update, "message", None) is not None and not update.callback_query and storage.is_user_whitelisted(user.id):
        msg = update.message
        text = msg.text if isinstance(msg.text, str) else ""
        stripped = text.strip()
        storage.log_user_event(user.id, "inbound_message", {
            "kind": _classify_inbound_message(msg),
            "has_command": bool(stripped.startswith("/")),
            "text_len": len(stripped),
        })

    # Approval cutoff: onboarding listeners must never survive authorization.
    if context is not None and storage.is_user_whitelisted(user.id):
        if context.user_data.get("expecting_start_request_message") or context.user_data.get("start_request_confirm_pending"):
            context.user_data.pop("expecting_start_request_message", None)
            context.user_data.pop("start_request_message_draft", None)
            context.user_data.pop("start_request_confirm_pending", None)

    message = update.effective_message
    command_name = None
    if message and isinstance(message.text, str):
        text = message.text.strip()
        if text.startswith("/"):
            token = text.split()[0]
            command_name = token.split("@")[0][1:].lower()
        if command_name == "start":
            return
    callback_data = update.callback_query.data if update.callback_query else None
    onboarding_active = bool(context and context.user_data.get("expecting_start_request_message"))
    onboarding_confirm = bool(context and context.user_data.get("start_request_confirm_pending"))
    if onboarding_active and message and isinstance(message.text, str) and not message.text.strip().startswith("/"):
        return
    if onboarding_confirm and message and isinstance(message.text, str) and not message.text.strip().startswith("/"):
        return
    if command_name == "cancel" and (onboarding_active or onboarding_confirm):
        return
    if onboarding_active and command_name and command_name not in {"start", "cancel"}:
        try:
            await message.reply_text(
                "⚠️ I am waiting for the message to admins. Send that text now, or use /cancel."
            )
        except Exception:
            pass
        raise ApplicationHandlerStop
    if callback_data in {"startreq_proceed", "startreq_cancel", "startreq_edit_yes", "startreq_edit_no"}:
        return
    if (onboarding_active or onboarding_confirm) and message and not isinstance(getattr(message, 'text', None), str):
        hint = ("⚠️ Please send a text message for identification."
                if onboarding_active
                else "⚠️ Use the buttons above to proceed or cancel your request.")
        try:
            await message.reply_text(hint)
        except Exception:
            pass
        raise ApplicationHandlerStop
    if storage.is_user_whitelisted(user.id):
        if context is not None:
            target_id = context.user_data.get("acting_as_user_id")
        else:
            target_id = None
        if target_id is None or str(target_id) == str(user.id):
            lock = _get_active_acting_lock(user.id)
            if lock and str(lock.get("by")) != str(user.id):
                text = "🛠️ Maintenance in progress. Try again later."
                try:
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(text, show_alert=True)
                        except Exception:
                            pass
                        await context.bot.send_message(chat_id=user.id, text=text)
                    elif update.effective_message:
                        if _is_read_only_command(update.effective_message.text):
                            return
                        await update.effective_message.reply_text(text)
                    else:
                        await context.bot.send_message(chat_id=user.id, text=text)
                except Exception:
                    pass
                raise ApplicationHandlerStop
        if context is not None:
            target_id = context.user_data.get("acting_as_user_id")
            if target_id and not storage.is_user_whitelisted(target_id):
                context.user_data.pop("acting_as_user_id", None)
                try:
                    storage.update_user_meta(target_id, {"acting_as_lock": None})
                except Exception:
                    pass
                try:
                    await context.bot.send_message(
                        chat_id=user.id,
                        text="⚠️ Acting as cleared. Target user is no longer whitelisted.",
                    )
                except Exception:
                    pass
        return

    from modules.security.whitelist_store import get_whitelist_request_state, find_whitelist_request
    pending = False
    try:
        state = get_whitelist_request_state(user.id)
        if isinstance(state, dict) and state.get("status") == "pending":
            pending = True
        elif find_whitelist_request(user.id):
            pending = True
    except Exception:
        pending = False

    text = (
        "Access request pending. You are under approval and will be notified when approved or rejected."
        if pending
        else "Access required. Use /start to request access."
    )
    try:
        if update.callback_query:
            try:
                await update.callback_query.answer(text, show_alert=True)
            except Exception:
                pass
            # Best effort fallback when callback alert is not visible enough.
            await context.bot.send_message(chat_id=user.id, text=text)
        elif update.effective_message:
            await update.effective_message.reply_text(text)
        else:
            await context.bot.send_message(chat_id=user.id, text=text)
    except Exception:
        pass

    raise ApplicationHandlerStop


def _prepare_startup_whitelist(admin_id, *, whitelist_path=WHITELIST_PATH):
    """Prepare startup whitelist reconciliation before singleton lock acquisition."""
    result = reconcile_startup_whitelist(
        admin_id=admin_id,
        path=whitelist_path,
    )
    status = result.get("status")
    canonical_available_by_status = {
        "seeded": True,
        "exists": True,
        "corrupt": False,
        "skipped": False,
        "error": False,
    }
    canonical_available = canonical_available_by_status.get(status, False)
    admin_id_str = str(admin_id).strip() if admin_id is not None else None
    admin_present_in_canonical = False
    if canonical_available and admin_id_str:
        admin_present_in_canonical = admin_id_str in get_role_map(path=whitelist_path, admin_id=None)

    event_name = None
    event_payload = {
        "admin_id": admin_id,
        "path": whitelist_path,
    }
    event_level = "INFO"
    message = None

    if status == "seeded":
        event_name = "whitelist_seeded"
        message = f"INFO: seeded whitelist storage at {whitelist_path}"
    elif status == "exists":
        message = f"INFO: whitelist storage already present at {whitelist_path}"
    elif status == "corrupt":
        event_name = "whitelist_seed_skipped_corrupt"
        event_level = "WARNING"
        message = f"WARNING: whitelist storage at {whitelist_path} is corrupt; startup will continue without seeding."
    elif status == "skipped":
        event_name = "whitelist_seed_skipped_invalid_admin"
        event_level = "WARNING"
        event_payload["reason"] = result.get("reason")
        message = "WARNING: whitelist storage seeding skipped for invalid admin id; startup will continue without seeding."
    elif status == "error":
        event_name = "whitelist_seed_failed"
        event_level = "WARNING"
        event_payload["reason"] = result.get("reason")
        event_payload["error_type"] = result.get("error_type")
        message = f"WARNING: whitelist storage seeding failed for {whitelist_path}; startup will continue."
    else:
        message = f"INFO: whitelist startup preparation returned status={status!r} for {whitelist_path}"

    return {
        "status": status,
        "message": message,
        "event_name": event_name,
        "event_payload": event_payload,
        "event_level": event_level,
        "canonical_available": canonical_available,
        "admin_present_in_canonical": admin_present_in_canonical,
        "path": whitelist_path,
        "result": result,
    }

if __name__ == '__main__':
    lock_acquired = False
    exit_clean = False
    exit_reason = "startup_incomplete"
    lock_conflict_exit_code = int(getattr(C, "MAINBOT_EXIT_LOCK_CONFLICT", 73))
    try:
        # Validate required env first so misconfigured startups do not emit
        # misleading lock-conflict exits (no lock should be taken in this case).
        if not TOKEN or not ADMIN_ID:
            print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID not found in .env")
            exit_reason = "missing_env"
            raise SystemExit(1)

        whitelist_prep = _prepare_startup_whitelist(ADMIN_ID, whitelist_path=WHITELIST_PATH)
        if whitelist_prep.get("message"):
            print(whitelist_prep["message"])
        if whitelist_prep.get("event_name"):
            log_system(
                "lifecycle",
                whitelist_prep["event_name"],
                whitelist_prep.get("event_payload") or {},
                level=whitelist_prep.get("event_level", "INFO"),
            )

        if whitelist_prep.get("canonical_available") and not whitelist_prep.get("admin_present_in_canonical"):
            admin_id_str = str(ADMIN_ID).strip() if ADMIN_ID else None
            if admin_id_str:
                print(f"WARNING: env admin {admin_id_str} is not present in {WHITELIST_PATH}; developer fallback is active.")
                log_system("lifecycle", "whitelist_env_fallback_active", {
                    "admin_id": ADMIN_ID,
                    "path": WHITELIST_PATH,
                }, level="WARNING")

        lock_acquired, _lock_meta = acquire_single_instance_lock(TOKEN)
        if not lock_acquired:
            print("Another bot instance is already running. Exiting.")
            exit_reason = "lock_conflict"
            raise SystemExit(lock_conflict_exit_code)

        app = ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
        set_bot_runtime(
            app.bot_data,
            BotRuntime(
                storage=storage,
                api_failure_tracker=API_FAILURE_TRACKER,
            ),
        )

        # Initialize the scheduler with app and storage
        scheduler.init_scheduler(app, storage)

        # --- HANDLERS ---
        
        # 0. Activity tracking (group -4, before everything else)
        app.add_handler(TypeHandler(Update, touch_activity_handler), group=-4)

        # 1. Global Text (Priority Group -1 so it catches text before other wizards)
        app.add_handler(CallbackQueryHandler(authorization_guard, pattern=".*"), group=-3)
        app.add_handler(MessageHandler(filters.ALL, authorization_guard), group=-3)
        app.add_handler(MessageHandler(filters.LOCATION, handle_timezone_location_input), group=-1)
        app.add_handler(MessageHandler(filters.Document.ALL, handle_import_document_upload), group=-1)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler), group=-1)
        # Dynamic shortcuts (/01, /a0F, ...). Built-in commands still handled by CommandHandler.
        app.add_handler(MessageHandler(filters.COMMAND, handle_dynamic_shortcut_command), group=-1)
        
        # 2. Add Alert Wizard
        register_conversation_handler(add_alert_handler)
        app.add_handler(add_alert_handler)
        register_conversation_handler(birthday_add_handler)
        app.add_handler(birthday_add_handler)

        # 3. Callback Handlers (ORDER MATTERS - more specific patterns first)
        app.add_handler(CallbackQueryHandler(log_callback_press, pattern=".*", block=False), group=-2)
        app.add_handler(CallbackQueryHandler(handle_start_request_callback, pattern="^startreq_"))
        app.add_handler(CallbackQueryHandler(handle_help_callback, pattern="^help_"))
        app.add_handler(CallbackQueryHandler(handle_legacy_review_callback, pattern=LEGACY_REVIEW_CALLBACK_PATTERN))
        app.add_handler(CallbackQueryHandler(list_alerts_start, pattern="^alert_filter_back$"))
        app.add_handler(CallbackQueryHandler(show_alerts_list, pattern="^filter_"))
        app.add_handler(CallbackQueryHandler(show_alerts_list, pattern="^alpage_"))
        app.add_handler(CallbackQueryHandler(show_next_alerts, pattern="^alert_next$"))
        app.add_handler(CallbackQueryHandler(alert_search_start, pattern="^alert_search$"))
        app.add_handler(CallbackQueryHandler(list_alerts_start, pattern="^alert_list$"))
        app.add_handler(CallbackQueryHandler(birthday_list_start, pattern="^bday_filter_back$"))
        app.add_handler(CallbackQueryHandler(show_birthdays_list, pattern=r"^bday_page_"))
        app.add_handler(CallbackQueryHandler(handle_birthday_menu, pattern="^bday_(list|next|search)$"))
        app.add_handler(CallbackQueryHandler(show_birthdays_list, pattern=r"^bday_filter_"))
        app.add_handler(CallbackQueryHandler(handle_tag_callbacks, pattern="^manage_tag_"))
        app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^settings_"))
        app.add_handler(CallbackQueryHandler(handle_manage_callback, pattern="^mgmt_"))
        app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin_"))
        app.add_handler(CallbackQueryHandler(handle_developer_callback, pattern="^developer_"))
        register_conversation_handler(edit_alert_handler)
        app.add_handler(edit_alert_handler)
        app.add_handler(CallbackQueryHandler(handle_management, pattern="^manage_"))
        
        # 4. Scheduler callback handlers (snooze, done, pre-alert ack)
        for handler in get_scheduler_handlers():
            app.add_handler(handler)

        # Ghost flow callbacks (missed-summary picker and ghost notification actions)
        app.add_handler(CallbackQueryHandler(handle_missed_dtl, pattern=r"^missed_dtl_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_set, pattern=r"^ghost_set_(?!cust_)"))
        app.add_handler(CallbackQueryHandler(handle_ghost_set_custom, pattern=r"^ghost_set_cust_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_dedup_confirm, pattern=r"^ghost_dedup_ok_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_dedup_cancel, pattern=r"^ghost_dedup_no_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_noop, pattern=r"^ghost_noop_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_noted, pattern=r"^ghost_noted_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_dtl, pattern=r"^ghost_dtl_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_del, pattern=r"^ghost_del_(?!ok_|no_)"))
        app.add_handler(CallbackQueryHandler(handle_ghost_del_confirm, pattern=r"^ghost_del_ok_"))
        app.add_handler(CallbackQueryHandler(handle_ghost_del_cancel, pattern=r"^ghost_del_no_"))
        
        # 5. Commands
        app.add_handler(CommandHandler('start', start))
        app.add_handler(CommandHandler('manage', _wrap_with_implicit_pre_cancel(manage_dashboard_start)))
        app.add_handler(CommandHandler('alerts', _wrap_with_implicit_pre_cancel(alerts_start)))
        app.add_handler(CommandHandler('help', _wrap_with_implicit_pre_cancel(help_command)))
        app.add_handler(CommandHandler('status', _wrap_with_implicit_pre_cancel(status)))
        app.add_handler(CommandHandler('settings', _wrap_with_implicit_pre_cancel(settings)))
        app.add_handler(CommandHandler('cancel', cancel))
        app.add_handler(CommandHandler('birthdays', _wrap_with_implicit_pre_cancel(birthday_start)))
        app.add_handler(CommandHandler('tags', _wrap_with_implicit_pre_cancel(tags_dashboard_start)))
        app.add_error_handler(error_handler)

        print(f"Bot is running. Admin ID: {ADMIN_ID}")
        try:
            app.run_polling()
            exit_clean = True
            exit_reason = "run_polling_returned"
        except KeyboardInterrupt:
            exit_clean = True
            exit_reason = "keyboard_interrupt"
        except Exception as exc:
            exit_clean = False
            exit_reason = f"run_polling_crash:{exc.__class__.__name__}"
            log_system("lifecycle", "run_polling_crash", {
                "error": str(exc),
                "type": exc.__class__.__name__,
            }, level="ERROR")
            raise
    finally:
        if lock_acquired:
            _record_runtime_shutdown(exit_clean, exit_reason)
        release_single_instance_lock()
