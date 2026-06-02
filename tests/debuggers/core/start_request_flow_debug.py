#!/usr/bin/env python3
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
from core.start_request_flow_checks import FakeStorage, load_runtime_modules, run_checks

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "start_request_flow_debug"
FEATURE_TITLE = "Start Request Flow"

IMPORT_ERROR = None
try:
    from telegram.ext import ApplicationHandlerStop
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
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

    module_names = [
        "mainbot",
        "modules.handlers.base",
        "modules.security.whitelist_store",
    ]
    had_modules = {name: name in sys.modules for name in module_names}
    old_modules = {name: sys.modules.get(name) for name in module_names}
    previous_data_dir = os.environ.get("BOT_DATA_DIR")
    previous_backup_dir = os.environ.get("BOT_BACKUP_DIR")

    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["BOT_DATA_DIR"] = os.path.join(tmpdir, "data")
            os.environ["BOT_BACKUP_DIR"] = os.path.join(tmpdir, "backups")
            cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                fake_storage = FakeStorage()
                try:
                    mainbot, base_handlers, whitelist_store = load_runtime_modules(fake_storage)
                except ModuleNotFoundError as exc:
                    dbg.mark_dependency_error(exc)
                    dbg.finish(exit_on_problems=False)
                    return
                run_checks(dbg, mainbot, base_handlers, whitelist_store, ApplicationHandlerStop)
            finally:
                os.chdir(cwd)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        if previous_data_dir is None:
            os.environ.pop("BOT_DATA_DIR", None)
        else:
            os.environ["BOT_DATA_DIR"] = previous_data_dir

        if previous_backup_dir is None:
            os.environ.pop("BOT_BACKUP_DIR", None)
        else:
            os.environ["BOT_BACKUP_DIR"] = previous_backup_dir

        for name in module_names:
            if had_modules[name]:
                sys.modules[name] = old_modules[name]
            else:
                sys.modules.pop(name, None)

    start_auto_ok = not dbg.has_problem("start_auto_create_failed")
    repeat_ok = not dbg.has_problem("start_repeated_idempotent_failed")
    edit_ok = not dbg.has_problem("start_edit_message_failed")
    multi_request_ok = not dbg.has_problem("multi_request_notifications_failed")
    stale_ok = not dbg.has_problem("start_stale_recovery_failed")
    nontext_onboard_ok = not dbg.has_problem("nontext_during_onboarding_failed")
    cmd_conflict_ok = not dbg.has_problem("command_conflict_onboarding_failed")
    legacy_ok = not dbg.has_problem("legacy_callback_no_mutation_failed")
    whitelisted_flags_ok = not dbg.has_problem("whitelisted_onboarding_flags_failed")
    legacy_confirm_ok = not dbg.has_problem("legacy_confirm_flag_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"start_auto_create: {'OK' if start_auto_ok else 'FAIL'}",
        f"start_repeat_idempotent: {'OK' if repeat_ok else 'FAIL'}",
        f"edit_message_update: {'OK' if edit_ok else 'FAIL'}",
        f"multi_request_notifications: {'OK' if multi_request_ok else 'FAIL'}",
        f"stale_resolved_recovery: {'OK' if stale_ok else 'FAIL'}",
        f"nontext_during_onboarding: {'OK' if nontext_onboard_ok else 'FAIL'}",
        f"command_conflict_onboarding: {'OK' if cmd_conflict_ok else 'FAIL'}",
        f"legacy_callback_no_mutation: {'OK' if legacy_ok else 'FAIL'}",
        f"whitelisted_flags_cleanup: {'OK' if whitelisted_flags_ok else 'FAIL'}",
        f"legacy_confirm_cleanup: {'OK' if legacy_confirm_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
