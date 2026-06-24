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
SCRIPT_TITLE = "developer_dashboard_debug"
FEATURE_TITLE = "Developer Dashboard Helpers"

IMPORT_ERROR = None
try:
    from modules.handlers.developer import (
        _build_storage_summary,
        _build_users_list,
        _dashboard_keyboard,
        _dashboard_text,
        _user_detail_keyboard,
        _users_text,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc

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


def _test_dashboard_keyboard():
    kb_none = _dashboard_keyboard(None)
    kb_target = _dashboard_keyboard("123")
    rows_none = len(kb_none.inline_keyboard)
    rows_target = len(kb_target.inline_keyboard)
    labels_none = [btn.text for row in kb_none.inline_keyboard for btn in row]
    checks = {
        "rows_none": rows_none == 4,
        "rows_target": rows_target == 5,
        "no_act_as_entry": all("Act As" not in label for label in labels_none),
        "has_storage_summary": any("Storage" in label for label in labels_none),
        "has_pending_request": any("Pending Request" in label for label in labels_none),
        "has_add_user": any("Add User" in label for label in labels_none),
    }
    print_section(
        "dashboard_keyboard",
        {"rows_none": rows_none, "rows_target": rows_target, "labels_none": labels_none, "checks": checks},
    )
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "dashboard_keyboard", "checks": checks})


def _test_dashboard_text():
    text_none = _dashboard_text(None)
    text_target = _dashboard_text("456", "456")
    checks = {
        "text_none": "Manage Dashboard" in text_none and "none" in text_none,
        "text_target": "Manage Dashboard" in text_target and "456" in text_target,
    }
    print_section("dashboard_text", {"text_none": text_none, "text_target": text_target, "checks": checks})
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "dashboard_text", "checks": checks})


def _test_storage_summary_text():
    entries = [{"id": "100"}, {"id": "200"}]
    meta_map = {
        "100": {"username": "beta"},
        "200": {"username": "alpha"},
    }
    text = _build_storage_summary(None, entries, meta_map)
    checks = {
        "has_title": "Storage Summary" in text,
        "has_total_data_line": "Total space (data/):" in text,
        "has_total_system_log_line": "Total space (data/systemlog.d):" in text,
        "has_total_user_log_line": "Total space (data/userlog.d):" in text,
        "has_total_backup_line": "Total space (backups/):" in text,
        "has_header": "User name - Data / Logs / Backups" in text,
        "has_alpha_row": "@alpha - " in text and " / " in text,
        "has_beta_row": "@beta - " in text and " / " in text,
    }
    print_section("storage_summary", {"text": text, "checks": checks})
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "storage_summary", "checks": checks})


def _test_users_text():
    empty_text = _users_text([], {})
    populated_text = _users_text(
        [{"id": 1, "role": "admin"}],
        {"1": {"username": "alpha"}},
        {"1": {"alerts": 2, "birthdays": 1, "tags": 3}},
    )
    checks = {
        "empty_state": "No users found." in empty_text,
        "section_headers": "**ADMINS**" in populated_text,
        "populated_state": "01 @alpha | 2-1-3" in populated_text,
        "summary_state": "2-1-3" in populated_text and "`" not in populated_text,
        "legend_mentions_never_active": "(no icon)=never active" in populated_text,
    }
    print_section("users_text", {"empty_text": empty_text, "populated_text": populated_text, "checks": checks})
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "users_text", "checks": checks})


