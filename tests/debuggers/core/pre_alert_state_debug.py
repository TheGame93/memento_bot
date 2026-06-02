#!/usr/bin/env python3
import json
import os
import shutil
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
SCRIPT_TITLE = "pre_alert_state_debug"
FEATURE_TITLE = "Pre-Alert State Persistence"

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


def _setup_temp_runtime(tmp_dir):
    import modules.systemlog as syslog_mod

    sys_log_dir = os.path.join(tmp_dir, "systemlog.d")
    os.makedirs(sys_log_dir, exist_ok=True)
    orig_log_dir = syslog_mod.LOG_DIR
    orig_runtime = syslog_mod.RUNTIME_STATE_FILE
    syslog_mod.LOG_DIR = sys_log_dir
    syslog_mod.RUNTIME_STATE_FILE = os.path.join(sys_log_dir, "runtime_state.json")
    return orig_log_dir, orig_runtime


def _restore_runtime(orig_log_dir, orig_runtime):
    import modules.systemlog as syslog_mod

    syslog_mod.LOG_DIR = orig_log_dir
    syslog_mod.RUNTIME_STATE_FILE = orig_runtime


def _test_save_load_roundtrip():
    from modules.scheduler_core import state as st

    tmp_dir = tempfile.mkdtemp(prefix="prealert_debug_")
    orig_log_dir, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict = dict(st.sent_pre_alerts)
    orig_dirty = st.sent_pre_alerts_dirty

    try:
        st.sent_pre_alerts.clear()
        st.sent_pre_alerts_dirty = False

        t1 = datetime(2026, 2, 13, 10, 0, 0)
        t2 = datetime(2026, 2, 13, 11, 30, 0)
        st.sent_pre_alerts[("123", "abc123", "1h")] = t1
        st.sent_pre_alerts[("456", "def456", "1d")] = t2
        st.mark_dirty()

        save_ok = st.save_pre_alert_state()
        dirty_after_save = st.sent_pre_alerts_dirty

        st.sent_pre_alerts.clear()
        st.load_pre_alert_state()

        restored = dict(st.sent_pre_alerts)
        checks = {
            "save_ok": save_ok is True,
            "not_dirty_after_save": dirty_after_save is False,
            "entry_count": len(restored) == 2,
            "key1_restored": ("123", "abc123", "1h") in restored,
            "key2_restored": ("456", "def456", "1d") in restored,
            "val1_match": restored.get(("123", "abc123", "1h")) == t1,
            "val2_match": restored.get(("456", "def456", "1d")) == t2,
        }
        print_section("save_load_roundtrip", {"restored": {str(k): str(v) for k, v in restored.items()}, "checks": checks})
        if not all(checks.values()):
            _log_problem("roundtrip_failed", {"checks": checks})
    finally:
        st.sent_pre_alerts = orig_dict
        st.sent_pre_alerts_dirty = orig_dirty
        _restore_runtime(orig_log_dir, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_empty_load():
    from modules.scheduler_core import state as st

    tmp_dir = tempfile.mkdtemp(prefix="prealert_debug_")
    orig_log_dir, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict = dict(st.sent_pre_alerts)
    orig_dirty = st.sent_pre_alerts_dirty

    try:
        import modules.systemlog as syslog_mod

        with open(syslog_mod.RUNTIME_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"some_other_key": 42}, f)

        st.sent_pre_alerts.clear()
        st.load_pre_alert_state()

        checks = {
            "empty_dict": len(st.sent_pre_alerts) == 0,
            "no_crash": True,
        }
        print_section("empty_load", {"checks": checks})
        if not all(checks.values()):
            _log_problem("empty_load_failed", {"checks": checks})
    finally:
        st.sent_pre_alerts = orig_dict
        st.sent_pre_alerts_dirty = orig_dirty
        _restore_runtime(orig_log_dir, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_dirty_flag():
    from modules.scheduler_core import state as st

    tmp_dir = tempfile.mkdtemp(prefix="prealert_debug_")
    orig_log_dir, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict = dict(st.sent_pre_alerts)
    orig_dirty = st.sent_pre_alerts_dirty

    try:
        import modules.systemlog as syslog_mod

        state_file = syslog_mod.RUNTIME_STATE_FILE

        st.sent_pre_alerts.clear()
        st.sent_pre_alerts_dirty = False
        st.sent_pre_alerts[("999", "xyz", "2h")] = datetime(2026, 1, 1, 0, 0)

        result_no_dirty = st.save_pre_alert_state()
        file_exists_before = os.path.exists(state_file)

        st.mark_dirty()
        result_dirty = st.save_pre_alert_state()
        file_exists_after = os.path.exists(state_file)

        checks = {
            "noop_when_clean": result_no_dirty is True,
            "no_file_before": not file_exists_before,
            "save_ok_when_dirty": result_dirty is True,
            "file_created_after": file_exists_after,
        }
        print_section("dirty_flag", {"checks": checks})
        if not all(checks.values()):
            _log_problem("dirty_flag_failed", {"checks": checks})
    finally:
        st.sent_pre_alerts = orig_dict
        st.sent_pre_alerts_dirty = orig_dirty
        _restore_runtime(orig_log_dir, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_key_serialization():
    from modules.scheduler_core.state import _serialize_key, _deserialize_key

    test_cases = [
        (("123", "abc", "1h"), "123|abc|1h"),
        (("user_456", "def-789", "30m"), "user_456|def-789|30m"),
        ((123, "abc", "1d"), "123|abc|1d"),
    ]
    all_ok = True
    results = []
    for key_tuple, expected_str in test_cases:
        serialized = _serialize_key(key_tuple)
        deserialized = _deserialize_key(serialized)
        ok = serialized == expected_str and deserialized == (str(key_tuple[0]), str(key_tuple[1]), str(key_tuple[2]))
        results.append({"input": str(key_tuple), "serialized": serialized, "deserialized": str(deserialized), "ok": ok})
        if not ok:
            all_ok = False

    bad = _deserialize_key("only_one_part")
    bad_ok = bad is None
    results.append({"input": "only_one_part", "deserialized": str(bad), "ok": bad_ok})
    if not bad_ok:
        all_ok = False

    print_section("key_serialization", {"results": results})
    if not all_ok:
        _log_problem("serialization_failed", {"results": results})


def _test_no_key_clobber():
    from modules.systemlog import update_runtime_state_key, _read_runtime_state, _runtime_state_lock

    tmp_dir = tempfile.mkdtemp(prefix="prealert_debug_")
    orig_log_dir, orig_runtime = _setup_temp_runtime(tmp_dir)

    try:
        update_runtime_state_key("test_key_a", {"value": "alpha"})
        update_runtime_state_key("test_key_b", {"value": "beta"})

        with _runtime_state_lock:
            state = _read_runtime_state()
        checks = {
            "key_a_present": state.get("test_key_a") == {"value": "alpha"},
            "key_b_present": state.get("test_key_b") == {"value": "beta"},
        }
        print_section("no_key_clobber", {"state_keys": list(state.keys()), "checks": checks})
        if not all(checks.values()):
            _log_problem("key_clobber_detected", {"checks": checks, "state": state})
    finally:
        _restore_runtime(orig_log_dir, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _test_clear_pre_alert_tracking_for_alert():
    from modules.scheduler_core import state as st

    orig_dict = dict(st.sent_pre_alerts)
    orig_dirty = st.sent_pre_alerts_dirty
    try:
        st.sent_pre_alerts.clear()
        st.sent_pre_alerts_dirty = False

        st.sent_pre_alerts[("100", "a1", "15m")] = datetime(2026, 1, 1, 8, 0, 0)
        st.sent_pre_alerts[("200", "a1", "1h")] = datetime(2026, 1, 1, 9, 0, 0)
        st.sent_pre_alerts[("300", "b2", "1h")] = datetime(2026, 1, 1, 10, 0, 0)

        removed = st.clear_pre_alert_tracking_for_alert("a1")
        removed_second = st.clear_pre_alert_tracking_for_alert("missing")

        checks = {
            "removed_count_matches": removed == 2,
            "target_removed": ("100", "a1", "15m") not in st.sent_pre_alerts
            and ("200", "a1", "1h") not in st.sent_pre_alerts,
            "non_target_kept": ("300", "b2", "1h") in st.sent_pre_alerts,
            "dirty_marked": st.sent_pre_alerts_dirty is True,
            "second_remove_zero": removed_second == 0,
        }
        print_section("clear_pre_alert_tracking_for_alert", {"checks": checks})
        if not all(checks.values()):
            _log_problem("clear_pre_alert_tracking_failed", {"checks": checks})
    finally:
        st.sent_pre_alerts = orig_dict
        st.sent_pre_alerts_dirty = orig_dirty


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        _test_key_serialization()
        _test_save_load_roundtrip()
        _test_empty_load()
        _test_dirty_flag()
        _test_no_key_clobber()
        _test_clear_pre_alert_tracking_for_alert()
    except ModuleNotFoundError as exc:
        dbg.mark_dependency_error(exc)
        dbg.finish(exit_on_problems=False)
        return
    except Exception as exc:
        import traceback

        dbg.problem("unhandled_exception", {"error": str(exc), "tb": traceback.format_exc()})
    finally:
        _DBG = None

    roundtrip_ok = not dbg.has_problem("roundtrip_failed")
    empty_ok = not dbg.has_problem("empty_load_failed")
    dirty_ok = not dbg.has_problem("dirty_flag_failed")
    serial_ok = not dbg.has_problem("serialization_failed")
    no_clobber_ok = not dbg.has_problem("key_clobber_detected")
    clear_tracking_ok = not dbg.has_problem("clear_pre_alert_tracking_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"save-load-roundtrip: {'OK' if roundtrip_ok else 'FAIL'}",
        f"empty-load: {'OK' if empty_ok else 'FAIL'}",
        f"dirty-flag: {'OK' if dirty_ok else 'FAIL'}",
        f"key-serialization: {'OK' if serial_ok else 'FAIL'}",
        f"no-key-clobber: {'OK' if no_clobber_ok else 'FAIL'}",
        f"clear-tracking: {'OK' if clear_tracking_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
