#!/usr/bin/env python3
import json
import os
import platform
import sys
import copy
import logging
import tempfile
from datetime import datetime, timedelta

# Allow running from any nested debugger folder.
def _find_root_dir(start_path):
    current = os.path.abspath(os.path.dirname(start_path))
    while True:
        if os.path.exists(os.path.join(current, "mainbot.py")) and os.path.isdir(os.path.join(current, "modules")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(os.path.dirname(start_path), "..", "..", ".."))
        current = parent


ROOT_DIR = _find_root_dir(__file__)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

ARGS = sys.argv[1:]
VERBOSE = "--verbose" in ARGS
QUIET = "--quiet" in ARGS and not VERBOSE

LOG_FILE = None
LOG_PATH = None
PROBLEMS = []
SCRIPT_TITLE = "debug_script"
FEATURE_TITLE = "Core Alert Logic"

def _write_log(line):
    if LOG_FILE:
        LOG_FILE.write(line + "\n")
        LOG_FILE.flush()

def _log_problem(message, payload=None):
    PROBLEMS.append(message)
    record = {"section": "problem", "message": message, "payload": payload or {}}
    _write_log(json.dumps(record, indent=2, default=str))


def _has_problem(*codes):
    return any(code in PROBLEMS for code in codes)


def _print_compact_summary():
    if QUIET:
        return
    recurrence_ok = not _has_problem("next_occurrence_missing")
    prealert_ok = not _has_problem("pre_alert_parse_failed")
    snooze_ok = not _has_problem("snooze_limit_missing_next")
    storage_ok = not _has_problem("unhandled_exception")
    print(f"[{SCRIPT_TITLE}] {FEATURE_TITLE}")
    print(f"- recurrence: {'OK' if recurrence_ok else 'FAIL'}")
    print(f"- pre-alerts: {'OK' if prealert_ok else 'FAIL'}")
    print(f"- snooze: {'OK' if snooze_ok else 'FAIL'}")
    print(f"- storage: {'OK' if storage_ok else 'FAIL'}")

try:
    from modules import constants as C
    from modules.scheduler_mathlogic import (
        get_next_occurrence,
        is_due,
        calculate_pre_alert_times,
        parse_pre_alert_string,
        resolve_pre_alert_fire_time,
        calculate_snooze_time,
        can_snooze_to,
        get_snooze_limit,
        format_pre_alert_human,
        DUE_TOLERANCE_SECONDS,
    )
    from modules.scheduler_messagelogic import (
        ACTION_LABEL_DELETE,
        ACTION_LABEL_SNOOZE,
        format_missed_alerts_summary,
    )
    from modules.storage import StorageManager
    from modules.handlers.list_alerts import build_manage_list_keyboard, build_info_keyboard
except ModuleNotFoundError as exc:
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    log_path = os.path.join(os.path.dirname(__file__), f"{script_name}.log")
    error_payload = {
        "section": "dependency_error",
        "error": str(exc),
        "hint": "Missing dependencies. Activate venv and install requirements.",
        "suggested_commands": [
            "source venv/bin/activate",
            "pip install -r pythonrequirements.txt"
        ],
    }
    try:
        with open(log_path, "w") as f:
            f.write(json.dumps(error_payload, indent=2) + "\n")
    except OSError:
        pass
    if not QUIET:
        print(f"Debug script failed. See {log_path} for details.")
    sys.exit(1)


def print_section(label, payload):
    record = {"section": label, **payload}
    rendered = json.dumps(record, indent=2, default=str)
    _write_log(rendered)
    if VERBOSE:
        print(rendered)


def build_alert(alert_id, title, a_type, schedule, pre_alerts=None, tags=None):
    return {
        "id": alert_id,
        "title": title,
        "type": a_type,
        "type_name": C.ALERT_TYPES.get(a_type, "Unknown"),
        "schedule": schedule,
        "pre_alerts": pre_alerts or [],
        "tags": tags or [],
        "active": True,
    }

