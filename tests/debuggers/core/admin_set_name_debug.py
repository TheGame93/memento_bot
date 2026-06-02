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
SCRIPT_TITLE = "admin_set_name_debug"
FEATURE_TITLE = "Admin Set Name UI"

IMPORT_ERROR = None
try:
    from modules.handlers.admin import ADMIN_USER_SET_NAME_PROMPT, _admin_user_set_name_keyboard
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

        expected_prompt = "Send the custom name for this user"
        prompt_ok = ADMIN_USER_SET_NAME_PROMPT == expected_prompt
        dbg.section("prompt", {
            "expected": expected_prompt,
            "actual": ADMIN_USER_SET_NAME_PROMPT,
            "checks": {"match": prompt_ok},
        })
        if not prompt_ok:
            dbg.problem("admin_set_name_prompt_mismatch", {"expected": expected_prompt, "actual": ADMIN_USER_SET_NAME_PROMPT})

        target_id = "42"
        keyboard = _admin_user_set_name_keyboard(target_id)
        rows = getattr(keyboard, "inline_keyboard", None) or []
        row_count_ok = len(rows) == 2
        row_sizes_ok = row_count_ok and all(len(row) == 1 for row in rows)
        clear_btn = rows[0][0] if len(rows) > 0 and rows[0] else None
        back_btn = rows[1][0] if len(rows) > 1 and rows[1] else None

        checks = {
            "rows": row_count_ok,
            "single_buttons": row_sizes_ok,
            "clear_label": clear_btn is not None and clear_btn.text == "🗑️ Clear Name",
            "clear_cb": clear_btn is not None and clear_btn.callback_data == f"admin_user_clear_name:{target_id}",
            "back_label": back_btn is not None and back_btn.text == "⬅️ Back to Dashboard",
            "back_cb": back_btn is not None and back_btn.callback_data == "mgmt_menu",
        }
        dbg.section("keyboard", {
            "rows": [[getattr(btn, "text", None) for btn in row] for row in rows],
            "checks": checks,
        })
        if not all(checks.values()):
            dbg.problem("admin_set_name_keyboard_mismatch", {"checks": checks})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ok = not dbg.problems
    dbg.finish(summary_lines=[f"admin_set_name: {'OK' if ok else 'FAIL'}"], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
