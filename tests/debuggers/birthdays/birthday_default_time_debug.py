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
SCRIPT_TITLE = "birthday_default_time_debug"
FEATURE_TITLE = "Birthday Default Time"

IMPORT_ERROR = None
try:
    from modules.handlers.birthday_flow.list_view import _birthday_occurrence_for_year
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

        alert_missing = {"schedule": {"date": "25/12"}}
        occ_missing = _birthday_occurrence_for_year(alert_missing, 2026, "07:30")

        alert_invalid = {"schedule": {"date": "25/12", "time": "99:99"}}
        occ_invalid = _birthday_occurrence_for_year(alert_invalid, 2026, "06:15")

        checks = {
            "missing_time_hour": occ_missing is not None and occ_missing.hour == 7 and occ_missing.minute == 30,
            "invalid_time_hour": occ_invalid is not None and occ_invalid.hour == 6 and occ_invalid.minute == 15,
        }
        dbg.section("default_time", {
            "missing": occ_missing.isoformat() if occ_missing else None,
            "invalid": occ_invalid.isoformat() if occ_invalid else None,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("birthday_default_time_failed", {"checks": checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ok = not dbg.problems
    dbg.finish(summary_lines=[f"birthday_default_time: {'OK' if ok else 'FAIL'}"], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
