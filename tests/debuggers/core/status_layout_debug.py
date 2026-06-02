#!/usr/bin/env python3
import os
import sys


def _find_debuggers_root(start_path):
    current = os.path.abspath(os.path.dirname(start_path))
    while True:
        if os.path.basename(current) == "debuggers" and os.path.isdir(os.path.join(current, "_lib")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(os.path.dirname(start_path), ".."))
        current = parent


DEBUGGERS_ROOT = _find_debuggers_root(__file__)
if DEBUGGERS_ROOT not in sys.path:
    sys.path.insert(0, DEBUGGERS_ROOT)

from _lib.harness import DebugHarness
from _lib.root import add_project_root_to_path

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "status_layout_debug"
FEATURE_TITLE = "Status Layout Contract"

IMPORT_ERROR = None
try:
    from modules.shared.status_render import build_status_message
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc

_DBG = None


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _dbg():
    if _DBG is None:
        raise RuntimeError("debug harness not initialized")
    return _DBG


def print_section(label, payload):
    _dbg().section(label, payload)


def _log_problem(message, payload=None):
    _dbg().problem(message, payload or {})


def _base_payload():
    return {
        "server_line": "2026-03-12 21:07:28 (Europe/Rome, UTC+01:00)",
        "user_time_line": None,
        "system_metrics": {
            "uptime": "20:10:01",
            "memory": "63.9% (4.56GB / 7.14GB)",
            "bot_log_size": "8.49MB",
            "user_log_size": "3.49MB",
        },
        "counts": {"users": 23, "admins": 1, "developers": 2},
        "log_maintenance": {
            "last_run_ts": "2026-03-12T21:07:06.671689",
            "last_result": "within_limit",
            "last_limit_bytes": 10 * 1024 * 1024 * 1024,
            "last_freed_bytes": 0,
            "total_freed_bytes": 0,
            "last_deleted_rotated": 0,
            "total_deleted_rotated": 0,
            "last_truncated_current": 0,
            "total_truncated_current": 0,
        },
        "user_id": "987654321",
        "user_meta": {
            "username": "SynthDevUser",
            "display_name": "Nadia Ricci",
            "custom_name": "Nadia Ricci",
            "first_start": "2026-02-09 11:11:02 (Europe/Rome, UTC+01:00)",
            "last_seen": "2026-03-12 21:07:21 (Europe/Rome, UTC+01:00)",
        },
        "user_stats": {
            "total_space": "8.31MB",
            "data_json": "32.59KB",
            "data_json_bak": "32.59KB",
            "images": "153.85KB",
            "logs": "3.49MB",
            "backups": "32.59KB",
            "alerts_count": 7,
            "alerts_active": 7,
            "alerts_inactive": 0,
            "birthdays_count": 43,
            "tags_count": 10,
        },
        "backup_prefs": {
            "email_enabled": True,
            "email_address": "nadia.ricci@example.com",
            "last_email_sent": "2026-03-02T01:13:30.869972",
        },
        "degraded": {
            "window_seconds": 600,
            "user_failures": 0,
            "global_failures": 0,
            "user_icon": "🟢",
            "global_icon": "🟢",
            "user_threshold": 5,
            "global_threshold": 25,
        },
    }


def _contains_in_order(text, tokens):
    idx = -1
    for token in tokens:
        found = text.find(token)
        if found <= idx:
            return False
        idx = found
    return True


def _check_developer_layout():
    payload = _base_payload()
    message = build_status_message(
        viewer_role="developer",
        subject_role="developer",
        show_debug_labels=True,
        email_service={"configured": True, "from_addr": "bot.sender@example.com", "active_count": 1},
        **payload,
    )
    ordered_tokens = [
        "(U)🖥️ **System Status**",
        "(U)🕒 **Server Time:**",
        "(D)⏱️ **Uptime:**",
        "(D)🧠 **Memory:**",
        "(D)📡 **API degraded (global):",
        "(D)🧹 **Log maintenance**",
        "(D)📝 **Total bot log size:**",
        "(D)📝 **Total user log size:**",
        "(D)📧 **Email backup service:**",
        "(D)🤖 **Bot mail:**",
        "(D)📨 **Email backup active users:**",
        "(A)👥 **# of users:**",
        "(A)🛡️ **# of admins:**",
        "(D)🧑‍💻 **# of developers:**",
        "(U)👤 **User Status**",
        "(A)🏷️ **Active Label:**",
        "(A)🧩 **Custom name:**",
        "(U)👤 **Username:**",
        "(U)🧾 **Full name:**",
        "(U)🆔 **User ID:**",
        "(A)🟢 **First /start:**",
        "(A)🕒 **Last active:**",
        "(U)📂 **Folder data size:**",
        "(A)📄 **Data (.json):**",
        "(A)📄 **Data (.json.bak):**",
        "(U)🖼️ **Data (img):**",
        "(D)📝 **Log size:**",
        "(D)💾 **Backup size:**",
        "(U)✉️ **Backup via mail:**",
        "(U)📧 **Email:**",
        "(U)📤 **Last backup sent:**",
        "(U)🔔 **# of alerts:**",
        "(U)🎂 **# of birthdays:**",
        "(U)🏷️ **# of tags:**",
        "(D)📡 **API degraded:**",
    ]
    checks = {
        "ordered_layout": _contains_in_order(message, ordered_tokens),
        "separator_count": message.count("━━━━━━━━━━━━━━") >= 2,
        "alert_line_no_inactive_counter": "🔴" not in message,
        "global_service_disabled_word_absent_when_configured": "Disabled ⛔️" not in message,
        "blank_scope_marker_before_log_maintenance": "\n(D)\n(D)🧹 **Log maintenance**" in message,
        "blank_scope_marker_before_user_status": "\n(U)\n(U)👤 **User Status**" in message,
    }
    print_section("developer_layout", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_layout_failed", {"label": "developer_layout", "checks": checks})


def _check_unconfigured_service():
    payload = _base_payload()
    message = build_status_message(
        viewer_role="developer",
        subject_role="developer",
        show_debug_labels=True,
        email_service={"configured": False, "from_addr": None, "active_count": 0},
        **payload,
    )
    checks = {
        "service_disabled_label": "Disabled ⛔️" in message,
        "no_bot_mail_when_unconfigured": "🤖 **Bot mail:**" not in message,
        "no_double_scoped_blank_after_truncation": "(D)\n(A)\n(A)👥" not in message,
    }
    print_section("unconfigured_service", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_layout_failed", {"label": "unconfigured_service", "checks": checks})


def _check_admin_layout():
    payload = _base_payload()
    message = build_status_message(
        viewer_role="admin",
        subject_role="admin",
        show_debug_labels=True,
        email_service={"configured": True, "from_addr": "bot@example.com", "active_count": 1},
        **payload,
    )
    checks = {
        "admin_has_counts": "(A)👥 **# of users:**" in message and "(A)🛡️ **# of admins:**" in message,
        "admin_has_identity_admin_fields": "(A)🏷️ **Active Label:**" in message and "(A)🧩 **Custom name:**" in message,
        "admin_has_storage_rows": "(A)📄 **Data (.json):**" in message and "(A)📄 **Data (.json.bak):**" in message,
        "admin_no_dev_lines": "(D)" not in message,
        "admin_no_log_maintenance": "Log maintenance" not in message,
    }
    print_section("admin_layout", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_layout_failed", {"label": "admin_layout", "checks": checks})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        _check_developer_layout()
        _check_unconfigured_service()
        _check_admin_layout()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    checks_ok = not dbg.has_problem("status_layout_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
