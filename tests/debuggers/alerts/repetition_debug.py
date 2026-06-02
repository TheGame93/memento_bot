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
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "repetition_debug"
FEATURE_TITLE = "Repetition Constants Contracts"


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
    try:
        suppress_ptb_user_warning()

        unknown = _parse_cli_args(dbg.args)
        if unknown:
            dbg.problem("cli_args_unknown", {"unknown": unknown, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules import constants as C
            from modules import repetition_utils as repetition_utils
            from modules.scheduler_core import actions as scheduler_actions
            from modules.scheduler_core import coordinator as scheduler_coordinator
            from modules.scheduler_core import missed as scheduler_missed
            from modules import scheduler_mathlogic as scheduler_mathlogic
            from modules import storage as storage_mod
            from modules.handlers.add_flow import repetition_flow
            import repetition_checks as checks_mod
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        def _runtime_storage_override(_context):
            return getattr(sys.modules.get("mainbot"), "storage", None)

        if hasattr(repetition_flow, "get_runtime_storage"):
            repetition_flow.get_runtime_storage = _runtime_storage_override

        states = {
            "GET_REPETITION_MENU": getattr(C, "GET_REPETITION_MENU", None),
            "GET_REPETITION_COUNT": getattr(C, "GET_REPETITION_COUNT", None),
            "GET_REPETITION_UNTIL_DATE": getattr(C, "GET_REPETITION_UNTIL_DATE", None),
        }
        modes = {
            "REPETITION_MODE_FOREVER": getattr(C, "REPETITION_MODE_FOREVER", None),
            "REPETITION_MODE_UNTIL_DATE": getattr(C, "REPETITION_MODE_UNTIL_DATE", None),
            "REPETITION_MODE_COUNT": getattr(C, "REPETITION_MODE_COUNT", None),
        }
        supported_types = getattr(C, "REPETITION_SUPPORTED_TYPES", None)

        checks = {
            "states_exist": all(value is not None for value in states.values()),
            "states_are_int": all(isinstance(value, int) for value in states.values()),
            "states_unique": len(set(states.values())) == len(states),
            "modes_exist": all(isinstance(value, str) and value for value in modes.values()),
            "modes_unique": len(set(modes.values())) == len(modes),
            "supported_types_set": isinstance(supported_types, set),
            "supported_types_exact": supported_types == {1, 2, 3, 4, 7},
            "unsupported_missing": 5 not in (supported_types or set()) and 6 not in (supported_types or set()),
        }

        sections = {
            "repetition_constants": {
                "states": states,
                "modes": modes,
                "supported_types": sorted(supported_types) if isinstance(supported_types, set) else supported_types,
                "checks": checks,
            },
            "support_checks": checks_mod.run_support_checks(repetition_utils),
            "default_payload_checks": checks_mod.run_default_payload_checks(repetition_utils, C),
            "parse_until_date_checks": checks_mod.run_parse_until_date_checks(repetition_utils),
            "parse_until_date_input_checks": checks_mod.run_parse_until_date_input_checks(repetition_utils),
            "normalize_payload_checks": checks_mod.run_normalize_payload_checks(repetition_utils, C),
            "format_human_checks": checks_mod.run_format_human_checks(repetition_utils),
            "candidate_allowed_checks": checks_mod.run_candidate_allowed_checks(repetition_utils),
            "decrement_checks": checks_mod.run_decrement_checks(repetition_utils, C),
            "mathlogic_checks": checks_mod.run_mathlogic_repetition_checks(scheduler_mathlogic, C),
            "actions_checks": checks_mod.run_actions_repetition_checks(scheduler_actions, C),
            "missed_coordinator_checks": checks_mod.run_missed_coordinator_repetition_checks(
                scheduler_missed,
                scheduler_coordinator,
                storage_mod,
                C,
            ),
            "handler_checks": checks_mod.run_handler_checks(repetition_flow, C),
            "storage_checks": checks_mod.run_storage_checks(storage_mod, C),
        }
        for section_name, payload in sections.items():
            dbg.section(section_name, payload)

        failed_checks = _collect_failed_checks(sections)
        if failed_checks:
            dbg.problem("repetition_checks_failed", {"failed_checks": failed_checks})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("repetition_checks_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"repetition_checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
