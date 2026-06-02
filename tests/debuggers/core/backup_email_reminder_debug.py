#!/usr/bin/env python3
import os
import sys
from datetime import datetime


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
SCRIPT_TITLE = "backup_email_reminder_debug"
FEATURE_TITLE = "Email Backup Reminder"

_DBG = None


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


def _dbg():
    if _DBG is None:
        raise RuntimeError("debug harness not initialized")
    return _DBG


def print_section(label, payload):
    _dbg().section(label, payload)


def _log_problem(message, payload=None):
    _dbg().problem(message, payload or {})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.backup_core.email_backup import should_send_monthly_reminder
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        base_now = datetime(2026, 2, 20, 3, 0, 0)
        ok, reason = should_send_monthly_reminder(base_now, {})
        checks = {
            "ok_reason": ok is True and reason == "ok",
        }
        print_section("ok_case", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_ok_failed", {"ok": ok, "reason": reason})

        ok, reason = should_send_monthly_reminder(base_now, {"email_address": "a@b.com"})
        checks = {"has_email": ok is False and reason == "has_email"}
        print_section("has_email", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_has_email_failed", {"ok": ok, "reason": reason})

        ok, reason = should_send_monthly_reminder(base_now, {"email_address": "   "})
        checks = {"whitespace_treated_not_set": ok is True and reason == "ok"}
        print_section("whitespace_email", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_whitespace_email_failed", {"ok": ok, "reason": reason})

        ok, reason = should_send_monthly_reminder(base_now, {"email_reminder_disabled": True})
        checks = {"disabled": ok is False and reason == "disabled"}
        print_section("disabled", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_disabled_failed", {"ok": ok, "reason": reason})

        ok, reason = should_send_monthly_reminder(base_now, {"email_enabled": True})
        checks = {"backup_enabled": ok is False and reason == "backup_enabled"}
        print_section("backup_enabled", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_backup_enabled_failed", {"ok": ok, "reason": reason})

        ok, reason = should_send_monthly_reminder(base_now, {
            "email_reminder_snooze_until": "2026-02-20T12:00:00",
        })
        checks = {"snoozed": ok is False and reason == "snoozed"}
        print_section("snoozed", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_snoozed_failed", {"ok": ok, "reason": reason})

        ok, reason = should_send_monthly_reminder(base_now, {
            "last_email_reminder_sent": base_now.isoformat(),
        })
        checks = {"already_sent": ok is False and reason == "already_sent"}
        print_section("already_sent", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_already_sent_failed", {"ok": ok, "reason": reason})

        not_day = base_now.replace(day=21)
        ok, reason = should_send_monthly_reminder(not_day, {})
        checks = {"not_day": ok is False and reason == "not_day"}
        print_section("not_day", {"ok": ok, "reason": reason, "checks": checks})
        if not all(checks.values()):
            _log_problem("reminder_not_day_failed", {"ok": ok, "reason": reason})

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    ok = not dbg.problems
    dbg.finish(summary_lines=[f"reminder: {'OK' if ok else 'FAIL'}"], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
