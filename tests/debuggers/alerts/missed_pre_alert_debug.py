#!/usr/bin/env python3
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
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
from _lib.runtime import run_async

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "missed_pre_alert_debug"
FEATURE_TITLE = "Missed Pre-Alert Recovery Guards"


def _parse_pre_alert_silenced(parse_func, spec):
    """Capture parser stderr noise so debug output stays log-only unless a real problem appears."""
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        delta = parse_func(spec)
    return delta, err_buf.getvalue()


def _check_parse_pre_alert(dbg, C, parse_func, resolve_func):
    checks = {}
    captured_stderr = {}
    for spec, check_fn in [
        ("2h", lambda d: d == timedelta(hours=2)),
        ("7d", lambda d: d == timedelta(days=7)),
        ("3w", lambda d: d == timedelta(weeks=3)),
        ("1mo", lambda d: d is not None),
        ("invalid", lambda d: d is None),
        ("", lambda d: d is None),
    ]:
        delta, stderr_text = _parse_pre_alert_silenced(parse_func, spec)
        checks[spec or "(empty)"] = check_fn(delta)
        if stderr_text.strip():
            captured_stderr[spec or "(empty)"] = stderr_text.strip().splitlines()

    evening_token = C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN
    delta_evening, stderr_evening = _parse_pre_alert_silenced(parse_func, evening_token)
    checks["birthday_evening_token_parse_none"] = delta_evening is None
    if stderr_evening.strip():
        captured_stderr[evening_token] = stderr_evening.strip().splitlines()

    pre_dt, pre_kind = resolve_func(
        {"type": 6, "schedule": {"date": "12/03", "time": "08:00"}},
        evening_token,
        datetime(2026, 3, 12, 8, 0),
        user_prefs={"birthday_evening_before_time": "20:00"},
    )
    checks["birthday_evening_token_resolves"] = (
        pre_kind == "birthday_evening_before"
        and pre_dt == datetime(2026, 3, 11, 20, 0)
    )

    dbg.section("parse_pre_alert_check", {"checks": checks, "captured_stderr": captured_stderr})
    if not all(checks.values()):
        dbg.problem("parse_pre_alert_failed", {"checks": checks})


async def _run_missed_check(handle_missed_alerts, storage, now):
    flagged_alerts = []

    async def _fake_send_missed(_bot, _uid, missed_list):
        for item in missed_list:
            flagged_alerts.append({
                "alert_id": item.get("alert", {}).get("id"),
                "missed_pre": [t.isoformat() for t in item.get("missed_pre", [])],
                "missed_due": [t.isoformat() for t in item.get("missed_due", [])],
            })
        return {"ok": True}

    await handle_missed_alerts(
        bot=object(),
        storage=storage,
        now=now,
        send_missed_func=_fake_send_missed,
    )
    return flagged_alerts


def _setup_isolation():
    """Save and redirect syslog paths + scheduler-state slices. Returns restore args."""
    import modules.systemlog as syslog_mod
    from modules.scheduler_core import state as st
    orig_log_dir = syslog_mod.LOG_DIR
    orig_summary = getattr(syslog_mod, "SUMMARY_LOG", None)
    orig_runtime = syslog_mod.RUNTIME_STATE_FILE
    orig_notified = dict(st.notified_missed_pre)
    orig_dirty = st.notified_missed_pre_dirty
    orig_sent = dict(st.sent_pre_alerts)
    orig_sent_dirty = st.sent_pre_alerts_dirty
    return (
        syslog_mod, st,
        orig_log_dir, orig_summary, orig_runtime,
        orig_notified, orig_dirty,
        orig_sent, orig_sent_dirty,
    )


def _apply_isolation(syslog_mod, st, tmpdir):
    """Redirect syslog to tmpdir and clear notified state."""
    sys_log_dir = os.path.join(tmpdir, "systemlog.d")
    os.makedirs(sys_log_dir, exist_ok=True)
    syslog_mod.LOG_DIR = sys_log_dir
    orig_summary = getattr(syslog_mod, "SUMMARY_LOG", None)
    if orig_summary is not None:
        syslog_mod.SUMMARY_LOG = os.path.join(sys_log_dir, "system.log")
    syslog_mod.RUNTIME_STATE_FILE = os.path.join(sys_log_dir, "runtime_state.json")
    st.notified_missed_pre.clear()
    st.notified_missed_pre_dirty = False
    st.sent_pre_alerts.clear()
    st.sent_pre_alerts_dirty = False


