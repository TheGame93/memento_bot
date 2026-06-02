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
SCRIPT_TITLE = "manage_dashboard_debug"
FEATURE_TITLE = "Manage Dashboard Helpers"

IMPORT_ERROR = None
try:
    from modules.handlers.manage import (
        build_manage_keyboard,
        build_manage_text,
        _is_elevated,
    )
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


def _test_admin_keyboard():
    kb = build_manage_keyboard("admin", None)
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    checks = {
        "rows": len(kb.inline_keyboard) == 3,
        "has_user_list": any("User List" in label for label in labels),
        "has_pending_request": any("Pending Request" in label for label in labels),
        "has_add_user": any("Add User" in label for label in labels),
        "has_pending_invite": any("Pending Invite" in label for label in labels),
        "no_storage": not any("Storage" in label for label in labels),
        "no_export": not any("Export" in label for label in labels),
        "no_import": not any("Import" in label for label in labels),
        "no_stop_acting": not any("Stop Acting" in label for label in labels),
    }
    print_section("admin_keyboard", {"labels": labels, "checks": checks})
    if not all(checks.values()):
        _log_problem("manage_helpers_failed", {"step": "admin_keyboard", "checks": checks})


def _test_developer_keyboard():
    kb_none = build_manage_keyboard("developer", None)
    kb_target = build_manage_keyboard("developer", "123")
    labels_none = [btn.text for row in kb_none.inline_keyboard for btn in row]
    labels_target = [btn.text for row in kb_target.inline_keyboard for btn in row]
    checks = {
        "rows_none": len(kb_none.inline_keyboard) == 4,
        "rows_target": len(kb_target.inline_keyboard) == 5,
        "has_storage": any("Storage" in label for label in labels_none),
        "has_admin_buttons": any("Pending Request" in label for label in labels_none),
        "stop_acting_only_on_target": ("Stop Acting" not in " ".join(labels_none)) and any("Stop Acting" in label for label in labels_target),
    }
    print_section("developer_keyboard", {
        "labels_none": labels_none,
        "labels_target": labels_target,
        "checks": checks,
    })
    if not all(checks.values()):
        _log_problem("manage_helpers_failed", {"step": "developer_keyboard", "checks": checks})


def _test_dashboard_text():
    admin_text = build_manage_text("admin")
    dev_none_text = build_manage_text("developer")
    dev_target_text = build_manage_text("developer", "456", "@alpha")
    checks = {
        "admin_title": "Manage Dashboard" in admin_text,
        "admin_no_acting": "Acting as" not in admin_text,
        "dev_none": "Acting as: `none`" in dev_none_text,
        "dev_target": "Acting as: @alpha" in dev_target_text,
    }
    print_section("dashboard_text", {
        "admin_text": admin_text,
        "dev_none_text": dev_none_text,
        "dev_target_text": dev_target_text,
        "checks": checks,
    })
    if not all(checks.values()):
        _log_problem("manage_helpers_failed", {"step": "dashboard_text", "checks": checks})


def _test_role_guard():
    checks = {
        "admin_true": _is_elevated("admin") is True,
        "dev_true": _is_elevated("developer") is True,
        "user_false": _is_elevated("user") is False,
        "none_false": _is_elevated(None) is False,
    }
    print_section("role_guard", {"checks": checks})
    if not all(checks.values()):
        _log_problem("manage_helpers_failed", {"step": "role_guard", "checks": checks})


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

        _test_admin_keyboard()
        _test_developer_keyboard()
        _test_dashboard_text()
        _test_role_guard()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    helpers_ok = not dbg.has_problem("manage_helpers_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"helpers: {'OK' if helpers_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
