#!/usr/bin/env python3
import os
import sys
from datetime import date, datetime


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
SCRIPT_TITLE = "birthday_age_debug"
FEATURE_TITLE = "Birthday Year & Age"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _check_date_parsing(dbg):
    """Test birthday date parsing: DD/MM, DD/MM/YYYY, DD/MM/YY rejection, validation."""

    def _parse_date(text):
        """Simulate the logic in birthday_get_date without Telegram context."""
        parts = text.strip().split("/")
        if len(parts) == 3:
            dd, mm, yy = parts
            if len(yy) == 2:
                return {"error": "2-digit year"}
            try:
                parsed = datetime.strptime(text, "%d/%m/%Y")
                birth_year = parsed.year
                if birth_year > datetime.now().year:
                    return {"error": "future year"}
                if birth_year < 1900:
                    return {"error": "year before 1900"}
                return {"date": f"{dd}/{mm}", "birth_year": birth_year}
            except ValueError:
                return {"error": "invalid date"}
        try:
            datetime.strptime(text + "/2024", "%d/%m/%Y")
            return {"date": text, "birth_year": None}
        except ValueError:
            return {"error": "invalid date"}

    cases = {
        "dd_mm_valid": ("25/12", {"date": "25/12", "birth_year": None}),
        "dd_mm_yyyy_valid": ("25/12/1990", {"date": "25/12", "birth_year": 1990}),
        "dd_mm_yy_rejected": ("25/12/90", {"error": "2-digit year"}),
        "invalid_day": ("32/01", {"error": "invalid date"}),
        "invalid_month": ("15/13", {"error": "invalid date"}),
        "invalid_full": ("32/13/2000", {"error": "invalid date"}),
        "future_year": (f"01/01/{datetime.now().year + 1}", {"error": "future year"}),
        "year_1899": ("01/01/1899", {"error": "year before 1900"}),
        "year_1900": ("01/01/1900", {"date": "01/01", "birth_year": 1900}),
        "leap_day": ("29/02", {"date": "29/02", "birth_year": None}),
        "leap_day_year": ("29/02/2000", {"date": "29/02", "birth_year": 2000}),
        "current_year": (f"15/06/{datetime.now().year}", {"date": "15/06", "birth_year": datetime.now().year}),
    }

    results = {}
    checks = {}
    for name, (input_text, expected) in cases.items():
        result = _parse_date(input_text)
        results[name] = {"input": input_text, "result": result, "expected": expected}
        checks[name] = result == expected

    dbg.section("date_parsing", {"results": results, "checks": checks})

    if not all(checks.values()):
        failed = {k: results[k] for k, v in checks.items() if not v}
        dbg.problem("date_parsing_failed", {"failed": failed})


def _check_age_helpers(dbg):
    """Test calculate_current_age and calculate_turning_age."""
    from modules.birthday_utils import calculate_current_age, calculate_turning_age

    ref = date(2026, 2, 20)
    cases = {
        # current age — birthday not yet this year
        "age_bday_not_yet": (calculate_current_age(15, 3, 1990, ref), 35),
        # current age — birthday already passed
        "age_bday_passed": (calculate_current_age(15, 1, 1990, ref), 36),
        # current age — birthday is today
        "age_bday_today": (calculate_current_age(20, 2, 1990, ref), 36),
        # no birth year → None
        "age_no_year": (calculate_current_age(15, 3, None, ref), None),
        # Feb 29 birthday in non-leap year (2026) — before Mar 1 → not yet
        "age_feb29_nonleap_before_mar1": (calculate_current_age(29, 2, 2000, date(2026, 2, 28)), 25),
        # Feb 29 birthday in non-leap year — on Mar 1 → already passed
        "age_feb29_nonleap_on_mar1": (calculate_current_age(29, 2, 2000, date(2026, 3, 1)), 26),
        # Feb 29 birthday in leap year — on Feb 29
        "age_feb29_leap": (calculate_current_age(29, 2, 2000, date(2024, 2, 29)), 24),
        # turning age
        "turning_age_2026": (calculate_turning_age(1990, 2026), 36),
        "turning_age_none": (calculate_turning_age(None, 2026), None),
        "turning_age_no_year": (calculate_turning_age(1990, None), None),
    }

    checks = {}
    results = {}
    for name, (actual, expected) in cases.items():
        checks[name] = actual == expected
        results[name] = {"actual": actual, "expected": expected}

    dbg.section("age_helpers", {"results": results, "checks": checks})

    if not all(checks.values()):
        failed = {k: results[k] for k, v in checks.items() if not v}
        dbg.problem("age_helpers_failed", {"failed": failed})


