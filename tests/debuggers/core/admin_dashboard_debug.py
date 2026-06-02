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
from _lib.warnings_policy import suppress_ptb_user_warning
from core.admin_dashboard_checks import AdminHelpers, run_checks

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "admin_dashboard_debug"
FEATURE_TITLE = "Admin Dashboard Helpers"

def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.handlers.admin import (
                _build_invite_message,
                _build_requests_list,
                _build_user_status,
                _build_users_list,
                _is_admin_role,
                _is_self_removal,
                _is_target_whitelisted,
                _md_escape,
                _removal_result_text,
                _requests_text,
                _user_status_keyboard,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        helpers = AdminHelpers(
            build_invite_message=_build_invite_message,
            build_requests_list=_build_requests_list,
            build_users_list=_build_users_list,
            build_user_status=_build_user_status,
            is_admin_role=_is_admin_role,
            is_self_removal=_is_self_removal,
            is_target_whitelisted=_is_target_whitelisted,
            md_escape=_md_escape,
            removal_result_text=_removal_result_text,
            requests_text=_requests_text,
            user_status_keyboard=_user_status_keyboard,
        )
        run_checks(dbg, helpers)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("admin_helpers_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"helpers: {'OK' if checks_ok else 'FAIL'}",
        f"role_protection: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
