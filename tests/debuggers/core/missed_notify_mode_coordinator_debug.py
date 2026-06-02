#!/usr/bin/env python3
"""
Debugger for MISSED_ALERTS_NOTIFY_MODE wiring in coordinator.py (Steps 5-6).

Uses static source analysis (AST + string patterns) to verify:

  - start_scheduler(): loads notified_missed_pre / pending_missed BEFORE
    handle_missed_alerts() runs.
  - start_scheduler(): restores pre-alert sent-state BEFORE
    handle_missed_alerts() runs.
  - stop_scheduler(): saves AND clears the new dicts after pre_alert_state save.
    (Logic Error 1 fix: mirrors sent_pre_alerts.clear() behaviour.)
  - check_due_alerts(): captures trigger_alert() return value and calls
    clear_pending_missed_alert() on success for "always" mode.
    (Logic Error 2 fix: moved from actions.py → coordinator.py.)
  - check_due_alerts(): save_pending_missed() called at end of tick.
  - actions.py: does NOT call save_pending_missed() (clean separation).
"""
import ast
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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "missed_notify_mode_coordinator_debug"
FEATURE_TITLE = "Missed Notify Mode Coordinator Wiring (steps 5-6)"

_DBG = None


def _dbg():
    if _DBG is None:
        raise RuntimeError("debug harness not initialized")
    return _DBG


