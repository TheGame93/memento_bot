#!/usr/bin/env python3
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
from _lib.runtime import run_async

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "error_handler_debug"
FEATURE_TITLE = "Error Handler Classification"


def _run_async_check(coro):
    return run_async(coro)


def _test_polling_network_error_rate_limited(dbg, NetworkError, TimedOut, RetryAfter):
    logged = []
    state = {
        "window_start_mono": None,
        "window_start_ts": None,
        "error_count": 0,
        "immediate_warning_count": 0,
        "rollup_count": 0,
        "last_rollup_mono": None,
        "last_error_mono": None,
        "last_error_ts": None,
        "last_error_type": None,
    }
    window_seconds = 60
    immediate_cap = 2
    rollup_min_interval = 10
    recovery_quiet_seconds = 30

    def fake_log_system(category, event, payload=None, level="INFO"):
        logged.append({"category": category, "event": event, "level": level, "payload": payload or {}})

    def _reset(now_mono=None, now_ts=None):
        state["window_start_mono"] = now_mono
        state["window_start_ts"] = now_ts
        state["error_count"] = 0
        state["immediate_warning_count"] = 0
        state["rollup_count"] = 0
        state["last_rollup_mono"] = None
        state["last_error_mono"] = None
        state["last_error_ts"] = None
        state["last_error_type"] = None

    def _emit_rollup(now_mono, force=False):
        if state["window_start_mono"] is None:
            return False
        suppressed_total = max(0, state["error_count"] - state["immediate_warning_count"])
        if suppressed_total <= 0:
            return False
        if not force and state["last_rollup_mono"] is not None:
            if (now_mono - state["last_rollup_mono"]) < rollup_min_interval:
                return False
        fake_log_system("api", "polling_network_error_rollup", {
            "window_error_count": state["error_count"],
            "window_immediate_warning_count": state["immediate_warning_count"],
            "suppressed_total": suppressed_total,
            "rollup_index": state["rollup_count"] + 1,
            "window_start_ts": state["window_start_ts"],
            "last_error_ts": state["last_error_ts"],
            "last_error_type": state["last_error_type"],
        }, level="WARNING")
        state["last_rollup_mono"] = now_mono
        state["rollup_count"] += 1
        return True

    def _emit_recovery(quiet_seconds):
        if state["window_start_mono"] is None or state["error_count"] <= 0:
            return
        fake_log_system("api", "polling_network_recovered", {
            "quiet_seconds": int(quiet_seconds),
            "burst_error_count": state["error_count"],
            "burst_immediate_warning_count": state["immediate_warning_count"],
            "burst_rollup_count": state["rollup_count"],
            "window_start_ts": state["window_start_ts"],
            "last_error_ts": state["last_error_ts"],
            "last_error_type": state["last_error_type"],
        }, level="INFO")

    async def error_handler_under_test(update, err, now_mono):
        if update is None and isinstance(err, (NetworkError, TimedOut, RetryAfter)):
            now_ts = f"t={now_mono}"

            if state["window_start_mono"] is not None and state["last_error_mono"] is not None:
                quiet_seconds = now_mono - state["last_error_mono"]
                if quiet_seconds >= recovery_quiet_seconds:
                    _emit_rollup(now_mono, force=True)
                    _emit_recovery(quiet_seconds)
                    _reset()

            if state["window_start_mono"] is not None:
                if (now_mono - state["window_start_mono"]) >= window_seconds:
                    _emit_rollup(now_mono, force=True)
                    _reset()

            if state["window_start_mono"] is None:
                _reset(now_mono=now_mono, now_ts=now_ts)

            state["error_count"] += 1
            state["last_error_mono"] = now_mono
            state["last_error_ts"] = now_ts
            state["last_error_type"] = err.__class__.__name__

            if state["immediate_warning_count"] < immediate_cap:
                state["immediate_warning_count"] += 1
                fake_log_system("api", "polling_network_error", {
                    "error": str(err),
                    "type": err.__class__.__name__,
                    "window_error_count": state["error_count"],
                    "immediate_warning_index": state["immediate_warning_count"],
                    "immediate_warning_cap": immediate_cap,
                }, level="WARNING")
            else:
                _emit_rollup(now_mono, force=False)
            return

        fake_log_system("errors", "unhandled_exception", {
            "error": str(err),
            "type": err.__class__.__name__,
        }, level="ERROR")

    _run_async_check(error_handler_under_test(None, NetworkError("DNS failure"), 0))
    _run_async_check(error_handler_under_test(None, TimedOut("timeout"), 1))
    _run_async_check(error_handler_under_test(None, RetryAfter(30), 2))
    _run_async_check(error_handler_under_test(None, NetworkError("DNS failure"), 3))
    _run_async_check(error_handler_under_test(None, NetworkError("DNS failure"), 12))

    immediate = [row for row in logged if row["event"] == "polling_network_error"]
    rollups = [row for row in logged if row["event"] == "polling_network_error_rollup"]
    checks = {
        "immediate_capped": len(immediate) == immediate_cap,
        "rollup_emitted": len(rollups) >= 1,
        "immediate_api_warning": all(
            row["category"] == "api" and row["level"] == "WARNING" for row in immediate
        ),
        "rollup_api_warning": all(
            row["category"] == "api" and row["level"] == "WARNING" for row in rollups
        ),
    }
    dbg.section("polling_network_rate_limited", {"logged": logged, "checks": checks})
    if not all(checks.values()):
        dbg.problem("polling_rate_limit_failed", {"checks": checks, "logged": logged})


