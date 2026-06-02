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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "startup_scope_sanity_debug"
FEATURE_TITLE = "Startup Scope Sanity Telemetry"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _DummyStorage:
    def __init__(self, *, admin_id, dataset_users, authorized_users, raise_scan=False):
        self.admin_id = admin_id
        self._dataset_users = list(dataset_users or [])
        self._authorized_users = list(authorized_users or [])
        self._raise_scan = raise_scan

    def get_all_dataset_users(self, raise_on_error=False):
        if self._raise_scan and raise_on_error:
            raise RuntimeError("dataset_scan_failed")
        return list(self._dataset_users)

    def get_all_users(self):
        return list(self._authorized_users)


def _run_case(mainbot, *, admin_id, dataset_users, authorized_users, threshold, sample_size, raise_scan=False):
    events = []
    original_storage = mainbot.storage
    original_log_system = mainbot.log_system
    original_threshold = getattr(mainbot.C, "STARTUP_SCOPE_WARNING_EXCLUDED_USERS", 5)
    original_sample_size = getattr(mainbot.C, "STARTUP_SCOPE_EXCLUDED_SAMPLE_SIZE", 5)

    def _fake_log(category, event, payload=None, level="INFO"):
        events.append({
            "category": category,
            "event": event,
            "payload": payload or {},
            "level": level,
        })

    try:
        mainbot.storage = _DummyStorage(
            admin_id=admin_id,
            dataset_users=dataset_users,
            authorized_users=authorized_users,
            raise_scan=raise_scan,
        )
        mainbot.log_system = _fake_log
        mainbot.C.STARTUP_SCOPE_WARNING_EXCLUDED_USERS = int(threshold)
        mainbot.C.STARTUP_SCOPE_EXCLUDED_SAMPLE_SIZE = int(sample_size)
        result = mainbot._log_startup_user_scope_telemetry(
            authorized_users=list(authorized_users) if authorized_users is not None else None
        )
        return {"events": events, "result": result}
    finally:
        mainbot.storage = original_storage
        mainbot.log_system = original_log_system
        mainbot.C.STARTUP_SCOPE_WARNING_EXCLUDED_USERS = original_threshold
        mainbot.C.STARTUP_SCOPE_EXCLUDED_SAMPLE_SIZE = original_sample_size


def _event_rows(case, event):
    return [row for row in (case.get("events") or []) if row.get("event") == event]


def _test_high_excluded_warning(dbg, mainbot):
    case = _run_case(
        mainbot,
        admin_id="1",
        dataset_users=["100", "101", "102", "103", "104", "105"],
        authorized_users=["100"],
        threshold=3,
        sample_size=2,
    )
    snapshot = _event_rows(case, "startup_scope_snapshot")
    warning = _event_rows(case, "startup_scope_warning")
    payload = snapshot[0]["payload"] if snapshot else {}
    checks = {
        "snapshot_logged": len(snapshot) == 1,
        "warning_logged": len(warning) == 1,
        "auth_filter_enabled": payload.get("auth_filter_enabled") is True,
        "excluded_count_expected": payload.get("excluded_users") == 5,
        "sample_capped": len(payload.get("excluded_user_ids_sample") or []) == 2,
        "suppressed_reason_none": payload.get("warning_suppressed_reason") is None,
    }
    dbg.section("high_excluded_warning", {"checks": checks, "case": case})
    if not all(checks.values()):
        dbg.problem("startup_scope_high_excluded_failed", {"checks": checks, "case": case})


def _test_low_excluded_no_warning(dbg, mainbot):
    case = _run_case(
        mainbot,
        admin_id="1",
        dataset_users=["100", "101", "102"],
        authorized_users=["100", "101"],
        threshold=3,
        sample_size=4,
    )
    snapshot = _event_rows(case, "startup_scope_snapshot")
    warning = _event_rows(case, "startup_scope_warning")
    payload = snapshot[0]["payload"] if snapshot else {}
    checks = {
        "snapshot_logged": len(snapshot) == 1,
        "warning_not_logged": len(warning) == 0,
        "excluded_count_expected": payload.get("excluded_users") == 1,
        "suppressed_reason_below_threshold": payload.get("warning_suppressed_reason") == "below_threshold",
    }
    dbg.section("low_excluded_no_warning", {"checks": checks, "case": case})
    if not all(checks.values()):
        dbg.problem("startup_scope_low_excluded_failed", {"checks": checks, "case": case})


