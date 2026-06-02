#!/usr/bin/env python3
import os
import sys
import time
from datetime import timedelta


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
SCRIPT_TITLE = "bot_uptime_debug"
FEATURE_TITLE = "Bot Uptime Monotonic"

IMPORT_ERROR = None
try:
    from modules import constants as C
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


def _test_bot_start_monotonic():
    start = getattr(C, "BOT_START_MONO", None)
    checks = {
        "exists": start is not None,
        "is_number": isinstance(start, (int, float)),
        "elapsed_non_negative": False,
        "formatted_non_empty": False,
    }
    elapsed = None
    formatted = None
    if checks["exists"] and checks["is_number"]:
        elapsed = time.monotonic() - start
        checks["elapsed_non_negative"] = elapsed >= 0
        formatted = str(timedelta(seconds=max(0, elapsed))).split('.')[0]
        checks["formatted_non_empty"] = bool(formatted)

    print_section("bot_uptime_monotonic", {
        "checks": checks,
        "start_value": start,
        "elapsed": elapsed,
        "formatted": formatted,
    })
    if not all(checks.values()):
        _log_problem("bot_uptime_invalid", {
            "checks": checks,
            "start_value": start,
            "elapsed": elapsed,
        })


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

        _test_bot_start_monotonic()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    check_ok = not dbg.has_problem("bot_uptime_invalid")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"uptime: {'OK' if check_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
