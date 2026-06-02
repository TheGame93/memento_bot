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
SCRIPT_TITLE = "status_email_service_debug"
FEATURE_TITLE = "Email Service in /status and /manage Text Contract"

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


def _log_problem(message, payload=None):
    _dbg().problem(message, payload or {})


# =========================================================================
# CHECK: smtp_service_status() return shape
# =========================================================================

def check_smtp_service_status_shape():
    from modules.backup_core.email_backup import smtp_service_status

    result = smtp_service_status()
    _dbg().section("smtp_service_status_result", {"result": result})

    if not isinstance(result, dict):
        _log_problem("smtp_service_status_not_dict", {"type": type(result).__name__})
        return

    required_keys = {"configured", "reason", "from_addr"}
    missing = required_keys - set(result.keys())
    if missing:
        _log_problem("smtp_service_status_missing_keys", {"missing": sorted(missing)})

    if not isinstance(result.get("configured"), bool):
        _log_problem("smtp_service_status_configured_not_bool", {"value": result.get("configured")})


# =========================================================================
# CHECK: smtp_service_status() with env manipulation
# =========================================================================

def check_smtp_service_status_unconfigured():
    """Verify that when SMTP host is missing, status reports unconfigured."""
    from modules.backup_core.email_backup import smtp_service_status

    saved_host = os.environ.get("BOT_SMTP_HOST")
    try:
        os.environ.pop("BOT_SMTP_HOST", None)
        result = smtp_service_status()
        _dbg().section("smtp_unconfigured_result", {"result": result})
        if result.get("configured") is not False:
            _log_problem("smtp_unconfigured_should_be_false", {"result": result})
        if result.get("from_addr") is not None:
            _log_problem("smtp_unconfigured_from_addr_should_be_none", {"from_addr": result.get("from_addr")})
    finally:
        if saved_host is not None:
            os.environ["BOT_SMTP_HOST"] = saved_host
        else:
            os.environ.pop("BOT_SMTP_HOST", None)


def check_smtp_service_status_configured():
    """Verify that when SMTP host is set, status reports configured."""
    from modules.backup_core.email_backup import smtp_service_status

    saved = {
        "BOT_SMTP_HOST": os.environ.get("BOT_SMTP_HOST"),
        "BOT_SMTP_FROM": os.environ.get("BOT_SMTP_FROM"),
    }
    try:
        os.environ["BOT_SMTP_HOST"] = "smtp.example.com"
        os.environ["BOT_SMTP_FROM"] = "bot@example.com"
        result = smtp_service_status()
        _dbg().section("smtp_configured_result", {"result": result})
        if result.get("configured") is not True:
            _log_problem("smtp_configured_should_be_true", {"result": result})
        if result.get("from_addr") != "bot@example.com":
            _log_problem("smtp_configured_from_addr_wrong", {"from_addr": result.get("from_addr")})
    finally:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def check_smtp_service_status_empty_from():
    """Verify that empty/whitespace BOT_SMTP_FROM falls back correctly."""
    from modules.backup_core.email_backup import smtp_service_status

    saved = {
        "BOT_SMTP_HOST": os.environ.get("BOT_SMTP_HOST"),
        "BOT_SMTP_FROM": os.environ.get("BOT_SMTP_FROM"),
        "BOT_SMTP_USER": os.environ.get("BOT_SMTP_USER"),
    }
    try:
        os.environ["BOT_SMTP_HOST"] = "smtp.example.com"
        os.environ["BOT_SMTP_FROM"] = "   "
        os.environ.pop("BOT_SMTP_USER", None)
        result = smtp_service_status()
        _dbg().section("smtp_empty_from_result", {"result": result})
        if result.get("from_addr") is not None:
            _log_problem("smtp_empty_from_should_be_none", {"from_addr": result.get("from_addr")})
    finally:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


# =========================================================================
# CHECK: build_status_message with email_service
# =========================================================================

