#!/usr/bin/env python3
import asyncio
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
SCRIPT_TITLE = "backup_email_startup_debug"
FEATURE_TITLE = "Email Backup Startup Catchup"

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
            from modules.backup_core.constants import EMAIL_BACKUP_DAY
            from modules.backup_core.email_backup import (
                last_expected_backup_time,
                last_expected_reminder_time,
                should_send_monthly,
                should_send_startup_backup,
                should_send_startup_reminder,
            )
            from modules.scheduler_core import coordinator as scheduler_coordinator
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        now = datetime(2026, 3, 1, 10, 0, 0)
        expected_backup = last_expected_backup_time(now)
        expected_reminder = last_expected_reminder_time(now)
        backup_checks = {
            "backup_expected_prev_month": expected_backup == datetime(2026, 2, 28, 3, 0, 0),
            "reminder_expected_prev_month": expected_reminder == datetime(2026, 2, 20, 3, 0, 0),
        }
        print_section("expected_prev_month", {
            "expected_backup": expected_backup,
            "expected_reminder": expected_reminder,
            "checks": backup_checks,
        })
        if not all(backup_checks.values()):
            _log_problem("startup_expected_prev_month_failed", {
                "expected_backup": expected_backup,
                "expected_reminder": expected_reminder,
                "checks": backup_checks,
            })

        now = datetime(2026, 3, 28, 4, 0, 0)
        expected_backup = last_expected_backup_time(now)
        checks = {
            "backup_expected_same_month": expected_backup == datetime(2026, 3, 28, 3, 0, 0),
        }
        print_section("expected_same_month", {
            "expected_backup": expected_backup,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_expected_same_month_failed", {
                "expected_backup": expected_backup,
                "checks": checks,
            })

        now = datetime(2026, 3, 1, 10, 0, 0)
        ok, reason, expected = should_send_startup_backup(now, {
            "email_enabled": True,
            "last_email_sent": None,
        })
        checks = {
            "ok": ok is True,
            "reason_ok": reason == "ok",
            "expected_matches": expected == datetime(2026, 2, 28, 3, 0, 0),
        }
        print_section("backup_ok", {"ok": ok, "reason": reason, "expected": expected, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_backup_ok_failed", {
                "ok": ok,
                "reason": reason,
                "expected": expected,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_backup(now, {
            "email_enabled": False,
            "last_email_sent": None,
        })
        checks = {
            "disabled": ok is False and reason == "disabled",
        }
        print_section("backup_disabled", {"ok": ok, "reason": reason, "expected": expected, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_backup_disabled_failed", {
                "ok": ok,
                "reason": reason,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_backup(now, {
            "email_enabled": True,
            "last_email_sent": "2026-03-01T00:00:00",
        })
        checks = {
            "already_sent": ok is False and reason == "already_sent",
        }
        print_section("backup_already_sent", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_backup_already_sent_failed", {
                "ok": ok,
                "reason": reason,
                "expected": expected,
                "checks": checks,
            })

        # --- should_send_monthly scenarios ---

        # no history, no last_sent → True (must send this month)
        now_backup_day = datetime(2026, 3, EMAIL_BACKUP_DAY, 4, 0, 0)
        result_ssm = should_send_monthly(now_backup_day, {})
        checks = {"no_history_no_last_sent": result_ssm is True}
        print_section("monthly_no_history_no_last_sent", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_no_history_no_last_sent_failed", {
                "result": result_ssm, "checks": checks,
            })

        # monthly entry in slot → False (already sent this month)
        result_ssm = should_send_monthly(now_backup_day, {
            "email_send_history": [{"reason": "monthly", "slot_key": "2026-03"}],
        })
        checks = {"history_present_blocks": result_ssm is False}
        print_section("monthly_history_present", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_history_present_failed", {
                "result": result_ssm, "checks": checks,
            })

        # only manual entry in slot → True (manual doesn't consume scheduled slot)
        result_ssm = should_send_monthly(now_backup_day, {
            "email_send_history": [{"reason": "manual", "slot_key": "2026-03"}],
        })
        checks = {"manual_only_does_not_block": result_ssm is True}
        print_section("monthly_manual_only", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_manual_only_failed", {
                "result": result_ssm, "checks": checks,
            })

        # manual history present + same-month last_sent → True (history takes precedence)
        result_ssm = should_send_monthly(now_backup_day, {
            "email_send_history": [{"reason": "manual", "slot_key": "2026-03"}],
            "last_email_sent": "2026-03-28T03:30:00",
        })
        checks = {"manual_history_with_last_sent_coexists": result_ssm is True}
        print_section("monthly_manual_with_last_sent", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_manual_with_last_sent_failed", {
                "result": result_ssm,
                "checks": checks,
            })

        # no history, last_sent same month → False (backward-compat)
        result_ssm = should_send_monthly(now_backup_day, {
            "email_send_history": [],
            "last_email_sent": "2026-03-01T00:00:00",
        })
        checks = {"backward_compat_same_month_blocks": result_ssm is False}
        print_section("monthly_backward_compat_same_month", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_backward_compat_failed", {
                "result": result_ssm, "checks": checks,
            })

        # no history, last_sent different month → True
        result_ssm = should_send_monthly(now_backup_day, {
            "email_send_history": [],
            "last_email_sent": "2026-02-28T03:00:00",
        })
        checks = {"different_month_allows_send": result_ssm is True}
        print_section("monthly_backward_compat_diff_month", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_backward_compat_failed", {
                "result": result_ssm, "checks": checks,
            })

        # wrong day → False (regardless of prefs)
        now_wrong_day = datetime(2026, 3, EMAIL_BACKUP_DAY - 1, 4, 0, 0)
        result_ssm = should_send_monthly(now_wrong_day, {})
        checks = {"wrong_day_blocks": result_ssm is False}
        print_section("monthly_wrong_day", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_wrong_day_failed", {
                "result": result_ssm, "checks": checks,
            })

        # --- should_send_startup_backup history scenarios ---

        # monthly history entry matching expected slot → already_sent
        now_startup = datetime(2026, 3, 1, 10, 0, 0)
        expected_slot = "2026-02"  # last_expected_backup_time(now_startup).month = Feb
        ok, reason, expected = should_send_startup_backup(now_startup, {
            "email_enabled": True,
            "email_send_history": [{"reason": "monthly", "slot_key": expected_slot}],
        })
        checks = {
            "history_already_sent_ok": ok is False,
            "history_already_sent_reason": reason == "already_sent",
        }
        print_section("backup_history_already_sent", {
            "ok": ok, "reason": reason, "expected": expected, "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_backup_history_already_sent_failed", {
                "ok": ok, "reason": reason, "checks": checks,
            })

        # manual-only history entry → ok (manual doesn't block startup catchup)
        ok, reason, expected = should_send_startup_backup(now_startup, {
            "email_enabled": True,
            "email_send_history": [{"reason": "manual", "slot_key": expected_slot}],
        })
        checks = {
            "manual_history_ok": ok is True,
            "manual_history_reason": reason == "ok",
        }
        print_section("backup_history_manual_only", {
            "ok": ok, "reason": reason, "expected": expected, "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_backup_history_manual_only_failed", {
                "ok": ok, "reason": reason, "checks": checks,
            })

        # manual-only history + last_sent after expected slot must still allow startup catchup
        ok, reason, expected = should_send_startup_backup(now_startup, {
            "email_enabled": True,
            "email_send_history": [{"reason": "manual", "slot_key": expected_slot}],
            "last_email_sent": "2026-03-01T00:00:00",
        })
        checks = {
            "manual_history_with_last_sent_ok": ok is True,
            "manual_history_with_last_sent_reason": reason == "ok",
            "manual_history_with_last_sent_expected": expected == datetime(2026, 2, 28, 3, 0, 0),
        }
        print_section("backup_history_manual_with_last_sent", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_backup_history_manual_with_last_sent_failed", {
                "ok": ok,
                "reason": reason,
                "expected": expected,
                "checks": checks,
            })

        # malformed non-list history should not raise and should behave as empty history
        result_ssm = should_send_monthly(now_backup_day, {
            "email_send_history": {"bad": "shape"},
        })
        checks = {
            "non_list_history_treated_empty": result_ssm is True,
        }
        print_section("monthly_history_non_list", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_history_non_list_failed", {
                "result": result_ssm,
                "checks": checks,
            })

        # mixed lists should ignore malformed entries and still respect valid dict entries
        result_ssm = should_send_monthly(now_backup_day, {
            "email_send_history": [
                {"reason": "monthly", "slot_key": "2026-03"},
                "oops",
                123,
                None,
            ],
        })
        checks = {
            "mixed_history_respects_valid_dict": result_ssm is False,
        }
        print_section("monthly_history_mixed_entries", {"result": result_ssm, "checks": checks})
        if not all(checks.values()):
            _log_problem("startup_monthly_history_mixed_entries_failed", {
                "result": result_ssm,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_backup(now_startup, {
            "email_enabled": True,
            "email_send_history": "bad_history_shape",
        })
        checks = {
            "startup_non_list_history_ok": ok is True,
            "startup_non_list_history_reason": reason == "ok",
            "startup_non_list_history_expected": expected == datetime(2026, 2, 28, 3, 0, 0),
        }
        print_section("backup_history_non_list", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_backup_history_non_list_failed", {
                "ok": ok,
                "reason": reason,
                "expected": expected,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_backup(now_startup, {
            "email_enabled": True,
            "email_send_history": [
                {"reason": "monthly", "slot_key": expected_slot},
                "oops",
                123,
                None,
            ],
        })
        checks = {
            "startup_mixed_history_already_sent_ok": ok is False,
            "startup_mixed_history_already_sent_reason": reason == "already_sent",
        }
        print_section("backup_history_mixed_entries", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_backup_history_mixed_entries_failed", {
                "ok": ok,
                "reason": reason,
                "expected": expected,
                "checks": checks,
            })

        expected_slot = datetime(2026, 2, 28, 3, 0, 0)
        captured_call = {}

        class _FakeStartupStorage:
            def get_all_users(self):
                return ["1001"]

            def is_user_whitelisted(self, user_id):
                return True

            def get_backup_prefs(self, user_id):
                return {
                    "email_enabled": True,
                    "email_address": "slot@example.com",
                }

            def update_backup_prefs(self, user_id, updates):
                return None

            def log_user_event(self, user_id, event_type, payload):
                return None

        class _FakeBot:
            async def send_message(self, **kwargs):
                return None

        class _FakeApp:
            def __init__(self):
                self.bot = _FakeBot()

        original_storage = scheduler_coordinator._storage
        original_app = scheduler_coordinator._app
        original_should_startup_backup = scheduler_coordinator.should_send_startup_backup
        original_should_startup_reminder = scheduler_coordinator.should_send_startup_reminder
        original_send_backup_email = scheduler_coordinator.send_backup_email
        original_to_thread = scheduler_coordinator.asyncio.to_thread
        try:
            scheduler_coordinator._storage = _FakeStartupStorage()
            scheduler_coordinator._app = _FakeApp()

            def _fake_should_send_startup_backup(now, prefs):
                return True, "ok", expected_slot

            def _fake_should_send_startup_reminder(now, prefs):
                return False, "not_due", None

            def _fake_send_backup_email(
                storage,
                user_id,
                to_email,
                now=None,
                reason="manual",
                *,
                history_slot_dt=None,
            ):
                captured_call.update({
                    "user_id": user_id,
                    "to_email": to_email,
                    "reason": reason,
                    "history_slot_dt": history_slot_dt,
                    "now": now,
                })
                return {"sent": False, "error": "email_missing"}

            async def _fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            scheduler_coordinator.should_send_startup_backup = _fake_should_send_startup_backup
            scheduler_coordinator.should_send_startup_reminder = _fake_should_send_startup_reminder
            scheduler_coordinator.send_backup_email = _fake_send_backup_email
            scheduler_coordinator.asyncio.to_thread = _fake_to_thread

            asyncio.run(scheduler_coordinator._run_startup_email_backup_catchup())

            checks = {
                "reason_startup_catchup": captured_call.get("reason") == "startup_catchup",
                "slot_forwarded": captured_call.get("history_slot_dt") == expected_slot,
                "email_forwarded": captured_call.get("to_email") == "slot@example.com",
            }
            print_section("startup_catchup_slot_forwarding", {
                "captured_call": captured_call,
                "expected_slot": expected_slot,
                "checks": checks,
            })
            if not all(checks.values()):
                _log_problem("startup_catchup_slot_forwarding_failed", {
                    "captured_call": captured_call,
                    "expected_slot": expected_slot,
                    "checks": checks,
                })
        finally:
            scheduler_coordinator._storage = original_storage
            scheduler_coordinator._app = original_app
            scheduler_coordinator.should_send_startup_backup = original_should_startup_backup
            scheduler_coordinator.should_send_startup_reminder = original_should_startup_reminder
            scheduler_coordinator.send_backup_email = original_send_backup_email
            scheduler_coordinator.asyncio.to_thread = original_to_thread

        now = datetime(2026, 3, 21, 10, 0, 0)
        ok, reason, expected = should_send_startup_reminder(now, {
            "email_address": None,
            "email_reminder_disabled": False,
            "last_email_reminder_sent": None,
        })
        checks = {
            "ok": ok is True,
            "reason_ok": reason == "ok",
            "expected_matches": expected == datetime(2026, 3, 20, 3, 0, 0),
        }
        print_section("reminder_ok", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_reminder_ok_failed", {
                "ok": ok,
                "reason": reason,
                "expected": expected,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_reminder(now, {
            "email_address": "user@example.com",
            "email_reminder_disabled": False,
        })
        checks = {
            "has_email": ok is False and reason == "has_email",
        }
        print_section("reminder_has_email", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_reminder_has_email_failed", {
                "ok": ok,
                "reason": reason,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_reminder(now, {
            "email_enabled": True,
            "email_address": None,
            "email_reminder_disabled": False,
        })
        checks = {
            "backup_enabled": ok is False and reason == "backup_enabled",
        }
        print_section("reminder_backup_enabled", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_reminder_backup_enabled_failed", {
                "ok": ok,
                "reason": reason,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_reminder(now, {
            "email_address": None,
            "email_reminder_disabled": False,
            "email_reminder_snooze_until": "2026-03-21T12:00:00",
        })
        checks = {
            "snoozed": ok is False and reason == "snoozed",
        }
        print_section("reminder_snoozed", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_reminder_snoozed_failed", {
                "ok": ok,
                "reason": reason,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_reminder(now, {
            "email_address": None,
            "email_reminder_disabled": True,
        })
        checks = {
            "disabled": ok is False and reason == "disabled",
        }
        print_section("reminder_disabled", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_reminder_disabled_failed", {
                "ok": ok,
                "reason": reason,
                "checks": checks,
            })

        ok, reason, expected = should_send_startup_reminder(now, {
            "email_address": None,
            "email_reminder_disabled": False,
            "last_email_reminder_sent": "2026-03-20T03:30:00",
        })
        checks = {
            "already_sent": ok is False and reason == "already_sent",
        }
        print_section("reminder_already_sent", {
            "ok": ok,
            "reason": reason,
            "expected": expected,
            "checks": checks,
        })
        if not all(checks.values()):
            _log_problem("startup_reminder_already_sent_failed", {
                "ok": ok,
                "reason": reason,
                "checks": checks,
            })

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    ok = not dbg.has_problem(
        "startup_expected_prev_month_failed",
        "startup_expected_same_month_failed",
        "startup_backup_ok_failed",
        "startup_backup_disabled_failed",
        "startup_backup_already_sent_failed",
        "startup_monthly_no_history_no_last_sent_failed",
        "startup_monthly_history_present_failed",
        "startup_monthly_manual_only_failed",
        "startup_monthly_manual_with_last_sent_failed",
        "startup_monthly_backward_compat_failed",
        "startup_monthly_wrong_day_failed",
        "startup_monthly_history_non_list_failed",
        "startup_monthly_history_mixed_entries_failed",
        "startup_backup_history_already_sent_failed",
        "startup_backup_history_manual_only_failed",
        "startup_backup_history_manual_with_last_sent_failed",
        "startup_backup_history_non_list_failed",
        "startup_backup_history_mixed_entries_failed",
        "startup_catchup_slot_forwarding_failed",
        "startup_reminder_ok_failed",
        "startup_reminder_has_email_failed",
        "startup_reminder_disabled_failed",
        "startup_reminder_backup_enabled_failed",
        "startup_reminder_snoozed_failed",
        "startup_reminder_already_sent_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"startup: {'OK' if ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