def _test_no_excluded_no_warning(dbg, mainbot):
    case = _run_case(
        mainbot,
        admin_id="1",
        dataset_users=["100", "101"],
        authorized_users=["100", "101"],
        threshold=0,
        sample_size=2,
    )
    snapshot = _event_rows(case, "startup_scope_snapshot")
    warning = _event_rows(case, "startup_scope_warning")
    payload = snapshot[0]["payload"] if snapshot else {}
    checks = {
        "snapshot_logged": len(snapshot) == 1,
        "warning_not_logged": len(warning) == 0,
        "excluded_count_expected": payload.get("excluded_users") == 0,
        "suppressed_reason_no_excluded": payload.get("warning_suppressed_reason") == "no_excluded_users",
    }
    dbg.section("no_excluded_no_warning", {"checks": checks, "case": case})
    if not all(checks.values()):
        dbg.problem("startup_scope_no_excluded_failed", {"checks": checks, "case": case})


def _test_filter_disabled(dbg, mainbot):
    case = _run_case(
        mainbot,
        admin_id=None,
        dataset_users=["100", "101", "102", "103"],
        authorized_users=["100"],
        threshold=1,
        sample_size=2,
    )
    snapshot = _event_rows(case, "startup_scope_snapshot")
    warning = _event_rows(case, "startup_scope_warning")
    payload = snapshot[0]["payload"] if snapshot else {}
    checks = {
        "snapshot_logged": len(snapshot) == 1,
        "warning_not_logged": len(warning) == 0,
        "auth_filter_disabled": payload.get("auth_filter_enabled") is False,
        "suppressed_reason_auth_disabled": payload.get("warning_suppressed_reason") == "auth_filter_disabled",
    }
    dbg.section("filter_disabled", {"checks": checks, "case": case})
    if not all(checks.values()):
        dbg.problem("startup_scope_filter_disabled_failed", {"checks": checks, "case": case})


def _test_scan_failure(dbg, mainbot):
    case = _run_case(
        mainbot,
        admin_id="1",
        dataset_users=[],
        authorized_users=[],
        threshold=1,
        sample_size=2,
        raise_scan=True,
    )
    failed = _event_rows(case, "startup_scope_snapshot_failed")
    checks = {
        "failure_event_logged": len(failed) == 1,
        "failure_is_warning": failed[0]["level"] == "WARNING" if failed else False,
        "result_none": case.get("result") is None,
    }
    dbg.section("scan_failure", {"checks": checks, "case": case})
    if not all(checks.values()):
        dbg.problem("startup_scope_scan_failure_failed", {"checks": checks, "case": case})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            import mainbot
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_high_excluded_warning(dbg, mainbot)
        _test_low_excluded_no_warning(dbg, mainbot)
        _test_no_excluded_no_warning(dbg, mainbot)
        _test_filter_disabled(dbg, mainbot)
        _test_scan_failure(dbg, mainbot)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    high_ok = not dbg.has_problem("startup_scope_high_excluded_failed")
    low_ok = not dbg.has_problem("startup_scope_low_excluded_failed")
    no_excluded_ok = not dbg.has_problem("startup_scope_no_excluded_failed")
    disabled_ok = not dbg.has_problem("startup_scope_filter_disabled_failed")
    scan_ok = not dbg.has_problem("startup_scope_scan_failure_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"high_excluded: {'OK' if high_ok else 'FAIL'}",
        f"low_excluded: {'OK' if low_ok else 'FAIL'}",
        f"no_excluded: {'OK' if no_excluded_ok else 'FAIL'}",
        f"filter_disabled: {'OK' if disabled_ok else 'FAIL'}",
        f"scan_failure: {'OK' if scan_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