def _test_polling_recovery_event(dbg, NetworkError, TimedOut, RetryAfter):
    logged = []
    state = {
        "window_start_mono": None,
        "window_start_ts": None,
        "error_count": 0,
        "immediate_warning_count": 0,
        "rollup_count": 0,
        "last_rollup_mono": None,
        "last_error_mono": None,
        "last_error_ts": None,
        "last_error_type": None,
    }
    recovery_quiet_seconds = 30
    immediate_cap = 2

    def fake_log_system(category, event, payload=None, level="INFO"):
        logged.append({"category": category, "event": event, "level": level, "payload": payload or {}})

    def _reset(now_mono=None):
        state["window_start_mono"] = now_mono
        state["window_start_ts"] = f"t={now_mono}" if now_mono is not None else None
        state["error_count"] = 0
        state["immediate_warning_count"] = 0
        state["rollup_count"] = 0
        state["last_rollup_mono"] = None
        state["last_error_mono"] = None
        state["last_error_ts"] = None
        state["last_error_type"] = None

    def _emit_recovery(quiet_seconds):
        fake_log_system("api", "polling_network_recovered", {
            "quiet_seconds": int(quiet_seconds),
            "burst_error_count": state["error_count"],
            "burst_immediate_warning_count": state["immediate_warning_count"],
        }, level="INFO")

    async def error_handler_under_test(update, err, now_mono):
        if update is None and isinstance(err, (NetworkError, TimedOut, RetryAfter)):
            if state["window_start_mono"] is not None and state["last_error_mono"] is not None:
                quiet_seconds = now_mono - state["last_error_mono"]
                if quiet_seconds >= recovery_quiet_seconds:
                    _emit_recovery(quiet_seconds)
                    _reset()
            if state["window_start_mono"] is None:
                _reset(now_mono)

            state["error_count"] += 1
            state["last_error_mono"] = now_mono
            state["last_error_ts"] = f"t={now_mono}"
            state["last_error_type"] = err.__class__.__name__

            if state["immediate_warning_count"] < immediate_cap:
                state["immediate_warning_count"] += 1
                fake_log_system("api", "polling_network_error", {
                    "type": err.__class__.__name__,
                    "window_error_count": state["error_count"],
                    "immediate_warning_index": state["immediate_warning_count"],
                }, level="WARNING")
            return

        fake_log_system("errors", "unhandled_exception", {
            "error": str(err),
            "type": err.__class__.__name__,
        }, level="ERROR")

    _run_async_check(error_handler_under_test(None, NetworkError("DNS failure"), 0))
    _run_async_check(error_handler_under_test(None, TimedOut("timeout"), 1))
    _run_async_check(error_handler_under_test(None, RetryAfter(30), 2))
    _run_async_check(error_handler_under_test(None, NetworkError("DNS failure"), 40))

    recovery = [row for row in logged if row["event"] == "polling_network_recovered"]
    checks = {
        "recovery_emitted": len(recovery) == 1,
        "recovery_is_info": recovery[0]["level"] == "INFO" if recovery else False,
        "recovery_burst_count": recovery[0]["payload"].get("burst_error_count") == 3 if recovery else False,
        "recovery_quiet_seconds": recovery[0]["payload"].get("quiet_seconds") == 38 if recovery else False,
    }
    dbg.section("polling_network_recovery", {"logged": logged, "checks": checks})
    if not all(checks.values()):
        dbg.problem("polling_recovery_failed", {"checks": checks, "logged": logged})


