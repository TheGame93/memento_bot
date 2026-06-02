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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "add_flow_reorder_debug"
FEATURE_TITLE = "Add Flow Reorder Contracts"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _collect_failed_checks(section_payloads):
    failed = []
    for section_name, payload in section_payloads.items():
        checks = payload.get("checks")
        if not isinstance(checks, dict):
            continue
        for check_name, value in checks.items():
            if not value:
                failed.append(f"{section_name}:{check_name}")
    return failed


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules import constants as C
            from modules.handlers.add_flow import flow_start
            from modules.handlers.add_flow import keyboards
            from modules.handlers.add_flow import settings_flow
            import add_flow_reorder_checks as checks_mod
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        sections = {
            "constants": checks_mod.run_constants_checks(C),
            "settings_menu": checks_mod.run_settings_change_type_button_checks(settings_flow, C),
            "change_type_keyboard": checks_mod.run_change_type_keyboard_contract_checks(keyboards),
            "change_type_schedule_clear": checks_mod.run_change_type_schedule_clearing_checks(settings_flow, C),
            "change_type_invalid_type": checks_mod.run_change_type_invalid_type_checks(settings_flow, C),
            "prompt_callback_context": checks_mod.run_prompt_type_specific_callback_context_checks(flow_start, C),
            "prompt_daily_callback_context": checks_mod.run_prompt_type_specific_daily_callback_context_checks(flow_start, C),
        }

        for section_name, payload in sections.items():
            dbg.section(section_name, payload)

        failed_checks = _collect_failed_checks(sections)
        if failed_checks:
            dbg.problem("add_flow_reorder_checks_failed", {"failed_checks": failed_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("add_flow_reorder_checks_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(
        summary_lines=[
            f"add_flow_reorder_checks: {'OK' if checks_ok else 'FAIL'}",
            f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        ],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
