#!/usr/bin/env python3
import logging
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
from _lib.runtime import run_async
from _lib.warnings_policy import suppress_ptb_user_warning
from alerts.scheduler_behavior_checks import SchedulerBehaviorDeps, run_checks

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "scheduler_behavior_debug"
FEATURE_TITLE = "Scheduler Behavior"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        suppress_ptb_user_warning()

        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as constants_module
            from modules import scheduler as scheduler_module
            from modules.scheduler_mathlogic import get_constants_compatibility_issues, get_next_occurrence
            from modules.scheduler_messagelogic import (
                format_main_alert,
                format_missed_alert,
                format_missed_alerts_summary,
                format_pre_alert,
                get_alert_keyboard,
                get_pre_alert_keyboard,
                send_alert,
                send_done_confirmation,
                send_snooze_confirmation,
            )
            from modules.handlers.list_alerts import format_detailed_card
            from modules.storage import StorageManager
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        deps = SchedulerBehaviorDeps(
            constants=constants_module,
            scheduler_module=scheduler_module,
            get_constants_compatibility_issues=get_constants_compatibility_issues,
            get_next_occurrence=get_next_occurrence,
            format_main_alert=format_main_alert,
            format_pre_alert=format_pre_alert,
            format_missed_alert=format_missed_alert,
            format_missed_alerts_summary=format_missed_alerts_summary,
            get_alert_keyboard=get_alert_keyboard,
            get_pre_alert_keyboard=get_pre_alert_keyboard,
            send_alert=send_alert,
            send_snooze_confirmation=send_snooze_confirmation,
            send_done_confirmation=send_done_confirmation,
            format_detailed_card=format_detailed_card,
            storage_manager_cls=StorageManager,
        )
        run_checks(dbg, deps, run_async)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        logging.disable(previous_disable_level)

    constants_ok = not dbg.has_problem("constants_incompatible")
    missed_ok = not dbg.has_problem(
        "missed_toggle_behavior_failed",
        "type2_last_cached_repair_failed",
    )
    messages_ok = not dbg.has_problem("fired_message_checks_failed")
    detail_ok = not dbg.has_problem("detail_repetition_rendering_failed")
    toggle_dispatch_ok = not dbg.has_problem("toggle_context_dispatch_failed")
    media_ok = not dbg.has_problem(
        "scheduler_media_fallback_checks_failed",
        "scheduler_storage_scope_guard_failed",
    )
    markdown_ok = not dbg.has_problem(
        "scheduler_markdown_hardening_failed",
        "scheduler_markdown_escape_helper_missing",
    )
    boundary_ok = not dbg.has_problem("creation_boundary_checks_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"constants: {'OK' if constants_ok else 'FAIL'}",
        f"missed-state: {'OK' if missed_ok else 'FAIL'}",
        f"fired-msg: {'OK' if messages_ok else 'FAIL'}",
        f"detail-repetition: {'OK' if detail_ok else 'FAIL'}",
        f"toggle-dispatch: {'OK' if toggle_dispatch_ok else 'FAIL'}",
        f"media-fallback: {'OK' if media_ok else 'FAIL'}",
        f"markdown-harden: {'OK' if markdown_ok else 'FAIL'}",
        f"boundaries: {'OK' if boundary_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
