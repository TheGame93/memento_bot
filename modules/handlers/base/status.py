"""Render status summaries and expose status size helpers."""

import os
import time
from datetime import datetime, timedelta

import psutil
from telegram import Update
from telegram.ext import ContextTypes

from modules import constants as C
from modules.shared.acting_as import (
    build_acting_as_banner,
    build_acting_as_payload,
    get_actor_user_id,
    get_target_user_id,
)
from modules.shared.paths import DATA_DIR, SYSTEM_LOG_DIR, USER_LOG_DIR
from modules.shared.runtime_context import (
    get_runtime_api_failure_tracker,
    get_runtime_storage,
)
from modules.shared.status_render import build_status_message, format_meta_timestamp
from modules.shared.storage_metrics import (
    get_dir_size_bytes,
    get_user_backup_dir_bytes,
    get_user_data_dir_bytes,
    get_user_event_logs_bytes,
    get_user_json_backup_files_bytes,
    get_user_json_files_bytes,
)
from modules.security.roles import build_status_role_counts
from modules.systemlog import get_log_maintenance_metrics, log_system
from modules.timezone_utils import (
    format_tz_offset,
    get_server_tz,
    get_server_tz_name,
    resolve_user_timezone,
)


def get_size_format(b, factor=1024, suffix="B"):
    """Scale bytes to its proper format (e.g., 125.50MB)"""
    for unit in ["", "K", "M", "G", "T", "P"]:
        if b < factor:
            return f"{b:.2f}{unit}{suffix}"
        b /= factor


def get_dir_size(path):
    """Calculate total size of a directory"""
    return get_dir_size_bytes(path)


def get_file_size(path):
    """Return file size in bytes, falling back to zero when unavailable."""
    try:
        return os.path.getsize(path)
    except (OSError, FileNotFoundError):
        return 0


