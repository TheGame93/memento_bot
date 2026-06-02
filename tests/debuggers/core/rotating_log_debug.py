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
from core.rotating_log_checks import run_checks

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "rotating_log_debug"
FEATURE_TITLE = "Log Rotation"

IMPORT_ERROR = None
try:
    from modules import systemlog as sl
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _reset_cache():
    sl.clear_logger_cache()
    sl._last_prune_mono = 0.0
    sl._last_wall_dt = None
    sl._last_mono_ts = None
    sl._clock_event_in_progress = False


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)

    if IMPORT_ERROR is not None:
        dbg.run_meta({"project_root": ROOT_DIR})
        dbg.mark_dependency_error(IMPORT_ERROR)
        dbg.finish(exit_on_problems=False)
        return

    original = {
        "ROTATION_BACKUP_COUNT": sl.ROTATION_BACKUP_COUNT,
        "DEFAULT_LOG_RETENTION_DAYS": sl.DEFAULT_LOG_RETENTION_DAYS,
        "USER_LOG_RETENTION_DAYS": sl.USER_LOG_RETENTION_DAYS,
        "LOG_RETENTION_DAYS": dict(sl.LOG_RETENTION_DAYS),
        "ROTATION_WHEN": sl.ROTATION_WHEN,
        "ROTATION_INTERVAL": sl.ROTATION_INTERVAL,
        "LOG_SIZE_LIMIT_BYTES": sl.LOG_SIZE_LIMIT_BYTES,
        "LOGGER_CACHE_MAX_ENTRIES": sl.LOGGER_CACHE_MAX_ENTRIES,
        "LOG_DIR": sl.LOG_DIR,
        "DATA_DIR": sl.DATA_DIR,
        "USER_LOG_DIR": sl.USER_LOG_DIR,
        "SUMMARY_LOG": sl.SUMMARY_LOG,
        "RUNTIME_STATE_FILE": sl.RUNTIME_STATE_FILE,
    }

    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        run_checks(dbg, sl)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        sl.ROTATION_BACKUP_COUNT = original["ROTATION_BACKUP_COUNT"]
        sl.DEFAULT_LOG_RETENTION_DAYS = original["DEFAULT_LOG_RETENTION_DAYS"]
        sl.USER_LOG_RETENTION_DAYS = original["USER_LOG_RETENTION_DAYS"]
        sl.LOG_RETENTION_DAYS = original["LOG_RETENTION_DAYS"]
        sl.ROTATION_WHEN = original["ROTATION_WHEN"]
        sl.ROTATION_INTERVAL = original["ROTATION_INTERVAL"]
        sl.LOG_SIZE_LIMIT_BYTES = original["LOG_SIZE_LIMIT_BYTES"]
        sl.LOGGER_CACHE_MAX_ENTRIES = original["LOGGER_CACHE_MAX_ENTRIES"]
        sl.LOG_DIR = original["LOG_DIR"]
        sl.DATA_DIR = original["DATA_DIR"]
        sl.USER_LOG_DIR = original["USER_LOG_DIR"]
        sl.SUMMARY_LOG = original["SUMMARY_LOG"]
        sl.RUNTIME_STATE_FILE = original["RUNTIME_STATE_FILE"]
        _reset_cache()

    config_ok = not dbg.has_problem(
        "rotation_policy_mismatch",
        "size_policy_mismatch",
        "user_retention_detection_failed",
        "logger_cache_eviction_failed",
    )
    rotate_ok = not dbg.has_problem("rotation_missing", "json_parse_failed")
    retention_ok = not dbg.has_problem("retention_failed")
    security_ok = not dbg.has_problem("category_sanitize_failed")
    cap_ok = not dbg.has_problem("size_cap_failed")
    observability_ok = not dbg.has_problem("maintenance_metrics_failed", "identity_tag_missing")
    runtime_ok = not dbg.has_problem(
        "downtime_summary_failed",
        "downtime_identity_fields_missing",
        "clock_jump_not_logged",
        "unhandled_exception",
        "cli_args_unknown",
    )
    dbg.finish(summary_lines=[
        f"config: {'OK' if config_ok else 'FAIL'}",
        f"rollover: {'OK' if rotate_ok else 'FAIL'}",
        f"retention: {'OK' if retention_ok else 'FAIL'}",
        f"safety: {'OK' if security_ok else 'FAIL'}",
        f"size-cap: {'OK' if cap_ok else 'FAIL'}",
        f"observability: {'OK' if observability_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
