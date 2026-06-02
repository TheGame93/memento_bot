#!/usr/bin/env python3
import json
import os
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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "one_time_past_debug"
FEATURE_TITLE = "Past One-Time Policy"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _parse_iso_optional(value):
    if not value:
        return None, None
    try:
        return datetime.fromisoformat(value), None
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def _test_past_one_time_policy(dbg, is_due, StorageManager, now_server_naive):
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            storage = StorageManager(base_data_dir=os.path.join(tmpdir, "data"), admin_id=1)
            user_id = 1
            storage.setup_user_space(user_id)
            reference_now = now_server_naive()
            past_day = reference_now - timedelta(days=2)
            payload = {
                "title": "Past one-time",
                "type": 5,
                "type_name": "One Time",
                "schedule": {
                    "date": past_day.strftime("%d/%m/%Y"),
                    "time": "10:00",
                },
                "pre_alerts": [],
                "tags": [],
            }

            alert_id = storage.save_alert(user_id, payload)
            alert = storage.get_alert_by_id(user_id, alert_id)
            next_scheduled_raw = (alert or {}).get("next_scheduled")
            next_scheduled, next_iso_error = _parse_iso_optional(next_scheduled_raw)
            due = is_due(alert, current_time=reference_now + timedelta(seconds=2))
            checks = {
                "saved_alert_exists": bool(alert_id and alert),
                "next_scheduled_set": next_scheduled is not None,
                "next_scheduled_iso_valid": next_iso_error is None,
                "next_scheduled_near_now": (
                    next_scheduled is not None
                    and abs((reference_now - next_scheduled).total_seconds()) < 30
                ),
                "immediate_due_true": due is True,
            }
            dbg.section("past_one_time_immediate", {
                "checks": checks,
                "alert_id": alert_id,
                "next_scheduled": next_scheduled_raw,
                "next_scheduled_iso_error": next_iso_error,
            })
            if not all(checks.values()):
                dbg.problem("past_one_time_immediate_failed", {"checks": checks, "alert": alert})
                return

            done_ok, was_one_time = storage.mark_alert_done(user_id, alert_id)
            updated = storage.get_alert_by_id(user_id, alert_id)
            due_after_done = is_due(updated, current_time=reference_now + timedelta(minutes=1))
            done_checks = {
                "mark_done_success": done_ok is True,
                "mark_done_one_time": was_one_time is True,
                "alert_inactive_after_done": bool(updated) and updated.get("active") is False,
                "not_due_after_done": due_after_done is False,
            }
            dbg.section("past_one_time_done_state", {"checks": done_checks})
            if not all(done_checks.values()):
                dbg.problem("past_one_time_done_failed", {"checks": done_checks, "alert": updated})
        finally:
            os.chdir(cwd)


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.scheduler_mathlogic import is_due
            from modules.storage import StorageManager
            from modules.timezone_utils import now_server_naive
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_past_one_time_policy(dbg, is_due, StorageManager, now_server_naive)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    immediate_ok = not dbg.has_problem("past_one_time_immediate_failed")
    done_ok = not dbg.has_problem("past_one_time_done_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"immediate: {'OK' if immediate_ok else 'FAIL'}",
        f"done-state: {'OK' if done_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
