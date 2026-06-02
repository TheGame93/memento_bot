#!/usr/bin/env python3
"""
Debugger for pending_missed_notifications state (Step 3 of plan_update3).

Covers:
  - record_pending_missed / get_pending_missed_for_user
  - clear_pending_missed_alert (dirty flag + removal)
  - save_pending_missed / load_pending_missed round-trip
  - dirty flag — no write when clean
  - empty load (key absent from runtime_state.json)
  - runtime_state.json key does not clobber other keys
"""
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
SCRIPT_TITLE = "pending_missed_debug"
FEATURE_TITLE = "Pending Missed Notifications State (plan_update3 step 3)"

_DBG = None


def _dbg():
    if _DBG is None:
        raise RuntimeError("debug harness not initialized")
    return _DBG


def _setup_temp_runtime(tmp_dir):
    import modules.systemlog as syslog_mod
    sys_log_dir = os.path.join(tmp_dir, "systemlog.d")
    os.makedirs(sys_log_dir, exist_ok=True)
    orig_log_dir = syslog_mod.LOG_DIR
    orig_summary = syslog_mod.SUMMARY_LOG
    orig_runtime = syslog_mod.RUNTIME_STATE_FILE
    syslog_mod.LOG_DIR = sys_log_dir
    syslog_mod.SUMMARY_LOG = os.path.join(sys_log_dir, "system.log")
    syslog_mod.RUNTIME_STATE_FILE = os.path.join(sys_log_dir, "runtime_state.json")
    return orig_log_dir, orig_summary, orig_runtime


def _restore_runtime(orig_log_dir, orig_summary, orig_runtime):
    import modules.systemlog as syslog_mod
    syslog_mod.LOG_DIR = orig_log_dir
    syslog_mod.SUMMARY_LOG = orig_summary
    syslog_mod.RUNTIME_STATE_FILE = orig_runtime


def _isolate(st):
    """Save and clear pending_missed_notifications state; return originals."""
    import copy
    orig_dict = copy.deepcopy(st.pending_missed_notifications)
    orig_dirty = st.pending_missed_dirty
    st.pending_missed_notifications.clear()
    st.pending_missed_dirty = False
    return orig_dict, orig_dirty


def _restore(st, orig_dict, orig_dirty):
    st.pending_missed_notifications.clear()
    st.pending_missed_notifications.update(orig_dict)
    st.pending_missed_dirty = orig_dirty