def _teardown_isolation(syslog_mod, st, orig_log_dir, orig_summary, orig_runtime,
                        orig_notified, orig_dirty, orig_sent, orig_sent_dirty):
    """Restore syslog paths + notified_missed_pre state."""
    st.notified_missed_pre.clear()
    st.notified_missed_pre.update(orig_notified)
    st.notified_missed_pre_dirty = orig_dirty
    st.sent_pre_alerts.clear()
    st.sent_pre_alerts.update(orig_sent)
    st.sent_pre_alerts_dirty = orig_sent_dirty
    syslog_mod.LOG_DIR = orig_log_dir
    if orig_summary is not None:
        syslog_mod.SUMMARY_LOG = orig_summary
    syslog_mod.RUNTIME_STATE_FILE = orig_runtime


def _seed_runtime_offline_window(syslog_mod, now, *, hours=2):
    state = {
        "last_shutdown_ts": (now - timedelta(hours=hours)).isoformat(),
        "last_exit": "clean",
        "instance_identity": syslog_mod._runtime_identity_payload(),
    }
    with open(syslog_mod.RUNTIME_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


async def _run_false_positive_check(dbg, C, StorageManager, handle_missed_alerts):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]
    syslog_mod, st, *orig = _setup_isolation()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            _apply_isolation(syslog_mod, st, tmpdir)
            storage = StorageManager(base_data_dir=tmpdir)
            user_id = "2001"
            storage.setup_user_space(user_id)

            alert_id = storage.save_alert(user_id, {
                "title": "New Alert With 1mo Pre",
                "type": 3,
                "type_name": C.ALERT_TYPES[3],
                "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
                "pre_alerts": ["1mo"],
                "tags": [],
            })
            future_occ = now + timedelta(days=9)
            storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=future_occ)
            _seed_runtime_offline_window(syslog_mod, now, hours=2)
            flagged = await _run_missed_check(handle_missed_alerts, storage, now + timedelta(seconds=5))
            alert_flagged = any(f["alert_id"] == alert_id and f["missed_pre"] for f in flagged)
            checks = {"false_positive_avoided": not alert_flagged}
            dbg.section("false_positive_check", {"checks": checks, "flagged": flagged, "alert_id": alert_id})
            if alert_flagged:
                dbg.problem("false_positive_detected", {"flagged": flagged})
        finally:
            _teardown_isolation(syslog_mod, st, *orig)


async def _run_true_positive_check(dbg, C, StorageManager, handle_missed_alerts):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]
    syslog_mod, st, *orig = _setup_isolation()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            _apply_isolation(syslog_mod, st, tmpdir)
            storage = StorageManager(base_data_dir=tmpdir)
            user_id = "2002"
            storage.setup_user_space(user_id)

            alert_id = storage.save_alert(user_id, {
                "title": "Old Alert With 1h Pre",
                "type": 3,
                "type_name": C.ALERT_TYPES[3],
                "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
                "pre_alerts": ["3h"],
                "tags": [],
            })
            old_created = (now - timedelta(days=2)).isoformat()
            future_occ = now + timedelta(hours=2)  # main alert not overdue; only pre is missed
            storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=future_occ)
            all_data = storage.get_all_alerts(user_id)
            for item in all_data.get("alerts", []):
                if item.get("id") == alert_id:
                    item["created_at"] = old_created
            storage._write_user_data(user_id, all_data)
            _seed_runtime_offline_window(syslog_mod, now, hours=2)

            flagged = await _run_missed_check(handle_missed_alerts, storage, now)
            alert_flagged = any(
                f["alert_id"] == alert_id and f["missed_pre"] and not f["missed_due"]
                for f in flagged
            )
            checks = {"true_positive_detected": alert_flagged}
            dbg.section("true_positive_check", {"checks": checks, "flagged": flagged, "alert_id": alert_id})
            if not alert_flagged:
                dbg.problem("true_positive_missed", {"flagged": flagged})
        finally:
            _teardown_isolation(syslog_mod, st, *orig)