def _test_polling_recovery_success_path(dbg):
    logged = []
    state = {
        "window_start_mono": None,
        "window_start_ts": None,
        "error_count": 0,
        "immediate_warning_count": 0,
        "rollup_count": 0,
        "last_rollup_mono": None,
        "last_error_mono": None,
        "last_error_ts": None,
        "last_error_type": None,
    }
    recovery_quiet_seconds = 30
    immediate_cap = 1
    no_prior_success_recovery = True

    def _log(event, payload=None, level="INFO"):
        logged.append({"event": event, "level": level, "payload": payload or {}})

    def _reset(now_mono=None):
        state["window_start_mono"] = now_mono
        state["window_start_ts"] = f"t={now_mono}" if now_mono is not None else None
        state["error_count"] = 0
        state["immediate_warning_count"] = 0
        state["rollup_count"] = 0
        state["last_rollup_mono"] = None
        state["last_error_mono"] = None
        state["last_error_ts"] = None
        state["last_error_type"] = None

    def _emit_recovery(now_mono, quiet_seconds, recovery_source, operation):
        burst_seconds = max(0, int(state["last_error_mono"] - state["window_start_mono"]))
        _log("polling_network_recovered", {
            "quiet_seconds": int(quiet_seconds),
            "window_start_ts": state["window_start_ts"],
            "last_error_ts": state["last_error_ts"],
            "burst_error_count": int(state["error_count"]),
            "burst_immediate_warning_count": int(state["immediate_warning_count"]),
            "burst_rollup_count": int(state["rollup_count"]),
            "burst_duration_seconds": burst_seconds,
            "last_error_type": state["last_error_type"],
            "recovery_source": recovery_source,
            "operation": operation,
        }, level="INFO")

    def _handle_polling_error(now_mono, error_type="NetworkError"):
        if state["window_start_mono"] is None:
            _reset(now_mono)
        state["error_count"] += 1
        state["last_error_mono"] = now_mono
        state["last_error_ts"] = f"t={now_mono}"
        state["last_error_type"] = error_type
        if state["immediate_warning_count"] < immediate_cap:
            state["immediate_warning_count"] += 1
            _log("polling_network_error", {
                "window_error_count": state["error_count"],
                "immediate_warning_index": state["immediate_warning_count"],
            }, level="WARNING")

    def _success_close(now_mono, operation):
        if state["window_start_mono"] is None or state["error_count"] <= 0:
            return False
        if state["last_error_mono"] is None:
            return False
        quiet_seconds = now_mono - state["last_error_mono"]
        if quiet_seconds < recovery_quiet_seconds:
            return False
        _emit_recovery(now_mono, quiet_seconds, "api_success", operation)
        _reset()
        return True

    if _success_close(5, "send_message"):
        no_prior_success_recovery = False
    _handle_polling_error(0, "NetworkError")
    _handle_polling_error(1, "TimedOut")
    _success_close(10, "send_message")
    _success_close(40, "send_message")
    _success_close(41, "send_message")

    recovery = [row for row in logged if row["event"] == "polling_network_recovered"]
    checks = {
        "no_recovery_without_prior_errors": no_prior_success_recovery,
        "single_recovery_for_burst": len(recovery) == 1,
        "recovery_is_info": recovery[0]["level"] == "INFO" if recovery else False,
        "source_is_api_success": recovery[0]["payload"].get("recovery_source") == "api_success" if recovery else False,
        "operation_present": recovery[0]["payload"].get("operation") == "send_message" if recovery else False,
        "quiet_seconds_expected": recovery[0]["payload"].get("quiet_seconds") == 39 if recovery else False,
        "burst_error_count_expected": recovery[0]["payload"].get("burst_error_count") == 2 if recovery else False,
    }
    dbg.section("polling_network_recovery_success_path", {"logged": logged, "checks": checks})
    if not all(checks.values()):
        dbg.problem("polling_recovery_success_path_failed", {"checks": checks, "logged": logged})