def _check_summary_age(dbg):
    """Test that format_birthday_summary shows age when birth_year present, hides when absent."""
    from modules.handlers.birthday_flow.render import format_birthday_summary

    payload_with_year = {
        "title": "Alice",
        "schedule": {"date": "15/03", "time": "08:00"},
        "birth_year": 1990,
        "pre_alerts": [],
        "tags": [],
    }
    payload_no_year = {
        "title": "Bob",
        "schedule": {"date": "25/12", "time": "08:00"},
        "pre_alerts": [],
        "tags": [],
    }
    payload_age_zero = {
        "title": "Baby",
        "schedule": {"date": "01/01", "time": "08:00"},
        "birth_year": datetime.now().year,
        "pre_alerts": [],
        "tags": [],
    }

    summary_with = format_birthday_summary(payload_with_year)
    summary_without = format_birthday_summary(payload_no_year)
    summary_zero = format_birthday_summary(payload_age_zero)

    checks = {
        "with_year_has_age": "**Current Age:**" in summary_with,
        "without_year_no_age": "**Current Age:**" not in summary_without,
        "age_zero_shown": "**Current Age:** `0`" in summary_zero,
    }

    dbg.section("summary_age", {"checks": checks})

    if not all(checks.values()):
        dbg.problem("summary_age_failed", {"checks": checks})


def _check_main_alert_age(dbg):
    """Test that format_main_alert shows turning-age for birthdays with birth_year."""
    from modules.scheduler_messagelogic import format_main_alert

    alert_with = {
        "title": "Alice",
        "type": 6,
        "type_name": "Birthday",
        "birth_year": 1990,
        "tags": [],
    }
    alert_without = {
        "title": "Bob",
        "type": 6,
        "type_name": "Birthday",
        "tags": [],
    }
    alert_non_bday = {
        "title": "Meeting",
        "type": 3,
        "type_name": "Weekly",
        "birth_year": 1990,
        "tags": [],
    }

    sched = datetime(2026, 3, 15, 8, 0)
    msg_with = format_main_alert(alert_with, scheduled_time=sched)
    msg_without = format_main_alert(alert_without, scheduled_time=sched)
    msg_non_bday = format_main_alert(alert_non_bday, scheduled_time=sched)
    msg_no_sched = format_main_alert(alert_with, scheduled_time=None)

    checks = {
        "with_year_shows_turns": "turns **36**" in msg_with,
        "without_year_no_turns": "turns" not in msg_without,
        "non_birthday_no_turns": "turns" not in msg_non_bday,
        "no_scheduled_time_safe": "turns" not in msg_no_sched,
    }

    dbg.section("main_alert_age", {"checks": checks})

    if not all(checks.values()):
        dbg.problem("main_alert_age_failed", {"checks": checks})


def _check_pre_alert_age(dbg):
    """Test that format_pre_alert shows turning-age using main_trigger_time year, not scheduled_time."""
    from modules.scheduler_messagelogic import format_pre_alert

    alert_with = {
        "title": "Alice",
        "type": 6,
        "type_name": "Birthday",
        "birth_year": 1990,
        "tags": [],
    }
    alert_without = {
        "title": "Bob",
        "type": 6,
        "type_name": "Birthday",
        "tags": [],
    }

    # Pre-alert fires Dec 26 2025, birthday is Jan 2 2026 → turning age uses 2026
    main_trigger = datetime(2026, 1, 2, 8, 0)
    sched_time = datetime(2025, 12, 26, 8, 0)
    msg_cross_year = format_pre_alert(alert_with, main_trigger, scheduled_time=sched_time)

    # Normal case: pre-alert and birthday in same year
    main_same = datetime(2026, 3, 15, 8, 0)
    msg_with = format_pre_alert(alert_with, main_same)
    msg_without = format_pre_alert(alert_without, main_same)

    checks = {
        "with_year_shows_will_be": "will be **36**" in msg_with,
        "without_year_no_will_be": "will be **" not in msg_without,
        "cross_year_uses_bday_year": "will be **36**" in msg_cross_year,
    }

    dbg.section("pre_alert_age", {"checks": checks})

    if not all(checks.values()):
        dbg.problem("pre_alert_age_failed", {"checks": checks})


