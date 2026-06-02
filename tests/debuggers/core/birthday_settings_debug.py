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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "birthday_settings_debug"
FEATURE_TITLE = "Birthday Settings"

IMPORT_ERROR = None
try:
    from modules import constants as C
    from modules.handlers.base import (
        build_settings_keyboard,
        build_birthday_time_status,
        build_birthday_zodiac_status,
        build_settings_placeholder_status,
        normalize_time_input,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
    IMPORT_ERROR = exc


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

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        settings_kb = build_settings_keyboard()
        labels = [btn.text for row in settings_kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for row in settings_kb.inline_keyboard for btn in row]
        checks = {
            "no_birthday_time_entry": not any("Birthday time" in label for label in labels),
            "has_bdays_section": any("birthdays" in label.lower() for label in labels),
            "has_alerts_section": any("alerts" in label.lower() for label in labels),
            "has_bdays_callback": "settings_bdays" in callbacks,
            "has_alerts_callback": "settings_alerts" in callbacks,
            "no_legacy_birthday_time_callback": "settings_birthday_time" not in callbacks,
        }
        dbg.section("settings_keyboard", {"labels": labels, "callbacks": callbacks, "checks": checks})
        if not all(checks.values()):
            dbg.problem(
                "birthday_settings_keyboard_missing",
                {"checks": checks, "labels": labels, "callbacks": callbacks},
            )

        message, kb = build_birthday_time_status({"birthday_default_time": "07:30"})
        button_rows = kb.inline_keyboard
        btn_labels = [btn.text for row in button_rows for btn in row]
        callback_rows = [[btn.callback_data for btn in row] for row in button_rows]
        row_lengths = [len(row) for row in button_rows]
        status_checks = {
            "has_birthdays_title": "🎂 <b>Birthdays</b>" in message,
            "has_time": "07:30" in message,
            "has_evening_default": str(C.BIRTHDAY_EVENING_BEFORE_DEFAULT_TIME) in message,
            "has_bulk_capability_text": "export or import birthdays in bulk" in message,
            "has_set_default": any("Set default time" in label for label in btn_labels),
            "has_two_reset_to_default": sum(1 for label in btn_labels if "Reset to default" in label) == 2,
            "has_set_evening": any("Set evening-before time" in label for label in btn_labels),
            "has_bulk_export_button": any("Bulk Bday Export" in label for label in btn_labels),
            "has_bulk_import_button": any("Bulk Bday Import" in label for label in btn_labels),
            "layout_2_2_2_1_1": row_lengths == [2, 2, 2, 1, 1],
            "row1_callbacks": callback_rows[0] == ["settings_birthday_time_set", "settings_birthday_time_reset"] if len(callback_rows) > 0 else False,
            "row2_callbacks": callback_rows[1] == ["settings_birthday_evening_time_set", "settings_birthday_evening_time_reset"] if len(callback_rows) > 1 else False,
            "row3_callbacks_bulk": callback_rows[2] == ["settings_bday_bulk_export", "settings_bday_bulk_import"] if len(callback_rows) > 2 else False,
            "row4_callback_zodiac": callback_rows[3] == ["settings_bday_zodiac"] if len(callback_rows) > 3 else False,
            "row5_callback_back": callback_rows[4] == ["settings_back"] if len(callback_rows) > 4 else False,
            "has_back": any("Back" in label for label in btn_labels),
        }
        dbg.section(
            "birthday_status",
            {
                "message": message,
                "labels": btn_labels,
                "row_lengths": row_lengths,
                "callback_rows": callback_rows,
                "checks": status_checks,
            },
        )
        if not all(status_checks.values()):
            dbg.problem("birthday_status_failed", {"checks": status_checks, "labels": btn_labels})

        message_custom, _kb_custom = build_birthday_time_status({
            "birthday_default_time": "07:30",
            "birthday_evening_before_time": "21:15",
        })
        custom_checks = {
            "shows_custom_evening_time": "21:15" in message_custom,
        }
        dbg.section("birthday_status_custom_evening", {"checks": custom_checks, "message": message_custom})
        if not all(custom_checks.values()):
            dbg.problem("birthday_status_custom_evening_failed", {"checks": custom_checks})

        zodiac_prefs_none = {"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_NONE}
        zodiac_message, zodiac_kb = build_birthday_zodiac_status(zodiac_prefs_none)
        zodiac_rows = zodiac_kb.inline_keyboard
        zodiac_callbacks = [[btn.callback_data for btn in row] for row in zodiac_rows]
        zodiac_labels = [btn.text for row in zodiac_rows for btn in row]
        zodiac_checks = {
            "has_zodiac_title": "Zodiaco" in zodiac_message,
            "has_current_mode": "Disattivato" in zodiac_message,
            "has_five_rows": len(zodiac_rows) == 5,
            "row1_none": zodiac_callbacks[0] == ["settings_bday_zodiac_none"] if zodiac_callbacks else False,
            "row2_west": zodiac_callbacks[1] == ["settings_bday_zodiac_west"] if len(zodiac_callbacks) > 1 else False,
            "row3_east": zodiac_callbacks[2] == ["settings_bday_zodiac_east"] if len(zodiac_callbacks) > 2 else False,
            "row4_both": zodiac_callbacks[3] == ["settings_bday_zodiac_both"] if len(zodiac_callbacks) > 3 else False,
            "row5_back_bdays": zodiac_callbacks[4] == ["settings_bdays"] if len(zodiac_callbacks) > 4 else False,
        }
        zodiac_message_both, _ = build_birthday_zodiac_status({"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_BOTH})
        zodiac_checks["mode_both_shown"] = "Entrambi" in zodiac_message_both
        zodiac_message_none_prefs, _ = build_birthday_zodiac_status(None)
        zodiac_checks["handles_none_prefs"] = "Disattivato" in zodiac_message_none_prefs
        dbg.section(
            "zodiac_status",
            {
                "labels": zodiac_labels,
                "callbacks": zodiac_callbacks,
                "checks": zodiac_checks,
            },
        )
        if not all(zodiac_checks.values()):
            dbg.problem("birthday_zodiac_status_failed", {"checks": zodiac_checks, "labels": zodiac_labels})

        alerts_message, alerts_kb = build_settings_placeholder_status("alerts")
        alerts_buttons = [btn.callback_data for row in alerts_kb.inline_keyboard for btn in row]
        placeholder_checks = {
            "alerts_title": "Alert Settings" in alerts_message,
            "alerts_has_back": "settings_back" in alerts_buttons,
        }
        dbg.section(
            "settings_placeholders",
            {
                "alerts_buttons": alerts_buttons,
                "checks": placeholder_checks,
            },
        )
        if not all(placeholder_checks.values()):
            dbg.problem("settings_placeholder_failed", {"checks": placeholder_checks})

        norm_checks = {
            "accepts_single_digit": normalize_time_input("7:05") == "07:05",
            "rejects_invalid": normalize_time_input("24:00") is None,
        }
        dbg.section("normalize_time", {"checks": norm_checks})
        if not all(norm_checks.values()):
            dbg.problem("birthday_time_parse_failed", {"checks": norm_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ok = not dbg.problems
    dbg.finish(summary_lines=[f"birthday_settings: {'OK' if ok else 'FAIL'}"], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
