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
SCRIPT_TITLE = "birthday_next_window_debug"
FEATURE_TITLE = "Birthday Next Window Constants"


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
            from modules import constants as C
            from modules.handlers.birthday_flow import list_view  # noqa: F401
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        past = getattr(C, "BIRTHDAY_NEXT_PAST_DAYS", None)
        future = getattr(C, "BIRTHDAY_NEXT_FUTURE_DAYS", None)

        checks = {
            "past_is_int": isinstance(past, int),
            "future_is_int": isinstance(future, int),
            "past_positive": isinstance(past, int) and past > 0,
            "future_positive": isinstance(future, int) and future > 0,
            "past_lt_future": isinstance(past, int) and isinstance(future, int) and past < future,
        }
        dbg.section("birthday_next_window", {
            "past_days": past,
            "future_days": future,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("birthday_next_window_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("birthday_next_window_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"constants: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
