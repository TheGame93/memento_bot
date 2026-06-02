#!/usr/bin/env python3
import json
import os
import shutil
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
SCRIPT_TITLE = "onboarding_log_debug"
FEATURE_TITLE = "Onboarding Log Stream"

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


def _test_onboarding_log_created():
    tmp_dir = tempfile.mkdtemp(prefix="onb_debug_")
    try:
        sys_log_dir = os.path.join(tmp_dir, "systemlog.d")
        os.makedirs(sys_log_dir, exist_ok=True)

        import modules.systemlog as syslog_mod
        import modules.shared.paths as paths_mod

        orig_log_dir = syslog_mod.LOG_DIR
        orig_sys_log_dir = paths_mod.SYSTEM_LOG_DIR

        syslog_mod.LOG_DIR = sys_log_dir
        paths_mod.SYSTEM_LOG_DIR = sys_log_dir

        orig_cache = getattr(syslog_mod, "_stream_loggers", {})
        syslog_mod._stream_loggers = {}

        try:
            from modules.systemlog import log_system

            log_system("onboarding", "whitelist_request_created", {
                "user_id": "999999",
                "note": "user_not_yet_whitelisted",
                "extra_field": "test_value",
            }, level="INFO")

            onb_log = os.path.join(sys_log_dir, "onboarding.log")
            log_exists = os.path.isfile(onb_log)
            log_content = None
            payload_ok = False
            if log_exists:
                with open(onb_log, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                if raw:
                    last_line = raw.strip().split("\n")[-1]
                    log_content = json.loads(last_line)
                    inner = log_content.get("payload", {})
                    payload_ok = (
                        log_content.get("event") == "whitelist_request_created"
                        and inner.get("user_id") == "999999"
                        and inner.get("extra_field") == "test_value"
                        and inner.get("note") == "user_not_yet_whitelisted"
                    )

            checks = {
                "log_file_exists": log_exists,
                "payload_preserved": payload_ok,
            }
            print_section("onboarding_log_created", {"checks": checks, "log_content": log_content})
            if not log_exists:
                _log_problem("onboarding_log_not_created")
            if not payload_ok:
                _log_problem("payload_not_preserved", {"log_content": log_content})
        finally:
            syslog_mod.LOG_DIR = orig_log_dir
            paths_mod.SYSTEM_LOG_DIR = orig_sys_log_dir
            syslog_mod._stream_loggers = orig_cache
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_no_user_dir_created():
    from modules.storage import StorageManager

    tmp_dir = tempfile.mkdtemp(prefix="onb_debug_")
    try:
        import modules.systemlog as syslog_mod
        import modules.storage as storage_mod

        orig_log_system = syslog_mod.log_system
        captured = []

        def fake_log_system(category, event, payload=None, level="INFO"):
            captured.append({"category": category, "event": event, "level": level, "payload": payload or {}})

        syslog_mod.log_system = fake_log_system
        orig_storage_log = storage_mod.log_system
        storage_mod.log_system = fake_log_system

        try:
            sm = StorageManager(base_data_dir=tmp_dir, admin_id=12345)
            result = sm.log_user_event(999888, "some_event", {"key": "val"})

            user_dir = os.path.join(tmp_dir, "999888")
            user_dir_exists = os.path.isdir(user_dir)
            returned_false = result is False

            checks = {
                "no_user_dir": not user_dir_exists,
                "returned_false": returned_false,
            }
            print_section("no_user_dir_created", {"checks": checks, "user_dir_exists": user_dir_exists})
            if user_dir_exists:
                _log_problem("user_dir_created_for_unauthorized")
        finally:
            syslog_mod.log_system = orig_log_system
            storage_mod.log_system = orig_storage_log
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_no_storage_warning():
    import modules.systemlog as syslog_mod
    import modules.storage as storage_mod
    from modules.storage import StorageManager

    tmp_dir = tempfile.mkdtemp(prefix="onb_debug_")
    try:
        captured = []
        orig_log_system = syslog_mod.log_system
        orig_storage_log = storage_mod.log_system

        def fake_log_system(category, event, payload=None, level="INFO"):
            captured.append({"category": category, "event": event, "level": level, "payload": payload or {}})

        syslog_mod.log_system = fake_log_system
        storage_mod.log_system = fake_log_system

        try:
            sm = StorageManager(base_data_dir=tmp_dir, admin_id=12345)
            sm.log_user_event(777666, "test_event", {"some": "data"})

            storage_warnings = [c for c in captured if c["category"] == "storage" and c["level"] == "WARNING"]
            onboarding_events = [c for c in captured if c["category"] == "onboarding"]
            matching_event = next((
                c for c in onboarding_events
                if c.get("event") == "test_event"
                and c.get("payload", {}).get("note") == "user_not_yet_whitelisted"
                and c.get("payload", {}).get("some") == "data"
            ), None)

            checks = {
                "no_storage_warning": len(storage_warnings) == 0,
                "has_onboarding_event": len(onboarding_events) >= 1,
                "onboarding_event_correct": matching_event is not None,
            }
            print_section("no_storage_warning", {"checks": checks, "captured": captured})
            if storage_warnings:
                _log_problem("storage_warning_still_emitted", {"warnings": storage_warnings})
            if matching_event is None:
                _log_problem("payload_not_preserved", {"captured": captured})
        finally:
            syslog_mod.log_system = orig_log_system
            storage_mod.log_system = orig_storage_log
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_retention_registered():
    from modules.systemlog import LOG_RETENTION_DAYS

    registered = "onboarding.log" in LOG_RETENTION_DAYS
    checks = {"registered": registered}
    print_section("retention_registered", {"checks": checks, "retention_days": LOG_RETENTION_DAYS.get("onboarding.log")})
    if not registered:
        _log_problem("retention_not_registered")


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        _test_retention_registered()
        _test_onboarding_log_created()
        _test_no_user_dir_created()
        _test_no_storage_warning()
    except ModuleNotFoundError as exc:
        dbg.mark_dependency_error(exc)
        dbg.finish(exit_on_problems=False)
        return
    except Exception as exc:
        import traceback

        dbg.problem("unhandled_exception", {"error": str(exc), "tb": traceback.format_exc()})
    finally:
        _DBG = None

    log_created_ok = not dbg.has_problem("onboarding_log_not_created")
    no_user_dir_ok = not dbg.has_problem("user_dir_created_for_unauthorized")
    no_warning_ok = not dbg.has_problem("storage_warning_still_emitted")
    payload_ok = not dbg.has_problem("payload_not_preserved")
    retention_ok = not dbg.has_problem("retention_not_registered")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"onboarding-log-created: {'OK' if log_created_ok else 'FAIL'}",
        f"no-user-dir: {'OK' if no_user_dir_ok else 'FAIL'}",
        f"no-storage-warning: {'OK' if no_warning_ok else 'FAIL'}",
        f"payload-preserved: {'OK' if payload_ok else 'FAIL'}",
        f"retention-registered: {'OK' if retention_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
