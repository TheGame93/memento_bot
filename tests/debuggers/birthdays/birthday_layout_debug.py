#!/usr/bin/env python3
"""birthday_layout_debug.py — Debugger for birthday message layout overhaul.

Covers steps 1-5 of plan_bdaylayout.md:
  Step 1: append_zodiac_block public export.
  Step 2: user_prefs threading through detail view chain.
  Step 3: format_main_alert birthday new layout.
  Step 4: format_pre_alert birthday new layout.
  Step 5: _format_detailed_card birthday new layout.
"""
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

from birthday_layout_checks import (
    parse_unknown_args,
    run_zodiac_public_export_checks,
    run_user_prefs_threading_checks,
    run_alert_message_layout_checks,
    run_alert_tags_position_checks,
    run_prealert_message_layout_checks,
    run_detail_card_layout_checks,
    run_new_birthday_format_checks,
)

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "birthday_layout_debug"
FEATURE_TITLE = "Birthday Message Layout (Steps 1-3)"

IMPORT_ERROR = None
try:
    from modules.scheduler_messagelogic import format_main_alert, format_pre_alert
    from modules.handlers.list_alerts import format_detailed_card
except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
    IMPORT_ERROR = exc


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = parse_unknown_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        run_zodiac_public_export_checks(dbg)
        run_user_prefs_threading_checks(dbg)
        run_alert_message_layout_checks(dbg)
        run_alert_tags_position_checks(dbg)
        run_prealert_message_layout_checks(dbg)
        run_detail_card_layout_checks(dbg)
        run_new_birthday_format_checks(dbg)

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem(
        "zodiac_public_export_checks_failed",
        "user_prefs_threading_checks_failed",
        "alert_message_layout_checks_failed",
        "alert_tags_position_checks_failed",
        "prealert_message_layout_checks_failed",
        "detail_card_layout_checks_failed",
        "new_birthday_format_checks_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(
        summary_lines=[
            f"layout_checks: {'OK' if checks_ok else 'FAIL'}",
            f"runtime: {'OK' if runtime_ok else 'FAIL'}",
            f"logfile: {dbg.log_path}",
        ],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
