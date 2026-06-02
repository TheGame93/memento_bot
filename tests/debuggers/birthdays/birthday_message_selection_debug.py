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

from birthday_message_selection_checks import (
    parse_unknown_args,
    run_archive_integration_checks,
    run_inference_checks,
    run_selector_randomness_checks,
    run_selector_stage_checks,
)

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "birthday_message_selection_debug"
FEATURE_TITLE = "Birthday Message Selection"

IMPORT_ERROR = None
try:
    from modules.handlers.birthday_flow.message_suggestions import catalog, inference, selector
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

        run_inference_checks(dbg, inference)
        run_selector_stage_checks(dbg, selector)
        run_selector_randomness_checks(dbg, selector)
        run_archive_integration_checks(dbg, selector, catalog)

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem(
        "birthday_message_inference_failed",
        "birthday_message_selector_stage_failed",
        "birthday_message_selector_randomness_failed",
        "birthday_message_selector_archive_integration_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(
        summary_lines=[
            f"selection_checks: {'OK' if checks_ok else 'FAIL'}",
            f"runtime: {'OK' if runtime_ok else 'FAIL'}",
            f"logfile: {dbg.log_path}",
        ],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