def _get_func_source(source, func_name):
    """Extract source text of a named function/async-function from module source."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            seg = ast.get_source_segment(source, node)
            return seg or ""
    return ""


def _ordered(source_text, *patterns):
    """
    Return True if all patterns appear in source_text in the given order.
    Patterns that are not found return False immediately.
    """
    pos = 0
    for p in patterns:
        idx = source_text.find(p, pos)
        if idx == -1:
            return False
        pos = idx + len(p)
    return True


# ---------------------------------------------------------------------------
# Test: start_scheduler — load state BEFORE handle_missed_alerts
# ---------------------------------------------------------------------------
def _test_start_scheduler(coordinator_src):
    func_src = _get_func_source(coordinator_src, "start_scheduler")
    checks = {
        "has_load_pre_alert_state": "load_pre_alert_state()" in func_src,
        "has_load_notified_missed_pre": "load_notified_missed_pre()" in func_src,
        "has_load_pending_missed": "load_pending_missed()" in func_src,
        "load_pre_alert_before_handle_missed_alerts": _ordered(
            func_src,
            "load_pre_alert_state()",
            "handle_missed_alerts()",
        ),
        "load_before_handle_missed_alerts": _ordered(
            func_src,
            "load_notified_missed_pre()",
            "handle_missed_alerts()",
        ),
        "load_pending_before_handle_missed_alerts": _ordered(
            func_src,
            "load_pending_missed()",
            "handle_missed_alerts()",
        ),
    }
    _dbg().section("start_scheduler_checks", {"checks": checks})
    if not all(checks.values()):
        _dbg().problem("start_scheduler_wiring_failed", {"checks": checks})


# ---------------------------------------------------------------------------
# Test: stop_scheduler — save + clear both dicts (Logic Error 1 fix)
# ---------------------------------------------------------------------------
def _test_stop_scheduler(coordinator_src):
    func_src = _get_func_source(coordinator_src, "stop_scheduler")
    checks = {
        "saves_notified_missed_pre": "save_notified_missed_pre()" in func_src,
        "clears_notified_missed_pre": "notified_missed_pre.clear()" in func_src,
        "saves_pending_missed": "save_pending_missed()" in func_src,
        "clears_pending_missed_notifications": "pending_missed_notifications.clear()" in func_src,
        # save happens before clear (belt-and-suspenders ordering)
        "save_before_clear_notified": _ordered(
            func_src, "save_notified_missed_pre()", "notified_missed_pre.clear()"
        ),
        "save_before_clear_pending": _ordered(
            func_src, "save_pending_missed()", "pending_missed_notifications.clear()"
        ),
    }
    _dbg().section("stop_scheduler_checks", {"checks": checks})
    if not all(checks.values()):
        _dbg().problem("stop_scheduler_wiring_failed", {"checks": checks})


# ---------------------------------------------------------------------------
# Test: check_due_alerts — captures trigger return value + clears pending
#        + saves pending_missed at end of tick (Logic Error 2 fix)
# ---------------------------------------------------------------------------
def _test_check_due_alerts(coordinator_src):
    func_src = _get_func_source(coordinator_src, "check_due_alerts")
    checks = {
        "has_clear_pending_missed_alert": "clear_pending_missed_alert(" in func_src,
        "has_save_pending_missed": "save_pending_missed()" in func_src,
        # The return value of _trigger_alert must be captured (sent = await _trigger_alert)
        "captures_trigger_return": "sent = await _trigger_alert(" in func_src,
        # clear happens inside the tick loop (before save_pre_alert_state)
        "clear_before_end_of_tick_save": _ordered(
            func_src,
            "clear_pending_missed_alert(",
            "save_pre_alert_state()",
        ),
        # save_pending_missed after save_pre_alert_state (end-of-tick pattern)
        "pending_save_after_pre_alert_save": _ordered(
            func_src,
            "save_pre_alert_state()",
            "save_pending_missed()",
        ),
    }
    _dbg().section("check_due_alerts_checks", {"checks": checks})
    if not all(checks.values()):
        _dbg().problem("check_due_alerts_wiring_failed", {"checks": checks})


# ---------------------------------------------------------------------------
# Test: actions.py — clean separation: save_pending_missed NOT called there
# ---------------------------------------------------------------------------
def _test_actions_clean(actions_src):
    has_save = "save_pending_missed()" in actions_src
    checks = {
        "no_save_pending_missed_in_actions": not has_save,
    }
    _dbg().section("actions_clean_separation", {"checks": checks})
    if not all(checks.values()):
        _dbg().problem("actions_separation_violated", {"checks": checks})


# ---------------------------------------------------------------------------
# Test: remove_alert_from_queue — clears pending_missed for "always" mode
#        (Bug fix: stale entries after UI deletion cleared immediately)
# ---------------------------------------------------------------------------
def _test_remove_alert_from_queue(coordinator_src):
    func_src = _get_func_source(coordinator_src, "remove_alert_from_queue")
    checks = {
        "has_clear_pending_missed_alert": "clear_pending_missed_alert(" in func_src,
        "guards_by_always_mode": 'MISSED_ALERTS_NOTIFY_MODE == "always"' in func_src,
        # clear must come after the sent_pre_alerts cleanup (ordering check)
        "clear_after_sent_pre_cleanup": _ordered(
            func_src,
            "sent_pre_alerts",
            "clear_pending_missed_alert(",
        ),
    }
    _dbg().section("remove_alert_queue_checks", {"checks": checks})
    if not all(checks.values()):
        _dbg().problem("remove_alert_queue_wiring_failed", {"checks": checks})


# ---------------------------------------------------------------------------
# Test: missed.py handle_missed_alerts — pentry preservation in Step 4e
#        (Bug fix: missed_pre_strs / first_notified preserved on re-record)
# ---------------------------------------------------------------------------
def _test_missed_pentry_preservation(missed_src):
    func_src = _get_func_source(missed_src, "handle_missed_alerts")
    checks = {
        # Must read existing pentry before re-recording
        "reads_existing_pentry": "get_pending_missed_for_user(_uid_str).get(_alert_id" in func_src,
        # Must fall back to pentry's missed_pre_strs when _pre_keys is empty
        "preserves_missed_pre_strs": '_existing_pentry.get("missed_pre_strs"' in func_src,
        # Must preserve original first_notified
        "preserves_first_notified": '_existing_pentry.get("first_notified")' in func_src,
        # Pentry read must appear BEFORE record_pending_missed call
        "read_before_record": _ordered(
            func_src,
            "_existing_pentry",
            "record_pending_missed(",
        ),
    }
    _dbg().section("missed_pentry_preservation", {"checks": checks})
    if not all(checks.values()):
        _dbg().problem("missed_pentry_preservation_failed", {"checks": checks})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        dbg.run_meta({"project_root": ROOT_DIR})

        coordinator_path = os.path.join(ROOT_DIR, "modules", "scheduler_core", "coordinator.py")
        actions_path = os.path.join(ROOT_DIR, "modules", "scheduler_core", "actions.py")
        missed_path = os.path.join(ROOT_DIR, "modules", "scheduler_core", "missed.py")

        missing = [p for p in (coordinator_path, actions_path, missed_path) if not os.path.exists(p)]
        if missing:
            dbg.problem("source_files_missing", {"missing": missing})
            dbg.finish(exit_on_problems=False)
            return

        with open(coordinator_path, "r", encoding="utf-8") as f:
            coordinator_src = f.read()
        with open(actions_path, "r", encoding="utf-8") as f:
            actions_src = f.read()
        with open(missed_path, "r", encoding="utf-8") as f:
            missed_src = f.read()

        _test_start_scheduler(coordinator_src)
        _test_stop_scheduler(coordinator_src)
        _test_check_due_alerts(coordinator_src)
        _test_actions_clean(actions_src)
        _test_remove_alert_from_queue(coordinator_src)
        _test_missed_pentry_preservation(missed_src)

    except Exception as exc:
        import traceback
        dbg.problem("unhandled_exception", {"error": str(exc), "tb": traceback.format_exc()})
    finally:
        _DBG = None

    start_ok = not dbg.has_problem("start_scheduler_wiring_failed")
    stop_ok = not dbg.has_problem("stop_scheduler_wiring_failed")
    tick_ok = not dbg.has_problem("check_due_alerts_wiring_failed")
    actions_ok = not dbg.has_problem("actions_separation_violated")
    remove_ok = not dbg.has_problem("remove_alert_queue_wiring_failed")
    pentry_ok = not dbg.has_problem("missed_pentry_preservation_failed")
    files_ok = not dbg.has_problem("source_files_missing")
    runtime_ok = not dbg.has_problem("unhandled_exception")

    dbg.finish(summary_lines=[
        f"start_scheduler_load: {'OK' if start_ok else 'FAIL'}",
        f"stop_scheduler_save_clear: {'OK' if stop_ok else 'FAIL'}",
        f"check_due_alerts_wiring: {'OK' if tick_ok else 'FAIL'}",
        f"actions_clean_separation: {'OK' if actions_ok else 'FAIL'}",
        f"remove_alert_queue_wiring: {'OK' if remove_ok else 'FAIL'}",
        f"missed_pentry_preservation: {'OK' if pentry_ok else 'FAIL'}",
        f"source_files_present: {'OK' if files_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
