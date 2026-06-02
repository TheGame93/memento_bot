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
SCRIPT_TITLE = "conversation_guard_debug"
FEATURE_TITLE = "ConversationHandler Guard"


def _is_guarded(func):
    return hasattr(func, "__wrapped__")


def _check_handler_guards(conv_handler):
    guarded = []
    unguarded = []
    for handlers in conv_handler.states.values():
        for handler in handlers:
            cb = getattr(handler, "callback", None)
            if cb is None:
                continue
            name = getattr(cb, "__name__", repr(cb))
            if _is_guarded(cb):
                guarded.append(name)
            else:
                unguarded.append(name)
    return guarded, unguarded


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.shared.context_cleanup import require_temp_alert, clear_transient_context
            from modules.handlers.add_alert import add_alert_handler
            from modules.handlers.birthday_flow.flow import birthday_add_handler
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        # Check 1: decorator exists.
        is_callable = callable(require_temp_alert)
        dbg.section("decorator_exists", {"callable": is_callable})
        if not is_callable:
            dbg.problem("decorator_missing", {"hint": "require_temp_alert not callable"})

        # Check 2: birthday handler state guards.
        bday_guarded, bday_unguarded = _check_handler_guards(birthday_add_handler)
        dbg.section("bday_guards", {
            "guarded": bday_guarded,
            "unguarded": bday_unguarded,
            "total_guarded": len(bday_guarded),
            "total_unguarded": len(bday_unguarded),
        })
        if bday_unguarded:
            dbg.problem("bday_guard_missing", {"unguarded_functions": bday_unguarded})

        # Check 3: add-alert handler state guards.
        add_guarded, add_unguarded = _check_handler_guards(add_alert_handler)
        dbg.section("add_guards", {
            "guarded": add_guarded,
            "unguarded": add_unguarded,
            "total_guarded": len(add_guarded),
            "total_unguarded": len(add_unguarded),
        })
        if add_unguarded:
            dbg.problem("add_guard_missing", {"unguarded_functions": add_unguarded})

        # Check 4: entry points must not be guarded.
        entry_problems = []
        for entry in birthday_add_handler.entry_points:
            cb = getattr(entry, "callback", None)
            if cb and _is_guarded(cb):
                entry_problems.append(f"birthday:{getattr(cb, '__name__', '?')}")
        for entry in add_alert_handler.entry_points:
            cb = getattr(entry, "callback", None)
            if cb and _is_guarded(cb):
                entry_problems.append(f"add_alert:{getattr(cb, '__name__', '?')}")

        dbg.section("entry_points_unguarded", {
            "guarded_entry_points": entry_problems,
            "ok": len(entry_problems) == 0,
        })
        if entry_problems:
            dbg.problem("entry_point_guarded", {
                "hint": "Entry points should NOT have @require_temp_alert",
                "functions": entry_problems,
            })

        # Check 5: context cleanup behavior.
        sample = {"temp_alert": {"title": "test"}, "custom_field": 42}
        clear_transient_context(sample)
        removed = "temp_alert" not in sample
        preserved = sample.get("custom_field") == 42
        dbg.section("cleanup_pops_temp_alert", {
            "temp_alert_removed": removed,
            "custom_field_preserved": preserved,
        })
        if not removed or not preserved:
            dbg.problem("cleanup_failed", {
                "temp_alert_removed": removed,
                "custom_field_preserved": preserved,
            })
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    decorator_ok = not dbg.has_problem("decorator_missing")
    bday_ok = not dbg.has_problem("bday_guard_missing")
    add_ok = not dbg.has_problem("add_guard_missing")
    entry_ok = not dbg.has_problem("entry_point_guarded")
    cleanup_ok = not dbg.has_problem("cleanup_failed")
    dbg.finish(summary_lines=[
        f"decorator: {'OK' if decorator_ok else 'FAIL'}",
        f"bday_guards: {'OK' if bday_ok else 'FAIL'}",
        f"add_guards: {'OK' if add_ok else 'FAIL'}",
        f"entry_unguarded: {'OK' if entry_ok else 'FAIL'}",
        f"cleanup: {'OK' if cleanup_ok else 'FAIL'}",
    ])


if __name__ == "__main__":
    main()