def _test_handler_network_error(dbg, NetworkError, TimedOut, RetryAfter):
    logged = []

    def fake_log_system(category, event, payload=None, level="INFO"):
        logged.append({"category": category, "event": event, "level": level})

    async def error_handler_under_test(update, err):
        if update is None and isinstance(err, (NetworkError, TimedOut, RetryAfter)):
            fake_log_system("api", "polling_network_error", {
                "error": str(err),
                "type": err.__class__.__name__,
            }, level="WARNING")
            return
        fake_log_system("errors", "unhandled_exception", {
            "error": str(err),
            "type": err.__class__.__name__,
        }, level="ERROR")

    fake_update = object()
    logged.clear()
    _run_async_check(error_handler_under_test(fake_update, NetworkError("send failed")))
    checks = {
        "logged_once": len(logged) == 1,
        "category_is_errors": logged[0]["category"] == "errors" if logged else False,
        "event_is_unhandled": logged[0]["event"] == "unhandled_exception" if logged else False,
        "level_is_error": logged[0]["level"] == "ERROR" if logged else False,
    }
    dbg.section("handler_network_error", {"logged": logged, "checks": checks})
    if not all(checks.values()):
        dbg.problem("handler_classification_failed", {"checks": checks})


def _test_non_network_error(dbg, NetworkError, TimedOut, RetryAfter):
    logged = []

    def fake_log_system(category, event, payload=None, level="INFO"):
        logged.append({"category": category, "event": event, "level": level})

    async def error_handler_under_test(update, err):
        if update is None and isinstance(err, (NetworkError, TimedOut, RetryAfter)):
            fake_log_system("api", "polling_network_error", {
                "error": str(err),
                "type": err.__class__.__name__,
            }, level="WARNING")
            return
        fake_log_system("errors", "unhandled_exception", {
            "error": str(err),
            "type": err.__class__.__name__,
        }, level="ERROR")

    logged.clear()
    _run_async_check(error_handler_under_test(None, ValueError("something broke")))
    checks = {
        "logged_once": len(logged) == 1,
        "category_is_errors": logged[0]["category"] == "errors" if logged else False,
        "event_is_unhandled": logged[0]["event"] == "unhandled_exception" if logged else False,
    }
    dbg.section("non_network_error", {"logged": logged, "checks": checks})
    if not all(checks.values()):
        dbg.problem("non_network_classification_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        try:
            from telegram.error import NetworkError, TimedOut, RetryAfter
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return
        _test_polling_network_error_rate_limited(dbg, NetworkError, TimedOut, RetryAfter)
        _test_polling_recovery_event(dbg, NetworkError, TimedOut, RetryAfter)
        _test_polling_recovery_success_path(dbg)
        _test_handler_network_error(dbg, NetworkError, TimedOut, RetryAfter)
        _test_non_network_error(dbg, NetworkError, TimedOut, RetryAfter)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    polling_ok = not dbg.has_problem("polling_rate_limit_failed")
    recovery_ok = not dbg.has_problem("polling_recovery_failed")
    recovery_success_ok = not dbg.has_problem("polling_recovery_success_path_failed")
    handler_ok = not dbg.has_problem("handler_classification_failed")
    nonnet_ok = not dbg.has_problem("non_network_classification_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"polling-rate-limit: {'OK' if polling_ok else 'FAIL'}",
        f"polling-recovery: {'OK' if recovery_ok else 'FAIL'}",
        f"polling-recovery-success: {'OK' if recovery_success_ok else 'FAIL'}",
        f"handler-network: {'OK' if handler_ok else 'FAIL'}",
        f"non-network: {'OK' if nonnet_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
