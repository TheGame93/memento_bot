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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "one_time_date_input_debug"
FEATURE_TITLE = "One-Time Date Input"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.timezone_utils import normalize_one_time_date, parse_user_datetime_expression
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        ref = datetime(2026, 3, 2, 9, 0, 0)
        status, normalized, assumed, reason = normalize_one_time_date(
            "05/03",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "future_ok": status == "ok",
            "future_normalized": normalized == "05/03/2026",
            "future_assumed": assumed is True,
        }
        dbg.section("future_no_year", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_future_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "02/03",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "needs_year": status == "needs_year",
            "normalized_none": normalized is None,
            "assumed_false": assumed is False,
        }
        dbg.section("today_requires_year", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_today_requires_year_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "02/03",
            reference_server_dt=ref,
            require_year_if_today=False,
            time_str="08:00",
        )
        checks = {
            "today_ok": status == "ok",
            "today_rolls_next_year": normalized == "02/03/2027",
            "today_assumed": assumed is True,
        }
        dbg.section("today_rolls_next_year", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_today_roll_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "29/02",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "leap_ok": status == "ok",
            "leap_normalized": normalized == "29/02/2028",
            "leap_assumed": assumed is True,
        }
        dbg.section("leap_year", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_leap_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "01/04/2026",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "full_ok": status == "ok",
            "full_normalized": normalized == "01/04/2026",
            "full_assumed_false": assumed is False,
        }
        dbg.section("full_date", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_full_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "11/03/26",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "short_ok": status == "ok",
            "short_normalized": normalized == "11/03/2026",
            "short_assumed_true": assumed is True,
            "short_reason_two_digit": reason == "two_digit_year",
        }
        dbg.section("two_digit_year_valid", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_two_digit_valid_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "31/11/26",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "short_invalid_rejected": status == "invalid",
            "short_invalid_normalized_none": normalized is None,
        }
        dbg.section("two_digit_year_invalid_date", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_two_digit_invalid_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "02/03/26",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "today_with_year_ok": status == "ok",
            "today_with_year_normalized": normalized == "02/03/2026",
            "today_with_year_assumed_true": assumed is True,
            "today_with_year_reason_two_digit": reason == "two_digit_year",
        }
        dbg.section("today_with_two_digit_year", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_today_with_two_digit_failed", {"checks": checks})

        status, normalized, assumed, reason = normalize_one_time_date(
            "31/04",
            reference_server_dt=ref,
            require_year_if_today=True,
            time_str="10:00",
        )
        checks = {
            "invalid_rejected": status == "invalid",
            "invalid_normalized_none": normalized is None,
        }
        dbg.section("invalid_date", {
            "status": status,
            "normalized": normalized,
            "assumed": assumed,
            "reason": reason,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("one_time_invalid_failed", {"checks": checks})

        expr_ref = datetime(2026, 3, 2, 9, 0, 0)
        expression_cases = [
            ("30m", datetime(2026, 3, 2, 9, 30, 0), "relative_token", None),
            ("2h", datetime(2026, 3, 2, 11, 0, 0), "relative_token", None),
            ("1d", datetime(2026, 3, 3, 9, 0, 0), "relative_token", None),
            ("1w", datetime(2026, 3, 9, 9, 0, 0), "relative_token", None),
            ("1mo", datetime(2026, 4, 2, 9, 0, 0), "relative_token", None),
            ("today", datetime(2026, 3, 2, 10, 15, 0), "natural_keyword", None),
            ("tomorrow at 7", datetime(2026, 3, 3, 7, 0, 0), "natural_keyword", None),
            ("yesterday 23:59", datetime(2026, 3, 1, 23, 59, 0), "natural_keyword", None),
            ("5/3", datetime(2026, 3, 5, 10, 15, 0), "absolute_date", "missing_year"),
            ("1/2", datetime(2027, 2, 1, 10, 15, 0), "absolute_date", "missing_year"),
            ("5/3/26 at 14:05", datetime(2026, 3, 5, 14, 5, 0), "absolute_date", "two_digit_year"),
            ("5/3/2026 14", datetime(2026, 3, 5, 14, 0, 0), "absolute_date", None),
        ]
        for idx, (raw_expr, expected_dt, expected_kind, expected_assumption_kind) in enumerate(expression_cases):
            status, candidate, meta = parse_user_datetime_expression(
                raw_expr,
                reference_server_dt=expr_ref,
                default_time="10:15",
            )
            checks = {
                "status_ok": status == "ok",
                "candidate_expected": candidate == expected_dt,
                "kind_expected": (meta or {}).get("input_kind") == expected_kind,
            }
            if expected_assumption_kind is None:
                checks["assumption_expected"] = (meta or {}).get("assumption_kind") in (None, "")
            else:
                checks["assumption_expected"] = (meta or {}).get("assumption_kind") == expected_assumption_kind

            section_name = f"expression_case_{idx + 1}"
            dbg.section(section_name, {
                "raw_expr": raw_expr,
                "expected_dt": expected_dt.isoformat(sep=" "),
                "status": status,
                "candidate": candidate.isoformat(sep=" ") if candidate else None,
                "meta": meta,
                "checks": checks,
            })
            if not all(checks.values()):
                dbg.problem("datetime_expression_case_failed", {
                    "section": section_name,
                    "raw_expr": raw_expr,
                    "checks": checks,
                })

        user_ref = datetime(2026, 1, 15, 12, 0, 0)
        status, candidate, meta = parse_user_datetime_expression(
            "today at 07:00",
            reference_server_dt=user_ref,
            user_prefs={
                "timezone_mode": "user",
                "timezone": {"name": "America/New_York"},
            },
        )
        checks = {
            "status_ok": status == "ok",
            "candidate_timezone_converted": candidate == datetime(2026, 1, 15, 13, 0, 0),
            "meta_timezone_mode_user": (meta or {}).get("timezone_mode") == "user",
        }
        dbg.section("expression_user_timezone_conversion", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_timezone_conversion_failed", {"checks": checks})

        invalid_cases = [
            ("", {"reason_code": "empty"}),
            ("10x", {"reason_code": "invalid_format"}),
            ("0h", {"input_kind": "relative_token", "reason_code": "relative_non_positive"}),
            ("1h", {"input_kind": "relative_token", "reason_code": "relative_tokens_disabled", "allow_relative_tokens": False}),
            ("today at 24:00", {"input_kind": "natural_keyword", "reason_code": "invalid_time"}),
            ("31/04", {"input_kind": "absolute_date", "reason_code": "invalid_date"}),
            ("15", {"reason_code": "invalid_format"}),
        ]
        for idx, (raw_expr, expectation) in enumerate(invalid_cases):
            kwargs = {
                "reference_server_dt": expr_ref,
                "default_time": "10:15",
            }
            if expectation.get("allow_relative_tokens") is False:
                kwargs["allow_relative_tokens"] = False
            status, candidate, meta = parse_user_datetime_expression(raw_expr, **kwargs)
            checks = {
                "status_invalid": status == "invalid",
                "candidate_none": candidate is None,
                "reason_expected": (meta or {}).get("reason_code") == expectation.get("reason_code"),
            }
            expected_kind = expectation.get("input_kind")
            if expected_kind is not None:
                checks["kind_expected"] = (meta or {}).get("input_kind") == expected_kind

            section_name = f"expression_invalid_case_{idx + 1}"
            dbg.section(section_name, {
                "raw_expr": raw_expr,
                "status": status,
                "candidate": candidate.isoformat(sep=" ") if candidate else None,
                "meta": meta,
                "checks": checks,
            })
            if not all(checks.values()):
                dbg.problem("datetime_expression_invalid_case_failed", {
                    "section": section_name,
                    "raw_expr": raw_expr,
                    "checks": checks,
                })

        status, candidate, meta = parse_user_datetime_expression(
            "15",
            reference_server_dt=expr_ref,
            default_time="10:15",
            allow_day_only=True,
        )
        checks = {
            "status_ok": status == "ok",
            "candidate_expected": candidate == datetime(2026, 3, 15, 10, 15, 0),
            "kind_day_only": (meta or {}).get("input_kind") == "day_only",
            "assumption_day_only": (meta or {}).get("assumption_kind") == "day_only",
        }
        dbg.section("expression_day_only_enabled", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_day_only_failed", {"checks": checks})

        status, candidate, meta = parse_user_datetime_expression(
            "15",
            reference_server_dt=datetime(2026, 3, 20, 9, 0, 0),
            default_time="10:15",
            allow_day_only=True,
        )
        checks = {
            "status_ok": status == "ok",
            "candidate_rolls_next_month": candidate == datetime(2026, 4, 15, 10, 15, 0),
            "kind_day_only": (meta or {}).get("input_kind") == "day_only",
        }
        dbg.section("expression_day_only_rolls_next_month", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_day_only_roll_failed", {"checks": checks})

        status, candidate, meta = parse_user_datetime_expression(
            "5/3/2026",
            reference_server_dt=expr_ref,
            default_time="08:45",
        )
        checks = {
            "status_ok": status == "ok",
            "candidate_default_time_applied": candidate == datetime(2026, 3, 5, 8, 45, 0),
            "used_default_time_true": (meta or {}).get("used_default_time") is True,
            "minute_defaulted_false": (meta or {}).get("minute_defaulted") is False,
        }
        dbg.section("expression_default_time_policy", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_default_time_policy_failed", {"checks": checks})

        status, candidate, meta = parse_user_datetime_expression(
            "5/3/2026 14",
            reference_server_dt=expr_ref,
            default_time="08:45",
        )
        checks = {
            "status_ok": status == "ok",
            "candidate_hour_only_defaults_minute_00": candidate == datetime(2026, 3, 5, 14, 0, 0),
            "used_default_time_false": (meta or {}).get("used_default_time") is False,
            "minute_defaulted_true": (meta or {}).get("minute_defaulted") is True,
        }
        dbg.section("expression_hour_only_minute_policy", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_hour_only_policy_failed", {"checks": checks})

        status, candidate, meta = parse_user_datetime_expression(
            "today at 09:00",
            reference_server_dt=expr_ref,
            boundary_mode="future",
            now_server_dt=expr_ref,
        )
        checks = {
            "status_invalid": status == "invalid",
            "candidate_none": candidate is None,
            "reason_candidate_not_future": (meta or {}).get("reason_code") == "candidate_not_future",
        }
        dbg.section("expression_boundary_future_strict", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_boundary_future_failed", {"checks": checks})

        status, candidate, meta = parse_user_datetime_expression(
            "today at 10:00",
            reference_server_dt=expr_ref,
            boundary_mode="before_boundary",
            boundary_server_dt=datetime(2026, 3, 2, 9, 30, 0),
            now_server_dt=expr_ref,
        )
        checks = {
            "status_invalid": status == "invalid",
            "candidate_none": candidate is None,
            "reason_not_before_boundary": (meta or {}).get("reason_code") == "candidate_not_before_boundary",
        }
        dbg.section("expression_boundary_before_due_reject", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_boundary_before_due_reject_failed", {"checks": checks})

        status, candidate, meta = parse_user_datetime_expression(
            "today at 09:15",
            reference_server_dt=expr_ref,
            boundary_mode="before_boundary",
            boundary_server_dt=datetime(2026, 3, 2, 9, 30, 0),
            now_server_dt=expr_ref,
        )
        checks = {
            "status_ok": status == "ok",
            "candidate_expected": candidate == datetime(2026, 3, 2, 9, 15, 0),
            "reason_none": (meta or {}).get("reason_code") is None,
        }
        dbg.section("expression_boundary_before_due_accept", {
            "status": status,
            "candidate": candidate.isoformat(sep=" ") if candidate else None,
            "meta": meta,
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("datetime_expression_boundary_before_due_accept_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ok = not dbg.problems
    dbg.finish(summary_lines=[f"input: {'OK' if ok else 'FAIL'}"], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
