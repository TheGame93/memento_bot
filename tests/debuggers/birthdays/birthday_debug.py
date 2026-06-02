#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import types
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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "birthday_debug"
FEATURE_TITLE = "Birthday Logic"


def _parse_cli_args(args):
    user_id = None
    include_bad = False
    unknown = []
    idx = 0
    while idx < len(args):
        token = args[idx]
        if token == "--user":
            if idx + 1 >= len(args):
                return {
                    "user_id": None,
                    "include_bad": include_bad,
                    "unknown": unknown,
                    "error": "--user requires a value",
                }
            candidate = str(args[idx + 1]).strip()
            if not candidate:
                return {
                    "user_id": None,
                    "include_bad": include_bad,
                    "unknown": unknown,
                    "error": "--user value cannot be empty",
                }
            user_id = candidate
            idx += 2
            continue
        if token == "--include-bad":
            include_bad = True
            idx += 1
            continue
        if token in ("--quiet", "--verbose"):
            idx += 1
            continue
        unknown.append(token)
        idx += 1
    return {
        "user_id": user_id,
        "include_bad": include_bad,
        "unknown": unknown,
        "error": None,
    }


def parse_date_str(date_str):
    if not date_str or "/" not in date_str:
        return None, None
    try:
        day, month = map(int, date_str.split("/"))
        return day, month
    except ValueError:
        return None, None


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def birthday_occurrence_for_year(alert, year, constants):
    """Return a datetime for the birthday occurrence in a specific year."""
    sch = alert.get("schedule", {})
    date_str = sch.get("date", "")
    day, month = parse_date_str(date_str)
    if not day or not month:
        return None

    policy = (getattr(constants, "BIRTHDAY_FEB29_POLICY", "mar1") or "mar1").lower()
    if day == 29 and month == 2 and not _is_leap(year):
        if policy == "mar1":
            day, month = 1, 3
        else:
            day, month = 28, 2

    time_str = sch.get("time") or getattr(constants, "BIRTHDAY_DEFAULT_TIME", "08:00")
    try:
        t = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        t = datetime.strptime(getattr(constants, "BIRTHDAY_DEFAULT_TIME", "08:00"), "%H:%M").time()

    try:
        return datetime(year, month, day, t.hour, t.minute, 0, 0)
    except ValueError:
        return None


def build_alert(alert_id, title, date_str, constants, time_str=None, active=True, tags=None, pre_alerts=None, image_id=None):
    return {
        "id": alert_id,
        "title": title,
        "type": 6,
        "type_name": constants.ALERT_TYPES.get(6, "Birthday"),
        "schedule": {
            "date": date_str,
            "time": time_str or getattr(constants, "BIRTHDAY_DEFAULT_TIME", "08:00"),
        },
        "pre_alerts": pre_alerts or [],
        "tags": tags or [],
        "image_id": image_id,
        "active": active,
    }


def collect_window_occurrences(alerts, now, constants, past_days=10, future_days=60, include_inactive=False):
    window_start = now.date() - timedelta(days=past_days)
    window_end = now.date() + timedelta(days=future_days)
    results = []
    for alert in alerts:
        if alert.get("type") != 6:
            continue
        if not include_inactive and not alert.get("active", True):
            continue
        for year in (now.year - 1, now.year, now.year + 1):
            occ = birthday_occurrence_for_year(alert, year, constants)
            if not occ:
                continue
            if window_start <= occ.date() <= window_end:
                results.append({
                    "alert_id": alert.get("id"),
                    "title": alert.get("title"),
                    "occurrence": occ,
                })
    results.sort(key=lambda item: item["occurrence"])
    return results, window_start, window_end


