#!/usr/bin/env python3
"""
Debugger for notified_missed_pre state (Steps 1-2 of plan_update3).

Covers:
  - save / load round-trip
  - is_missed_pre_notified / mark_missed_pre_notified
  - dirty-flag behaviour
  - cleanup: condition 1 (last_triggered >= occ_dt removes entry)
  - cleanup: condition 1 (last_triggered < occ_dt keeps entry)
  - cleanup: condition 2 (deleted alert removed even without last_triggered) — FRINGE CASE FIX
  - cleanup: None known_alert_ids_by_user degrades gracefully
  - empty load (key absent from runtime_state.json)
  - MISSED_ALERTS_NOTIFY_MODE constant present in constants
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
SCRIPT_TITLE = "notified_missed_pre_debug"
FEATURE_TITLE = "Notified Missed Pre-Alert State (plan_update3 steps 1-2)"

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
    orig_summary = getattr(syslog_mod, "SUMMARY_LOG", None)
    orig_runtime = syslog_mod.RUNTIME_STATE_FILE
    syslog_mod.LOG_DIR = sys_log_dir
    if orig_summary is not None:
        syslog_mod.SUMMARY_LOG = os.path.join(sys_log_dir, "system.log")
    syslog_mod.RUNTIME_STATE_FILE = os.path.join(sys_log_dir, "runtime_state.json")
    return orig_log_dir, orig_summary, orig_runtime


def _restore_runtime(orig_log_dir, orig_summary, orig_runtime):
    import modules.systemlog as syslog_mod
    syslog_mod.LOG_DIR = orig_log_dir
    if orig_summary is not None:
        syslog_mod.SUMMARY_LOG = orig_summary
    syslog_mod.RUNTIME_STATE_FILE = orig_runtime


def _isolate(st):
    """Save and clear notified_missed_pre state; return originals for restore."""
    orig_dict = dict(st.notified_missed_pre)
    orig_dirty = st.notified_missed_pre_dirty
    st.notified_missed_pre.clear()
    st.notified_missed_pre_dirty = False
    return orig_dict, orig_dirty


def _restore(st, orig_dict, orig_dirty):
    st.notified_missed_pre.clear()
    st.notified_missed_pre.update(orig_dict)
    st.notified_missed_pre_dirty = orig_dirty


# ---------------------------------------------------------------------------
# Test: MISSED_ALERTS_NOTIFY_MODE constant
# ---------------------------------------------------------------------------
def _test_constant_present():
    from modules import constants as C
    mode = getattr(C, "MISSED_ALERTS_NOTIFY_MODE", None)
    checks = {
        "constant_exists": mode is not None,
        "valid_value": mode in ("once", "always"),
        "default_is_once": mode == "once",
    }
    _dbg().section("constant_check", {"MISSED_ALERTS_NOTIFY_MODE": mode, "checks": checks})
    if not all(checks.values()):
        _dbg().problem("constant_invalid", {"checks": checks, "value": mode})


# ---------------------------------------------------------------------------
# Test: is / mark
# ---------------------------------------------------------------------------
def _test_mark_and_check():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        key = ("uid1", "alert1", "12h", "2026-02-21T18:00:00")
        before = st.is_missed_pre_notified(*key)
        when = datetime(2026, 2, 21, 11, 10, 0)
        st.mark_missed_pre_notified(*key, when)
        after = st.is_missed_pre_notified(*key)
        checks = {
            "false_before_mark": before is False,
            "true_after_mark": after is True,
            "dirty_set": st.notified_missed_pre_dirty is True,
            "stored_value": st.notified_missed_pre.get(key) == when,
        }
        _dbg().section("mark_and_check", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("mark_check_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: save / load round-trip
# ---------------------------------------------------------------------------
def _test_save_load_roundtrip():
    from modules.scheduler_core import state as st
    tmp_dir = tempfile.mkdtemp(prefix="notified_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict, orig_dirty = _isolate(st)
    try:
        t1 = datetime(2026, 2, 21, 11, 10, 0)
        t2 = datetime(2026, 3, 5, 9, 0, 0)
        k1 = ("987654321", "7d9450b1", "12h", "2026-02-21T18:00:00")
        k2 = ("999", "abc123", "1d", "2026-03-05T10:00:00")
        st.mark_missed_pre_notified(*k1, t1)
        st.mark_missed_pre_notified(*k2, t2)

        save_ok = st.save_notified_missed_pre()
        dirty_after_save = st.notified_missed_pre_dirty

        st.notified_missed_pre.clear()
        st.load_notified_missed_pre()
        restored = dict(st.notified_missed_pre)

        checks = {
            "save_ok": save_ok is True,
            "not_dirty_after_save": dirty_after_save is False,
            "entry_count": len(restored) == 2,
            "k1_restored": k1 in restored,
            "k2_restored": k2 in restored,
            "v1_match": restored.get(k1) == t1,
            "v2_match": restored.get(k2) == t2,
        }
        _dbg().section("save_load_roundtrip", {
            "restored_keys": [str(k) for k in restored],
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
    tmp_dir = tempfile.mkdtemp(prefix="notified_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict, orig_dirty = _isolate(st)
    try:
        import modules.systemlog as syslog_mod
        state_file = syslog_mod.RUNTIME_STATE_FILE

        # dirty=False → save is a no-op
        result_no_dirty = st.save_notified_missed_pre()
        file_before = os.path.exists(state_file)

        st.mark_missed_pre_notified("u", "a", "1h", "2026-01-01T10:00:00", datetime(2026, 1, 1))
        result_dirty = st.save_notified_missed_pre()
        file_after = os.path.exists(state_file)

        checks = {
            "noop_when_clean": result_no_dirty is True,
            "no_file_before": not file_before,
            "save_ok_when_dirty": result_dirty is True,
            "file_created": file_after,
            "not_dirty_after_save": st.notified_missed_pre_dirty is False,
        }
        _dbg().section("dirty_flag", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("dirty_flag_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)
        _restore_runtime(orig_log_dir, orig_summary, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: empty load (key absent)
# ---------------------------------------------------------------------------
def _test_empty_load():
    from modules.scheduler_core import state as st
    tmp_dir = tempfile.mkdtemp(prefix="notified_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    orig_dict, orig_dirty = _isolate(st)
    try:
        import modules.systemlog as syslog_mod
        with open(syslog_mod.RUNTIME_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"some_other_key": 42}, f)

        st.load_notified_missed_pre()
        checks = {
            "empty_dict": len(st.notified_missed_pre) == 0,
            "no_crash": True,
            "not_dirty": st.notified_missed_pre_dirty is False,
        }
        _dbg().section("empty_load", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("empty_load_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)
        _restore_runtime(orig_log_dir, orig_summary, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test: cleanup condition 1 — last_triggered >= occ_dt removes entry
# ---------------------------------------------------------------------------
def _test_cleanup_cond1_removes_when_fired():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        occ_iso = "2026-02-21T18:00:00"
        k = ("uid", "alertA", "12h", occ_iso)
        st.mark_missed_pre_notified(*k, datetime(2026, 2, 21, 11, 10))

        # last_triggered = 18:01, occ = 18:00 → 18:01 >= 18:00 → removed
        lt_map = {("uid", "alertA"): datetime(2026, 2, 21, 18, 1)}
        known = {"uid": {"alertA"}}
        st.cleanup_notified_missed_pre(lt_map, known)

        checks = {
            "entry_removed": k not in st.notified_missed_pre,
            "dirty_set": st.notified_missed_pre_dirty is True,
        }
        _dbg().section("cleanup_cond1_removes", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("cleanup_cond1_removes_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: cleanup condition 1 — last_triggered < occ_dt keeps entry
# ---------------------------------------------------------------------------
def _test_cleanup_cond1_keeps_when_not_fired():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        occ_iso = "2026-02-21T18:00:00"
        k = ("uid", "alertB", "12h", occ_iso)
        st.mark_missed_pre_notified(*k, datetime(2026, 2, 21, 11, 10))
        st.notified_missed_pre_dirty = False  # reset to detect if cleanup changes it

        # last_triggered = 11:10, occ = 18:00 → 11:10 < 18:00 → kept
        lt_map = {("uid", "alertB"): datetime(2026, 2, 21, 11, 10)}
        known = {"uid": {"alertB"}}
        st.cleanup_notified_missed_pre(lt_map, known)

        checks = {
            "entry_kept": k in st.notified_missed_pre,
            "not_dirty": st.notified_missed_pre_dirty is False,
        }
        _dbg().section("cleanup_cond1_keeps", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("cleanup_cond1_keeps_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: cleanup condition 1 — no last_triggered keeps entry
# ---------------------------------------------------------------------------
def _test_cleanup_cond1_keeps_when_no_last_triggered():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        occ_iso = "2026-02-21T18:00:00"
        k = ("uid", "alertC", "12h", occ_iso)
        st.mark_missed_pre_notified(*k, datetime(2026, 2, 21, 11, 10))
        st.notified_missed_pre_dirty = False

        # No last_triggered entry → kept
        lt_map = {}
        known = {"uid": {"alertC"}}
        st.cleanup_notified_missed_pre(lt_map, known)

        checks = {
            "entry_kept": k in st.notified_missed_pre,
            "not_dirty": st.notified_missed_pre_dirty is False,
        }
        _dbg().section("cleanup_cond1_no_lt", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("cleanup_cond1_no_lt_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: cleanup condition 2 — deleted alert removed (FRINGE CASE FIX)
# ---------------------------------------------------------------------------
def _test_cleanup_cond2_deleted_alert():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        occ_iso = "2026-02-21T18:00:00"
        k_deleted = ("uid", "deletedAlert", "12h", occ_iso)
        k_alive = ("uid", "aliveAlert", "12h", occ_iso)
        st.mark_missed_pre_notified(*k_deleted, datetime(2026, 2, 21, 11, 10))
        st.mark_missed_pre_notified(*k_alive, datetime(2026, 2, 21, 11, 10))

        # known_alert_ids_by_user only contains aliveAlert
        # deletedAlert has no last_triggered — without the fix it would be kept forever
        lt_map = {}
        known = {"uid": {"aliveAlert"}}
        st.cleanup_notified_missed_pre(lt_map, known)

        checks = {
            "deleted_removed": k_deleted not in st.notified_missed_pre,
            "alive_kept": k_alive in st.notified_missed_pre,
            "dirty_set": st.notified_missed_pre_dirty is True,
        }
        _dbg().section("cleanup_cond2_deleted", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("cleanup_cond2_deleted_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: cleanup with known_alert_ids_by_user=None — degrades gracefully
# ---------------------------------------------------------------------------
def _test_cleanup_none_known():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        occ_iso = "2026-02-21T18:00:00"
        k = ("uid", "orphanAlert", "12h", occ_iso)
        st.mark_missed_pre_notified(*k, datetime(2026, 2, 21, 11, 10))
        st.notified_missed_pre_dirty = False

        # None → condition 2 skipped → entry kept (no last_triggered in map)
        lt_map = {}
        st.cleanup_notified_missed_pre(lt_map, known_alert_ids_by_user=None)

        checks = {
            "entry_kept": k in st.notified_missed_pre,
            "not_dirty": st.notified_missed_pre_dirty is False,
            "no_crash": True,
        }
        _dbg().section("cleanup_none_known", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("cleanup_none_known_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: cleanup condition 2 — deleted user removed (user absent from system)
# ---------------------------------------------------------------------------
def _test_cleanup_cond2_deleted_user():
    from modules.scheduler_core import state as st
    orig_dict, orig_dirty = _isolate(st)
    try:
        occ_iso = "2026-02-21T18:00:00"
        k_deleted_user = ("deleted_uid", "alertX", "12h", occ_iso)
        k_alive_user = ("alive_uid", "alertY", "12h", occ_iso)
        st.mark_missed_pre_notified(*k_deleted_user, datetime(2026, 2, 21, 11, 10))
        st.mark_missed_pre_notified(*k_alive_user, datetime(2026, 2, 21, 11, 10))

        # known_alert_ids_by_user only has alive_uid; deleted_uid is absent entirely
        lt_map = {}
        known = {"alive_uid": {"alertY"}}
        st.cleanup_notified_missed_pre(lt_map, known)

        checks = {
            "deleted_user_removed": k_deleted_user not in st.notified_missed_pre,
            "alive_user_kept": k_alive_user in st.notified_missed_pre,
            "dirty_set": st.notified_missed_pre_dirty is True,
        }
        _dbg().section("cleanup_cond2_deleted_user", {"checks": checks})
        if not all(checks.values()):
            _dbg().problem("cleanup_cond2_deleted_user_failed", {"checks": checks})
    finally:
        _restore(st, orig_dict, orig_dirty)


# ---------------------------------------------------------------------------
# Test: runtime_state.json key does not clobber other keys
# ---------------------------------------------------------------------------
def _test_no_key_clobber():
    from modules.systemlog import update_runtime_state_key, _read_runtime_state, _runtime_state_lock
    tmp_dir = tempfile.mkdtemp(prefix="notified_missed_debug_")
    orig_log_dir, orig_summary, orig_runtime = _setup_temp_runtime(tmp_dir)
    try:
        update_runtime_state_key("sent_pre_alerts", {"existing": "data"})
        from modules.scheduler_core import state as st
        orig_dict, orig_dirty = _isolate(st)
        try:
            st.mark_missed_pre_notified("u", "a", "1h", "2026-01-01T10:00:00", datetime(2026, 1, 1))
            st.save_notified_missed_pre()
        finally:
            _restore(st, orig_dict, orig_dirty)
        with _runtime_state_lock:
            state = _read_runtime_state()
        checks = {
            "sent_pre_alerts_intact": state.get("sent_pre_alerts") == {"existing": "data"},
            "notified_key_present": "notified_missed_pre" in state,
        }
        _dbg().section("no_key_clobber", {"state_keys": list(state.keys()), "checks": checks})
        if not all(checks.values()):
            _dbg().problem("key_clobber_detected", {"checks": checks})
    finally:
        _restore_runtime(orig_log_dir, orig_summary, orig_runtime)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from modules.scheduler_core import state as _st  # noqa: F401
            from modules import constants as _C  # noqa: F401
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_constant_present()
        _test_mark_and_check()
        _test_save_load_roundtrip()
        _test_dirty_flag()
        _test_empty_load()
        _test_cleanup_cond1_removes_when_fired()
        _test_cleanup_cond1_keeps_when_not_fired()
        _test_cleanup_cond1_keeps_when_no_last_triggered()
        _test_cleanup_cond2_deleted_alert()
        _test_cleanup_cond2_deleted_user()
        _test_cleanup_none_known()
        _test_no_key_clobber()

    except Exception as exc:
        import traceback
        dbg.problem("unhandled_exception", {"error": str(exc), "tb": traceback.format_exc()})
    finally:
        _DBG = None

    constant_ok = not dbg.has_problem("constant_invalid")
    mark_ok = not dbg.has_problem("mark_check_failed")
    roundtrip_ok = not dbg.has_problem("roundtrip_failed")
    dirty_ok = not dbg.has_problem("dirty_flag_failed")
    empty_ok = not dbg.has_problem("empty_load_failed")
    c1_rem_ok = not dbg.has_problem("cleanup_cond1_removes_failed")
    c1_keep_ok = not dbg.has_problem("cleanup_cond1_keeps_failed")
    c1_no_lt_ok = not dbg.has_problem("cleanup_cond1_no_lt_failed")
    c2_del_ok = not dbg.has_problem("cleanup_cond2_deleted_failed")
    c2_del_user_ok = not dbg.has_problem("cleanup_cond2_deleted_user_failed")
    c2_none_ok = not dbg.has_problem("cleanup_none_known_failed")
    clobber_ok = not dbg.has_problem("key_clobber_detected")
    runtime_ok = not dbg.has_problem("unhandled_exception")

    dbg.finish(summary_lines=[
        f"constant: {'OK' if constant_ok else 'FAIL'}",
        f"mark-and-check: {'OK' if mark_ok else 'FAIL'}",
        f"save-load-roundtrip: {'OK' if roundtrip_ok else 'FAIL'}",
        f"dirty-flag: {'OK' if dirty_ok else 'FAIL'}",
        f"empty-load: {'OK' if empty_ok else 'FAIL'}",
        f"cleanup-cond1-removes: {'OK' if c1_rem_ok else 'FAIL'}",
        f"cleanup-cond1-keeps: {'OK' if c1_keep_ok else 'FAIL'}",
        f"cleanup-cond1-no-last-triggered: {'OK' if c1_no_lt_ok else 'FAIL'}",
        f"cleanup-cond2-deleted-alert (fringe fix): {'OK' if c2_del_ok else 'FAIL'}",
        f"cleanup-cond2-deleted-user (fringe fix): {'OK' if c2_del_user_ok else 'FAIL'}",
        f"cleanup-none-known-degrades: {'OK' if c2_none_ok else 'FAIL'}",
        f"no-key-clobber: {'OK' if clobber_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
