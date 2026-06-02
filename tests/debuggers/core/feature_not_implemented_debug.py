#!/usr/bin/env python3
import inspect
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
SCRIPT_TITLE = "feature_not_implemented_debug"
FEATURE_TITLE = "Feature Not Implemented Message"

IMPORT_ERROR = None
try:
    from modules.shared.messages import FEATURE_NOT_IMPLEMENTED_TEXT, send_feature_not_implemented
except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
    IMPORT_ERROR = exc


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

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        expected = "Feature still not implemented, sorry for the inconvenience."
        text_ok = FEATURE_NOT_IMPLEMENTED_TEXT == expected
        dbg.section("message", {
            "expected": expected,
            "actual": FEATURE_NOT_IMPLEMENTED_TEXT,
            "checks": {"match": text_ok},
        })
        if not text_ok:
            dbg.problem("feature_message_mismatch", {"expected": expected, "actual": FEATURE_NOT_IMPLEMENTED_TEXT})

        coro_ok = inspect.iscoroutinefunction(send_feature_not_implemented)
        dbg.section("helper", {"checks": {"is_coroutine": coro_ok}})
        if not coro_ok:
            dbg.problem("feature_helper_not_coroutine", {"type": str(type(send_feature_not_implemented))})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ok = not dbg.problems
    dbg.finish(summary_lines=[f"feature_message: {'OK' if ok else 'FAIL'}"], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