def sanity_checks(alerts, now, constants, get_next_occurrence):
    checks = []
    type_mismatches = [a.get("id") for a in alerts if a.get("type") != 6]
    checks.append({
        "check": "all_type_6",
        "ok": len(type_mismatches) == 0,
        "details": {"bad_ids": type_mismatches},
    })

    images_present = [{"id": a.get("id"), "image_id": a.get("image_id")} for a in alerts if a.get("image_id")]
    checks.append({
        "check": "no_images_expected",
        "ok": len(images_present) == 0,
        "details": {"found": images_present},
    })

    bad_dates = []
    for alert in alerts:
        day, month = parse_date_str(alert.get("schedule", {}).get("date"))
        if not day or not month:
            bad_dates.append({"id": alert.get("id"), "date": alert.get("schedule", {}).get("date")})
    checks.append({
        "check": "date_format_dd_mm",
        "ok": len(bad_dates) == 0,
        "details": {"bad_dates": bad_dates},
    })

    default_time = getattr(constants, "BIRTHDAY_DEFAULT_TIME", "08:00")
    non_default_time = [
        {"id": alert.get("id"), "time": alert.get("schedule", {}).get("time")}
        for alert in alerts
        if alert.get("schedule", {}).get("time") != default_time
    ]
    checks.append({
        "check": "time_is_default",
        "ok": len(non_default_time) == 0,
        "details": {"non_default": non_default_time, "expected": default_time},
    })

    invalid_next = []
    for alert in alerts:
        next_occ = get_next_occurrence(alert, now)
        if next_occ is None:
            invalid_next.append({"id": alert.get("id"), "date": alert.get("schedule", {}).get("date")})
    checks.append({
        "check": "next_occurrence_available",
        "ok": len(invalid_next) == 0,
        "details": {"missing": invalid_next},
    })

    return checks


def run_birthday_date_parser_checks(parse_birthday_date_input, current_year):
    cases = {
        "dd_mm_valid": "25/12",
        "dd_mm_yyyy_valid": "25/12/1990",
        "dd_mm_yy_rejected": "25/12/90",
        "future_year_rejected": f"01/01/{current_year + 1}",
        "year_before_1900_rejected": "01/01/1899",
        "leap_day_no_year_valid": "29/02",
        "non_leap_year_rejected": "29/02/2001",
        "invalid_format_rejected": "12-03-2000",
        "empty_rejected": "   ",
    }
    results = {
        name: parse_birthday_date_input(raw, current_year=current_year)
        for name, raw in cases.items()
    }

    expected_keys = {"ok", "date_ddmm", "birth_year", "reason_code"}
    checks = {
        "contract_keys_stable": all(
            isinstance(item, dict) and set(item.keys()) == expected_keys
            for item in results.values()
        ),
        "dd_mm_valid": (
            results["dd_mm_valid"]["ok"]
            and results["dd_mm_valid"]["date_ddmm"] == "25/12"
            and results["dd_mm_valid"]["birth_year"] is None
            and results["dd_mm_valid"]["reason_code"] is None
        ),
        "dd_mm_yyyy_valid": (
            results["dd_mm_yyyy_valid"]["ok"]
            and results["dd_mm_yyyy_valid"]["date_ddmm"] == "25/12"
            and results["dd_mm_yyyy_valid"]["birth_year"] == 1990
            and results["dd_mm_yyyy_valid"]["reason_code"] is None
        ),
        "yy_rejected": (
            not results["dd_mm_yy_rejected"]["ok"]
            and results["dd_mm_yy_rejected"]["reason_code"] == "year_two_digits"
        ),
        "future_year_rejected": (
            not results["future_year_rejected"]["ok"]
            and results["future_year_rejected"]["reason_code"] == "year_in_future"
        ),
        "year_before_1900_rejected": (
            not results["year_before_1900_rejected"]["ok"]
            and results["year_before_1900_rejected"]["reason_code"] == "year_before_1900"
        ),
        "leap_day_no_year_valid": (
            results["leap_day_no_year_valid"]["ok"]
            and results["leap_day_no_year_valid"]["date_ddmm"] == "29/02"
        ),
        "non_leap_year_rejected": (
            not results["non_leap_year_rejected"]["ok"]
            and results["non_leap_year_rejected"]["reason_code"] == "invalid_date"
        ),
        "invalid_format_rejected": (
            not results["invalid_format_rejected"]["ok"]
            and results["invalid_format_rejected"]["reason_code"] == "invalid_format"
        ),
        "empty_rejected": (
            not results["empty_rejected"]["ok"]
            and results["empty_rejected"]["reason_code"] == "empty"
        ),
    }
    return {
        "checks": checks,
        "results": results,
    }


