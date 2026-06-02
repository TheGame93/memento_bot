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
SCRIPT_TITLE = "path_config_debug"
FEATURE_TITLE = "Path Centralization"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _test_path_constants(dbg, base_handler, paths, systemlog_dir):
    sample_token = "path-debug-token"
    token_lock_path = paths.token_global_lock_path(sample_token)
    checks = {
        "project_root_absolute": os.path.isabs(paths.PROJECT_ROOT),
        "data_dir_absolute": os.path.isabs(paths.DATA_DIR),
        "backup_dir_absolute": os.path.isabs(paths.BACKUP_DIR),
        "global_lock_dir_absolute": os.path.isabs(paths.GLOBAL_LOCK_DIR),
        "system_log_dir_absolute": os.path.isabs(paths.SYSTEM_LOG_DIR),
        "system_data_dir_absolute": os.path.isabs(paths.SYSTEM_DATA_DIR),
        "whitelist_path_absolute": os.path.isabs(paths.WHITELIST_PATH),
        "whitelist_path_parent": os.path.abspath(os.path.dirname(paths.WHITELIST_PATH)) == os.path.abspath(paths.SYSTEM_DATA_DIR),
        "whitelist_requests_absolute": os.path.isabs(paths.WHITELIST_REQUESTS_PATH),
        "whitelist_requests_parent": os.path.abspath(os.path.dirname(paths.WHITELIST_REQUESTS_PATH)) == os.path.abspath(paths.SYSTEM_DATA_DIR),
        "whitelist_invites_absolute": os.path.isabs(paths.WHITELIST_INVITES_PATH),
        "whitelist_invites_parent": os.path.abspath(os.path.dirname(paths.WHITELIST_INVITES_PATH)) == os.path.abspath(paths.SYSTEM_DATA_DIR),
        "token_lock_path_absolute": os.path.isabs(token_lock_path),
        "token_lock_under_global_dir": os.path.abspath(os.path.dirname(token_lock_path)) == os.path.abspath(paths.GLOBAL_LOCK_DIR),
        "token_lock_no_raw_token": sample_token not in token_lock_path,
        "base_data_matches_shared": os.path.abspath(base_handler.DATA_DIR) == os.path.abspath(paths.DATA_DIR),
        "base_system_log_matches_shared": os.path.abspath(base_handler.SYSTEM_LOG_DIR) == os.path.abspath(paths.SYSTEM_LOG_DIR),
        "base_user_log_matches_shared": os.path.abspath(base_handler.USER_LOG_DIR) == os.path.abspath(paths.USER_LOG_DIR),
        "systemlog_matches_shared": os.path.abspath(systemlog_dir) == os.path.abspath(paths.SYSTEM_LOG_DIR),
    }
    dbg.section("path_constants", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("path_constants_failed", {"checks": checks})


def _test_paths_writable(dbg):
    checks = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        probe_dir = os.path.join(tmpdir, "probe")
        os.makedirs(probe_dir, exist_ok=True)
        probe_file = os.path.join(probe_dir, "touch.txt")
        with open(probe_file, "w", encoding="utf-8") as handle:
            handle.write("ok")
        checks["can_create_file"] = os.path.exists(probe_file)
    dbg.section("path_writable_probe", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("path_writable_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers import base as base_handler
            from modules.shared import paths
            from modules.systemlog import LOG_DIR as SYSTEMLOG_DIR
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_path_constants(dbg, base_handler, paths, SYSTEMLOG_DIR)
        _test_paths_writable(dbg)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    constants_ok = not dbg.has_problem("path_constants_failed")
    writable_ok = not dbg.has_problem("path_writable_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"constants: {'OK' if constants_ok else 'FAIL'}",
        f"writable: {'OK' if writable_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
