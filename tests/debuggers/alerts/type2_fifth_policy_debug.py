#!/usr/bin/env python3
import os
import sys
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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "type2_fifth_policy_debug"
FEATURE_TITLE = "Type 2 Fifth Ordinal Policy"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _make_alert(ordinals, weekdays, fifth_policy=None, interval=1):
    schedule = {
        "ordinals": ordinals,
        "weekdays": weekdays,
        "time": "10:00",
        "interval": interval,
    }
    if fifth_policy is not None:
        schedule["fifth_policy"] = fifth_policy
    return {
        "type": 2,
        "type_name": "Monthly (Relative)",
        "title": "Test Alert",
        "schedule": schedule,
        "active": True,
        "pre_alerts": [],
    }


def _test_last_ordinal_boundaries(dbg, get_next_occurrence):
    alert = _make_alert(["Last"], ["Fri"])
    alert["schedule"]["time"] = "23:00"

    before_ref = datetime(2026, 3, 27, 22, 58, 0)
    just_after_ref = datetime(2026, 3, 27, 23, 0, 1)
    may_ref = datetime(2026, 5, 1, 0, 0, 0)

    before_result = get_next_occurrence(alert, before_ref)
    just_after_result = get_next_occurrence(alert, just_after_ref)
    may_result = get_next_occurrence(alert, may_ref)

    checks = {
        "before_result_not_none": before_result is not None,
        "before_same_day_fire": bool(
            before_result
            and before_result == datetime(2026, 3, 27, 23, 0, 0)
        ),
        "after_result_not_none": just_after_result is not None,
        "after_rolls_to_april_last_friday": bool(
            just_after_result
            and just_after_result == datetime(2026, 4, 24, 23, 0, 0)
        ),
        "may_result_not_none": may_result is not None,
        "may_is_last_friday_not_first_day": bool(
            may_result
            and may_result == datetime(2026, 5, 29, 23, 0, 0)
            and may_result.day != 1
        ),
    }

    dbg.section("last_ordinal_boundaries", {
        "checks": checks,
        "before_ref": before_ref.isoformat(),
        "before_result": before_result.isoformat() if before_result else None,
        "just_after_ref": just_after_ref.isoformat(),
        "just_after_result": just_after_result.isoformat() if just_after_result else None,
        "may_ref": may_ref.isoformat(),
        "may_result": may_result.isoformat() if may_result else None,
    })

    if not all(checks.values()):
        dbg.problem("last_ordinal_boundaries_failed", {
            "checks": checks,
            "before_result": before_result.isoformat() if before_result else None,
            "just_after_result": just_after_result.isoformat() if just_after_result else None,
            "may_result": may_result.isoformat() if may_result else None,
        })


def _test_skip_policy(dbg, get_next_occurrence):
    alert = _make_alert(["5th"], ["Mon"], fifth_policy="skip")
    ref = datetime(2026, 2, 1, 0, 0, 0)
    result = get_next_occurrence(alert, ref)
    checks = {"result_not_none": result is not None}
    if result is not None:
        checks["skipped_february"] = result.month != 2
        checks["landed_in_march"] = result.month == 3 and result.year == 2026
        checks["is_monday"] = result.weekday() == 0
        checks["day_is_30"] = result.day == 30
    dbg.section("skip_policy", {"result": result.isoformat() if result else None, "checks": checks})
    if not all(checks.values()):
        dbg.problem("fifth_skip_failed", {"checks": checks, "result": result.isoformat() if result else None})


def _test_fallback_4th_policy(dbg, get_next_occurrence):
    alert = _make_alert(["5th"], ["Mon"], fifth_policy="fallback_4th")
    ref = datetime(2026, 2, 1, 0, 0, 0)
    result = get_next_occurrence(alert, ref)
    checks = {"result_not_none": result is not None}
    if result is not None:
        checks["landed_in_february"] = result.month == 2 and result.year == 2026
        checks["is_monday"] = result.weekday() == 0
        checks["day_is_23"] = result.day == 23
    dbg.section("fallback_4th_policy", {"result": result.isoformat() if result else None, "checks": checks})
    if not all(checks.values()):
        dbg.problem("fifth_fallback_failed", {"checks": checks, "result": result.isoformat() if result else None})


