#!/usr/bin/env python3
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
SCRIPT_TITLE = "timezone_debug"
FEATURE_TITLE = "Timezone Handling"

IMPORT_ERROR = None
try:
    from zoneinfo import ZoneInfo
    from modules import constants as C
    from modules.handlers import base as base_handler
    from modules.handlers.add_flow import summary_flow
    from modules.storage import StorageManager
    from modules.timezone_utils import (
        format_tz_offset,
        get_server_tz,
        now_server_naive,
        to_user_naive_from_server,
    )
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


def _extract_offset(line):
    if not line:
        return None
    if "(" not in line or not line.endswith(")"):
        return None
    return line.split("(", 1)[1][:-1]


def _find_offset_divergence(server_tz, user_tz):
    start = datetime(2026, 1, 1, 0, 0, 0)
    for hour in range(0, 24 * 366, 3):
        sample = start + timedelta(hours=hour)
        expected = format_tz_offset(sample.replace(tzinfo=server_tz), user_tz)
        old = format_tz_offset(sample, user_tz)
        if expected != old:
            return sample
    return None


def _test_offset_reference():
    server_tz = get_server_tz()
    user_tz = ZoneInfo("America/New_York")
    reference = _find_offset_divergence(server_tz, user_tz)
    if reference is None:
        reference = datetime(2026, 2, 1, 12, 0, 0)

    line = base_handler._format_timezone_line(user_tz.key, reference)
    offset = _extract_offset(line)
    expected = format_tz_offset(reference.replace(tzinfo=server_tz), user_tz)
    checks = {
        "reference": reference.isoformat(),
        "offset_line": line,
        "offset_extracted": offset,
        "expected_offset": expected,
    }
    print_section("timezone_offset_reference", checks)
    if offset != expected:
        _log_problem("timezone_offset_reference_failed", checks)


def _test_one_time_past_user_timezone():
    server_now = now_server_naive()
    user_tz = ZoneInfo("America/Los_Angeles")
    user_now = to_user_naive_from_server(server_now, user_tz)
    candidate = user_now + timedelta(hours=2)
    payload = {
        "type": 5,
        "schedule": {
            "date": candidate.strftime("%d/%m/%Y"),
            "time": candidate.strftime("%H:%M"),
        },
    }
    user_prefs = {
        "timezone_mode": C.TIMEZONE_MODE_USER,
        "timezone": {"name": user_tz.key},
    }
    is_past = summary_flow.is_one_time_past(payload, user_prefs=user_prefs)
    checks = {
        "server_now": server_now.isoformat(),
        "user_now": user_now.isoformat(),
        "candidate": candidate.isoformat(),
        "is_past": is_past,
    }
    print_section("one_time_past_timezone", checks)
    if is_past:
        _log_problem("one_time_past_timezone_failed", checks)


def _test_one_time_immediate_user_ahead():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        user_id = "9001"
        storage.setup_user_space(user_id)

        user_tz = ZoneInfo("Asia/Tokyo")
        storage.update_user_prefs(user_id, {
            "timezone_mode": C.TIMEZONE_MODE_USER,
            "timezone": {"name": user_tz.key},
        })

        server_now = now_server_naive()
        user_now = to_user_naive_from_server(server_now, user_tz)
        candidate = user_now - timedelta(hours=1)
        alert = {
            "type": 5,
            "title": "Timezone immediate check",
            "schedule": {
                "date": candidate.strftime("%d/%m/%Y"),
                "time": candidate.strftime("%H:%M"),
            },
        }

        before = now_server_naive()
        alert_id = storage.save_alert(user_id, alert)
        after = now_server_naive()

        data = storage.get_all_alerts(user_id) or {}
        alerts = data.get("alerts", []) or []
        saved = next((a for a in alerts if a.get("id") == alert_id), None)
        next_scheduled = saved.get("next_scheduled") if saved else None

        checks = {
            "server_now": server_now.isoformat(),
            "user_now": user_now.isoformat(),
            "candidate": candidate.isoformat(),
            "alert_id": alert_id,
            "next_scheduled": next_scheduled,
        }
        print_section("one_time_immediate_timezone", checks)

        if not next_scheduled:
            _log_problem("one_time_immediate_timezone_failed", {**checks, "reason": "missing_next_scheduled"})
            return

        try:
            scheduled_dt = datetime.fromisoformat(next_scheduled)
        except Exception:
            _log_problem("one_time_immediate_timezone_failed", {**checks, "reason": "invalid_next_scheduled"})
            return

        if scheduled_dt < before - timedelta(seconds=1) or scheduled_dt > after + timedelta(seconds=1):
            _log_problem("one_time_immediate_timezone_failed", {**checks, "reason": "next_scheduled_outside_now_window"})


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

        _test_offset_reference()
        _test_one_time_past_user_timezone()
        _test_one_time_immediate_user_ahead()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    offset_ok = not dbg.has_problem("timezone_offset_reference_failed")
    past_ok = not dbg.has_problem("one_time_past_timezone_failed")
    immediate_ok = not dbg.has_problem("one_time_immediate_timezone_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"offset_reference: {'OK' if offset_ok else 'FAIL'}",
        f"one_time_past: {'OK' if past_ok else 'FAIL'}",
        f"one_time_immediate: {'OK' if immediate_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