def check_status_message_with_email_service():
    from modules.shared.status_render import build_status_message

    base_kwargs = {
        "viewer_role": "developer",
        "subject_role": "developer",
        "server_line": "2026-03-04 10:00:00 (Europe/Rome, +01:00)",
        "user_time_line": None,
        "system_metrics": {
            "uptime": "1:00:00",
            "memory": "50% (1.00GB / 2.00GB)",
            "bot_log_size": "5.00KB",
            "user_log_size": "2.00KB",
        },
        "counts": {"users": 2, "admins": 1, "developers": 1},
        "user_id": "12345",
        "user_meta": {},
        "user_stats": {
            "total_space": "10.00KB",
            "data_json": "5.00KB",
            "images": "0.00B",
            "logs": "1.00KB",
            "backups": "2.00KB",
            "alerts_count": 5,
            "alerts_active": 3,
            "alerts_inactive": 2,
            "birthdays_count": 1,
            "tags_count": 2,
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

    # Test with email_service provided
    email_svc = {"configured": True, "from_addr": "bot@example.com", "active_count": 2}
    result = build_status_message(**base_kwargs, email_service=email_svc)
    _dbg().section("status_with_email_service", {"output_len": len(result)})

    if "Email backup service" not in result:
        _log_problem("status_missing_email_service_line", {"result_snippet": result[:500]})
    if "Configured ✅" not in result:
        _log_problem("status_missing_configured_label", {"result_snippet": result[:500]})
    if "Bot mail" not in result:
        _log_problem("status_missing_bot_mail_label", {"result_snippet": result[:500]})
    if "bot@example.com" not in result:
        _log_problem("status_missing_from_addr", {"result_snippet": result[:500]})
    if "Email backup active users" not in result:
        _log_problem("status_missing_active_users_line", {"result_snippet": result[:500]})

    # Test with email_service unconfigured
    email_svc_off = {"configured": False, "from_addr": None, "active_count": 0}
    result_off = build_status_message(**base_kwargs, email_service=email_svc_off)
    _dbg().section("status_with_email_unconfigured", {"output_len": len(result_off)})
    if "Disabled ⛔️" not in result_off:
        _log_problem("status_missing_disabled_label", {"result_snippet": result_off[:500]})
    if "Bot mail:" in result_off:
        _log_problem("status_unconfigured_shows_bot_mail", {"result_snippet": result_off[:500]})

    # Test with from_addr containing underscores (markdown escape check)
    email_svc_underscore = {"configured": True, "from_addr": "my_bot@example.com", "active_count": 1}
    result_esc = build_status_message(**base_kwargs, email_service=email_svc_underscore)
    _dbg().section("status_email_underscore_escape", {"output_len": len(result_esc)})
    # In legacy Markdown, underscores must be escaped to avoid italic parsing.
    if "🤖 **Bot mail:**" not in result_esc:
        _log_problem("status_missing_bot_mail_line", {"result_snippet": result_esc[:500]})
    if "my_bot@example.com" in result_esc and r"my\_bot@example.com" not in result_esc:
        _log_problem("status_from_addr_underscore_not_escaped", {"result_snippet": result_esc[:500]})


def check_status_message_without_email_service():
    """Backward compat: build_status_message without email_service still works."""
    from modules.shared.status_render import build_status_message

    base_kwargs = {
        "viewer_role": "developer",
        "subject_role": "developer",
        "server_line": "2026-03-04 10:00:00",
        "user_time_line": None,
        "system_metrics": {
            "uptime": "1:00:00",
            "memory": "50%",
            "bot_log_size": "5KB",
            "user_log_size": "2KB",
        },
        "counts": {"users": 1, "admins": 0, "developers": 1},
        "user_id": "99999",
        "user_meta": {},
        "user_stats": {
            "total_space": "0B",
            "data_json": "0B",
            "images": "0B",
            "logs": "0B",
            "backups": "0B",
            "alerts_count": 0,
            "alerts_active": 0,
            "alerts_inactive": 0,
            "birthdays_count": 0,
            "tags_count": 0,
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

    # Must not raise — backward compat
    try:
        result = build_status_message(**base_kwargs)
        _dbg().section("status_without_email_service", {"output_len": len(result)})
        if "Email backup service" in result:
            _log_problem("status_shows_email_without_param", {"result_snippet": result[:500]})
        if "Bot mail:" in result:
            _log_problem("status_shows_bot_mail_without_param", {"result_snippet": result[:500]})
    except Exception as exc:
        _log_problem("status_without_email_service_raises", {"error": str(exc)})


def check_status_message_user_role_no_email():
    """Regular user role should never see email service lines."""
    from modules.shared.status_render import build_status_message

    email_svc = {"configured": True, "from_addr": "bot@example.com", "active_count": 5}
    result = build_status_message(
        viewer_role="user",
        subject_role="user",
        server_line="2026-03-04 10:00:00",
        user_time_line=None,
        system_metrics={},
        counts={},
        user_id="11111",
        user_meta={},
        user_stats={
            "total_space": "0B", "data_json": "0B", "images": "0B",
            "logs": "0B", "backups": "0B",
            "alerts_count": 0, "alerts_active": 0, "alerts_inactive": 0,
            "birthdays_count": 0, "tags_count": 0,
        },
        degraded={
            "window_seconds": 600, "user_failures": 0, "global_failures": 0,
            "user_icon": "🟢", "global_icon": "🟢",
            "user_threshold": 5, "global_threshold": 25,
        },
        email_service=email_svc,
    )
    _dbg().section("status_user_role_with_email", {"output_len": len(result)})
    if "Email backup service" in result:
        _log_problem("status_user_sees_email_service", {"result_snippet": result[:500]})


# =========================================================================
# CHECK: build_manage_text contract (/manage has no SMTP summary line)
# =========================================================================

def check_manage_text_developer():
    from modules.handlers.manage import build_manage_text

    result = build_manage_text("developer")
    _dbg().section("manage_text_developer", {"result": result})
    if "Email service" in result:
        _log_problem("manage_text_developer_shows_email_service", {"result": result})
    if "Acting as:" not in result:
        _log_problem("manage_text_developer_missing_acting_line", {"result": result})


def check_manage_text_admin_no_email():
    from modules.handlers.manage import build_manage_text

    result = build_manage_text("admin")
    _dbg().section("manage_text_admin", {"result": result})
    if "Email service" in result:
        _log_problem("manage_text_admin_shows_email_service", {"result": result})


def check_manage_text_developer_unconfigured():
    from modules.handlers.manage import build_manage_text

    saved_host = os.environ.get("BOT_SMTP_HOST")
    try:
        os.environ.pop("BOT_SMTP_HOST", None)
        result = build_manage_text("developer")
        _dbg().section("manage_text_developer_unconfigured", {"result": result})
        if "Email service" in result:
            _log_problem("manage_text_developer_unconfigured_shows_email", {"result": result})
        if "Acting as:" not in result:
            _log_problem("manage_text_developer_unconfigured_missing_acting_line", {"result": result})
    finally:
        if saved_host is None:
            os.environ.pop("BOT_SMTP_HOST", None)
        else:
            os.environ["BOT_SMTP_HOST"] = saved_host


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.backup_core.email_backup import smtp_service_status
            from modules.shared.status_render import build_status_message
            from modules.handlers.manage import build_manage_text
        except Exception as exc:
            dbg.mark_dependency_error(exc)
            return

        check_smtp_service_status_shape()
        check_smtp_service_status_unconfigured()
        check_smtp_service_status_configured()
        check_smtp_service_status_empty_from()
        check_status_message_with_email_service()
        check_status_message_without_email_service()
        check_status_message_user_role_no_email()
        check_manage_text_developer()
        check_manage_text_admin_no_email()
        check_manage_text_developer_unconfigured()

        summary = []
        if dbg.problems:
            summary.append(f"PROBLEMS: {len(dbg.problems)}")
            for p in dbg.problems:
                summary.append(f"  - {p}")
        else:
            summary.append("All checks passed.")

        dbg.finish(summary_lines=summary, summary_only_on_problems=True)

    except SystemExit:
        raise
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
        dbg.finish(summary_lines=[f"FATAL: {exc}"])


if __name__ == "__main__":
    main()