def _test_default_policy(dbg, get_next_occurrence):
    alert = _make_alert(["5th"], ["Mon"])  # no fifth_policy key
    ref = datetime(2026, 2, 1, 0, 0, 0)
    result = get_next_occurrence(alert, ref)
    checks = {"result_not_none": result is not None}
    if result is not None:
        checks["skipped_february"] = result.month != 2
        checks["landed_in_march"] = result.month == 3 and result.year == 2026
    dbg.section("default_policy", {"result": result.isoformat() if result else None, "checks": checks})
    if not all(checks.values()):
        dbg.problem("fifth_default_failed", {"checks": checks, "result": result.isoformat() if result else None})


def _test_no_fifth_no_policy(dbg, get_next_occurrence):
    alert = _make_alert(["1st", "3rd"], ["Mon"])
    ref = datetime(2026, 2, 1, 0, 0, 0)
    result = get_next_occurrence(alert, ref)
    checks = {"result_not_none": result is not None}
    if result is not None:
        checks["landed_in_february"] = result.month == 2
        checks["is_monday"] = result.weekday() == 0
        checks["day_is_2"] = result.day == 2
    dbg.section("no_fifth_no_policy", {"result": result.isoformat() if result else None, "checks": checks})
    if not all(checks.values()):
        dbg.problem("no_fifth_policy_failed", {
            "checks": checks,
            "result": result.isoformat() if result else None,
        })


def _test_mixed_ordinals_fallback(dbg, get_next_occurrence):
    alert = _make_alert(["3rd", "5th"], ["Mon"], fifth_policy="fallback_4th")
    ref = datetime(2026, 2, 1, 0, 0, 0)
    result = get_next_occurrence(alert, ref)
    checks = {"result_not_none": result is not None}
    if result is not None:
        checks["first_is_3rd_monday"] = result.day == 16 and result.month == 2
    dbg.section("mixed_ordinals_fallback", {"result": result.isoformat() if result else None, "checks": checks})
    if not all(checks.values()):
        dbg.problem("fifth_fallback_failed", {"checks": checks, "result": result.isoformat() if result else None})


def _test_summary_display(dbg, format_alert_summary):
    alert_skip = _make_alert(["5th"], ["Mon"], fifth_policy="skip")
    alert_fallback = _make_alert(["5th"], ["Mon"], fifth_policy="fallback_4th")
    alert_no_fifth = _make_alert(["1st"], ["Mon"])

    summary_skip = format_alert_summary(alert_skip)
    summary_fallback = format_alert_summary(alert_fallback)
    summary_no_fifth = format_alert_summary(alert_no_fifth)

    checks = {
        "skip_shown": "Skip that month" in summary_skip,
        "fallback_shown": "Alert on the 4th instead" in summary_fallback,
        "no_fifth_hidden": "5th day policy" not in summary_no_fifth,
    }
    dbg.section("summary_display", {
        "summary_skip_excerpt": summary_skip[:300],
        "summary_fallback_excerpt": summary_fallback[:300],
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("fifth_summary_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        suppress_ptb_user_warning()

        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR, "reference_month": "2026-02"})

        try:
            from modules.handlers.add_flow.summary_flow import format_alert_summary
            from modules.scheduler_mathlogic import get_next_occurrence
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_skip_policy(dbg, get_next_occurrence)
        _test_fallback_4th_policy(dbg, get_next_occurrence)
        _test_default_policy(dbg, get_next_occurrence)
        _test_no_fifth_no_policy(dbg, get_next_occurrence)
        _test_mixed_ordinals_fallback(dbg, get_next_occurrence)
        _test_last_ordinal_boundaries(dbg, get_next_occurrence)
        _test_summary_display(dbg, format_alert_summary)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    skip_ok = not dbg.has_problem("fifth_skip_failed")
    fallback_ok = not dbg.has_problem("fifth_fallback_failed")
    default_ok = not dbg.has_problem("fifth_default_failed")
    no_fifth_ok = not dbg.has_problem("no_fifth_policy_failed")
    last_ok = not dbg.has_problem("last_ordinal_boundaries_failed")
    summary_ok = not dbg.has_problem("fifth_summary_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"skip_policy: {'OK' if skip_ok else 'FAIL'}",
        f"fallback_4th: {'OK' if fallback_ok else 'FAIL'}",
        f"default_policy: {'OK' if default_ok else 'FAIL'}",
        f"no_fifth_path: {'OK' if no_fifth_ok else 'FAIL'}",
        f"last_ordinal: {'OK' if last_ok else 'FAIL'}",
        f"summary_display: {'OK' if summary_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
