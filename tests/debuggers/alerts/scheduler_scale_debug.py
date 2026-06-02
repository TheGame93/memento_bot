#!/usr/bin/env python3
import os
import sys
import tempfile
import time
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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "scheduler_scale_debug"
FEATURE_TITLE = "Scheduler Scale"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _coerce_int(value, fallback):
    try:
        return int(value), False
    except (TypeError, ValueError):
        return fallback, True


async def _run_scale_check(dbg, StorageManager, constants, coordinator, scheduler_state):
    now = datetime.now().replace(second=0, microsecond=0)
    future_dt = now + timedelta(days=7)
    future_date = future_dt.strftime("%d/%m/%Y")

    users = 25
    alerts_per_user = 20
    threshold_raw = os.environ.get("SCHEDULER_SCALE_TICK_THRESHOLD_MS", "8000")
    threshold_ms, threshold_fallback = _coerce_int(threshold_raw, 8000)
    if threshold_fallback or threshold_ms <= 0:
        dbg.problem("config_invalid_threshold", {"raw": threshold_raw, "effective": 8000})
        threshold_ms = 8000

    with tempfile.TemporaryDirectory(prefix="sched_scale_debug_") as tmpdir:
        storage_manager = StorageManager(base_data_dir=os.path.join(tmpdir, "data"))

        alert_template = {
            "title": "Scale Alert",
            "type": 5,
            "type_name": constants.ALERT_TYPES.get(5, "One Time"),
            "schedule": {"date": future_date, "time": "10:00"},
            "pre_alerts": [],
            "tags": [],
        }

        build_start = time.monotonic()
        for uid in range(1, users + 1):
            user_id = str(uid)
            storage_manager.setup_user_space(user_id)
            for idx in range(alerts_per_user):
                alert_id = storage_manager.save_alert(user_id, {
                    **alert_template,
                    "title": f"Scale Alert {uid}-{idx}",
                })
                if alert_id:
                    storage_manager.update_alert_schedule_state(user_id, alert_id, next_scheduled=future_dt)
        build_ms = int((time.monotonic() - build_start) * 1000)

        class _DummyApp:
            bot = object()

        prev_app = coordinator.get_app()
        prev_storage = coordinator.get_storage()
        prev_last_tick = scheduler_state.last_tick_time
        prev_sent = dict(scheduler_state.sent_pre_alerts)
        prev_log_system = coordinator.log_system
        prev_tick_slow_threshold = getattr(constants, "SCHEDULER_TICK_SLOW_THRESHOLD_MS", 1000)
        captured_events = []

        coordinator._app = _DummyApp()
        coordinator._storage = storage_manager
        scheduler_state.last_tick_time = None
        scheduler_state.sent_pre_alerts.clear()
        constants.SCHEDULER_TICK_SLOW_THRESHOLD_MS = 1

        def _fake_log_system(category, event, payload=None, level="INFO"):
            captured_events.append({
                "category": category,
                "event": event,
                "payload": payload or {},
                "level": level,
            })

        coordinator.log_system = _fake_log_system

        tick_ms = None
        try:
            start_tick = time.monotonic()
            await coordinator.check_due_alerts()
            tick_ms = int((time.monotonic() - start_tick) * 1000)
        except Exception as exc:
            dbg.problem("tick_exception", {"error": str(exc)})
        finally:
            coordinator._app = prev_app
            coordinator._storage = prev_storage
            scheduler_state.last_tick_time = prev_last_tick
            scheduler_state.sent_pre_alerts.clear()
            scheduler_state.sent_pre_alerts.update(prev_sent)
            coordinator.log_system = prev_log_system
            constants.SCHEDULER_TICK_SLOW_THRESHOLD_MS = prev_tick_slow_threshold

    slow_events = [row for row in captured_events if row.get("event") == "scheduler_tick_slow"]
    slow_payload = slow_events[-1].get("payload", {}) if slow_events else {}
    slow_event_checks = {
        "scheduler_tick_slow_logged": len(slow_events) >= 1,
        "scheduler_tick_slow_warning": bool(slow_events and slow_events[-1].get("level") == "WARNING"),
        "scheduler_tick_slow_has_duration": isinstance(slow_payload.get("duration_ms"), int),
        "scheduler_tick_slow_has_threshold": isinstance(slow_payload.get("threshold_ms"), int),
    }
    dbg.section("scale_run", {
        "users": users,
        "alerts_per_user": alerts_per_user,
        "total_alerts": users * alerts_per_user,
        "build_ms": build_ms,
        "tick_ms": tick_ms,
        "threshold_raw": threshold_raw,
        "threshold_ms": threshold_ms,
        "slow_event_checks": slow_event_checks,
        "slow_event_count": len(slow_events),
    })

    if tick_ms is None:
        dbg.problem("tick_runtime_missing", {"tick_ms": tick_ms})
    elif tick_ms > threshold_ms:
        dbg.problem("tick_runtime_slow", {
            "tick_ms": tick_ms,
            "threshold_ms": threshold_ms,
        })
    if not all(slow_event_checks.values()):
        dbg.problem("scheduler_tick_slow_event_missing", {
            "slow_event_checks": slow_event_checks,
            "slow_event_count": len(slow_events),
        })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        suppress_ptb_user_warning()

        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as C
            from modules.scheduler_core import coordinator
            from modules.scheduler_core import state as scheduler_state
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        run_async(_run_scale_check(dbg, StorageManager, C, coordinator, scheduler_state))
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    runtime_ok = not dbg.has_problem(
        "tick_runtime_slow",
        "tick_runtime_missing",
        "scheduler_tick_slow_event_missing",
    )
    tick_ok = not dbg.has_problem("tick_exception")
    config_ok = not dbg.has_problem("config_invalid_threshold")
    app_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"tick-runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"tick-exec: {'OK' if tick_ok else 'FAIL'}",
        f"config: {'OK' if config_ok else 'FAIL'}",
        f"runtime: {'OK' if app_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
