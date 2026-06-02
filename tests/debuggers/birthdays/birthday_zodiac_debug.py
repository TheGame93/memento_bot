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

from birthday_zodiac_checks import (
    parse_unknown_args,
    run_western_zodiac_checks,
    run_eastern_zodiac_checks,
    run_zodiac_info_checks,
    run_format_checks,
    run_cny_table_checks,
    run_zodiac_constants_checks,
    run_storage_default_checks,
    run_scheduler_zodiac_checks,
    run_birthday_summary_zodiac_checks,
    run_zodiac_assembler_checks,
    run_infer_zodiac_context_checks,
)

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "birthday_zodiac_debug"
FEATURE_TITLE = "Zodiac Module (Western + Eastern)"

IMPORT_ERROR = None
try:
    from modules import zodiac
    from modules import constants
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

        run_cny_table_checks(dbg, zodiac)
        run_western_zodiac_checks(dbg, zodiac)
        run_eastern_zodiac_checks(dbg, zodiac)
        run_zodiac_info_checks(dbg, zodiac)
        run_format_checks(dbg, zodiac)
        run_zodiac_constants_checks(dbg, constants)
        run_storage_default_checks(dbg)
        run_scheduler_zodiac_checks(dbg)
        run_birthday_summary_zodiac_checks(dbg)
        run_zodiac_assembler_checks(dbg)
        run_infer_zodiac_context_checks(dbg)

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem(
        "cny_table_checks_failed",
        "western_zodiac_checks_failed",
        "eastern_zodiac_checks_failed",
        "zodiac_info_checks_failed",
        "format_checks_failed",
        "zodiac_constants_checks_failed",
        "storage_default_checks_failed",
        "scheduler_zodiac_checks_failed",
        "birthday_summary_zodiac_checks_failed",
        "zodiac_assembler_checks_failed",
        "infer_zodiac_context_checks_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(
        summary_lines=[
            f"zodiac_checks: {'OK' if checks_ok else 'FAIL'}",
            f"runtime: {'OK' if runtime_ok else 'FAIL'}",
            f"logfile: {dbg.log_path}",
        ],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
