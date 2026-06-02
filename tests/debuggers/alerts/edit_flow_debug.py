#!/usr/bin/env python3
import os
import sys
import types


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
SCRIPT_TITLE = "edit_flow_debug"
FEATURE_TITLE = "Edit Flow Contracts"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _collect_failed_checks(section_payloads):
    failed = []
    for section_name, payload in section_payloads.items():
        checks = payload.get("checks")
        if not isinstance(checks, dict):
            continue
        for check_name, value in checks.items():
            if not value:
                failed.append(f"{section_name}:{check_name}")
    return failed


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    original_mainbot = sys.modules.get("mainbot")
    had_mainbot = "mainbot" in sys.modules
    mainbot_stub = types.SimpleNamespace(storage=None)

    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()
        sys.modules["mainbot"] = mainbot_stub

        try:
            from modules.handlers.add_flow import flow_start as add_flow_start_mod
            from modules.handlers.add_flow import repetition_flow as repetition_flow_mod
            from modules.handlers.add_flow import settings_flow as settings_flow_mod
            from modules.handlers.add_flow import type_flow as type_flow_mod
            from modules.handlers.edit_flow import dashboard as dashboard_mod
            from modules.handlers.edit_flow import flow as flow_mod
            import edit_flow_checks as checks_mod
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        def _runtime_storage_override(_context):
            return mainbot_stub.storage

        for module in (
            flow_mod,
            type_flow_mod,
            settings_flow_mod,
            repetition_flow_mod,
            add_flow_start_mod,
        ):
            if hasattr(module, "get_runtime_storage"):
                setattr(module, "get_runtime_storage", _runtime_storage_override)

        sections = {
            "dashboard_keyboard": checks_mod.run_dashboard_keyboard_checks(dashboard_mod),
            "commit_plan": checks_mod.run_commit_plan_checks(flow_mod),
            "one_time_edit_source": checks_mod.run_one_time_edit_source_checks(mainbot_stub),
            "start_edit": checks_mod.run_start_edit_checks(flow_mod, mainbot_stub),
            "origin_context_capture": checks_mod.run_notification_origin_context_capture_checks(flow_mod, mainbot_stub),
            "start_edit_failure_cleanup": checks_mod.run_start_edit_failure_cleanup_checks(flow_mod, mainbot_stub),
            "ed_tags_preselected": checks_mod.run_ed_tags_preselected_checks(flow_mod, mainbot_stub),
            "ed_repetition_route": checks_mod.run_ed_repetition_route_checks(flow_mod, mainbot_stub),
            "ed_schedule_route": checks_mod.run_ed_schedule_route_checks(flow_mod, mainbot_stub),
            "ed_name_prompt_context": checks_mod.run_ed_name_prompt_context_checks(flow_mod, mainbot_stub),
            "ed_additional_info_clear": checks_mod.run_edit_additional_info_clear_checks(flow_mod, mainbot_stub),
            "photo_origin_start_edit": checks_mod.run_photo_origin_start_edit_checks(flow_mod, mainbot_stub),
            "photo_origin_edit_choice": checks_mod.run_photo_origin_edit_choice_checks(flow_mod, mainbot_stub),
            "ed_birthday_date_route": checks_mod.run_ed_birthday_date_route_checks(flow_mod, mainbot_stub),
            "ed_birthday_date_input": checks_mod.run_ed_birthday_date_input_checks(flow_mod, mainbot_stub),
            "daily_prompt_callback_context": checks_mod.run_daily_prompt_callback_context_checks(flow_mod, mainbot_stub),
            "daily_interval_prompt_source": checks_mod.run_daily_interval_prompt_source_checks(),
            "birthday_prealert_edit_context": checks_mod.run_birthday_prealert_edit_context_checks(flow_mod, mainbot_stub),
            "pre_alert_custom_edit_parity": checks_mod.run_pre_alert_custom_edit_parity_checks(flow_mod, mainbot_stub),
            "origin_context_persistence": checks_mod.run_edit_origin_context_persistence_checks(flow_mod, mainbot_stub),
            "notification_origin_commit": checks_mod.run_commit_notification_origin_completion_checks(flow_mod, mainbot_stub),
            "pre_alert_tracking_clear": checks_mod.run_pre_alert_tracking_clear_checks(),
            "postpone_expire": checks_mod.run_postpone_expire_checks(),
            "cancel_cleanup": checks_mod.run_cancel_cleanup_checks(flow_mod, mainbot_stub),
            "change_type_same_type": checks_mod.run_change_type_same_type_checks(settings_flow_mod),
        }

        for section_name, payload in sections.items():
            dbg.section(section_name, payload)

        failed_checks = _collect_failed_checks(sections)
        if failed_checks:
            dbg.problem("edit_flow_checks_failed", {"failed_checks": failed_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        if had_mainbot:
            sys.modules["mainbot"] = original_mainbot
        else:
            sys.modules.pop("mainbot", None)

    checks_ok = not dbg.has_problem("edit_flow_checks_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(
        summary_lines=[
            f"edit_flow_checks: {'OK' if checks_ok else 'FAIL'}",
            f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        ],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
