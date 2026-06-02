#!/usr/bin/env python3
"""message_format_debug — Smoke tests for modules/ui/formatters/shared.py helpers."""
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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "message_format_debug"
FEATURE_TITLE = "Shared Message Format Helpers"

IMPORT_ERROR = None
try:
    from modules.ui.formatters.shared import (
        format_tags_line,
        format_alert_type_rows,
        format_time_until,
    )
    from modules.ui.formatters.alert_text import (
        format_pa,
        format_aa,
    )
    from modules.ui.formatters.birthday_text import (
        format_pb,
        format_bb,
    )
    from modules.ui.formatters.info_text import (
        format_ia,
        format_ib,
    )
except ModuleNotFoundError as exc:
    IMPORT_ERROR = exc


def _test_format_tags_line(dbg):
    checks = {}
    checks["empty_list_is_untagged"] = format_tags_line([]) == "🏷️ Untagged"
    checks["none_is_untagged"] = format_tags_line(None) == "🏷️ Untagged"
    checks["single_tag"] = format_tags_line(["🎯 Work"]) == "🎯 Work"
    checks["multi_tag"] = format_tags_line(["🎯 Work", "📅 Personal"]) == "🎯 Work, 📅 Personal"
    # Tag without emoji falls back via parse_tag
    result_no_emoji = format_tags_line(["NoEmoji"])
    checks["no_emoji_tag_renders"] = isinstance(result_no_emoji, str) and len(result_no_emoji) > 0
    dbg.section("format_tags_line", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_tags_line_failed", {"checks": checks})


def _test_format_alert_type_rows(dbg):
    checks = {}

    # Type 1 — Monthly (day): single row
    t1 = {"type": 1, "schedule": {"days": [5, 20], "interval": 2}}
    rows1 = format_alert_type_rows(t1)
    checks["type1_one_row"] = len(rows1) == 1
    checks["type1_uses_corner"] = rows1[0].startswith("╰─")
    checks["type1_has_days"] = "Days:" in rows1[0]

    # Type 2 — Monthly (relative): single row
    t2 = {"type": 2, "schedule": {"ordinals": ["last"], "weekdays": ["Monday"], "interval": 1}}
    rows2 = format_alert_type_rows(t2)
    checks["type2_one_row"] = len(rows2) == 1
    checks["type2_uses_corner"] = rows2[0].startswith("╰─")
    checks["type2_has_relative"] = "Relative:" in rows2[0]

    # Type 3 — Weekly: single row
    t3 = {"type": 3, "schedule": {"weekdays": ["Mon", "Wed"]}}
    rows3 = format_alert_type_rows(t3)
    checks["type3_one_row"] = len(rows3) == 1
    checks["type3_has_weekdays"] = "Weekdays:" in rows3[0]

    # Type 4 — Yearly: single row
    t4 = {"type": 4, "schedule": {"dates": "15/03"}}
    rows4 = format_alert_type_rows(t4)
    checks["type4_one_row"] = len(rows4) == 1
    checks["type4_has_dates"] = "Dates:" in rows4[0]

    # Type 5 — Once: single row
    t5 = {"type": 5, "schedule": {"date": "25/12/2025"}}
    rows5 = format_alert_type_rows(t5)
    checks["type5_one_row"] = len(rows5) == 1
    checks["type5_has_date"] = "Date:" in rows5[0]

    # Type 6 — Birthday: empty
    t6 = {"type": 6, "schedule": {"date": "15/06"}}
    rows6 = format_alert_type_rows(t6)
    checks["type6_empty"] = rows6 == []

    # Type 7 — Daily: empty
    t7 = {"type": 7, "schedule": {"interval": 3}}
    rows7 = format_alert_type_rows(t7)
    checks["type7_empty"] = rows7 == []

    dbg.section("format_alert_type_rows", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_alert_type_rows_failed", {"checks": checks})


def _test_format_time_until(dbg):
    from datetime import datetime, timedelta
    now = datetime(2025, 3, 1, 10, 0, 0)
    checks = {}
    checks["falsy_is_unknown"] = format_time_until(None) == "Unknown"
    checks["past_is_less_than_minute"] = format_time_until(now - timedelta(seconds=30), now=now) == "less than a minute"
    checks["45min"] = "minute" in format_time_until(now + timedelta(minutes=45), now=now)
    checks["3hours"] = "hour" in format_time_until(now + timedelta(hours=3), now=now)
    checks["2days"] = "day" in format_time_until(now + timedelta(days=2), now=now)
    checks["2weeks"] = "week" in format_time_until(now + timedelta(weeks=2), now=now)
    dbg.section("format_time_until", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_time_until_failed", {"checks": checks})


def _test_format_pa(dbg):
    from datetime import datetime, timedelta
    now = datetime(2025, 3, 25, 9, 0, 0)
    main_time = now + timedelta(hours=3)
    alert = {
        "type": 1, "type_name": "Monthly",
        "title": "Pay Bills", "tags": ["💰 Finance"],
        "additional_info": "",
    }

    checks = {}
    text = format_pa(alert, main_time)
    checks["has_upcoming_header"] = "UPCOMING ALERT" in text
    checks["has_countdown"] = "due in" in text
    checks["has_scheduled_line"] = "Scheduled:" in text
    checks["has_title"] = "PAY BILLS" in text
    checks["has_type"] = "Monthly" in text
    checks["no_additional_info_when_empty"] = "Additional info" not in text
    checks["has_tags"] = "Finance" in text

    # With additional_info
    alert_with_info = dict(alert, additional_info="Remember to check online account first.")
    text_info = format_pa(alert_with_info, main_time)
    checks["additional_info_present_when_set"] = "Additional info:\n" in text_info

    # No next-occurrence line in PA
    checks["no_next_occurrence_in_pa"] = "Next occurrence" not in text

    dbg.section("format_pa", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_pa_failed", {"checks": checks, "sample": text[:300]})


def _test_format_aa(dbg):
    from datetime import datetime
    alert = {
        "type": 3, "type_name": "Weekly",
        "title": "Team Standup", "tags": ["💼 Work"],
        "additional_info": "",
    }

    checks = {}
    text = format_aa(alert, scheduled_time=datetime(2025, 3, 25, 10, 0))
    checks["no_header_line"] = "ALERT" not in text.split("\n")[0]
    checks["has_title"] = "TEAM STANDUP" in text
    checks["has_type"] = "Weekly" in text
    checks["has_tags"] = "Work" in text
    checks["no_additional_info_when_empty"] = "Additional info" not in text
    # No next-occurrence line in AA
    checks["no_next_occurrence_in_aa"] = "Next occurrence" not in text

    alert_with_info = dict(alert, additional_info="Check confluence board first.")
    text_info = format_aa(alert_with_info)
    checks["additional_info_present_when_set"] = "Additional info:\n" in text_info

    dbg.section("format_aa", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_aa_failed", {"checks": checks, "sample": text[:300]})


def _test_format_pb(dbg):
    from datetime import datetime, timedelta
    now = datetime(2025, 3, 20, 8, 0, 0)
    main_time = datetime(2025, 3, 21, 8, 0, 0)  # birthday fires tomorrow
    alert = {
        "type": 6, "type_name": "Birthday",
        "title": "Mario Rossi", "birth_year": 1988,
        "schedule": {"date": "21/03"},
        "tags": ["👨‍👩‍👧 Family"], "additional_info": "",
    }

    checks = {}
    text = format_pb(alert, main_time)
    checks["has_upcoming_header"] = "UPCOMING ALERT" in text
    checks["has_countdown"] = "due in" in text
    checks["has_scheduled_line"] = "Scheduled:" in text
    checks["has_birthday_of"] = "Birthday of" in text
    checks["has_name_caps"] = "MARIO ROSSI" in text
    checks["has_will_turn"] = "will turn" in text
    checks["has_age"] = "37" in text  # 2025 - 1988 = 37
    checks["no_zodiac_in_pb"] = "🔮" not in text and "🐉" not in text
    checks["has_tags"] = "Family" in text
    checks["no_additional_info_when_empty"] = "Additional info" not in text

    # Mystery line when no birth year
    alert_no_year = dict(alert, birth_year=None)
    text_mystery = format_pb(alert_no_year, main_time)
    checks["mystery_line_when_no_year"] = "mystery" in text_mystery.lower()

    # Additional info
    alert_with_info = dict(alert, additional_info="Organize a surprise party!")
    text_info = format_pb(alert_with_info, main_time)
    checks["additional_info_present_when_set"] = "Additional info:\n" in text_info

    dbg.section("format_pb", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_pb_failed", {"checks": checks, "sample": text[:300]})


def _test_format_bb(dbg):
    from datetime import datetime
    fire_time = datetime(2025, 3, 21, 8, 0, 0)
    alert = {
        "type": 6, "type_name": "Birthday",
        "title": "Mario Rossi", "birth_year": 1988,
        "schedule": {"date": "21/03"},
        "tags": ["👨‍👩‍👧 Family"], "additional_info": "",
    }

    checks = {}
    text = format_bb(alert, scheduled_time=fire_time)
    checks["has_birthday_of"] = "Birthday of" in text
    checks["has_name_caps"] = "MARIO ROSSI" in text
    checks["has_turns_today"] = "turns" in text and "today" in text
    checks["has_age"] = "37" in text  # 2025 - 1988
    checks["has_tags"] = "Family" in text
    checks["no_additional_info_when_empty"] = "Additional info" not in text
    # Zodiac absent when no prefs given (default mode = none)
    checks["no_zodiac_without_prefs"] = "🔮" not in text and "🐉" not in text

    # Mystery line
    alert_no_year = dict(alert, birth_year=None)
    text_mystery = format_bb(alert_no_year, scheduled_time=fire_time)
    checks["mystery_line_when_no_year"] = "mystery" in text_mystery.lower()

    # Additional info
    alert_with_info = dict(alert, additional_info="Call to wish happy birthday!")
    text_info = format_bb(alert_with_info, scheduled_time=fire_time)
    checks["additional_info_present_when_set"] = "Additional info:\n" in text_info

    dbg.section("format_bb", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_bb_failed", {"checks": checks, "sample": text[:300]})


def _test_format_ia(dbg):
    alert = {
        "type": 1, "type_name": "Monthly (day)",
        "title": "Pay Rent", "active": True,
        "schedule": {"days": [1], "interval": 1, "time": "10:00"},
        "tags": ["💰 Finance"],
        "additional_info": "",
        "pre_alerts": [],
    }

    checks = {}
    text = format_ia(alert)
    checks["has_info_header"] = "ℹ️ Detailed INFO" in text
    checks["has_status_dash_title"] = "🟢 ─" in text and "PAY RENT" in text
    checks["has_type_line"] = "Monthly (day)" in text
    checks["has_tree_row"] = "╰─" in text and "Days:" in text
    checks["has_interval_line"] = "🔁 Interval:" in text and "Every Month" in text
    checks["has_time_line"] = "⏰ Time: 10:00" in text
    checks["has_next_scheduled"] = "Next Scheduled:" in text
    checks["has_tags"] = "Finance" in text
    checks["no_additional_info_when_empty"] = "Additional info" not in text

    # Inactive status dot
    inactive_alert = dict(alert, active=False)
    text_inactive = format_ia(inactive_alert)
    checks["inactive_shows_red_dot"] = "🔴 ─" in text_inactive

    # Additional info present
    alert_with_info = dict(alert, additional_info="Check bank statement first.")
    text_info = format_ia(alert_with_info)
    checks["additional_info_shown_when_set"] = "Additional info:\n" in text_info

    # Type 7 (daily) — no tree rows, interval shown
    daily_alert = {
        "type": 7, "type_name": "Daily",
        "title": "Morning Walk", "active": True,
        "schedule": {"interval": 3, "time": "07:00"},
        "tags": [],
    }
    text_daily = format_ia(daily_alert)
    checks["daily_has_interval"] = "Every 3 Days" in text_daily
    checks["daily_no_tree_rows"] = "╰─" not in text_daily

    # Type 5 (once) — no interval line
    once_alert = {
        "type": 5, "type_name": "Once",
        "title": "Doctor Appointment", "active": True,
        "schedule": {"date": "25/12/2026", "time": "09:00"},
        "tags": [],
    }
    text_once = format_ia(once_alert)
    checks["once_has_date_tree_row"] = "╰─" in text_once and "Date:" in text_once
    checks["once_no_interval_line"] = "🔁 Interval:" not in text_once

    dbg.section("format_ia", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_ia_failed", {"checks": checks, "sample": text[:400]})


def _test_format_ib(dbg):
    alert = {
        "type": 6, "type_name": "Birthday",
        "title": "Anna Bianchi", "active": True,
        "birth_year": 1990,
        "schedule": {"date": "15/04"},
        "tags": ["👨‍👩‍👧 Family"],
        "additional_info": "",
        "pre_alerts": [],
    }

    checks = {}
    text = format_ib(alert)
    checks["has_info_header"] = "ℹ️ Detailed INFO" in text
    checks["has_status_bday_block"] = "🟢 ─ 🎂 Birthday of" in text
    checks["has_name_caps"] = "ANNA BIANCHI" in text
    checks["has_birth_date"] = "Birth date:" in text and "April" in text
    checks["has_current_age"] = "🎂 Current age:" in text
    checks["has_tags"] = "Family" in text
    checks["no_additional_info_when_empty"] = "Additional info" not in text
    # No zodiac when no prefs
    checks["no_zodiac_without_prefs"] = "🔮" not in text and "🐉" not in text

    # Year unknown
    alert_no_year = dict(alert, birth_year=None)
    text_no_year = format_ib(alert_no_year)
    checks["year_unknown_shown"] = "year unknown" in text_no_year
    checks["no_age_when_no_year"] = "🎂 Current age:" not in text_no_year

    # Additional info
    alert_with_info = dict(alert, additional_info="Send flowers!")
    text_info = format_ib(alert_with_info)
    checks["additional_info_shown_when_set"] = "Additional info:\n" in text_info

    # Pre-alert shown
    alert_with_pre = dict(alert, pre_alerts=["1d"])
    text_pre = format_ib(alert_with_pre)
    checks["pre_alert_shown"] = "🔔 Pre-alert:" in text_pre

    dbg.section("format_ib", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("format_ib_failed", {"checks": checks, "sample": text[:400]})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        _test_format_tags_line(dbg)
        _test_format_alert_type_rows(dbg)
        _test_format_time_until(dbg)
        _test_format_pa(dbg)
        _test_format_aa(dbg)
        _test_format_pb(dbg)
        _test_format_bb(dbg)
        _test_format_ia(dbg)
        _test_format_ib(dbg)

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    tags_ok = not dbg.has_problem("format_tags_line_failed")
    rows_ok = not dbg.has_problem("format_alert_type_rows_failed")
    time_ok = not dbg.has_problem("format_time_until_failed")
    pa_ok = not dbg.has_problem("format_pa_failed")
    aa_ok = not dbg.has_problem("format_aa_failed")
    pb_ok = not dbg.has_problem("format_pb_failed")
    bb_ok = not dbg.has_problem("format_bb_failed")
    ia_ok = not dbg.has_problem("format_ia_failed")
    ib_ok = not dbg.has_problem("format_ib_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"format_tags_line: {'OK' if tags_ok else 'FAIL'}",
        f"format_alert_type_rows: {'OK' if rows_ok else 'FAIL'}",
        f"format_time_until: {'OK' if time_ok else 'FAIL'}",
        f"format_pa: {'OK' if pa_ok else 'FAIL'}",
        f"format_aa: {'OK' if aa_ok else 'FAIL'}",
        f"format_pb: {'OK' if pb_ok else 'FAIL'}",
        f"format_bb: {'OK' if bb_ok else 'FAIL'}",
        f"format_ia: {'OK' if ia_ok else 'FAIL'}",
        f"format_ib: {'OK' if ib_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