def run_birthday_add_date_handler_parity_checks(birthday_flow_mod, constants):
    class _FakeStorage:
        def get_user_prefs(self, user_id):
            return {}

    class _DummyMessage:
        def __init__(self, text):
            self.text = text
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None):
            self.replies.append({
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            })
            return self

    class _DummyUpdate:
        def __init__(self, text):
            self.message = _DummyMessage(text)
            self.callback_query = None
            self.effective_user = types.SimpleNamespace(id=1001)
            self.effective_chat = types.SimpleNamespace(id=1001)

    class _DummyContext:
        def __init__(self, storage_obj):
            self.user_data = {
                "temp_alert": {
                    "type": 6,
                    "type_name": constants.ALERT_TYPES.get(6, "Birthday"),
                    "schedule": {},
                    "tags": [],
                    "pre_alerts": [],
                    "additional_info": "",
                }
            }
            self.bot_data = {}
            from modules.shared.runtime_context import BotRuntime, set_bot_runtime

            set_bot_runtime(
                self.bot_data,
                BotRuntime(storage=storage_obj, api_failure_tracker=None),
            )

    had_mainbot = "mainbot" in sys.modules
    original_mainbot = sys.modules.get("mainbot")
    original_show_menu = birthday_flow_mod.show_birthday_settings_menu
    fake_storage = _FakeStorage()
    sys.modules["mainbot"] = types.SimpleNamespace(storage=fake_storage)

    async def _fake_show_menu(_update, _context):
        return constants.BDAY_SETTINGS

    birthday_flow_mod.show_birthday_settings_menu = _fake_show_menu
    current_year = datetime.now().year
    future_year = current_year + 1

    async def _run_case(raw_text):
        update = _DummyUpdate(raw_text)
        context = _DummyContext(fake_storage)
        state = await birthday_flow_mod.birthday_get_date(update, context)
        return {
            "state": state,
            "temp_alert": context.user_data.get("temp_alert", {}),
            "replies": list(update.message.replies),
        }

    try:
        case_ddmm = asyncio.run(_run_case("25/12"))
        case_ddmmyyyy = asyncio.run(_run_case("25/12/1990"))
        case_yy = asyncio.run(_run_case("25/12/90"))
        case_future = asyncio.run(_run_case(f"01/01/{future_year}"))
        case_invalid = asyncio.run(_run_case("99/99"))
    finally:
        birthday_flow_mod.show_birthday_settings_menu = original_show_menu
        if had_mainbot:
            sys.modules["mainbot"] = original_mainbot
        else:
            sys.modules.pop("mainbot", None)

    checks = {
        "dd_mm_routes_to_settings": case_ddmm["state"] == constants.BDAY_SETTINGS,
        "dd_mm_keeps_no_birth_year": case_ddmm["temp_alert"].get("birth_year") is None,
        "dd_mm_sets_date": case_ddmm["temp_alert"].get("schedule", {}).get("date") == "25/12",
        "dd_mm_sets_default_time": bool(case_ddmm["temp_alert"].get("schedule", {}).get("time")),
        "dd_mm_yyyy_routes_to_settings": case_ddmmyyyy["state"] == constants.BDAY_SETTINGS,
        "dd_mm_yyyy_sets_birth_year": case_ddmmyyyy["temp_alert"].get("birth_year") == 1990,
        "dd_mm_yyyy_sets_date": case_ddmmyyyy["temp_alert"].get("schedule", {}).get("date") == "25/12",
        "yy_rejected_with_same_prompt": (
            case_yy["state"] == constants.TYPE_6_DATE
            and bool(case_yy["replies"])
            and "2-digit year not allowed" in case_yy["replies"][-1].get("text", "")
        ),
        "future_year_rejected_with_same_prompt": (
            case_future["state"] == constants.TYPE_6_DATE
            and bool(case_future["replies"])
            and "cannot be in the future" in case_future["replies"][-1].get("text", "")
        ),
        "invalid_dd_mm_rejected_with_same_prompt": (
            case_invalid["state"] == constants.TYPE_6_DATE
            and bool(case_invalid["replies"])
            and "Use format DD/MM or DD/MM/YYYY" in case_invalid["replies"][-1].get("text", "")
        ),
    }
    return {
        "checks": checks,
        "cases": {
            "dd_mm": case_ddmm,
            "dd_mm_yyyy": case_ddmmyyyy,
            "yy": case_yy,
            "future_year": case_future,
            "invalid_dd_mm": case_invalid,
        },
    }


