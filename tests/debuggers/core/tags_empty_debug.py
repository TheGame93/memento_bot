#!/usr/bin/env python3
import json
import os
import sys
import tempfile


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
SCRIPT_TITLE = "tags_empty_debug"
FEATURE_TITLE = "Tags Empty-State Handling"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _write_alerts_payload(base_dir, user_id, payload):
    user_dir = os.path.join(base_dir, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, "alerts.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return path


def _keyboard_rows(markup):
    rows = getattr(markup, "inline_keyboard", None)
    if rows is None:
        return []
    try:
        return list(rows)
    except TypeError:
        return []


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.storage import StorageManager
            from modules import constants as C
            from modules.handlers.add_flow.keyboards import build_toggle_keyboard
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StorageManager(base_data_dir=tmpdir)
            missing_id = 1
            empty_id = 2
            none_id = 3

            _write_alerts_payload(tmpdir, missing_id, {"alerts": []})
            _write_alerts_payload(tmpdir, empty_id, {"tags": [], "alerts": []})
            _write_alerts_payload(tmpdir, none_id, {"tags": None, "alerts": []})

            tags_missing = storage.get_user_tags(missing_id)
            tags_empty = storage.get_user_tags(empty_id)
            tags_none = storage.get_user_tags(none_id)

            tags_missing_copy = list(tags_missing)
            tags_missing_copy.append("🧪 Test")

            kb = build_toggle_keyboard([], [], C.CB_TAG)
            kb_rows = _keyboard_rows(kb)
            done_label = None
            if kb_rows and kb_rows[-1]:
                done_label = getattr(kb_rows[-1][0], "text", None)

            checks = {
                "missing_defaults": tags_missing == list(C.TAGS),
                "empty_preserved": tags_empty == [],
                "none_defaults": tags_none == list(C.TAGS),
                "default_copy_safe": "🧪 Test" not in C.TAGS,
                "done_only_keyboard": len(kb_rows) == 1 and done_label == "DONE",
            }
            dbg.section("tags_empty_state", {
                "tags_missing_len": len(tags_missing),
                "tags_empty_len": len(tags_empty),
                "tags_none_len": len(tags_none),
                "keyboard_rows": len(kb_rows),
                "checks": checks,
            })
            if not all(checks.values()):
                dbg.problem("tags_empty_state_failed", {"checks": checks})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("tags_empty_state_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"checks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
