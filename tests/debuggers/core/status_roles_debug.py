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
SCRIPT_TITLE = "status_roles_debug"
FEATURE_TITLE = "Status Role Gating"

IMPORT_ERROR = None
try:
    from modules.security.roles import build_status_role_counts
    from modules.shared.status_render import build_status_message, format_meta_timestamp
    from modules.timezone_utils import get_server_tz
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


def _build_payload():
    return {
        "server_line": "2026-02-09 10:00:00",
        "user_time_line": None,
        "system_metrics": {
            "uptime": "1 day",
            "memory": "50% (1 / 2)",
            "bot_log_size": "5 MB",
            "user_log_size": "3 MB",
        },
        "counts": {
            "users": 3,
            "admins": 1,
            "developers": 1,
        },
        "log_maintenance": {
            "last_run_ts": "2026-02-09T11:12:13",
            "last_result": "pruned_or_truncated",
            "last_limit_bytes": 1048576,
            "last_freed_bytes": 2048,
            "total_freed_bytes": 4096,
            "last_deleted_rotated": 2,
            "total_deleted_rotated": 4,
            "last_truncated_current": 1,
            "total_truncated_current": 2,
        },
        "user_id": 12345,
        "user_meta": {
            "added_at": "2026-02-09T09:00:00",
            "added_by": "987654321",
            "added_via": "admin_dashboard",
            "first_start": "2026-02-09T09:10:00",
            "last_seen": "2026-02-09T10:00:00",
            "username": "Alice",
            "display_name": "Alice Example",
            "custom_name": "Alias",
        },
        "user_stats": {
            "total_space": "1 MB",
            "data_json": "10 KB",
            "data_json_bak": "12 KB",
            "images": "0 KB",
            "logs": "5 KB",
            "backups": "0 KB",
            "alerts_count": 2,
            "alerts_active": 1,
            "alerts_inactive": 1,
            "birthdays_count": 1,
            "tags_count": 3,
        },
        "backup_prefs": {
            "email_enabled": True,
            "email_address": "user@example.com",
            "last_email_sent": "2026-02-22T23:19:09.021816",
        },
        "degraded": {
            "window_seconds": 600,
            "user_failures": 0,
            "global_failures": 1,
            "user_icon": "🟢",
            "global_icon": "🔴",
            "user_threshold": 5,
            "global_threshold": 25,
        },
    }


def _test_meta_formatting():
    tz = get_server_tz()
    formatted = format_meta_timestamp("2026-02-09T11:11:12.959321", tz)
    checks = {
        "formatted_has_date": "2026-02-09 11:11:12" in formatted,
        "formatted_has_tz": "Europe/Rome" in formatted,
        "formatted_has_offset": "UTC+01:00" in formatted,
    }
    print_section("meta_format", {"checks": checks, "formatted": formatted})
    if not all(checks.values()):
        _log_problem("status_gating_failed", {"label": "meta_format", "checks": checks, "formatted": formatted})


def _test_role_count_semantics():
    role_map = {
        "100": "user",
        "101": "admin",
        "102": "developer",
        "103": "user",
        "104": "owner",
        "105": "unexpected_role",
    }
    counts = build_status_role_counts(role_map)
    checks = {
        "users_count_role_user_only": counts.get("users") == 3,
        "admins_count": counts.get("admins") == 1,
        "developers_count": counts.get("developers") == 2,
    }
    print_section("role_count_semantics", {"counts": counts, "checks": checks, "role_map": role_map})
    if not all(checks.values()):
        _log_problem("status_role_counts_failed", {"checks": checks, "counts": counts})


def _assert_contains(message, required, forbidden, label):
    checks = {
        "required_present": all(token in message for token in required),
        "forbidden_absent": all(token not in message for token in forbidden),
    }
    print_section(label, {"checks": checks, "required": required, "forbidden": forbidden})
    if not all(checks.values()):
        _log_problem("status_gating_failed", {"label": label, "checks": checks})


def _test_user_role():
    payload = _build_payload()
    message = build_status_message(viewer_role="user", subject_role="user", **payload)
    required = [
        "Server Time",
        "User Status",
        "Username",
        "Full name",
        "User ID",
        "Folder data size",
        "Data (img)",
        "Backup via mail",
        "Email",
        "Last backup sent",
        "# of alerts",
        "# of birthdays",
        "# of tags",
    ]
    forbidden = [
        "Uptime",
        "Memory",
        "Total bot log size",
        "Total user log size",
        "API degraded (global)",
        "API degraded:",
        "# of users",
        "# of admins",
        "# of developers",
        "Log maintenance",
        "Freed bytes",
        "Rotated deleted",
        "Current logs truncated",
        "Active Label",
        "Custom name",
        "Data (.json)",
        "Data (.json.bak)",
        "First /start",
        "Last active",
        "Log size",
        "Backup size",
    ]
    _assert_contains(message, required, forbidden, "role_user")