async def _run_no_created_at_fallback_check(dbg, C, StorageManager, handle_missed_alerts):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]
    syslog_mod, st, *orig = _setup_isolation()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            _apply_isolation(syslog_mod, st, tmpdir)
            storage = StorageManager(base_data_dir=tmpdir)
            user_id = "2003"
            storage.setup_user_space(user_id)

            alert_id = storage.save_alert(user_id, {
                "title": "Legacy Alert No Created",
                "type": 3,
                "type_name": C.ALERT_TYPES[3],
                "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
                "pre_alerts": ["3h"],
                "tags": [],
            })
            all_data = storage.get_all_alerts(user_id)
            for item in all_data.get("alerts", []):
                if item.get("id") == alert_id:
                    item.pop("created_at", None)
            storage._write_user_data(user_id, all_data)
            storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=now + timedelta(hours=2))
            _seed_runtime_offline_window(syslog_mod, now, hours=2)

            flagged = await _run_missed_check(handle_missed_alerts, storage, now)
            alert_flagged = any(
                f["alert_id"] == alert_id and f["missed_pre"] and not f["missed_due"]
                for f in flagged
            )
            checks = {"fallback_flagged": alert_flagged}
            dbg.section("no_created_at_fallback", {"checks": checks, "flagged": flagged})
            if not alert_flagged:
                dbg.problem("no_created_at_fallback_failed", {"flagged": flagged})
        finally:
            _teardown_isolation(syslog_mod, st, *orig)


async def _run_already_sent_pre_alert_check(dbg, C, StorageManager, handle_missed_alerts):
    """
    Deterministic false-positive guard:
      - pre-alert time is inside downtime window
      - pre-alert is already present in sent_pre_alerts state
      - startup must NOT classify it as missed.
    """
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]
    syslog_mod, st, *orig = _setup_isolation()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            _apply_isolation(syslog_mod, st, tmpdir)
            storage = StorageManager(base_data_dir=tmpdir)
            user_id = "2005"
            storage.setup_user_space(user_id)

            alert_id = storage.save_alert(user_id, {
                "title": "Already Sent Pre Alert",
                "type": 3,
                "type_name": C.ALERT_TYPES[3],
                "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
                "pre_alerts": ["9h"],
                "tags": [],
            })
            next_occ = now + timedelta(hours=8)   # pre_time = now - 1h
            storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=next_occ)

            all_data = storage.get_all_alerts(user_id)
            for item in all_data.get("alerts", []):
                if item.get("id") == alert_id:
                    item["created_at"] = (now - timedelta(days=2)).isoformat()
            storage._write_user_data(user_id, all_data)

            # Simulate that this pre-alert was already delivered before shutdown.
            st.sent_pre_alerts[(str(user_id), alert_id, "9h")] = now - timedelta(hours=2)
            st.sent_pre_alerts_dirty = False
            _seed_runtime_offline_window(syslog_mod, now, hours=2)

            flagged = await _run_missed_check(handle_missed_alerts, storage, now)
            alert_flagged = any(f["alert_id"] == alert_id and f["missed_pre"] for f in flagged)
            checks = {"already_sent_not_reclassified": not alert_flagged}
            dbg.section("already_sent_pre_alert", {"checks": checks, "flagged": flagged})
            if alert_flagged:
                dbg.problem("already_sent_pre_alert_misclassified", {"flagged": flagged})
        finally:
            _teardown_isolation(syslog_mod, st, *orig)