def describe_delta(delta):
    if delta is None:
        return None
    if isinstance(delta, timedelta):
        return {"type": "timedelta", "seconds": int(delta.total_seconds())}
    parts = {}
    for key in ("years", "months", "days", "hours", "minutes", "seconds"):
        value = getattr(delta, key, 0)
        if value:
            parts[key] = value
    return {"type": "relativedelta", "parts": parts}


def simulate_due_window(alert, scheduled_time, tick_seconds, ticks_before=3, ticks_after=6):
    if not scheduled_time:
        return []
    start = scheduled_time - timedelta(seconds=tick_seconds * ticks_before)
    total_ticks = ticks_before + ticks_after + 1
    results = []
    for i in range(total_ticks):
        t = start + timedelta(seconds=tick_seconds * i)
        results.append({
            "tick_index": i - ticks_before,
            "time": t.isoformat(),
            "is_due": is_due(alert, t),
        })
    return results


def simulate_scheduler_cycle(alert, scheduled_time, tick_seconds, ticks_before=3, ticks_after=6):
    """
    Simulates scheduler ticks with state updates after the first fire.
    This mirrors runtime behavior: once an alert fires, next_scheduled advances,
    so subsequent ticks should not re-fire the same occurrence.
    """
    if not scheduled_time:
        return {"events": [], "ticks": []}

    alert_state = copy.deepcopy(alert)
    alert_state["next_scheduled"] = scheduled_time.isoformat()
    alert_state["last_triggered"] = None

    start = scheduled_time - timedelta(seconds=tick_seconds * ticks_before)
    total_ticks = ticks_before + ticks_after + 1
    fired_once = False
    events = []
    ticks = []

    for i in range(total_ticks):
        t = start + timedelta(seconds=tick_seconds * i)
        due = is_due(alert_state, t)
        ticks.append({
            "tick_index": i - ticks_before,
            "time": t.isoformat(),
            "next_scheduled": alert_state.get("next_scheduled"),
            "is_due": due,
        })

        if due and not fired_once:
            fired_once = True
            events.append({
                "action": "fire",
                "tick_index": i - ticks_before,
                "time": t.isoformat(),
                "scheduled_time": alert_state.get("next_scheduled"),
            })

            # Update state like trigger_alert does
            if alert_state.get("type") == 5:
                alert_state["active"] = False
                alert_state["last_triggered"] = t.isoformat()
                alert_state["next_scheduled"] = None
            else:
                next_occ = get_next_occurrence(alert_state, scheduled_time)
                alert_state["last_triggered"] = t.isoformat()
                alert_state["next_scheduled"] = next_occ.isoformat() if next_occ else None

    return {"events": events, "ticks": ticks}


