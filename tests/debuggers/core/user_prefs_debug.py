#!/usr/bin/env python3
import json
import os
import sys
import tempfile


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
SCRIPT_TITLE = "user_prefs_debug"
FEATURE_TITLE = "User Preferences Defaults"


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

        try:
            from modules import constants as C
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=None)
            user_id = 42
            storage.setup_user_space(user_id)

            prefs = storage.get_user_prefs(user_id)
            checks = {
                "prefs_dict": isinstance(prefs, dict),
                "has_timezone_mode": "timezone_mode" in prefs,
                "has_timezone": isinstance(prefs.get("timezone"), dict),
                "has_birthday_default": prefs.get("birthday_default_time") == C.BIRTHDAY_DEFAULT_TIME,
                "has_birthday_evening_default": (
                    prefs.get("birthday_evening_before_time") == C.BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME
                ),
                "has_zodiac_mode_default": (
                    prefs.get("birthday_zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_NONE
                ),
            }
            dbg.section("defaults", {"checks": checks, "prefs": prefs})
            if not all(checks.values()):
                dbg.problem("user_prefs_defaults_failed", {"checks": checks})

            legacy_path = os.path.join(tmpdir, "data", "99", "alerts.json")
            os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
            with open(legacy_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "tags": [],
                    "alerts": [],
                    "postpone_queue": [],
                    "user_prefs": {"timezone_mode": "server"},
                }, handle)

            legacy_prefs = storage.get_user_prefs(99)
            legacy_checks = {
                "legacy_merge": legacy_prefs.get("birthday_default_time") == C.BIRTHDAY_DEFAULT_TIME,
                "legacy_evening_merge": (
                    legacy_prefs.get("birthday_evening_before_time")
                    == C.BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME
                ),
                "legacy_zodiac_mode_merge": (
                    legacy_prefs.get("birthday_zodiac_mode") == C.BIRTHDAY_ZODIAC_MODE_NONE
                ),
                "legacy_timezone_mode": legacy_prefs.get("timezone_mode") == "server",
                "legacy_timezone_present": isinstance(legacy_prefs.get("timezone"), dict),
            }
            dbg.section("legacy_merge", {"checks": legacy_checks, "prefs": legacy_prefs})
            if not all(legacy_checks.values()):
                dbg.problem("user_prefs_legacy_merge_failed", {"checks": legacy_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    prefs_ok = not dbg.has_problem("user_prefs_defaults_failed", "user_prefs_legacy_merge_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"prefs: {'OK' if prefs_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