def get_user_dirs():
    """Return numeric user directories that contain an alerts database file."""
    users = []
    if not os.path.exists(DATA_DIR):
        return users
    for entry in os.scandir(DATA_DIR):
        if not entry.is_dir():
            continue
        # User folders are numeric and contain alerts.json.
        if not entry.name.isdigit():
            continue
        if os.path.exists(os.path.join(entry.path, "alerts.json")):
            users.append(entry.name)
    return users


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render the role-scoped status summary for the current target user."""
    storage = get_runtime_storage(context)
    api_failure_tracker = get_runtime_api_failure_tracker(context)
    actor_id = get_actor_user_id(update)
    user_id = get_target_user_id(update, context)
    acting_payload = build_acting_as_payload(update, context)
    storage.log_user_event(user_id, "command_status", acting_payload)
    from modules.security.authz import get_role_map
    target = update.effective_message or update.message
    role = "user"
    actor_role = "user"
    user_time_line = None
    size_data_bytes = None
    size_logs_bytes = None
    size_backups_bytes = None
    status_build_reason = None

    try:
        # 1. Server & User Time
        try:
            server_tz = get_server_tz()
            server_now = datetime.now(server_tz)
            server_offset = format_tz_offset(server_now, server_tz)
            server_line = f"{server_now.strftime('%Y-%m-%d %H:%M:%S')} ({get_server_tz_name()}, {server_offset})"
        except Exception:
            server_tz = None
            server_now = datetime.now()
            server_line = server_now.strftime("%Y-%m-%d %H:%M:%S")
        try:
            if server_tz is not None:
                user_prefs = storage.get_user_prefs(user_id) or {}
                user_mode = user_prefs.get("timezone_mode") if isinstance(user_prefs, dict) else C.TIMEZONE_DEFAULT_MODE
                user_tz = resolve_user_timezone(user_prefs)
                if user_mode == C.TIMEZONE_MODE_USER and user_tz.key != server_tz.key:
                    user_now = server_now.astimezone(user_tz)
                    user_offset = format_tz_offset(user_now, user_tz)
                    user_time_line = f"{user_now.strftime('%Y-%m-%d %H:%M:%S')} ({user_tz.key}, {user_offset})"
        except Exception:
            user_time_line = None

        role = storage.get_user_role(user_id) or "user"
        actor_role = storage.get_user_role(actor_id) or role
        show_debug_labels = bool(C.STATUS_DEBUG_LABELS_ENABLED and actor_role == "developer")
        is_dev = role == "developer"
        is_admin = role in {"admin", "developer"}

        system_metrics = {}
        counts = {}
        log_maintenance = {}
        email_service = None
        if is_dev:
            elapsed = time.monotonic() - C.BOT_START_MONO
            uptime = timedelta(seconds=max(0, elapsed))
            uptime_str = str(uptime).split('.')[0]  # Remove microseconds
            svmem = psutil.virtual_memory()
            mem_usage = f"{svmem.percent}% ({get_size_format(svmem.used)} / {get_size_format(svmem.total)})"
            bot_log_dir_size = get_dir_size(SYSTEM_LOG_DIR)
            user_log_dir_size = get_dir_size(USER_LOG_DIR)
            system_metrics = {
                "uptime": uptime_str,
                "memory": mem_usage,
                "bot_log_size": get_size_format(bot_log_dir_size),
                "user_log_size": get_size_format(user_log_dir_size),
            }
            from modules.backup_core.email_backup import smtp_service_status
            email_svc = smtp_service_status()
            email_active_count = sum(
                1 for uid in storage.get_all_users()
                if (storage.get_backup_prefs(uid) or {}).get("email_enabled")
            )
            email_service = {
                "configured": email_svc["configured"],
                "from_addr": email_svc.get("from_addr"),
                "active_count": email_active_count,
            }

        if is_admin:
            role_map = get_role_map(admin_id=None)
            counts = build_status_role_counts(role_map)
            log_maintenance = get_log_maintenance_metrics()

        user_dir = os.path.join(DATA_DIR, str(user_id))
        images_dir = os.path.join(user_dir, "images")
        total_user_size = get_size_format(get_user_data_dir_bytes(user_id))
        size_data_bytes = get_user_json_files_bytes(user_id)
        size_data_bak_bytes = get_user_json_backup_files_bytes(user_id)
        size_logs_bytes = get_user_event_logs_bytes(storage, user_id)
        size_backups_bytes = get_user_backup_dir_bytes(user_id)
        data_json_size = get_size_format(size_data_bytes)
        data_json_bak_size = get_size_format(size_data_bak_bytes)
        images_size = get_size_format(get_dir_size(images_dir))
        user_logs_size = get_size_format(size_logs_bytes)
        user_backups_size = get_size_format(size_backups_bytes)

        alerts_count = 0
        alerts_active = 0
        birthdays_count = 0
        tags_count = 0
        try:
            data = storage.get_all_alerts(user_id) or {}
            alerts = data.get("alerts", [])
            non_bday_alerts = [a for a in alerts if a.get("type") != 6]
            alerts_count = len(non_bday_alerts)
            alerts_active = sum(1 for a in non_bday_alerts if a.get("active", True))
            birthdays_count = sum(1 for a in alerts if a.get("type") == 6)
            tags_count = len(data.get("tags", []))
        except Exception:
            pass

        user_meta_raw = storage.get_user_meta(user_id) or {}
        tz_for_meta = server_tz if server_tz is not None else get_server_tz()
        user_meta = dict(user_meta_raw)
        for key in ("added_at", "first_start", "last_seen"):
            user_meta[key] = format_meta_timestamp(user_meta_raw.get(key), tz_for_meta)
        backup_prefs = storage.get_backup_prefs(user_id)

        degraded = {
            "window_seconds": C.API_FAILURE_WINDOW_SECONDS,
            "user_failures": 0,
            "global_failures": 0,
            "user_degraded": False,
            "global_degraded": False,
        }
        try:
            snap = api_failure_tracker.snapshot(user_id)
            if isinstance(snap, dict):
                degraded.update({
                    "window_seconds": snap.get("window_seconds", degraded["window_seconds"]),
                    "user_failures": snap.get("user_failures", 0),
                    "global_failures": snap.get("global_failures", 0),
                    "user_degraded": bool(snap.get("user_degraded", False)),
                    "global_degraded": bool(snap.get("global_degraded", False)),
                })
        except Exception:
            pass

        status_message = build_status_message(
            viewer_role=role,
            subject_role=role,
            server_line=server_line,
            user_time_line=user_time_line,
            system_metrics=system_metrics,
            counts=counts,
            log_maintenance=log_maintenance,
            user_id=user_id,
            user_meta=user_meta,
            user_stats={
                "total_space": total_user_size,
                "data_json": data_json_size,
                "data_json_bak": data_json_bak_size,
                "images": images_size,
                "logs": user_logs_size,
                "backups": user_backups_size,
                "alerts_count": alerts_count,
                "alerts_active": alerts_active,
                "birthdays_count": birthdays_count,
                "tags_count": tags_count,
            },
            backup_prefs=backup_prefs,
            degraded={
                "window_seconds": degraded["window_seconds"],
                "user_failures": degraded["user_failures"],
                "global_failures": degraded["global_failures"],
                "user_icon": "🔴" if degraded["user_degraded"] else "🟢",
                "global_icon": "🔴" if degraded["global_degraded"] else "🟢",
                "user_threshold": C.API_FAILURE_USER_THRESHOLD,
                "global_threshold": C.API_FAILURE_GLOBAL_THRESHOLD,
            },
            show_debug_labels=show_debug_labels,
            email_service=email_service,
        )
        banner = build_acting_as_banner(update, context, parse_mode="Markdown")
        if banner:
            status_message = f"{banner}{status_message}"
    except Exception as exc:
        log_system("errors", "status_failed", {
            "user_id": str(user_id),
            "error": str(exc),
        }, level="ERROR")
        status_build_reason = "build_exception_fallback_sent"
        status_message = (
            "⚠️ **Status unavailable**\n"
            "The bot encountered an error while building the status report.\n"
            "Try again in a moment."
        )
    send_ok = False
    try:
        if target:
            await target.reply_text(status_message, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=actor_id, text=status_message, parse_mode="Markdown")
        send_ok = True
    except Exception:
        storage.log_user_event(user_id, "status_render_failed", {
            "reason_code": "send_failed",
            "viewer_role": role,
            "subject_role": role,
            "has_user_time": bool(user_time_line),
            "size_data_bytes": size_data_bytes,
            "size_logs_bytes": size_logs_bytes,
            "size_backups_bytes": size_backups_bytes,
            "status_len": len(status_message or ""),
            **acting_payload,
        })
        raise

    if send_ok:
        storage.log_user_event(user_id, "status_rendered", {
            "viewer_role": role,
            "subject_role": role,
            "has_user_time": bool(user_time_line),
            "size_data_bytes": size_data_bytes,
            "size_logs_bytes": size_logs_bytes,
            "size_backups_bytes": size_backups_bytes,
            "status_len": len(status_message or ""),
            "fallback_used": bool(status_build_reason),
            **acting_payload,
        })
        if status_build_reason:
            storage.log_user_event(user_id, "status_render_failed", {
                "reason_code": status_build_reason,
                "viewer_role": role,
                "subject_role": role,
                "has_user_time": bool(user_time_line),
                "size_data_bytes": size_data_bytes,
                "size_logs_bytes": size_logs_bytes,
                "size_backups_bytes": size_backups_bytes,
                "status_len": len(status_message or ""),
                **acting_payload,
            })
