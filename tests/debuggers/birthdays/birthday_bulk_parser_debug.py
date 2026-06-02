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
SCRIPT_TITLE = "birthday_bulk_parser_debug"
FEATURE_TITLE = "Birthday Bulk Parser Primitives"


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
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers.birthday_flow import bulk_birthdays
            import birthday_bulk_parser_checks as checks_mod
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        sections = {
            "whitespace": checks_mod.run_whitespace_checks(bulk_birthdays),
            "control_chars": checks_mod.run_control_char_checks(bulk_birthdays),
            "separator_policy": checks_mod.run_separator_checks(bulk_birthdays),
            "date_normalization": checks_mod.run_date_normalization_checks(bulk_birthdays),
            "date_parsing": checks_mod.run_date_parsing_checks(bulk_birthdays),
            "message_parser": checks_mod.run_message_parser_checks(bulk_birthdays),
            "tag_analysis": checks_mod.run_tag_analysis_checks(bulk_birthdays),
            "export_render": checks_mod.run_export_render_checks(bulk_birthdays),
            "chunking": checks_mod.run_chunking_checks(bulk_birthdays),
            "preview_render": checks_mod.run_preview_render_checks(bulk_birthdays),
            "final_confirmation_render": checks_mod.run_final_confirmation_checks(bulk_birthdays),
        }

        for section_name, payload in sections.items():
            dbg.section(section_name, payload)

        failed_checks = _collect_failed_checks(sections)
        if failed_checks:
            dbg.problem("bulk_parser_primitives_failed", {"failed_checks": failed_checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    parser_ok = not dbg.has_problem("bulk_parser_primitives_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"parser_primitives: {'OK' if parser_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
