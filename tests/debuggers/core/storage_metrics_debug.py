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
SCRIPT_TITLE = "storage_metrics_debug"
FEATURE_TITLE = "Shared Storage Metrics Helpers"

IMPORT_ERROR = None
try:
    from modules.shared import storage_metrics as sm
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


def _write_bytes(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * int(size))


class _DummyStorage:
    def __init__(self, base_data):
        self._base_data = base_data

    def get_user_event_log_path(self, user_id):
        return os.path.join(self._base_data, "userlog.d", f"{user_id}_events.log")


def _run_checks():
    with tempfile.TemporaryDirectory(prefix="storage_metrics_debug_") as tmp:
        data_dir = os.path.join(tmp, "data")
        backup_dir = os.path.join(tmp, "backups")
        user_backup_dir = os.path.join(backup_dir, "users")
        user_log_dir = os.path.join(data_dir, "userlog.d")

        _write_bytes(os.path.join(data_dir, "42", "alerts.json"), 11)
        _write_bytes(os.path.join(data_dir, "42", "prefs.json"), 7)
        _write_bytes(os.path.join(data_dir, "42", "alerts.json.bak"), 5)
        _write_bytes(os.path.join(data_dir, "42", "prefs.json.bak"), 3)
        _write_bytes(os.path.join(data_dir, "42", "notes.corrupt.json.bak"), 2)
        _write_bytes(os.path.join(data_dir, "42", "images", "photo.jpg"), 13)
        _write_bytes(os.path.join(data_dir, "42", "images", "nested.json.bak"), 59)
        _write_bytes(os.path.join(data_dir, "42", "logs", "runtime.tmp"), 17)
        _write_bytes(os.path.join(data_dir, "42", "logs", "events.log"), 19)
        _write_bytes(os.path.join(data_dir, "42", "logs", "events.log.1"), 23)

        _write_bytes(os.path.join(user_log_dir, "42_events.log"), 29)
        _write_bytes(os.path.join(user_log_dir, "42_events.log.1"), 31)
        _write_bytes(os.path.join(user_log_dir, "42_events.log.legacy1"), 5)
        _write_bytes(os.path.join(user_log_dir, "420_events.log"), 37)

        _write_bytes(os.path.join(data_dir, "systemlog.d", "api.log"), 43)
        _write_bytes(os.path.join(data_dir, "systemlog.d", "runtime_state.json"), 47)

        _write_bytes(os.path.join(user_backup_dir, "42", "local", "backup_1.zip"), 41)

        original_constants = {
            "DATA_DIR": sm.DATA_DIR,
            "BACKUP_DIR": sm.BACKUP_DIR,
            "SYSTEM_LOG_DIR": sm.SYSTEM_LOG_DIR,
            "USER_BACKUP_DIR": sm.USER_BACKUP_DIR,
            "USER_LOG_DIR": sm.USER_LOG_DIR,
        }
        sm.DATA_DIR = data_dir
        sm.BACKUP_DIR = backup_dir
        sm.SYSTEM_LOG_DIR = os.path.join(data_dir, "systemlog.d")
        sm.USER_BACKUP_DIR = user_backup_dir
        sm.USER_LOG_DIR = user_log_dir

        try:
            direct_user_dir = sm.get_dir_size_bytes(os.path.join(data_dir, "42"))
            direct_user_logs = sm.get_logs_size_bytes(os.path.join(data_dir, "42", "logs"))
            direct_system_logs = sm.get_logs_size_bytes(os.path.join(data_dir, "systemlog.d"))
            json_size = sm.get_user_json_files_bytes("42")
            json_bak_size = sm.get_user_json_backup_files_bytes("42")
            data_dir_size = sm.get_user_data_dir_bytes("42")
            backup_size = sm.get_user_backup_dir_bytes("42")
            root_data_size = sm.get_data_root_bytes()
            root_system_log_size = sm.get_system_log_root_bytes()
            root_user_log_size = sm.get_user_log_root_bytes()
            root_backup_size = sm.get_backup_root_bytes()
            explicit_files = sm.get_files_size_bytes(
                [
                    os.path.join(data_dir, "42", "alerts.json"),
                    os.path.join(data_dir, "42", "prefs.json"),
                    os.path.join(data_dir, "42", "missing.json"),
                ]
            )

            storage = _DummyStorage(data_dir)
            event_paths = sm.get_user_event_log_paths(storage, "42")
            event_size = sm.get_user_event_logs_bytes(storage, "42")
            fallback_event_size = sm.get_user_event_logs_bytes(None, "42")

            checks = {
                "dir_size_user": direct_user_dir == 159,
                "logs_size_user_dir_only_log_files": direct_user_logs == 42,
                "logs_size_system_dir_only_log_files": direct_system_logs == 43,
                "files_size_explicit": explicit_files == 18,
                "user_data_dir_size_helper": data_dir_size == 159,
                "user_json_files_size_helper": json_size == 18,
                "user_json_backup_files_size_helper": json_bak_size == 8,
                "event_paths_count": len(event_paths) == 3,
                "event_size_storage": event_size == 65,
                "event_size_fallback": fallback_event_size == 65,
                "event_size_excludes_id_collision": all("420_events.log" not in path for path in event_paths),
                "backup_size_helper": backup_size == 41,
                "root_data_size_helper": root_data_size == 351,
                "root_system_log_size_helper": root_system_log_size == 90,
                "root_user_log_size_helper": root_user_log_size == 102,
                "root_backup_size_helper": root_backup_size == 41,
                "missing_dir_safe_zero": sm.get_dir_size_bytes(os.path.join(data_dir, "404")) == 0,
                "missing_logs_dir_safe_zero": sm.get_logs_size_bytes(os.path.join(data_dir, "404", "logs")) == 0,
            }
            print_section(
                "storage_metrics_checks",
                {
                    "checks": checks,
                    "event_paths": event_paths,
                    "values": {
                        "direct_user_dir": direct_user_dir,
                        "direct_user_logs": direct_user_logs,
                        "direct_system_logs": direct_system_logs,
                        "json_size": json_size,
                        "json_bak_size": json_bak_size,
                        "data_dir_size": data_dir_size,
                        "event_size": event_size,
                        "fallback_event_size": fallback_event_size,
                        "backup_size": backup_size,
                        "root_data_size": root_data_size,
                        "root_system_log_size": root_system_log_size,
                        "root_user_log_size": root_user_log_size,
                        "root_backup_size": root_backup_size,
                    },
                },
            )
            if not all(checks.values()):
                _log_problem("storage_metrics_failed", {"checks": checks})
        finally:
            for key, value in original_constants.items():
                setattr(sm, key, value)


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

        _run_checks()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    checks_ok = not dbg.has_problem("storage_metrics_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