def _test_users_alias_list():
    entries = [
        {"id": 1, "role": "user"},
        {"id": 2, "role": "developer"},
        {"id": 3, "role": "admin"},
        {"id": 4, "role": "developer"},
    ]
    meta_map = {
        "1": {"display_name": "Zulu User"},
        "2": {"username": "charlie"},
        "3": {"username": "bravo"},
        "4": {"username": "alpha"},
    }
    summary_map = {
        "1": {"alerts": 1, "birthdays": 0, "tags": 2},
        "2": {"alerts": 4, "birthdays": 3, "tags": 1},
        "3": {"alerts": 2, "birthdays": 0, "tags": 0},
        "4": {"alerts": 0, "birthdays": 1, "tags": 1},
    }
    text, alias_map = _build_users_list(entries, meta_map, summary_map)
    checks = {
        "alias_01": "/01 @alpha | 0-1-1" in text and alias_map.get("01") == "4",
        "alias_02": "/02 @charlie | 4-3-1" in text and alias_map.get("02") == "2",
        "alias_03": "/03 @bravo | 2-0-0" in text and alias_map.get("03") == "3",
        "alias_04": "/04 Zulu User | 1-0-2" in text and alias_map.get("04") == "1",
        "has_sections": "**DEVELOPERS**" in text and "**ADMINS**" in text and "**USERS**" in text,
        "role_not_shown": "(developer)" not in text and "(admin)" not in text and "(user)" not in text,
        "format_username": "@alpha" in text and "@bravo" in text and "@charlie" in text,
        "format_name_fallback": "Zulu User" in text,
        "summary_shown": "0-1-1" in text and "2-0-0" in text and "`" not in text,
    }
    print_section("users_alias_list", {"text": text, "alias_map": alias_map, "checks": checks})
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "users_alias_list", "checks": checks})


def _test_users_alias_list_no_hard_cap():
    entries = []
    meta_map = {}
    summary_map = {}
    for idx in range(1, 26):
        uid = str(300 + idx)
        entries.append({"id": uid, "role": "user"})
        meta_map[uid] = {"username": f"user{idx:02d}"}
        summary_map[uid] = {"alerts": idx % 4, "birthdays": 0, "tags": idx % 2}

    text, alias_map = _build_users_list(entries, meta_map, summary_map)
    checks = {
        "alias_count_full": len(alias_map) == 25,
        "alias_20": alias_map.get("20") == "320",
        "alias_21": alias_map.get("21") == "321",
        "alias_25": alias_map.get("25") == "325",
        "text_has_25th_row": "/25 @user25" in text,
        "no_truncation_footer": "Showing 20 of" not in text,
    }
    print_section("users_alias_list_no_hard_cap", {"alias_map_size": len(alias_map), "checks": checks})
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "users_alias_list_no_hard_cap", "checks": checks})


def _test_no_self_act_as_button():
    kb_self = _user_detail_keyboard("10", "developer", actor_id=10)
    labels_self = [btn.text for row in kb_self.inline_keyboard for btn in row]
    kb_other = _user_detail_keyboard("11", "user", actor_id=10)
    labels_other = [btn.text for row in kb_other.inline_keyboard for btn in row]
    checks = {
        "self_no_actas": "🧑‍💻 Act As" not in labels_self,
        "other_has_actas": "🧑‍💻 Act As" in labels_other,
    }
    print_section("self_actas_guard", {"labels_self": labels_self, "labels_other": labels_other, "checks": checks})
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "self_actas_guard", "checks": checks})


def _test_user_detail_admin_buttons():
    kb = _user_detail_keyboard("11", "user", actor_id=10)
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    checks = {
        "has_set_name": any("Set Name" in label for label in labels),
        "has_label_order": any("Label Order" in label for label in labels),
        "has_remove": any("Remove User" in label for label in labels),
        "has_set_admin": any("Set Admin" in label for label in labels),
        "has_set_developer": any("Set Developer" in label for label in labels),
        "no_set_user": all(label != "Set User" for label in labels),
    }
    print_section("user_detail_buttons", {"labels": labels, "checks": checks})
    if not all(checks.values()):
        _log_problem("developer_helpers_failed", {"step": "user_detail_buttons", "checks": checks})


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        _test_dashboard_keyboard()
        _test_dashboard_text()
        _test_storage_summary_text()
        _test_users_text()
        _test_users_alias_list()
        _test_users_alias_list_no_hard_cap()
        _test_no_self_act_as_button()
        _test_user_detail_admin_buttons()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    helpers_ok = not dbg.has_problem("developer_helpers_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"helpers: {'OK' if helpers_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