# ---------------------------------------------------------------------------
# Test: record + get
# ---------------------------------------------------------------------------
def _test_record_and_get():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        st.record_pending_missed(
            "uid1", "alert1", "2026-02-21T18:00:00",
            ["12h"], ["2026-02-21T06:00:00"],
            None, "2026-02-21T11:10:00",
        )
        result = st.get_pending_missed_for_user("uid1")
        entry = result.get("alert1", {})
        checks = {
            "user_key_exists": "uid1" in st.pending_missed_notifications,
            "alert_key_exists": "alert1" in result,
            "occurrence_ok": entry.get("occurrence") == "2026-02-21T18:00:00",
            "missed_pre_strs_ok": entry.get("missed_pre_strs") == ["12h"],
            "missed_due_time_none": entry.get("missed_due_time") is None,
            "dirty_set": st.pending_missed_dirty is True,
        }
        _dbg().section("record_and_get", {"entry": entry, "checks": checks})
        if not all(checks.values()):
            _dbg().problem("record_and_get_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: clear_pending_missed_alert
# ---------------------------------------------------------------------------
def _test_clear():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        st.record_pending_missed(
            "uid2", "alertX", "2026-03-01T10:00:00",
            [], [], "2026-03-01T10:00:00", "2026-02-28T09:00:00",
        )
        st.pending_missed_dirty = False  # reset to detect clear's effect

        st.clear_pending_missed_alert("uid2", "alertX")
        after = st.get_pending_missed_for_user("uid2")

        checks = {
            "entry_removed": "alertX" not in after,
            "dirty_set": st.pending_missed_dirty is True,
        }
        _dbg().section("clear_alert", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("clear_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: clear non-existent (no crash, no dirty)
# ---------------------------------------------------------------------------
def _test_clear_nonexistent():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        st.pending_missed_dirty = False
        st.clear_pending_missed_alert("ghost_user", "ghost_alert")
        checks = {
            "no_crash": True,
            "not_dirty": st.pending_missed_dirty is False,
        }
        _dbg().section("clear_nonexistent", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("clear_nonexistent_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: save / load round-trip
# ---------------------------------------------------------------------------
def _test_save_load_roundtrip():
    from modules.scheduler_core import state as st
    tmp_dir = tempfile.mkdtemp(prefix="pending_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict, orig_dirty = _isolate(st)
    try:
        st.record_pending_missed(
            "999", "abc", "2026-04-01T09:00:00",
            ["1d"], ["2026-03-31T09:00:00"],
            None, "2026-04-01T08:00:00",
        )
        st.record_pending_missed(
            "999", "def", "2026-05-15T14:00:00",
            [], [], "2026-05-15T14:00:00", "2026-05-15T12:00:00",
        )

        save_ok = st.save_pending_missed()
        dirty_after_save = st.pending_missed_dirty

        # Simulate restart: replace module global with new empty dict
        st.pending_missed_notifications = {}
        st.pending_missed_dirty = False
        st.load_pending_missed()

        user_data = st.get_pending_missed_for_user("999")
        entry_abc = user_data.get("abc", {})

        checks = {
            "save_ok": save_ok is True,
            "not_dirty_after_save": dirty_after_save is False,
            "abc_restored": "abc" in user_data,
            "def_restored": "def" in user_data,
            "abc_occurrence": entry_abc.get("occurrence") == "2026-04-01T09:00:00",
            "abc_pre_strs": entry_abc.get("missed_pre_strs") == ["1d"],
        }
        _dbg().section("save_load_roundtrip", {
            "user_data_keys": list(user_data.keys()),
            "checks": checks,
        })
        if not all(checks.values()):
            _dbg().problem("roundtrip_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)
        _restore_runtime(orig_log_dir, orig_summary, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: dirty flag — no write when clean
# ---------------------------------------------------------------------------
def _test_dirty_flag():
    from modules.scheduler_core import state as st
    tmp_dir = tempfile.mkdtemp(prefix="pending_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict, orig_dirty = _isolate(st)
    try:
        import modules.systemlog as syslog_mod
        state_file = syslog_mod.RUNTIME_STATE_FILE

        result_no_dirty = st.save_pending_missed()
        file_before = os.path.exists(state_file)

        st.record_pending_missed(
            "u", "a", "2026-01-01T10:00:00", [], [], None, "2026-01-01T09:00:00"
        )
        result_dirty = st.save_pending_missed()
        file_after = os.path.exists(state_file)

        checks = {
            "noop_when_clean": result_no_dirty is True,
            "no_file_before": not file_before,
            "save_ok_when_dirty": result_dirty is True,
            "file_created": file_after,
            "not_dirty_after_save": st.pending_missed_dirty is False,
        }
        _dbg().section("dirty_flag", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("dirty_flag_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)
        _restore_runtime(orig_log_dir, orig_summary, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: empty load (key absent from runtime_state.json)
# ---------------------------------------------------------------------------
def _test_empty_load():
    from modules.scheduler_core import state as st
    tmp_dir = tempfile.mkdtemp(prefix="pending_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict, orig_dirty = _isolate(st)
    try:
        import modules.systemlog as syslog_mod
        with open(syslog_mod.RUNTIME_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"some_other_key": 42}, f)

        st.load_pending_missed()
        checks = {
            "empty_dict": len(st.pending_missed_notifications) == 0,
            "no_crash": True,
            "not_dirty": st.pending_missed_dirty is False,
        }
        _dbg().section("empty_load", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("empty_load_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)
        _restore_runtime(orig_log_dir, orig_summary, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: runtime_state.json key does not clobber other keys
# ---------------------------------------------------------------------------
def _test_no_key_clobber():
    from modules.systemlog import update_runtime_state_key, _read_runtime_state, _runtime_state_lock
    tmp_dir = tempfile.mkdtemp(prefix="pending_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    try:
        update_runtime_state_key("notified_missed_pre", {"existing": "entry"})
        from modules.scheduler_core import state as st
        orig_dict, orig_dirty = _isolate(st)
        try:
            st.record_pending_missed(
                "u", "b", "2026-06-01T12:00:00", [], [], None, "2026-06-01T11:00:00"
            )
            st.save_pending_missed()
        finally:
            _restore(st, orig_dict, orig_dirty)
        with _runtime_state_lock:
            state = _read_runtime_state()
        checks = {
            "notified_pre_intact": state.get("notified_missed_pre") == {"existing": "entry"},
            "pending_key_present": "pending_missed_notifications" in state,
        }
        _dbg().section("no_key_clobber", {
            "state_keys": list(state.keys()),
            "checks": checks,
        })
        if not all(checks.values()):
            _dbg().problem("key_clobber_detected", {"checks": checks})
    finally:
        _restore_runtime(orig_log_dir, orig_summary, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: record_pending_missed preserves missed_pre_strs / first_notified
#       when re-recording a pending-sourced item (Bug fix verification).
# ---------------------------------------------------------------------------
def _test_preserve_pentry_on_rerecord():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        uid = "preserve_test_uid"
        aid = "preserve_test_alert"

        # Simulate initial record (first restart detection).
        st.record_pending_missed(
            uid, aid, "2026-04-01T09:00:00",
            ["12h"], ["2026-03-31T21:00:00"],
            None, "2026-04-01T08:00:00",
        )
        orig_pre_strs = st.get_pending_missed_for_user(uid)[aid]["missed_pre_strs"]
        orig_first_notified = st.get_pending_missed_for_user(uid)[aid]["first_notified"]

        # Simulate Step 4e re-record with pentry preservation fix:
        # _pre_keys=[] (pending-sourced), so fall back to existing pentry.
        _existing_pentry = st.get_pending_missed_for_user(uid).get(aid, {})
        _missed_pre_strs = [] or _existing_pentry.get("missed_pre_strs", [])
        _first_notified = _existing_pentry.get("first_notified") or "2099-01-01T00:00:00"

        # Re-record using preserved values (this is the fixed Step 4e pattern).
        st.record_pending_missed(
            uid, aid, "2026-04-01T09:00:00",
            _missed_pre_strs, ["2026-03-31T21:00:00"],
            None, _first_notified,
        )

        after_entry = st.get_pending_missed_for_user(uid)[aid]
        checks = {
            "missed_pre_strs_preserved": after_entry.get("missed_pre_strs") == orig_pre_strs,
            "first_notified_preserved": after_entry.get("first_notified") == orig_first_notified,
            "missed_pre_strs_not_empty": bool(after_entry.get("missed_pre_strs")),
        }
        _dbg().section("preserve_pentry_on_rerecord", {"after_entry": after_entry, "checks": checks})
        if not all(checks.values()):
            _dbg().problem("preserve_pentry_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from modules.scheduler_core import state as _st  # noqa: F401
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_record_and_get()
        _test_clear()
        _test_clear_nonexistent()
        _test_save_load_roundtrip()
        _test_dirty_flag()
        _test_empty_load()
        _test_no_key_clobber()
        _test_preserve_pentry_on_rerecord()

    except Exception as exc:
        import traceback
        dbg.problem("unhandled_exception", {"error": str(exc), "tb": traceback.format_exc()})
    finally:
        _DBG = None

    record_ok = not dbg.has_problem("record_and_get_failed")
    clear_ok = not dbg.has_problem("clear_failed")
    clear_nex_ok = not dbg.has_problem("clear_nonexistent_failed")
    roundtrip_ok = not dbg.has_problem("roundtrip_failed")
    dirty_ok = not dbg.has_problem("dirty_flag_failed")
    empty_ok = not dbg.has_problem("empty_load_failed")
    clobber_ok = not dbg.has_problem("key_clobber_detected")
    preserve_ok = not dbg.has_problem("preserve_pentry_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")

    dbg.finish(summary_lines=[
        f"record-and-get: {'OK' if record_ok else 'FAIL'}",
        f"clear-alert: {'OK' if clear_ok else 'FAIL'}",
        f"clear-nonexistent: {'OK' if clear_nex_ok else 'FAIL'}",
        f"save-load-roundtrip: {'OK' if roundtrip_ok else 'FAIL'}",
        f"dirty-flag: {'OK' if dirty_ok else 'FAIL'}",
        f"empty-load: {'OK' if empty_ok else 'FAIL'}",
        f"no-key-clobber: {'OK' if clobber_ok else 'FAIL'}",
        f"preserve-pentry-on-rerecord: {'OK' if preserve_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