def _check_detail_card_age(dbg):
    """Test that _format_detailed_card shows current age for birthdays with birth_year."""
    from modules.handlers.list_alerts import format_detailed_card

    alert_with = {
        "id": "b001",
        "title": "Alice",
        "type": 6,
        "type_name": "Birthday",
        "schedule": {"date": "15/03", "time": "08:00"},
        "birth_year": 1990,
        "tags": ["👨\u200d👩\u200d👧 Family"],
        "active": True,
        "pre_alerts": [],
    }
    alert_without = {
        "id": "b002",
        "title": "Bob",
        "type": 6,
        "type_name": "Birthday",
        "schedule": {"date": "25/12", "time": "08:00"},
        "tags": [],
        "active": True,
        "pre_alerts": [],
    }
    card_with = format_detailed_card(alert_with)
    card_without = format_detailed_card(alert_without)

    checks = {
        "with_year_has_age": "Current age:" in card_with,
        "without_year_no_age": "Current age:" not in card_without,
    }

    dbg.section("detail_card_age", {"checks": checks})

    if not all(checks.values()):
        dbg.problem("detail_card_age_failed", {"checks": checks})


def _check_compact_list_age(dbg):
    """Test that build_compact_birthday_lines shows (turns X) when birth_year present."""
    from modules.handlers.birthday_flow.render import build_compact_birthday_lines

    alerts = [
        {
            "id": "c1",
            "title": "Alice",
            "type": 6,
            "type_name": "Birthday",
            "schedule": {"date": "15/03", "time": "08:00"},
            "birth_year": 1990,
            "tags": [],
            "active": True,
            "pre_alerts": [],
        },
        {
            "id": "c2",
            "title": "Bob",
            "type": 6,
            "type_name": "Birthday",
            "schedule": {"date": "25/12", "time": "08:00"},
            "tags": [],
            "active": True,
            "pre_alerts": [],
        },
    ]

    lines, alias_map = build_compact_birthday_lines(alerts)
    joined = "\n".join(lines)

    checks = {
        "alice_has_turns": "(turns " in lines[1],
        "bob_no_turns": "(turns " not in lines[3],
        "alias_count": len(alias_map) == 2,
    }

    dbg.section("compact_list_age", {"lines": lines, "checks": checks})

    if not all(checks.values()):
        dbg.problem("compact_list_age_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        _check_date_parsing(dbg)
        _check_age_helpers(dbg)
        _check_summary_age(dbg)
        _check_main_alert_age(dbg)
        _check_pre_alert_age(dbg)
        _check_detail_card_age(dbg)
        _check_compact_list_age(dbg)

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    date_ok = not dbg.has_problem("date_parsing_failed")
    age_ok = not dbg.has_problem("age_helpers_failed")
    summary_ok = not dbg.has_problem("summary_age_failed")
    main_alert_ok = not dbg.has_problem("main_alert_age_failed")
    pre_alert_ok = not dbg.has_problem("pre_alert_age_failed")
    detail_ok = not dbg.has_problem("detail_card_age_failed")
    compact_ok = not dbg.has_problem("compact_list_age_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"date-parsing: {'OK' if date_ok else 'FAIL'}",
        f"age-helpers: {'OK' if age_ok else 'FAIL'}",
        f"summary-age: {'OK' if summary_ok else 'FAIL'}",
        f"main-alert-age: {'OK' if main_alert_ok else 'FAIL'}",
        f"pre-alert-age: {'OK' if pre_alert_ok else 'FAIL'}",
        f"detail-card-age: {'OK' if detail_ok else 'FAIL'}",
        f"compact-list-age: {'OK' if compact_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