async def _run_once_mode_suppression_check(dbg, C, StorageManager, handle_missed_alerts):
    """
    "once" mode: first call detects a missed pre-alert (main alert NOT overdue).
    Second call (simulating a restart with state reloaded) suppresses it.

    Uses: next_scheduled 6h in the future, pre_alert "7h" → pre_time = now-1h (missed).
    The main alert is not overdue, so next_scheduled is not advanced.
    Without fix: would re-detect on every restart.
    With fix: notified_missed_pre persisted → suppressed on second call.
    """
    import modules.systemlog as syslog_mod
    from modules.scheduler_core import state as st

    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]
    future_occ = now + timedelta(hours=6)   # main alert NOT overdue
    # pre_time = future_occ - 7h = now - 1h → missed

    tmpdir = tempfile.mkdtemp(prefix="once_mode_suppression_debug_")
    orig_log_dir = syslog_mod.LOG_DIR
    orig_summary = getattr(syslog_mod, "SUMMARY_LOG", None)
    orig_runtime = syslog_mod.RUNTIME_STATE_FILE
    orig_notified = dict(st.notified_missed_pre)
    orig_notified_dirty = st.notified_missed_pre_dirty

    try:
        sys_log_dir = os.path.join(tmpdir, "systemlog.d")
        os.makedirs(sys_log_dir, exist_ok=True)
        syslog_mod.LOG_DIR = sys_log_dir
        if orig_summary is not None:
            syslog_mod.SUMMARY_LOG = os.path.join(sys_log_dir, "system.log")
        syslog_mod.RUNTIME_STATE_FILE = os.path.join(sys_log_dir, "runtime_state.json")

        # Start with empty notified state
        st.notified_missed_pre.clear()
        st.notified_missed_pre_dirty = False
        _seed_runtime_offline_window(syslog_mod, now, hours=2)

        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "3001"
        storage.setup_user_space(user_id)

        alert_id = storage.save_alert(user_id, {
            "title": "Once Mode Suppression Test",
            "type": 3,
            "type_name": C.ALERT_TYPES[3],
            "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
            "pre_alerts": ["7h"],
            "tags": [],
        })
        # next_scheduled = 6h in the future (main alert NOT overdue)
        storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=future_occ)
        # created_at = 2 days ago (old enough for created_at guard to pass)
        all_data = storage.get_all_alerts(user_id)
        for item in all_data.get("alerts", []):
            if item.get("id") == alert_id:
                item["created_at"] = (now - timedelta(days=2)).isoformat()
        storage._write_user_data(user_id, all_data)

        # First call: should detect missed pre-alert and save state internally
        flagged_first = await _run_missed_check(handle_missed_alerts, storage, now)
        first_detected = any(
            f["alert_id"] == alert_id and f["missed_pre"] for f in flagged_first
        )

        # Simulate restart: clear in-memory state, reload from disk
        st.notified_missed_pre.clear()
        st.notified_missed_pre_dirty = False
        st.load_notified_missed_pre()

        # Second call: should suppress the pre-alert (already notified)
        flagged_second = await _run_missed_check(handle_missed_alerts, storage, now)
        second_detected = any(
            f["alert_id"] == alert_id and f["missed_pre"] for f in flagged_second
        )

        checks = {
            "first_detected": first_detected,
            "second_suppressed": not second_detected,
        }
        dbg.section("once_mode_suppression", {
            "checks": checks,
            "flagged_first": flagged_first,
            "flagged_second": flagged_second,
        })
        if not all(checks.values()):
            dbg.problem("once_mode_suppression_failed", {"checks": checks})
    finally:
        st.notified_missed_pre.clear()
        st.notified_missed_pre.update(orig_notified)
        st.notified_missed_pre_dirty = orig_notified_dirty
        syslog_mod.LOG_DIR = orig_log_dir
        if orig_summary is not None:
            syslog_mod.SUMMARY_LOG = orig_summary
        syslog_mod.RUNTIME_STATE_FILE = orig_runtime
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _run_always_mode_pentry_preservation_check(dbg, C, StorageManager, handle_missed_alerts):
    """
    "always" mode: after fresh detection on restart 1, advance next_scheduled
    so the pre-alert is no longer freshly detected on restart 2.  The pending
    entry must be re-notified from pending (Step 4d) and then re-recorded (Step
    4e) with the original missed_pre_strs and first_notified PRESERVED — not
    overwritten with [] / now.

    Bug: without the fix, _pre_keys=[] on re-record → missed_pre_strs=[].
    Fix: Step 4e reads existing pentry and falls back to its values.
    """
    import modules.systemlog as syslog_mod
    from modules.scheduler_core import state as st
    from modules import constants as C_mod

    orig_mode = C_mod.MISSED_ALERTS_NOTIFY_MODE
    C_mod.MISSED_ALERTS_NOTIFY_MODE = "always"

    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]
    future_occ = now + timedelta(hours=6)  # main alert NOT overdue

    tmpdir = tempfile.mkdtemp(prefix="always_pentry_debug_")
    orig_syslog_dir = syslog_mod.LOG_DIR
    orig_summary = getattr(syslog_mod, "SUMMARY_LOG", None)
    orig_runtime = syslog_mod.RUNTIME_STATE_FILE
    orig_pending = {}
    orig_pending.update(st.pending_missed_notifications)
    orig_pending_dirty = st.pending_missed_dirty

    try:
        sys_log_dir = os.path.join(tmpdir, "systemlog.d")
        os.makedirs(sys_log_dir, exist_ok=True)
        syslog_mod.LOG_DIR = sys_log_dir
        if orig_summary is not None:
            syslog_mod.SUMMARY_LOG = os.path.join(sys_log_dir, "system.log")
        syslog_mod.RUNTIME_STATE_FILE = os.path.join(sys_log_dir, "runtime_state.json")
        st.pending_missed_notifications.clear()
        st.pending_missed_dirty = False
        _seed_runtime_offline_window(syslog_mod, now, hours=2)

        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "4001"
        storage.setup_user_space(user_id)

        alert_id = storage.save_alert(user_id, {
            "title": "Always Mode Pentry Preservation Test",
            "type": 3,
            "type_name": C.ALERT_TYPES[3],
            "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
            "pre_alerts": ["7h"],
            "tags": [],
        })
        # next_scheduled 6h in the future → pre_time = now-1h (missed, main NOT overdue)
        storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=future_occ)
        all_data = storage.get_all_alerts(user_id)
        for item in all_data.get("alerts", []):
            if item.get("id") == alert_id:
                item["created_at"] = (now - timedelta(days=2)).isoformat()
        storage._write_user_data(user_id, all_data)

        # Restart 1: fresh detection → pending entry recorded with missed_pre_strs=["7h"]
        await _run_missed_check(handle_missed_alerts, storage, now)
        pentry_after_r1 = st.get_pending_missed_for_user(str(user_id)).get(alert_id, {})
        first_notified_r1 = pentry_after_r1.get("first_notified")
        pre_strs_r1 = pentry_after_r1.get("missed_pre_strs", [])

        # Advance next_scheduled far into future so pre_time = now + 23h (not missed)
        advanced_occ = now + timedelta(hours=30)
        storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=advanced_occ)

        # Restart 2: not freshly detected, re-notified from pending (Step 4d)
        # Step 4e must preserve missed_pre_strs and first_notified from pentry.
        await _run_missed_check(handle_missed_alerts, storage, now)
        pentry_after_r2 = st.get_pending_missed_for_user(str(user_id)).get(alert_id, {})

        checks = {
            "entry_recorded_r1": bool(pentry_after_r1),
            "pre_strs_r1_correct": pre_strs_r1 == ["7h"],
            "entry_still_exists_r2": bool(pentry_after_r2),
            "pre_strs_preserved_r2": pentry_after_r2.get("missed_pre_strs") == ["7h"],
            "first_notified_preserved_r2": pentry_after_r2.get("first_notified") == first_notified_r1,
        }
        dbg.section("always_mode_pentry_preservation", {
            "pentry_r1": pentry_after_r1,
            "pentry_r2": pentry_after_r2,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("always_pentry_preservation_failed", {"checks": checks})
    finally:
        C_mod.MISSED_ALERTS_NOTIFY_MODE = orig_mode
        st.pending_missed_notifications.clear()
        st.pending_missed_notifications.update(orig_pending)
        st.pending_missed_dirty = orig_pending_dirty
        syslog_mod.LOG_DIR = orig_syslog_dir
        if orig_summary is not None:
            syslog_mod.SUMMARY_LOG = orig_summary
        syslog_mod.RUNTIME_STATE_FILE = orig_runtime
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _run_upcoming_check(dbg, C, StorageManager, handle_missed_alerts):
    now = datetime.now().replace(second=0, microsecond=0)
    weekday = C.WEEKDAYS[now.weekday()]
    syslog_mod, st, *orig = _setup_isolation()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            _apply_isolation(syslog_mod, st, tmpdir)
            storage = StorageManager(base_data_dir=tmpdir)
            user_id = "2004"
            storage.setup_user_space(user_id)

            alert_id = storage.save_alert(user_id, {
                "title": "Future Pre Alert",
                "type": 3,
                "type_name": C.ALERT_TYPES[3],
                "schedule": {"weekdays": [weekday], "interval": 1, "time": "10:00"},
                "pre_alerts": ["2h"],
                "tags": [],
            })
            future_occ = now + timedelta(days=1)
            storage.update_alert_schedule_state(user_id, alert_id, next_scheduled=future_occ)
            _seed_runtime_offline_window(syslog_mod, now, hours=2)
            flagged = await _run_missed_check(handle_missed_alerts, storage, now)
            alert_flagged = any(f["alert_id"] == alert_id and f["missed_pre"] for f in flagged)
            checks = {"upcoming_not_flagged": not alert_flagged}
            dbg.section("upcoming_pre_alert_check", {"checks": checks, "flagged": flagged})
            if alert_flagged:
                dbg.problem("upcoming_misclassified", {"flagged": flagged})
        finally:
            _teardown_isolation(syslog_mod, st, *orig)


async def _run_evening_before_missed_check(dbg, C, StorageManager, handle_missed_alerts):
    now = datetime(2026, 3, 11, 21, 0, 0)
    syslog_mod, st, *orig = _setup_isolation()
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            _apply_isolation(syslog_mod, st, tmpdir)
            storage = StorageManager(base_data_dir=tmpdir)
            user_id = "2006"
            storage.setup_user_space(user_id)

            alert_id = storage.save_alert(user_id, {
                "title": "Birthday Evening Before",
                "type": 6,
                "type_name": C.ALERT_TYPES[6],
                "schedule": {"date": "12/03", "time": "08:00"},
                "pre_alerts": [C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN],
                "tags": [],
            })
            storage.update_alert_schedule_state(
                user_id,
                alert_id,
                next_scheduled=datetime(2026, 3, 12, 8, 0),
            )
            all_data = storage.get_all_alerts(user_id)
            for item in all_data.get("alerts", []):
                if item.get("id") == alert_id:
                    item["created_at"] = datetime(2026, 3, 1, 9, 0, 0).isoformat()
            storage._write_user_data(user_id, all_data)
            storage.update_user_prefs(user_id, {"birthday_evening_before_time": "20:00"})

            _seed_runtime_offline_window(syslog_mod, now, hours=3)

            flagged = await _run_missed_check(handle_missed_alerts, storage, now)
            target_pre_iso = datetime(2026, 3, 11, 20, 0, 0).isoformat()
            matched = next((f for f in flagged if f["alert_id"] == alert_id), None)
            checks = {
                "birthday_evening_missed_detected": bool(
                    matched
                    and target_pre_iso in (matched.get("missed_pre") or [])
                    and not (matched.get("missed_due") or [])
                ),
            }
            dbg.section("birthday_evening_before_missed", {
                "checks": checks,
                "flagged": flagged,
                "target_pre_iso": target_pre_iso,
            })
            if not all(checks.values()):
                dbg.problem("birthday_evening_before_missed_failed", {"checks": checks, "flagged": flagged})
        finally:
            _teardown_isolation(syslog_mod, st, *orig)


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from modules import constants as C
            from modules.scheduler_core.missed import handle_missed_alerts
            from modules.scheduler_mathlogic import parse_pre_alert_string, resolve_pre_alert_fire_time
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _check_parse_pre_alert(dbg, C, parse_pre_alert_string, resolve_pre_alert_fire_time)
        run_async(_run_false_positive_check(dbg, C, StorageManager, handle_missed_alerts))
        run_async(_run_already_sent_pre_alert_check(dbg, C, StorageManager, handle_missed_alerts))
        run_async(_run_true_positive_check(dbg, C, StorageManager, handle_missed_alerts))
        run_async(_run_no_created_at_fallback_check(dbg, C, StorageManager, handle_missed_alerts))
        run_async(_run_upcoming_check(dbg, C, StorageManager, handle_missed_alerts))
        run_async(_run_evening_before_missed_check(dbg, C, StorageManager, handle_missed_alerts))
        run_async(_run_once_mode_suppression_check(dbg, C, StorageManager, handle_missed_alerts))
        run_async(_run_always_mode_pentry_preservation_check(dbg, C, StorageManager, handle_missed_alerts))
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    parse_ok = not dbg.has_problem("parse_pre_alert_failed")
    false_pos_ok = not dbg.has_problem("false_positive_detected")
    already_sent_ok = not dbg.has_problem("already_sent_pre_alert_misclassified")
    true_pos_ok = not dbg.has_problem("true_positive_missed")
    fallback_ok = not dbg.has_problem("no_created_at_fallback_failed")
    upcoming_ok = not dbg.has_problem("upcoming_misclassified")
    evening_before_ok = not dbg.has_problem("birthday_evening_before_missed_failed")
    once_ok = not dbg.has_problem("once_mode_suppression_failed")
    always_preserve_ok = not dbg.has_problem("always_pentry_preservation_failed")
    dbg.finish(summary_lines=[
        f"parse: {'OK' if parse_ok else 'FAIL'}",
        f"false_positive: {'OK' if false_pos_ok else 'FAIL'}",
        f"already_sent_guard: {'OK' if already_sent_ok else 'FAIL'}",
        f"true_positive: {'OK' if true_pos_ok else 'FAIL'}",
        f"fallback: {'OK' if fallback_ok else 'FAIL'}",
        f"upcoming: {'OK' if upcoming_ok else 'FAIL'}",
        f"birthday_evening_before: {'OK' if evening_before_ok else 'FAIL'}",
        f"once_mode_suppression: {'OK' if once_ok else 'FAIL'}",
        f"always_pentry_preservation: {'OK' if always_preserve_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
