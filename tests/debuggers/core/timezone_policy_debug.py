#!/usr/bin/env python3
import os
import sys
import tempfile
from datetime import datetime


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
SCRIPT_TITLE = "timezone_policy_debug"
FEATURE_TITLE = "Timezone Policy"

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


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as C
            from modules.storage import StorageManager
            from modules.timezone_utils import (
                get_server_tz,
                localize_with_shift,
                validate_tz_name,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"))
            user_id = "9001"
            storage.setup_user_space(user_id)
            prefs = storage.get_user_prefs(user_id)
            tz_prefs = prefs.get("timezone", {}) if isinstance(prefs, dict) else {}

            checks = {
                "has_user_prefs": isinstance(prefs, dict),
                "mode_default": prefs.get("timezone_mode") == C.TIMEZONE_DEFAULT_MODE,
                "tz_name_default": tz_prefs.get("name") == C.SERVER_TZ,
            }
            print_section("default_prefs", {"checks": checks})
            if not all(checks.values()):
                _log_problem("prefs_missing", {"checks": checks})

        valid = validate_tz_name(C.SERVER_TZ)
        invalid = validate_tz_name("Invalid/Zone")
        print_section("tz_validation", {"server_ok": valid, "invalid_ok": invalid})
        if not valid or invalid:
            _log_problem("tz_invalid", {"server_ok": valid, "invalid_ok": invalid})

        tz = get_server_tz()
        gap_dt = datetime(2026, 3, 29, 2, 30, 0)
        shifted_dt, shifted = localize_with_shift(gap_dt, tz)
        gap_check = {
            "shifted": shifted,
            "shifted_hour": shifted_dt.hour,
            "shifted_minute": shifted_dt.minute,
        }
        print_section("dst_gap", gap_check)
        if not shifted or shifted_dt.hour < 3:
            _log_problem("dst_shift_failed", gap_check)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    policy_ok = not dbg.has_problem("prefs_missing", "tz_invalid", "dst_shift_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"policy: {'OK' if policy_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
