#!/usr/bin/env python3
import asyncio
import json
import logging
import os
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
SCRIPT_TITLE = "resilience_debug"
FEATURE_TITLE = "System Resilience"

IMPORT_ERROR = None
try:
    from modules.storage import StorageManager
    from modules import constants as C
    from modules.telegram_resilience import (
        ApiFailureTracker,
        BadRequest,
        TimedOut,
        run_with_retry,
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


_REQUIRED_ALERTS_KEYS = {
    "tags",
    "alerts",
    "postpone_queue",
    "backup_prefs",
    "user_prefs",
    "user_meta",
    "shortcut_meta",
}


def _has_required_alerts_schema(payload):
    return isinstance(payload, dict) and _REQUIRED_ALERTS_KEYS.issubset(set(payload.keys()))


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _test_storage_recovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StorageManager(base_data_dir=tmpdir)
        # Case A: recover from .tmp and normalize schema.
        user_tmp = "42"
        storage.setup_user_space(user_tmp)
        alerts_tmp = os.path.join(tmpdir, user_tmp, "alerts.json")
        tmp_candidate = alerts_tmp + ".tmp"
        with open(alerts_tmp, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        with open(tmp_candidate, "w", encoding="utf-8") as f:
            # Intentionally incomplete payload to verify post-recovery normalization.
            json.dump({"alerts": []}, f)
        recovered_tmp = storage.get_all_alerts(user_tmp)
        reloaded_tmp = _load_json(alerts_tmp)
        case_tmp_ok = (
            _has_required_alerts_schema(recovered_tmp)
            and _has_required_alerts_schema(reloaded_tmp)
            and not os.path.exists(tmp_candidate)
        )

        # Case B: recover from .bak without re-corrupting the restored target.
        user_bak = "43"
        storage.setup_user_space(user_bak)
        alerts_bak = os.path.join(tmpdir, user_bak, "alerts.json")
        bak_candidate = alerts_bak + ".bak"
        with open(alerts_bak, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        with open(bak_candidate, "w", encoding="utf-8") as f:
            json.dump({"tags": ["B"], "alerts": [], "postpone_queue": []}, f)
        recovered_bak = storage.get_all_alerts(user_bak)
        reloaded_bak = _load_json(alerts_bak)
        bak_after = _load_json(bak_candidate)
        case_bak_ok = (
            _has_required_alerts_schema(recovered_bak)
            and _has_required_alerts_schema(reloaded_bak)
            and isinstance(bak_after, dict)
            and (reloaded_bak.get("tags") or [None])[0] == "B"
        )

        # Case C: when both candidates exist, newest mtime wins.
        user_order = "44"
        storage.setup_user_space(user_order)
        alerts_order = os.path.join(tmpdir, user_order, "alerts.json")
        tmp_order = alerts_order + ".tmp"
        bak_order = alerts_order + ".bak"
        with open(alerts_order, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        with open(tmp_order, "w", encoding="utf-8") as f:
            json.dump({"tags": ["TMP"], "alerts": [], "postpone_queue": []}, f)
        with open(bak_order, "w", encoding="utf-8") as f:
            json.dump({"tags": ["BAK"], "alerts": [], "postpone_queue": []}, f)
        now_ts = datetime.now().timestamp()
        os.utime(tmp_order, (now_ts - 3600, now_ts - 3600))
        os.utime(bak_order, (now_ts, now_ts))
        recovered_order = storage.get_all_alerts(user_order)
        reloaded_order = _load_json(alerts_order)
        picked_tag = (recovered_order.get("tags") or [None])[0] if isinstance(recovered_order, dict) else None
        case_order_ok = (
            _has_required_alerts_schema(recovered_order)
            and _has_required_alerts_schema(reloaded_order)
            and picked_tag == "BAK"
        )

        ok = case_tmp_ok and case_bak_ok and case_order_ok
        print_section("storage_recovery", {
            "ok": ok,
            "cases": {
                "tmp_recovery": {"ok": case_tmp_ok},
                "bak_recovery": {"ok": case_bak_ok},
                "candidate_precedence": {"ok": case_order_ok, "picked_tag": picked_tag},
            },
        })
        if not ok:
            _log_problem("storage_recovery_failed", {
                "tmp_recovery": case_tmp_ok,
                "bak_recovery": case_bak_ok,
                "candidate_precedence": case_order_ok,
            })


async def _test_retry_logic():
    events = []

    def _fake_log(category, event, payload=None, level="INFO"):
        events.append({
            "category": category,
            "event": event,
            "level": level,
            "payload": payload or {},
        })

    tracker = ApiFailureTracker(window_seconds=120, user_threshold=2, global_threshold=3)
    attempts_counter = {
        "retryable": 0,
        "fatal": 0,
        "bad_request": 0,
        "not_modified_text": 0,
        "not_modified_non_text": 0,
    }

    async def _retryable_call():
        attempts_counter["retryable"] += 1
        if attempts_counter["retryable"] < 3:
            raise TimedOut("simulated timeout")
        return "ok"

    result = await run_with_retry(
        operation="debug_retryable",
        chat_id=111,
        call_coro_factory=_retryable_call,
        log_callback=_fake_log,
        tracker=tracker,
        attempts=3,
        max_window_seconds=4,
        base_delay_seconds=0.01,
        max_delay_seconds=0.05,
    )

    fatal_raised = False

    async def _fatal_call():
        attempts_counter["fatal"] += 1
        raise ValueError("fatal")

    try:
        await run_with_retry(
            operation="debug_fatal",
            chat_id=222,
            call_coro_factory=_fatal_call,
            log_callback=_fake_log,
            tracker=tracker,
            attempts=3,
            max_window_seconds=4,
            base_delay_seconds=0.01,
            max_delay_seconds=0.05,
        )
    except ValueError:
        fatal_raised = True

    bad_request_raised = False

    async def _bad_request_call():
        attempts_counter["bad_request"] += 1
        raise BadRequest("Wrong file identifier/HTTP URL specified")

    bad_request_before = tracker.snapshot(333)
    try:
        await run_with_retry(
            operation="debug_bad_request",
            chat_id=333,
            call_coro_factory=_bad_request_call,
            log_callback=_fake_log,
            tracker=tracker,
            attempts=3,
            max_window_seconds=4,
            base_delay_seconds=0.01,
            max_delay_seconds=0.05,
        )
    except BadRequest:
        bad_request_raised = True

    not_modified_text_raised = False

    async def _not_modified_text_call():
        attempts_counter["not_modified_text"] += 1
        raise BadRequest("Message is not modified: specified new message content")

    not_modified_text_before = tracker.snapshot(444)
    try:
        await run_with_retry(
            operation="edit_message_text",
            chat_id=444,
            call_coro_factory=_not_modified_text_call,
            log_callback=_fake_log,
            tracker=tracker,
            attempts=3,
            max_window_seconds=4,
            base_delay_seconds=0.01,
            max_delay_seconds=0.05,
        )
    except BadRequest:
        not_modified_text_raised = True

    not_modified_non_text_raised = False

    async def _not_modified_non_text_call():
        attempts_counter["not_modified_non_text"] += 1
        raise BadRequest("Message is not modified: specified new message content")

    not_modified_non_text_before = tracker.snapshot(445)
    try:
        await run_with_retry(
            operation="edit_message_caption",
            chat_id=445,
            call_coro_factory=_not_modified_non_text_call,
            log_callback=_fake_log,
            tracker=tracker,
            attempts=3,
            max_window_seconds=4,
            base_delay_seconds=0.01,
            max_delay_seconds=0.05,
        )
    except BadRequest:
        not_modified_non_text_raised = True

    bad_request_retry_events = [
        e for e in events
        if e.get("event") == "telegram_retry_scheduled"
        and (e.get("payload") or {}).get("operation") == "debug_bad_request"
    ]
    bad_request_failed_attempts = [
        e for e in events
        if e.get("event") == "telegram_call_attempt_failed"
        and (e.get("payload") or {}).get("operation") == "debug_bad_request"
    ]
    not_modified_text_retry_events = [
        e for e in events
        if e.get("event") == "telegram_retry_scheduled"
        and (e.get("payload") or {}).get("operation") == "edit_message_text"
    ]
    not_modified_text_noop_events = [
        e for e in events
        if e.get("event") == "telegram_call_attempt_noop"
        and (e.get("payload") or {}).get("operation") == "edit_message_text"
    ]
    not_modified_text_failed_events = [
        e for e in events
        if e.get("event") == "telegram_call_attempt_failed"
        and (e.get("payload") or {}).get("operation") == "edit_message_text"
    ]

    not_modified_non_text_retry_events = [
        e for e in events
        if e.get("event") == "telegram_retry_scheduled"
        and (e.get("payload") or {}).get("operation") == "edit_message_caption"
    ]
    not_modified_non_text_noop_events = [
        e for e in events
        if e.get("event") == "telegram_call_attempt_noop"
        and (e.get("payload") or {}).get("operation") == "edit_message_caption"
    ]
    not_modified_non_text_failed_events = [
        e for e in events
        if e.get("event") == "telegram_call_attempt_failed"
        and (e.get("payload") or {}).get("operation") == "edit_message_caption"
    ]

    not_modified_text_degraded_ok = (
        len(not_modified_text_noop_events) == 1
        and (not_modified_text_noop_events[0].get("payload") or {}).get("degraded", {}).get("user_failures")
        == not_modified_text_before.get("user_failures")
        and (not_modified_text_noop_events[0].get("payload") or {}).get("degraded", {}).get("global_failures")
        == not_modified_text_before.get("global_failures")
    )
    not_modified_text_reason_ok = (
        len(not_modified_text_noop_events) == 1
        and (not_modified_text_noop_events[0].get("payload") or {}).get("reason_code") == "message_not_modified"
    )
    not_modified_text_level_ok = (
        len(not_modified_text_noop_events) == 1
        and not_modified_text_noop_events[0].get("level") == "INFO"
    )
    not_modified_text_counts_toward_ok = (
        len(not_modified_text_noop_events) == 1
        and (not_modified_text_noop_events[0].get("payload") or {}).get("counts_toward_degraded") is False
    )
    not_modified_non_text_level_ok = (
        len(not_modified_non_text_failed_events) == 1
        and not_modified_non_text_failed_events[0].get("level") == "ERROR"
        and (not_modified_non_text_failed_events[0].get("payload") or {}).get("retryable") is False
    )
    bad_request_counts_toward_ok = (
        len(bad_request_failed_attempts) == 1
        and (bad_request_failed_attempts[0].get("payload") or {}).get("counts_toward_degraded") is False
    )
    bad_request_degraded_ok = (
        len(bad_request_failed_attempts) == 1
        and (bad_request_failed_attempts[0].get("payload") or {}).get("degraded", {}).get("user_failures")
        == bad_request_before.get("user_failures")
        and (bad_request_failed_attempts[0].get("payload") or {}).get("degraded", {}).get("global_failures")
        == bad_request_before.get("global_failures")
    )
    not_modified_non_text_degraded_ok = (
        len(not_modified_non_text_failed_events) == 1
        and (not_modified_non_text_failed_events[0].get("payload") or {}).get("degraded", {}).get("user_failures")
        == not_modified_non_text_before.get("user_failures")
        and (not_modified_non_text_failed_events[0].get("payload") or {}).get("degraded", {}).get("global_failures")
        == not_modified_non_text_before.get("global_failures")
    )
    not_modified_non_text_counts_toward_ok = (
        len(not_modified_non_text_failed_events) == 1
        and (not_modified_non_text_failed_events[0].get("payload") or {}).get("counts_toward_degraded") is False
    )

    ok = (
        result == "ok"
        and attempts_counter["retryable"] == 3
        and fatal_raised
        and attempts_counter["fatal"] == 1
        and bad_request_raised
        and attempts_counter["bad_request"] == 1
        and len(bad_request_retry_events) == 0
        and len(bad_request_failed_attempts) == 1
        and bad_request_failed_attempts[0].get("payload", {}).get("retryable") is False
        and bad_request_counts_toward_ok
        and bad_request_degraded_ok
        and not_modified_text_raised
        and attempts_counter["not_modified_text"] == 1
        and len(not_modified_text_retry_events) == 0
        and len(not_modified_text_failed_events) == 0
        and not_modified_text_reason_ok
        and not_modified_text_level_ok
        and not_modified_text_degraded_ok
        and not_modified_text_counts_toward_ok
        and not_modified_non_text_raised
        and attempts_counter["not_modified_non_text"] == 1
        and len(not_modified_non_text_retry_events) == 0
        and len(not_modified_non_text_noop_events) == 0
        and not_modified_non_text_level_ok
        and not_modified_non_text_degraded_ok
        and not_modified_non_text_counts_toward_ok
    )
    print_section("retry_logic", {
        "ok": ok,
        "attempts": attempts_counter,
        "events_count": len(events),
        "bad_request_retry_events": len(bad_request_retry_events),
        "bad_request_failed_attempts": len(bad_request_failed_attempts),
        "bad_request_counts_toward_ok": bad_request_counts_toward_ok,
        "bad_request_degraded_ok": bad_request_degraded_ok,
        "not_modified_text_retry_events": len(not_modified_text_retry_events),
        "not_modified_text_noop_events": len(not_modified_text_noop_events),
        "not_modified_text_failed_events": len(not_modified_text_failed_events),
        "not_modified_text_reason_ok": not_modified_text_reason_ok,
        "not_modified_text_level_ok": not_modified_text_level_ok,
        "not_modified_text_degraded_ok": not_modified_text_degraded_ok,
        "not_modified_text_counts_toward_ok": not_modified_text_counts_toward_ok,
        "not_modified_non_text_retry_events": len(not_modified_non_text_retry_events),
        "not_modified_non_text_noop_events": len(not_modified_non_text_noop_events),
        "not_modified_non_text_failed_events": len(not_modified_non_text_failed_events),
        "not_modified_non_text_level_ok": not_modified_non_text_level_ok,
        "not_modified_non_text_degraded_ok": not_modified_non_text_degraded_ok,
        "not_modified_non_text_counts_toward_ok": not_modified_non_text_counts_toward_ok,
    })
    if not ok:
        _log_problem("retry_logic_failed", {
            "result": result,
            "attempts": attempts_counter,
        })


def _test_degraded_tracker():
    tracker = ApiFailureTracker(window_seconds=600, user_threshold=2, global_threshold=3)
    s1 = tracker.record_failure(10)
    s2 = tracker.record_failure(10)
    s3 = tracker.record_failure(11)

    ok = (
        s1["user_degraded"] is False
        and s2["user_degraded"] is True
        and s2["user_transition"] == "on"
        and s3["global_degraded"] is True
        and s3["global_transition"] == "on"
    )
    print_section("degraded_tracker", {
        "ok": ok,
        "snapshots": [s1, s2, s3],
    })
    if not ok:
        _log_problem("degraded_tracker_failed", {"snapshots": [s1, s2, s3]})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        if IMPORT_ERROR is not None:
            dbg.run_meta({"project_root": ROOT_DIR})
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        logging.basicConfig(level=logging.CRITICAL)
        dbg.run_meta({
            "project_root": ROOT_DIR,
            "storage_fsync_enabled": C.STORAGE_ENABLE_FSYNC,
            "storage_auto_recover": C.STORAGE_AUTO_RECOVER_CORRUPTED_JSON,
            "retry_attempts": C.TELEGRAM_RETRY_ATTEMPTS,
            "retry_max_window_seconds": C.TELEGRAM_RETRY_MAX_WINDOW_SECONDS,
        })
        _test_storage_recovery()
        asyncio.run(_test_retry_logic())
        _test_degraded_tracker()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    storage_ok = not dbg.has_problem("storage_recovery_failed")
    retry_ok = not dbg.has_problem("retry_logic_failed")
    tracker_ok = not dbg.has_problem("degraded_tracker_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"storage: {'OK' if storage_ok else 'FAIL'}",
        f"retry: {'OK' if retry_ok else 'FAIL'}",
        f"degraded: {'OK' if tracker_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
