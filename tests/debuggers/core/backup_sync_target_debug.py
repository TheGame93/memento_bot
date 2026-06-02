#!/usr/bin/env python3
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
SCRIPT_TITLE = "backup_sync_target_debug"
FEATURE_TITLE = "Backup Sync Target"

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
            from modules.backup_core.sync_target import sync_backup_file
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            sync_dir = os.path.join(tmpdir, "sync")
            previous_external_dir = os.environ.get("BOT_EXTERNAL_BACKUP_DIR")
            os.environ["BOT_EXTERNAL_BACKUP_DIR"] = sync_dir

            try:
                user_id = "1001"
                src_path = os.path.join(tmpdir, "backup.zip")
                with open(src_path, "wb") as handle:
                    handle.write(b"fakebackup")

                result = sync_backup_file(src_path, user_id)
                dest_path = os.path.join(sync_dir, "users", user_id, "backup.zip")

                checks = {
                    "sync_ok": result.get("ok") is True,
                    "dest_exists": os.path.isfile(dest_path),
                }

                print_section("sync_checks", {"checks": checks})
                if not all(checks.values()):
                    _log_problem("sync_failed", {"checks": checks, "result": result})
            finally:
                if previous_external_dir is None:
                    os.environ.pop("BOT_EXTERNAL_BACKUP_DIR", None)
                else:
                    os.environ["BOT_EXTERNAL_BACKUP_DIR"] = previous_external_dir
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    sync_ok = not dbg.has_problem("sync_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"sync: {'OK' if sync_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
