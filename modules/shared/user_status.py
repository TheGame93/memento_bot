import os
import time
import psutil
from datetime import datetime, timedelta

from modules.handlers.base import get_size_format
from modules.security.authz import get_role_map
from modules.security.roles import build_status_role_counts
from modules.shared.storage_metrics import (
    get_dir_size_bytes,
    get_user_backup_dir_bytes,
    get_user_data_dir_bytes,
    get_user_event_logs_bytes,
    get_user_json_backup_files_bytes,
    get_user_json_files_bytes,
)
from modules.shared.status_render import build_status_message, format_meta_timestamp
from modules.systemlog import get_log_maintenance_metrics
from modules.timezone_utils import (
    format_tz_offset,
    get_server_tz,
    get_server_tz_name,
    resolve_user_timezone,
)
from modules.shared.paths import DATA_DIR, SYSTEM_LOG_DIR, USER_LOG_DIR
from modules import constants as C


VALID_STATUS_ROLES = {"user", "admin", "developer"}


def _normalize_viewer_role(role):
    text = str(role).strip().lower() if role is not None else ""
    if text in VALID_STATUS_ROLES:
        return text
    return "user"


def build_user_status_message(
    storage,
    user_id,
    *,
    viewer_role=None,
    actor_role=None,
    api_failure_tracker=None,
):
    """Assemble all status metrics and render a role-scoped `/status` response."""
    server_tz = get_server_tz()
    server_now = datetime.now(server_tz)
    server_offset = format_tz_offset(server_now, server_tz)
    server_line = f"{server_now.strftime('%Y-%m-%d %H:%M:%S')} ({get_server_tz_name()}, {server_offset})"

    user_time_line = None
    try:
        user_prefs = storage.get_user_prefs(user_id) or {}
        user_mode = user_prefs.get("timezone_mode") if isinstance(user_prefs, dict) else C.TIMEZONE_DEFAULT_MODE
        user_tz = resolve_user_timezone(user_prefs)
        if user_mode == C.TIMEZONE_MODE_USER and user_tz.key != server_tz.key:
            user_now = server_now.astimezone(user_tz)
            user_offset = format_tz_offset(user_now, user_tz)
            user_time_line = f"{user_now.strftime('%Y-%m-%d %H:%M:%S')} ({user_tz.key}, {user_offset})"
    except Exception:
        user_time_line = None

    user_dir = os.path.join(DATA_DIR, str(user_id))
    images_dir = os.path.join(user_dir, "images")

    total_user_size = get_size_format(get_user_data_dir_bytes(user_id))
    data_json_size = get_size_format(get_user_json_files_bytes(user_id))
    data_json_bak_size = get_size_format(get_user_json_backup_files_bytes(user_id))
    images_size = get_size_format(get_dir_size_bytes(images_dir))
    user_logs_size = get_size_format(get_user_event_logs_bytes(storage, user_id))
    user_backups_size = get_size_format(get_user_backup_dir_bytes(user_id))

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
    user_meta = dict(user_meta_raw)
    for key in ("added_at", "first_start", "last_seen"):
        user_meta[key] = format_meta_timestamp(user_meta_raw.get(key), server_tz)
    backup_prefs = storage.get_backup_prefs(user_id)

    degraded = {
        "window_seconds": C.API_FAILURE_WINDOW_SECONDS,
        "user_failures": 0,
        "global_failures": 0,
        "user_degraded": False,
        "global_degraded": False,
    }
    try:
        if api_failure_tracker is None:
            snap = None
        else:
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

    viewer_role = _normalize_viewer_role(viewer_role)
    effective_actor_role = _normalize_viewer_role(actor_role or viewer_role)
    subject_role = None
    try:
        subject_role = storage.get_user_role(user_id)
    except Exception:
        subject_role = None
    show_debug_labels = bool(C.STATUS_DEBUG_LABELS_ENABLED and effective_actor_role == "developer")
    system_metrics = {}
    counts = {}
    log_maintenance = {}
    if viewer_role == "developer":
        elapsed = time.monotonic() - C.BOT_START_MONO
        uptime = timedelta(seconds=max(0, elapsed))
        uptime_str = str(uptime).split('.')[0]
        svmem = psutil.virtual_memory()
        mem_usage = f"{svmem.percent}% ({get_size_format(svmem.used)} / {get_size_format(svmem.total)})"
        bot_log_dir_size = get_dir_size_bytes(SYSTEM_LOG_DIR)
        user_log_dir_size = get_dir_size_bytes(USER_LOG_DIR)
        system_metrics = {
            "uptime": uptime_str,
            "memory": mem_usage,
            "bot_log_size": get_size_format(bot_log_dir_size),
            "user_log_size": get_size_format(user_log_dir_size),
        }
    if viewer_role in {"admin", "developer"}:
        role_map = get_role_map(admin_id=None)
        counts = build_status_role_counts(role_map)
        log_maintenance = get_log_maintenance_metrics()
    return build_status_message(
        viewer_role=viewer_role,
        subject_role=subject_role,
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
    )