def _test_admin_role():
    payload = _build_payload()
    message = build_status_message(viewer_role="admin", subject_role="admin", **payload)
    required = [
        "Server Time",
        "Active Label",
        "Custom name",
        "Username",
        "Full name",
        "Folder data size",
        "Data (.json)",
        "Data (.json.bak)",
        "Data (img)",
        "Backup via mail",
        "Email",
        "Last backup sent",
        "# of users",
        "# of admins",
        "First /start",
        "Last active",
    ]
    forbidden = [
        "Uptime",
        "Memory",
        "Total bot log size",
        "Total user log size",
        "API degraded (global)",
        "API degraded:",
        "# of developers",
        "Log maintenance",
        "Freed bytes",
        "Rotated deleted",
        "Current logs truncated",
        "Log size",
        "Backup size",
    ]
    _assert_contains(message, required, forbidden, "role_admin")


def _test_developer_role():
    payload = _build_payload()
    message = build_status_message(viewer_role="developer", subject_role="developer", **payload)
    required = [
        "Server Time",
        "Uptime",
        "Memory",
        "Total bot log size",
        "Total user log size",
        "API degraded (global)",
        "Log maintenance",
        "Freed bytes",
        "Rotated deleted",
        "Current logs truncated",
        "# of users",
        "# of admins",
        "# of developers",
        "Active Label",
        "Custom name",
        "Username",
        "Full name",
        "Folder data size",
        "Data (.json)",
        "Data (.json.bak)",
        "Data (img)",
        "Log size",
        "Backup size",
        "Backup via mail",
        "Email",
        "Last backup sent",
        "First /start",
        "Last active",
        "API degraded:",
    ]
    forbidden = []
    _assert_contains(message, required, forbidden, "role_developer")


def _test_debug_labels_disabled():
    payload = _build_payload()
    message = build_status_message(
        viewer_role="developer",
        subject_role="developer",
        show_debug_labels=False,
        **payload,
    )
    checks = {
        "no_user_prefix": "(U)" not in message,
        "no_admin_prefix": "(A)" not in message,
        "no_dev_prefix": "(D)" not in message,
    }
    print_section("debug_labels_disabled", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_gating_failed", {"label": "debug_labels_disabled", "checks": checks})


def _test_debug_labels_enabled():
    payload = _build_payload()
    message = build_status_message(
        viewer_role="developer",
        subject_role="developer",
        show_debug_labels=True,
        **payload,
    )
    checks = {
        "user_prefix_present": "(U)👤 **User Status**" in message,
        "dev_log_maintenance_prefix_present": "(D)🧹 **Log maintenance**" in message,
        "dev_prefix_present": "(D)⏱️ **Uptime:**" in message,
        "blank_scope_marker_present": "\n(D)\n(D)🧹 **Log maintenance**" in message,
    }
    print_section("debug_labels_enabled", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_gating_failed", {"label": "debug_labels_enabled", "checks": checks})


def _test_user_labels_only_u_scope():
    payload = _build_payload()
    message = build_status_message(
        viewer_role="user",
        subject_role="user",
        show_debug_labels=True,
        **payload,
    )
    checks = {
        "user_prefix_present": "(U)👤 **User Status**" in message,
        "admin_prefix_absent": "(A)" not in message,
        "dev_prefix_absent": "(D)" not in message,
    }
    print_section("debug_labels_user_scope", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_gating_failed", {"label": "debug_labels_user_scope", "checks": checks})


def _test_viewer_subject_split():
    payload = _build_payload()
    message = build_status_message(
        viewer_role="developer",
        subject_role="user",
        show_debug_labels=True,
        **payload,
    )
    checks = {
        "shows_subject_role_user": "(role: `user`)" in message,
        "retains_dev_visibility": "⏱️ **Uptime:**" in message and "🧑‍💻 **# of developers:**" in message,
    }
    print_section("viewer_subject_split", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_gating_failed", {"label": "viewer_subject_split", "checks": checks})


def _test_unknown_subject_role_fallback():
    payload = _build_payload()
    message = build_status_message(
        viewer_role="admin",
        subject_role=None,
        **payload,
    )
    checks = {
        "shows_unknown_subject_role": "(role: `unknown`)" in message,
        "retains_admin_visibility": "🛡️ **# of admins:**" in message and "👤 **User Status**" in message,
    }
    print_section("unknown_subject_role", {"checks": checks})
    if not all(checks.values()):
        _log_problem("status_gating_failed", {"label": "unknown_subject_role", "checks": checks})


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

        _test_meta_formatting()
        _test_role_count_semantics()
        _test_user_role()
        _test_admin_role()
        _test_developer_role()
        _test_debug_labels_disabled()
        _test_debug_labels_enabled()
        _test_user_labels_only_u_scope()
        _test_viewer_subject_split()
        _test_unknown_subject_role_fallback()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    gating_ok = not dbg.has_problem("status_gating_failed", "status_role_counts_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"gating: {'OK' if gating_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
