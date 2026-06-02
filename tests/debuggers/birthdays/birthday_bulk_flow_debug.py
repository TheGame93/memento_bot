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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "birthday_bulk_flow_debug"
FEATURE_TITLE = "Birthday Bulk Export/Import Flow"


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
        for key, checks in payload.items():
            if not key.endswith("checks"):
                continue
            if not isinstance(checks, dict):
                continue
            for check_name, value in checks.items():
                if not value:
                    failed.append(f"{section_name}:{key}:{check_name}")
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
        sys.modules["mainbot"] = mainbot_stub

        try:
            from modules.handlers import base as base_handlers
            import birthday_bulk_flow_checks as checks_mod
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        sections = {
            "mode_open": checks_mod.run_mode_open_checks(base_handlers, mainbot_stub),
            "everything_export": checks_mod.run_everything_export_checks(base_handlers, mainbot_stub),
            "bytag_export": checks_mod.run_bytag_export_checks(base_handlers, mainbot_stub),
            "chunking_export": checks_mod.run_chunking_export_checks(base_handlers, mainbot_stub),
            "import_entry": checks_mod.run_import_entry_checks(base_handlers, mainbot_stub),
            "import_overlap_guard": checks_mod.run_import_overlap_guard_checks(base_handlers, mainbot_stub),
            "import_overlap_guard_empty_session": checks_mod.run_import_overlap_guard_empty_session_checks(base_handlers, mainbot_stub),
            "import_edit_decision": checks_mod.run_import_edit_decision_checks(base_handlers, mainbot_stub),
            "import_continue_stale": checks_mod.run_import_continue_stale_checks(base_handlers, mainbot_stub),
            "import_continue_missing_entries": checks_mod.run_import_continue_missing_entries_checks(base_handlers, mainbot_stub),
            "import_continue_commit": checks_mod.run_import_continue_commit_checks(base_handlers, mainbot_stub),
            "import_continue_failure": checks_mod.run_import_continue_failure_checks(base_handlers, mainbot_stub),
            "import_gototags": checks_mod.run_import_gototags_checks(base_handlers, mainbot_stub),
        }

        for section_name, payload in sections.items():
            dbg.section(section_name, payload)

        failed_checks = _collect_failed_checks(sections)
        if failed_checks:
            dbg.problem("birthday_bulk_flow_failed", {"failed_checks": failed_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        if had_mainbot:
            sys.modules["mainbot"] = original_mainbot
        else:
            sys.modules.pop("mainbot", None)

    flow_ok = not dbg.has_problem("birthday_bulk_flow_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"bulk_flow: {'OK' if flow_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
