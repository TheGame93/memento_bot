#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timedelta


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
SCRIPT_TITLE = "backup_retention_debug"
FEATURE_TITLE = "Backup Retention"

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
            from modules.backup_core.retention import select_retention
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        now = datetime.now().replace(microsecond=0)
        items = []
        for idx in range(1200):
            items.append({
                "id": f"b{idx}",
                "timestamp": now - timedelta(days=idx),
            })

        result = select_retention(items, now=now)
        stats = result.get("stats", {})
        keep_ids = {item.get("id") for item in result.get("keep", [])}

        checks = {
            "daily": stats.get("daily") == 7,
            "weekly": stats.get("weekly") == 4,
            "monthly": stats.get("monthly") == 6,
            "yearly": stats.get("yearly", 0) >= 1,
            "total_consistent": stats.get("total_keep") == (
                stats.get("daily", 0) + stats.get("weekly", 0)
                + stats.get("monthly", 0) + stats.get("yearly", 0)
            ),
            "most_recent_kept": "b0" in keep_ids,
        }

        print_section("retention_stats", {
            "stats": stats,
            "checks": checks,
        })

        if not (
            checks["daily"]
            and checks["weekly"]
            and checks["monthly"]
            and checks["yearly"]
            and checks["total_consistent"]
        ):
            _log_problem("retention_counts_failed", {
                "stats": stats,
                "checks": checks,
            })

        if not checks["most_recent_kept"]:
            _log_problem("retention_recent_missing", {
                "keep_sample": list(keep_ids)[:5],
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    retention_ok = not dbg.has_problem("retention_counts_failed", "retention_recent_missing")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"retention: {'OK' if retention_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