def load_birthdays_from_user(user_id):
    data_path = os.path.join(ROOT_DIR, "data", str(user_id), "alerts.json")
    if not os.path.exists(data_path):
        return [], {"error": f"alerts.json not found for user {user_id}"}

    try:
        with open(data_path, "r", encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
    except OSError as exc:
        return [], {"error": f"cannot read alerts.json: {exc}"}
    except json.JSONDecodeError as exc:
        return [], {"error": f"invalid JSON: {exc}"}

    if not isinstance(data, dict):
        return [], {"error": f"invalid alerts.json root type: {type(data).__name__}"}

    alerts = data.get("alerts", [])
    if not isinstance(alerts, list):
        return [], {"error": f"invalid alerts container type: {type(alerts).__name__}"}

    skipped_non_dict = 0
    valid_alerts = []
    for item in alerts:
        if isinstance(item, dict):
            valid_alerts.append(item)
        else:
            skipped_non_dict += 1

    birthdays = [alert for alert in valid_alerts if alert.get("type") == 6]
    return birthdays, {
        "source": "user_data",
        "user_id": str(user_id),
        "total_alerts": len(valid_alerts),
        "birthdays": len(birthdays),
        "skipped_non_dict_entries": skipped_non_dict,
    }


def run_birthday_cancel_cleanup_checks(birthday_flow_mod):
    class _BotStub:
        def __init__(self):
            self.delete_calls = []

        async def delete_message(self, *, chat_id, message_id):
            self.delete_calls.append({"chat_id": chat_id, "message_id": message_id})

    class _MsgStub:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append({"text": text, "kwargs": kwargs})
            return types.SimpleNamespace(message_id=2001)

    class _UpdateStub:
        def __init__(self):
            self.message = _MsgStub()
            self.callback_query = None
            self.effective_chat = types.SimpleNamespace(id=1001)

    class _ContextStub:
        def __init__(self):
            self.user_data = {}
            self.bot = _BotStub()

    original_end_conv = getattr(birthday_flow_mod, "end_registered_conversations", None)
    end_conv_calls = []

    def _mock_end_conv(_update):
        end_conv_calls.append(True)

    birthday_flow_mod.end_registered_conversations = _mock_end_conv
    try:
        update = _UpdateStub()
        context = _ContextStub()
        context.user_data["additional_info_copy_msg_id"] = 2001
        context.user_data["temp_alert"] = {"title": "Test Birthday"}

        from telegram.ext import ConversationHandler
        state = asyncio.run(birthday_flow_mod.birthday_cancel(update, context))
        delete_calls = list(context.bot.delete_calls)

        checks = {
            "copy_key_removed": "additional_info_copy_msg_id" not in context.user_data,
            "delete_attempted_once": len(delete_calls) == 1,
            "delete_correct_message_id": (delete_calls[0]["message_id"] == 2001) if delete_calls else False,
            "cancel_reply_sent": any("Cancelled" in (r.get("text") or "") for r in update.message.replies),
            "terminal_state_returned": state == ConversationHandler.END,
        }
    finally:
        if original_end_conv is not None:
            birthday_flow_mod.end_registered_conversations = original_end_conv

    return {
        "delete_calls": delete_calls,
        "state": state,
        "context_keys": sorted(context.user_data.keys()),
        "checks": checks,
    }


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    now = datetime.now()
    try:
        suppress_ptb_user_warning()

        cli = _parse_cli_args(dbg.args)
        if cli["error"]:
            dbg.problem("cli_args_invalid", {"error": cli["error"], "args": dbg.args})
        if cli["unknown"]:
            dbg.problem("cli_args_unknown", {"unknown": cli["unknown"], "args": dbg.args})

        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            from modules import constants as C
            from modules.handlers.birthday_flow import flow as birthday_flow_mod
            from modules.handlers.birthdays import build_birthday_home_keyboard, build_birthday_home_text
            from modules.handlers.birthday_flow.render import (
                build_compact_birthday_lines,
                format_bday_pre_alerts,
            )
            from modules.handlers.list_alerts import (
                _message_is_detail_view,
                build_info_keyboard,
                build_manage_list_keyboard,
            )
            from modules.handlers.birthday_flow.flow import parse_birthday_date_input
            from modules.scheduler_messagelogic import (
                ACTION_LABEL_ACTIVATE,
                ACTION_LABEL_DELETE,
                ACTION_LABEL_SNOOZE,
            )
            from modules.scheduler_mathlogic import (
                format_pre_alert_display,
                get_next_occurrence,
                resolve_pre_alert_fire_time,
            )
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        dbg.run_meta({
            "project_root": ROOT_DIR,
            "birthday_policy": getattr(C, "BIRTHDAY_FEB29_POLICY", None),
            "birthday_default_time": getattr(C, "BIRTHDAY_DEFAULT_TIME", None),
            "window_past_days": 10,
            "window_future_days": 60,
            "include_bad_records": cli["include_bad"],
            "target_user_id": cli["user_id"],
        })

        user_id = cli["user_id"]
        include_bad = cli["include_bad"]
        if user_id:
            birthdays, source_meta = load_birthdays_from_user(user_id)
            dbg.section("data_source", source_meta)
            if source_meta.get("error"):
                dbg.problem("data_source_error", source_meta)
        else:
            date_minus_5 = (now - timedelta(days=5)).strftime("%d/%m")
            date_plus_5 = (now + timedelta(days=5)).strftime("%d/%m")
            date_plus_70 = (now + timedelta(days=70)).strftime("%d/%m")
            date_minus_15 = (now - timedelta(days=15)).strftime("%d/%m")

            birthdays = [
                build_alert("s1", "Past 5 Days", date_minus_5, C, tags=["🏥 Health"]),
                build_alert("s2", "Next 5 Days", date_plus_5, C, tags=["🏠 Home", "💼 Work"]),
                build_alert("s3", "Next 70 Days (out)", date_plus_70, C, tags=[]),
                build_alert("s4", "Past 15 Days (out)", date_minus_15, C, tags=["✨ Other"]),
                build_alert("s5", "Leap Day", "29/02", C, tags=["👨‍👩‍👧 Family"]),
            ]
            if include_bad:
                birthdays.extend([
                    build_alert("s_bad_date", "Bad Date", "99/99", C, tags=["✨ Other"]),
                    build_alert("s_bad_time", "Bad Time", date_plus_5, C, time_str="12:34"),
                    build_alert("s_bad_pre", "Bad Pre", date_plus_5, C, pre_alerts=["1d"]),
                    build_alert("s_bad_img", "Bad Image", date_plus_5, C, image_id="file_id_123"),
                ])
            dbg.section("data_source", {
                "source": "synthetic",
                "birthdays": len(birthdays),
                "notes": "Synthetic data includes past/future and Feb 29 cases.",
            })

        checks = sanity_checks(birthdays, now, C, get_next_occurrence)
        dbg.section("sanity_checks", {"count": len(checks), "checks": checks})
        failed_checks = [check for check in checks if not check.get("ok", False)]
        if failed_checks:
            dbg.problem("sanity_checks_failed", {"failed": failed_checks})

        parser_contract = run_birthday_date_parser_checks(parse_birthday_date_input, now.year)
        dbg.section("birthday_date_parser_contract", parser_contract)
        if not all((parser_contract.get("checks") or {}).values()):
            dbg.problem("birthday_date_parser_contract_failed", parser_contract)

        add_date_handler_parity = run_birthday_add_date_handler_parity_checks(birthday_flow_mod, C)
        dbg.section("birthday_add_date_handler_parity", add_date_handler_parity)
        if not all((add_date_handler_parity.get("checks") or {}).values()):
            dbg.problem("birthday_add_date_handler_parity_failed", add_date_handler_parity)

        birthday_handler = getattr(birthday_flow_mod, "birthday_add_handler", None)
        birthday_states = getattr(birthday_handler, "states", {}) or {}
        additional_info_handlers = birthday_states.get(C.GET_ADDITIONAL_INFO, [])
        additional_info_patterns = set()
        for state_handler in additional_info_handlers:
            pattern = getattr(state_handler, "pattern", None)
            if isinstance(pattern, str):
                additional_info_patterns.add(pattern)
            else:
                pattern_text = getattr(pattern, "pattern", None)
                if isinstance(pattern_text, str):
                    additional_info_patterns.add(pattern_text)
        birthday_additional_info_checks = {
            "has_info_skip_callback": "^info_skip$" in additional_info_patterns,
            "has_info_clear_callback": "^info_clear$" in additional_info_patterns,
        }
        dbg.section("birthday_additional_info_callbacks", {
            "patterns": sorted(additional_info_patterns),
            "checks": birthday_additional_info_checks,
        })
        if not all(birthday_additional_info_checks.values()):
            dbg.problem("birthday_additional_info_callbacks_failed", {
                "checks": birthday_additional_info_checks,
                "patterns": sorted(additional_info_patterns),
            })

        for alert in birthdays:
            next_occ = get_next_occurrence(alert, now)
            if next_occ is None:
                dbg.problem("next_occurrence_missing", {
                    "alert_id": alert.get("id"),
                    "date": alert.get("schedule", {}).get("date"),
                })
            dbg.section("birthday_summary", {
                "alert_id": alert.get("id"),
                "title": alert.get("title"),
                "active": alert.get("active", True),
                "date": alert.get("schedule", {}).get("date"),
                "time": alert.get("schedule", {}).get("time"),
                "next_occurrence": next_occ.isoformat() if next_occ else None,
            })

        upcoming, window_start, window_end = collect_window_occurrences(
            birthdays,
            now,
            C,
            past_days=10,
            future_days=60,
            include_inactive=False,
        )
        dbg.section("window_summary", {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "count": len(upcoming),
        })
        for item in upcoming:
            days_delta = (item["occurrence"].date() - now.date()).days
            if days_delta == 0:
                when_str = "today"
            elif days_delta > 0:
                when_str = f"in {days_delta}d"
            else:
                when_str = f"{abs(days_delta)}d ago"
            dbg.section("window_item", {
                "alert_id": item["alert_id"],
                "title": item["title"],
                "occurrence": item["occurrence"].isoformat(),
                "relative_day": when_str,
            })

        additional_info = "Line one\nLine two\nLine three"
        dbg.section("additional_info_sample", {
            "raw": additional_info,
            "lines": additional_info.splitlines(),
        })

        evening_date = (now + timedelta(days=1)).strftime("%d/%m")
        evening_alert = build_alert(
            "s_evening",
            "Evening Token",
            evening_date,
            C,
            pre_alerts=[C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN],
        )
        pre_label = format_bday_pre_alerts({"pre_alerts": [C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN]})
        evening_lines, _ = build_compact_birthday_lines(
            [evening_alert],
            default_time=getattr(C, "BIRTHDAY_DEFAULT_TIME", "08:00"),
            user_prefs={"birthday_evening_before_time": "20:00"},
        )
        evening_due = get_next_occurrence(evening_alert, now)
        evening_pre_dt, evening_pre_kind = resolve_pre_alert_fire_time(
            evening_alert,
            C.BIRTHDAY_PREALERT_EVENING_BEFORE_TOKEN,
            evening_due,
            user_prefs={"birthday_evening_before_time": "20:00"},
        )
        pre_date_label = (
            evening_pre_dt.strftime("%d %b").lower()
            if evening_pre_dt is not None
            else None
        )
        evening_checks = {
            "summary_label_humanized": pre_label == "evening before",
            "prealert_kind_resolved": evening_pre_kind == "birthday_evening_before",
            "compact_line_has_pre_marker": bool(len(evening_lines) > 1 and "🔔" in evening_lines[1]),
            "compact_line_has_expected_pre_date": bool(
                pre_date_label
                and len(evening_lines) > 1
                and pre_date_label in evening_lines[1]
            ),
        }
        dbg.section("birthday_evening_before_prealert", {
            "checks": evening_checks,
            "pre_label": pre_label,
            "lines": evening_lines,
            "pre_date_label": pre_date_label,
            "due": evening_due.isoformat() if evening_due else None,
            "pre": evening_pre_dt.isoformat() if evening_pre_dt else None,
        })
        if not all(evening_checks.values()):
            dbg.problem("birthday_evening_before_prealert_failed", {"checks": evening_checks})

        ordered_alert = build_alert(
            "s_ordered",
            "Ordered Token",
            (now + timedelta(days=12)).strftime("%d/%m"),
            C,
            pre_alerts=["1h", "1d"],
        )
        ordered_alert["birth_year"] = 1990
        ordered_lines, _ = build_compact_birthday_lines(
            [ordered_alert],
            default_time=getattr(C, "BIRTHDAY_DEFAULT_TIME", "08:00"),
            user_prefs={},
        )
        ordered_due = get_next_occurrence(ordered_alert, now)
        ordered_pre_1d, _ = resolve_pre_alert_fire_time(ordered_alert, "1d", ordered_due, user_prefs={})
        ordered_pre_1h, _ = resolve_pre_alert_fire_time(ordered_alert, "1h", ordered_due, user_prefs={})
        expected_1d = ordered_pre_1d.strftime("%d %b").lower() if ordered_pre_1d else None
        expected_1h = ordered_pre_1h.strftime("%d %b").lower() if ordered_pre_1h else None
        ordered_detail_line = ordered_lines[1] if len(ordered_lines) > 1 else ""
        ordered_checks = {
            "compact_has_pre_marker": "🔔" in ordered_detail_line,
            "compact_has_1d_date": bool(expected_1d and expected_1d in ordered_detail_line),
            "compact_has_1h_date": bool(expected_1h and expected_1h in ordered_detail_line),
            "compact_pre_dates_sorted": bool(
                expected_1d
                and expected_1h
                and expected_1d in ordered_detail_line
                and expected_1h in ordered_detail_line
                and ordered_detail_line.index(expected_1d) < ordered_detail_line.index(expected_1h)
            ),
            "compact_keeps_turning_suffix": "(turns " in ordered_detail_line,
        }
        dbg.section("birthday_compact_prealert_order", {
            "checks": ordered_checks,
            "ordered_lines": ordered_lines,
            "ordered_due": ordered_due.isoformat() if ordered_due else None,
            "expected_1d": expected_1d,
            "expected_1h": expected_1h,
        })
        if not all(ordered_checks.values()):
            dbg.problem("birthday_compact_prealert_order_failed", {"checks": ordered_checks})

        class _DummyContext:
            user_data = {"current_filter": "ALL", "birthday_current_filter": "Family"}

        list_kb = build_manage_list_keyboard("b123")
        active_bday = {"id": "b123", "active": True}
        inactive_bday = {"id": "b123", "active": False}
        info_kb = build_info_keyboard(
            "b123", _DummyContext(), source="birthdays", include_back=True, alert=active_bday
        )
        info_inactive_kb = build_info_keyboard(
            "b123", _DummyContext(), source="birthdays", include_back=True, alert=inactive_bday
        )
        info_noback_kb = build_info_keyboard(
            "b123", _DummyContext(), source="birthdays", include_back=False, alert=active_bday
        )
        info_rows = [[btn.text for btn in row] for row in info_kb.inline_keyboard]
        info_inactive_rows = [[btn.text for btn in row] for row in info_inactive_kb.inline_keyboard]
        info_noback_rows = [[btn.text for btn in row] for row in info_noback_kb.inline_keyboard]
        info_callbacks = [[btn.callback_data for btn in row] for row in info_kb.inline_keyboard]
        info_inactive_callbacks = [[btn.callback_data for btn in row] for row in info_inactive_kb.inline_keyboard]
        info_noback_callbacks = [[btn.callback_data for btn in row] for row in info_noback_kb.inline_keyboard]
        expected_rows = [
            [ACTION_LABEL_SNOOZE],
            [ACTION_LABEL_DELETE],
            ["✏️ Edit fields"],
            ["⬅️ Back (Family)"],
        ]
        expected_inactive_rows = [
            [ACTION_LABEL_ACTIVATE],
            [ACTION_LABEL_DELETE],
            ["✏️ Edit fields"],
            ["⬅️ Back (Family)"],
        ]
        expected_noback_rows = [
            [ACTION_LABEL_SNOOZE],
            [ACTION_LABEL_DELETE],
            ["✏️ Edit fields"],
        ]
        expected_callbacks = [
            ["manage_toggle_b123"],
            ["manage_del_b123"],
            ["manage_fulledit_b123"],
            ["manage_backtolist"],
        ]
        expected_inactive_callbacks = [
            ["manage_toggle_b123"],
            ["manage_del_b123"],
            ["manage_fulledit_b123"],
            ["manage_backtolist"],
        ]
        expected_noback_callbacks = [
            ["manage_toggle_b123"],
            ["manage_del_b123"],
            ["manage_fulledit_b123"],
        ]
        legacy_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Legacy edit", callback_data="manage_edittext_b123")
        ]])
        modern_message = type("Msg", (), {"reply_markup": info_kb})()
        legacy_message = type("Msg", (), {"reply_markup": legacy_markup})()
        keyboard_checks = {
            "list_row_kept_compact": [btn.text for btn in list_kb.inline_keyboard[0]] == ["ℹ️ INFO", "🔄 Snooze", "🗑️ DELETE"],
            "info_rows_match": info_rows == expected_rows,
            "info_inactive_rows_match": info_inactive_rows == expected_inactive_rows,
            "info_noback_rows_match": info_noback_rows == expected_noback_rows,
            "info_callbacks_match": info_callbacks == expected_callbacks,
            "info_inactive_callbacks_match": info_inactive_callbacks == expected_inactive_callbacks,
            "info_noback_callbacks_match": info_noback_callbacks == expected_noback_callbacks,
            "detail_view_detects_new_prefix": _message_is_detail_view(modern_message),
            "detail_view_detects_legacy_prefix": _message_is_detail_view(legacy_message),
            "all_rows_single_button": all(
                len(row) == 1 for row in info_rows + info_inactive_rows + info_noback_rows
            ),
        }
        dbg.section("birthday_manage_keyboard_labels", {
            "list_row": [btn.text for btn in list_kb.inline_keyboard[0]],
            "info_rows": info_rows,
            "info_inactive_rows": info_inactive_rows,
            "info_noback_rows": info_noback_rows,
            "info_callbacks": info_callbacks,
            "info_inactive_callbacks": info_inactive_callbacks,
            "info_noback_callbacks": info_noback_callbacks,
            "checks": keyboard_checks,
        })
        if not all(keyboard_checks.values()):
            dbg.problem("birthday_manage_info_keyboard_layout", {
                "checks": keyboard_checks,
                "info_rows": info_rows,
                "info_inactive_rows": info_inactive_rows,
                "info_noback_rows": info_noback_rows,
                "info_callbacks": info_callbacks,
                "info_inactive_callbacks": info_inactive_callbacks,
                "info_noback_callbacks": info_noback_callbacks,
            })

        bday_cancel_cleanup = run_birthday_cancel_cleanup_checks(birthday_flow_mod)
        dbg.section("birthday_cancel_cleanup", bday_cancel_cleanup)
        if not all((bday_cancel_cleanup.get("checks") or {}).values()):
            dbg.problem("birthday_cancel_cleanup_failed", bday_cancel_cleanup)

        home_text = build_birthday_home_text(["👨‍👩‍👧 Family"], {"👨‍👩‍👧 Family": 2}, 1)
        home_kb = build_birthday_home_keyboard()
        home_rows = [[btn.text for btn in row] for row in home_kb.inline_keyboard]
        dbg.section("birthday_home_menu", {
            "has_search_hint_line": "Search by name:" in home_text,
            "rows": home_rows,
        })
        if "Search by name:" in home_text:
            dbg.problem("birthday_home_text_legacy_hint", {})
        expected_rows = [
            ["➕ Add Birthday", "📅 Next Birthdays"],
            ["🔎 Search", "📋 Show ALL Birthdays"],
        ]
        if home_rows != expected_rows:
            dbg.problem("birthday_home_menu_layout", {
                "expected": expected_rows,
                "actual": home_rows,
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    source_ok = not dbg.has_problem("data_source_error", "cli_args_invalid", "cli_args_unknown")
    rules_ok = not dbg.has_problem(
        "sanity_checks_failed",
        "birthday_date_parser_contract_failed",
        "birthday_add_date_handler_parity_failed",
    )
    next_ok = not dbg.has_problem("next_occurrence_missing")
    ui_ok = not dbg.has_problem(
        "unhandled_exception",
        "birthday_home_text_legacy_hint",
        "birthday_home_menu_layout",
        "birthday_manage_info_keyboard_layout",
        "birthday_evening_before_prealert_failed",
        "birthday_cancel_cleanup_failed",
    )
    dbg.finish(summary_lines=[
        f"source: {'OK' if source_ok else 'FAIL'}",
        f"rules: {'OK' if rules_ok else 'FAIL'}",
        f"recurrence: {'OK' if next_ok else 'FAIL'}",
        f"ui: {'OK' if ui_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