def main():
    logging.basicConfig(level=logging.ERROR)
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    log_path = os.path.join(os.path.dirname(__file__), f"{script_name}.log")
    global LOG_FILE, LOG_PATH
    LOG_PATH = log_path
    LOG_FILE = open(log_path, "w")
    try:
        now = datetime.now()
        print_section("run_meta", {
            "run_time": now.isoformat(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "scheduler_interval_seconds": C.SCHEDULER_INTERVAL_SECONDS,
            "due_tolerance_seconds": DUE_TOLERANCE_SECONDS,
            "birthday_policy": getattr(C, "BIRTHDAY_FEB29_POLICY", None),
            "birthday_default_time": getattr(C, "BIRTHDAY_DEFAULT_TIME", None),
            "log_file": log_path,
        })

        alerts = [
            build_alert(
                "t1",
                "Monthly Days Test",
                1,
                {"days": [1, 15], "interval": 1, "time": "10:00"},
                pre_alerts=["1w", "3mo", "1h", "3h", "30m", "1d"],
                tags=["Test"],
            ),
            build_alert(
                "t2",
                "Monthly Relative Test",
                2,
                {"ordinals": ["1st", "Last"], "weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            ),
            build_alert(
                "t3",
                "Weekly Test",
                3,
                {"weekdays": ["Mon", "Fri"], "interval": 1, "time": "10:00"},
            ),
            build_alert(
                "t4",
                "Yearly Test",
                4,
                {"dates": "25/12", "time": "10:00"},
            ),
            build_alert(
                "t5",
                "One Time Test",
                5,
                {"date": (now + timedelta(days=10)).strftime("%d/%m/%Y"), "time": "10:00"},
            ),
            build_alert(
                "t6",
                "Birthday Test",
                6,
                {"date": "29/02", "time": C.BIRTHDAY_DEFAULT_TIME},
            ),
            build_alert(
                "t7",
                "Defaults Test (No Time/Interval)",
                1,
                {"days": [1]},
                pre_alerts=["1h"],
            ),
            build_alert(
                "t8",
                "Daily Test",
                7,
                {"interval": 10, "time": "09:30", "start_marker": "01/03/2026"},
            ),
        ]

        for alert in alerts:
            next_occ = get_next_occurrence(alert, now)
            if not next_occ:
                _log_problem("next_occurrence_missing", {
                    "alert_id": alert.get("id"),
                    "type": alert.get("type"),
                    "schedule": alert.get("schedule"),
                })
            due_sim = simulate_due_window(
                alert,
                next_occ,
                C.SCHEDULER_INTERVAL_SECONDS,
                ticks_before=3,
                ticks_after=6,
            )
            scheduler_sim = simulate_scheduler_cycle(
                alert,
                next_occ,
                C.SCHEDULER_INTERVAL_SECONDS,
                ticks_before=3,
                ticks_after=6,
            )
            print_section("alert_summary", {
                "alert_id": alert["id"],
                "title": alert["title"],
                "type": alert["type"],
                "type_name": alert["type_name"],
                "schedule": alert["schedule"],
                "pre_alerts": alert.get("pre_alerts"),
                "next_occurrence": next_occ.isoformat() if next_occ else None,
                "due_simulation": due_sim,
                "scheduler_simulation": scheduler_sim,
            })

            if alert.get("pre_alerts"):
                invalid_units = []
                for pa in alert.get("pre_alerts"):
                    if parse_pre_alert_string(pa):
                        continue
                    resolved_pre, _kind = resolve_pre_alert_fire_time(alert, pa, next_occ)
                    if not resolved_pre:
                        invalid_units.append(pa)
                if invalid_units:
                    _log_problem("pre_alert_parse_failed", {
                        "alert_id": alert.get("id"),
                        "invalid": invalid_units,
                    })
                pre_times = calculate_pre_alert_times(alert, next_occ)
                print_section("pre_alert_times", {
                    "alert_id": alert["id"],
                    "main_time": next_occ.isoformat() if next_occ else None,
                    "pre_alerts": alert.get("pre_alerts"),
                    "computed_times": [
                        {"pre_alert": pa, "time": dt.isoformat()}
                        for dt, pa in pre_times
                    ],
                })

        # Edge case checks
        sample_units = ["15m", "2h", "1d", "1w", "1mo", "3mo", "5x"]
        parsed_units = {
            unit: describe_delta(parse_pre_alert_string(unit))
            for unit in sample_units
        }
        print_section("pre_alert_parse_samples", {"samples": parsed_units})

        human_units = {unit: format_pre_alert_human(unit) for unit in sample_units}
        print_section("pre_alert_human_samples", {"samples": human_units})

        # Snooze logic samples
        snooze_from = now.replace(second=0, microsecond=0)
        snooze_samples = ["30m", "2h", "1d", "1w", "1mo", "5x"]
        snooze_results = {}
        for unit in snooze_samples:
            target = calculate_snooze_time(unit, snooze_from)
            snooze_results[unit] = target.isoformat() if target else None
        print_section("snooze_calculate_samples", {"from_time": snooze_from.isoformat(), "samples": snooze_results})

        # Snooze limit check for recurring alerts
        recurring_alert = build_alert(
            "s1",
            "Weekly Snooze Limit Test",
            3,
            {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
        )
        recurring_next = get_next_occurrence(recurring_alert, now)
        recurring_alert["next_scheduled"] = recurring_next.isoformat() if recurring_next else None
        if not recurring_next:
            _log_problem("snooze_limit_missing_next", {"alert_id": recurring_alert.get("id")})
        limit = get_snooze_limit(recurring_alert)
        snooze_ok = None
        snooze_blocked = None
        if limit:
            snooze_ok = limit - timedelta(hours=1)
            snooze_blocked = limit + timedelta(hours=1)
        can_ok = can_snooze_to(recurring_alert, snooze_ok)[0] if snooze_ok else None
        can_block = can_snooze_to(recurring_alert, snooze_blocked)[0] if snooze_blocked else None
        print_section("snooze_limit_check", {
            "next_scheduled": recurring_alert.get("next_scheduled"),
            "limit": limit.isoformat() if limit else None,
            "snooze_ok": snooze_ok.isoformat() if snooze_ok else None,
            "snooze_ok_allowed": can_ok,
            "snooze_blocked": snooze_blocked.isoformat() if snooze_blocked else None,
            "snooze_blocked_allowed": can_block,
        })

        # Scheduler logic regression checks (interval anchoring + yearly multi-date + monthly-rel spill)
        yearly_multi = build_alert(
            "yr_multi",
            "Yearly Multi-Date",
            4,
            {"dates": "25/12, 01/01", "time": "10:00"},
        )
        yearly_next = get_next_occurrence(yearly_multi, datetime(2026, 12, 30, 12, 0))

        weekly_anchor = build_alert(
            "wk_anchor",
            "Weekly Anchor",
            3,
            {"weekdays": ["Mon", "Thu"], "interval": 2, "time": "10:00", "start_marker": "03/02/2026"},
        )
        weekly_next = get_next_occurrence(weekly_anchor, datetime(2026, 2, 5, 10, 0))

        monthly_rel = build_alert(
            "mr_5th",
            "Monthly Relative 5th Monday",
            2,
            {"ordinals": ["5th"], "weekdays": ["Mon"], "interval": 1, "time": "10:00"},
        )
        monthly_rel_next = get_next_occurrence(monthly_rel, datetime(2026, 2, 1, 0, 0))

        daily_anchor = build_alert(
            "daily_anchor",
            "Daily Anchored",
            7,
            {"interval": 3, "time": "10:00", "start_marker": "01/03/2026"},
        )
        daily_next = get_next_occurrence(daily_anchor, datetime(2026, 3, 7, 10, 0))

        regression_checks = {
            "yearly_multi_selects_jan1_next_year": (
                yearly_next is not None
                and yearly_next.year == 2027
                and yearly_next.month == 1
                and yearly_next.day == 1
            ),
            "weekly_interval_respects_start_marker_anchor": (
                weekly_next is not None
                and weekly_next.year == 2026
                and weekly_next.month == 2
                and weekly_next.day == 16
            ),
            "monthly_rel_5th_weekday_does_not_spill_to_first_next_month": (
                monthly_rel_next is not None
                and monthly_rel_next.year == 2026
                and monthly_rel_next.month == 3
                and monthly_rel_next.day == 30
            ),
            "daily_interval_is_strict_future_even_at_exact_reference": (
                daily_next is not None
                and daily_next.year == 2026
                and daily_next.month == 3
                and daily_next.day == 10
                and daily_next.hour == 10
                and daily_next.minute == 0
            ),
        }
        print_section("scheduler_regression_checks", {
            "checks": regression_checks,
            "yearly_next": yearly_next.isoformat() if yearly_next else None,
            "weekly_next": weekly_next.isoformat() if weekly_next else None,
            "monthly_rel_next": monthly_rel_next.isoformat() if monthly_rel_next else None,
            "daily_next": daily_next.isoformat() if daily_next else None,
        })
        if not all(regression_checks.values()):
            _log_problem("scheduler_logic_regression_failed", {
                "checks": regression_checks,
                "yearly_next": yearly_next.isoformat() if yearly_next else None,
                "weekly_next": weekly_next.isoformat() if weekly_next else None,
                "monthly_rel_next": monthly_rel_next.isoformat() if monthly_rel_next else None,
                "daily_next": daily_next.isoformat() if daily_next else None,
            })

        # Missed summary formatting preview
        sample_items = [
            {
                "alert": build_alert(
                    "m1",
                    "Missed Due + Pre",
                    1,
                    {"days": [1], "interval": 1, "time": "10:00"},
                    pre_alerts=["1h", "1d"],
                ),
                "missed_pre": [now - timedelta(hours=2), now - timedelta(days=1)],
                "missed_due": [now - timedelta(hours=1)],
                "upcoming_pre": [now + timedelta(hours=2)],
                "upcoming_due": [now + timedelta(hours=5)],
            },
            {
                "alert": build_alert(
                    "m2",
                    "Missed Pre Only",
                    1,
                    {"days": [1], "interval": 1, "time": "10:00"},
                    pre_alerts=["1d"],
                ),
                "missed_pre": [now - timedelta(hours=3)],
                "missed_due": [],
                "upcoming_pre": [now + timedelta(hours=1)],
                "upcoming_due": [now + timedelta(hours=4)],
            },
        ]
        summary_text = format_missed_alerts_summary(sample_items)
        print_section("missed_summary_preview", {
            "text": summary_text
        })

        additional_info = "Line one\\nLine two\\nLine three"
        print_section("additional_info_sample", {
            "raw": additional_info,
            "lines": additional_info.splitlines(),
        })

        # Management keyboard checks
        class _DummyContext:
            user_data = {"current_filter": "Work", "birthday_current_filter": "Family"}

        list_kb = build_manage_list_keyboard("abc123")
        info_alert_kb = build_info_keyboard("abc123", _DummyContext(), source="alerts", include_back=True)
        info_bday_kb = build_info_keyboard("abc123", _DummyContext(), source="birthdays", include_back=True)
        info_noback_kb = build_info_keyboard("abc123", _DummyContext(), source="alerts", include_back=False)
        info_alert_rows = [[btn.text for btn in row] for row in info_alert_kb.inline_keyboard]
        info_bday_rows = [[btn.text for btn in row] for row in info_bday_kb.inline_keyboard]
        info_noback_rows = [[btn.text for btn in row] for row in info_noback_kb.inline_keyboard]
        info_alert_callbacks = [[btn.callback_data for btn in row] for row in info_alert_kb.inline_keyboard]
        info_bday_callbacks = [[btn.callback_data for btn in row] for row in info_bday_kb.inline_keyboard]
        info_noback_callbacks = [[btn.callback_data for btn in row] for row in info_noback_kb.inline_keyboard]

        expected_alert_rows = [
            [ACTION_LABEL_SNOOZE],
            [ACTION_LABEL_DELETE],
            ["✏️ Edit text"],
            ["⬅️ Back (Work)"],
        ]
        expected_bday_rows = [
            [ACTION_LABEL_SNOOZE],
            [ACTION_LABEL_DELETE],
            ["✏️ Edit text"],
            ["⬅️ Back (Family)"],
        ]
        expected_noback_rows = [
            [ACTION_LABEL_SNOOZE],
            [ACTION_LABEL_DELETE],
            ["✏️ Edit text"],
        ]
        expected_with_back_callbacks = [
            ["manage_toggle_abc123"],
            ["manage_del_abc123"],
            ["manage_edittext_abc123"],
            ["manage_backtolist"],
        ]
        expected_noback_callbacks = [
            ["manage_toggle_abc123"],
            ["manage_del_abc123"],
            ["manage_edittext_abc123"],
        ]

        manage_checks = {
            "list_row_kept_compact": [btn.text for btn in list_kb.inline_keyboard[0]] == ["ℹ️ INFO", "🔄 Snooze", "🗑️ DELETE"],
            "info_alert_rows": info_alert_rows == expected_alert_rows,
            "info_bday_rows": info_bday_rows == expected_bday_rows,
            "info_noback_rows": info_noback_rows == expected_noback_rows,
            "info_alert_callbacks": info_alert_callbacks == expected_with_back_callbacks,
            "info_bday_callbacks": info_bday_callbacks == expected_with_back_callbacks,
            "info_noback_callbacks": info_noback_callbacks == expected_noback_callbacks,
            "all_info_rows_single_button": (
                all(len(row) == 1 for row in info_alert_rows)
                and all(len(row) == 1 for row in info_bday_rows)
                and all(len(row) == 1 for row in info_noback_rows)
            ),
        }
        print_section("manage_keyboard_labels", {
            "list_row": [btn.text for btn in list_kb.inline_keyboard[0]],
            "info_alert_rows": info_alert_rows,
            "info_bday_rows": info_bday_rows,
            "info_noback_rows": info_noback_rows,
            "info_alert_callbacks": info_alert_callbacks,
            "info_bday_callbacks": info_bday_callbacks,
            "info_noback_callbacks": info_noback_callbacks,
            "checks": manage_checks,
        })
        if not all(manage_checks.values()):
            _log_problem("manage_info_keyboard_layout", {
                "checks": manage_checks,
                "info_alert_rows": info_alert_rows,
                "info_bday_rows": info_bday_rows,
                "info_noback_rows": info_noback_rows,
                "info_alert_callbacks": info_alert_callbacks,
                "info_bday_callbacks": info_bday_callbacks,
                "info_noback_callbacks": info_noback_callbacks,
            })

        # Storage check for multiline custom text persistence
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StorageManager(base_data_dir=tmpdir)
            user_id = "999"
            storage.setup_user_space(user_id)
            alert_data = build_alert(
                "tmp",
                "Custom Text Test",
                3,
                {"weekdays": ["Mon"], "interval": 1, "time": "10:00"},
            )
            alert_data.pop("id", None)
            alert_id = storage.save_alert(user_id, alert_data)
            text_value = "Line one\nLine two\nLine three"
            updated = storage.update_alert_fields(user_id, alert_id, {"additional_info": text_value})
            alert_loaded = storage.get_alert_by_id(user_id, alert_id)
            cleared = storage.update_alert_fields(user_id, alert_id, {"additional_info": ""})
            alert_cleared = storage.get_alert_by_id(user_id, alert_id)
            toggled_existing = storage.toggle_alert(user_id, alert_id)
            toggled_missing = storage.toggle_alert(user_id, "missing-alert-id")
            all_data = storage.get_all_alerts(user_id) or {}
            schema_has_postpone_queue = isinstance(all_data.get("postpone_queue"), list)
            print_section("custom_text_storage_check", {
                "updated": updated,
                "stored_equals": (alert_loaded or {}).get("additional_info") == text_value,
                "cleared": cleared,
                "cleared_value": (alert_cleared or {}).get("additional_info"),
                "toggle_existing_type": type(toggled_existing).__name__,
                "toggle_missing": toggled_missing,
                "schema_has_postpone_queue": schema_has_postpone_queue,
            })
            if not schema_has_postpone_queue:
                _log_problem("storage_schema_missing_postpone_queue", {})
            if toggled_missing is not None:
                _log_problem("storage_toggle_missing_should_be_none", {"value": toggled_missing})
    except Exception as exc:
        _log_problem("unhandled_exception", {"error": str(exc)})
    finally:
        if LOG_FILE:
            LOG_FILE.close()

    _print_compact_summary()
    if PROBLEMS and not QUIET:
        print(f"- details: {len(PROBLEMS)} issue(s)")
        print(f"- logfile: {LOG_PATH}")


if __name__ == "__main__":
    main()
