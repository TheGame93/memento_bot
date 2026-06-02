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
SCRIPT_TITLE = "context_state_debug"
FEATURE_TITLE = "Context Cleanup"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _sample_context():
    return {
        "temp_alert": {"title": "x"},
        "expecting_tag_name": True,
        "expecting_tag_rename": True,
        "tag_rename_old": "🍕 Food",
        "tag_edit_token_map": {},
        "expecting_alert_search": True,
        "expecting_birthday_search": True,
        "expecting_birthday_time": True,
        "expecting_birthday_evening_time": True,
        "expecting_bday_bulk_import_message": True,
        "bday_bulk_import_session": {"summary": {"valid_lines": 2}},
        "daily_interval_confirm_source": "interval_text_input",
        "expecting_edit_text": True,
        "edit_text_detail_ctx": {"kind": "due"},
        "edit_alert_id": "abc123",
        "edit_alert_original": {"title": "old"},
        "edit_origin_context": {"source": "notification", "message_id": 100},
        "expecting_custom_postpone": True,
        "postpone_kind": "due",
        "expecting_timezone_query": True,
        "expecting_timezone_location": True,
        "expecting_admin_add_user": True,
        "expecting_admin_custom_name": True,
        "expecting_start_request_message": True,
        "start_request_confirm_pending": True,
        "manage_del_ctx_abc": "list",
        "manage_del_back_abc": True,
        "postpone_alert_id": "a1",
        "current_filter": "Work",
        "alerts_current_page": 2,
        "birthdays_current_page": 3,
        "birthday_current_filter": "Family",
        "compact_list_context": {"source": "alerts"},
        "custom_persistent_value": 123,
    }


def _test_scoped_cleanup(dbg, clear_transient_context):
    user_data = _sample_context()
    clear_transient_context(user_data, include_navigation=False)

    checks = {
        "temp_alert_removed": "temp_alert" not in user_data,
        "search_flags_removed": "expecting_alert_search" not in user_data and "expecting_birthday_search" not in user_data,
        "settings_flags_removed": (
            "expecting_birthday_time" not in user_data
            and "expecting_birthday_evening_time" not in user_data
            and "expecting_bday_bulk_import_message" not in user_data
            and "bday_bulk_import_session" not in user_data
        ),
        "daily_confirm_source_removed": "daily_interval_confirm_source" not in user_data,
        "edit_flags_removed": "expecting_edit_text" not in user_data,
        "edit_detail_removed": "edit_text_detail_ctx" not in user_data,
        "edit_flow_keys_removed": (
            "edit_alert_id" not in user_data
            and "edit_alert_original" not in user_data
            and "edit_origin_context" not in user_data
        ),
        "postpone_flags_removed": "expecting_custom_postpone" not in user_data and "postpone_alert_id" not in user_data,
        "timezone_flags_removed": "expecting_timezone_query" not in user_data and "expecting_timezone_location" not in user_data,
        "admin_flags_removed": "expecting_admin_add_user" not in user_data and "expecting_admin_custom_name" not in user_data,
        "onboarding_flags_removed": "expecting_start_request_message" not in user_data and "start_request_confirm_pending" not in user_data,
        "tag_rename_keys_removed": (
            "expecting_tag_rename" not in user_data
            and "tag_rename_old" not in user_data
            and "tag_edit_token_map" not in user_data
        ),
        "dynamic_manage_keys_removed": not any(k.startswith("manage_del_ctx_") or k.startswith("manage_del_back_") for k in user_data),
        "navigation_preserved": user_data.get("current_filter") == "Work" and user_data.get("alerts_current_page") == 2,
        "custom_values_preserved": user_data.get("custom_persistent_value") == 123,
    }
    dbg.section("scoped_cleanup", {"checks": checks, "remaining_keys": sorted(user_data.keys())})
    if not all(checks.values()):
        dbg.problem("scoped_cleanup_failed", {"checks": checks, "remaining": user_data})


def _test_full_cleanup(dbg, clear_transient_context):
    user_data = _sample_context()
    clear_transient_context(user_data, include_navigation=True)

    checks = {
        "navigation_removed": "current_filter" not in user_data and "alerts_current_page" not in user_data,
        "birthday_navigation_removed": "birthday_current_filter" not in user_data and "birthdays_current_page" not in user_data,
        "list_context_removed": "compact_list_context" not in user_data,
        "custom_values_preserved": user_data.get("custom_persistent_value") == 123,
    }
    dbg.section("full_cleanup", {"checks": checks, "remaining_keys": sorted(user_data.keys())})
    if not all(checks.values()):
        dbg.problem("full_cleanup_failed", {"checks": checks, "remaining": user_data})


def _test_idempotent_cleanup(dbg, clear_transient_context):
    user_data = _sample_context()
    clear_transient_context(user_data, include_navigation=True)
    snapshot = dict(user_data)
    clear_transient_context(user_data, include_navigation=True)

    checks = {
        "stable_after_second_cleanup": user_data == snapshot,
        "only_persistent_key_left": sorted(user_data.keys()) == ["custom_persistent_value"],
    }
    dbg.section("idempotent_cleanup", {"checks": checks, "remaining_keys": sorted(user_data.keys())})
    if not all(checks.values()):
        dbg.problem("idempotent_cleanup_failed", {"checks": checks, "remaining": user_data})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.shared.context_cleanup import clear_transient_context
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_scoped_cleanup(dbg, clear_transient_context)
        _test_full_cleanup(dbg, clear_transient_context)
        _test_idempotent_cleanup(dbg, clear_transient_context)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    scoped_ok = not dbg.has_problem("scoped_cleanup_failed")
    full_ok = not dbg.has_problem("full_cleanup_failed")
    idempotent_ok = not dbg.has_problem("idempotent_cleanup_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"scoped: {'OK' if scoped_ok else 'FAIL'}",
        f"full: {'OK' if full_ok else 'FAIL'}",
        f"idempotent: {'OK' if idempotent_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
