#!/usr/bin/env python3
import os
import re
import sys
import inspect


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
SCRIPT_TITLE = "commands_help_debug"
FEATURE_TITLE = "Commands Help"


def _extract_commands(help_text):
    return set(re.findall(r"(?<!<)/([a-zA-Z_]+)\b", help_text))


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers import base as base_handlers
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        help_intro_intro = getattr(base_handlers, "HELP_INTRO_INTRO_TEXT", "")
        help_intro_useit = getattr(base_handlers, "HELP_INTRO_USEIT_TEXT", "")
        help_intro_isnot = getattr(base_handlers, "HELP_INTRO_ISNOT_TEXT", "")
        help_commands = getattr(base_handlers, "HELP_COMMANDS_TEXT", "")
        help_system = getattr(base_handlers, "HELP_SYSTEM_COMMANDS_TEXT", "")
        help_admin = getattr(base_handlers, "HELP_ADMIN_TEXT", "")
        help_developer = getattr(base_handlers, "HELP_DEVELOPER_TEXT", "")
        has_legacy_intro = hasattr(base_handlers, "HELP_INTRO_TEXT")
        help_sections_for_role = getattr(base_handlers, "_help_sections_for_role", None)

        blocks = {
            "HELP_INTRO_INTRO_TEXT": help_intro_intro,
            "HELP_INTRO_USEIT_TEXT": help_intro_useit,
            "HELP_INTRO_ISNOT_TEXT": help_intro_isnot,
            "HELP_COMMANDS_TEXT": help_commands,
            "HELP_SYSTEM_COMMANDS_TEXT": help_system,
            "HELP_ADMIN_TEXT": help_admin,
            "HELP_DEVELOPER_TEXT": help_developer,
        }
        missing_blocks = sorted(
            name for name, value in blocks.items()
            if not isinstance(value, str) or not value.strip()
        )
        if missing_blocks:
            dbg.problem("help_blocks_missing", {"missing_blocks": missing_blocks})
        if has_legacy_intro:
            dbg.problem("help_legacy_intro_constant_present", {"constant": "HELP_INTRO_TEXT"})

        role_counts_ok = False
        role_order_ok = False
        role_sections_payload = {}
        if callable(help_sections_for_role):
            user_sections = help_sections_for_role("user")
            admin_sections = help_sections_for_role("admin")
            developer_sections = help_sections_for_role("developer")
            role_counts_ok = (
                isinstance(user_sections, list)
                and isinstance(admin_sections, list)
                and isinstance(developer_sections, list)
                and len(user_sections) == 5
                and len(admin_sections) == 6
                and len(developer_sections) == 7
            )
            role_order_ok = bool(user_sections) and [
                user_sections[0],
                user_sections[1],
                user_sections[2],
            ] == [help_intro_intro, help_intro_useit, help_intro_isnot]
            role_sections_payload = {
                "user_count": len(user_sections) if isinstance(user_sections, list) else None,
                "admin_count": len(admin_sections) if isinstance(admin_sections, list) else None,
                "developer_count": len(developer_sections) if isinstance(developer_sections, list) else None,
                "user_starts_with_split_intro": role_order_ok,
            }
        else:
            role_sections_payload = {"callable": False}

        dbg.section("help_role_sections", role_sections_payload)
        if not callable(help_sections_for_role):
            dbg.problem("help_role_sections_helper_missing")
        if not role_counts_ok:
            dbg.problem("help_role_sections_count_mismatch", role_sections_payload)
        if not role_order_ok:
            dbg.problem("help_role_sections_order_mismatch", role_sections_payload)

        telemetry_checks = {
            "has_help_callback_handler": hasattr(base_handlers, "handle_help_callback"),
            "command_help_logs_command_help": False,
            "command_help_logs_help_step_sent": False,
            "command_help_step_sent_after_send": False,
            "callback_logs_help_next_pressed": False,
            "callback_logs_help_step_sent": False,
            "callback_help_step_sent_after_send": False,
            "callback_logs_help_completed_popup": False,
            "callback_help_completed_popup_after_answer": False,
            "callback_logs_help_invalid": False,
        }
        try:
            help_command_src = inspect.getsource(base_handlers.help_command)
            help_callback_src = inspect.getsource(base_handlers.handle_help_callback)
            telemetry_checks["command_help_logs_command_help"] = "command_help" in help_command_src
            telemetry_checks["command_help_logs_help_step_sent"] = "help_step_sent" in help_command_src
            command_first_send_idx = help_command_src.find("await target.reply_text")
            command_step_sent_idx = help_command_src.find("help_step_sent")
            telemetry_checks["command_help_step_sent_after_send"] = (
                command_first_send_idx != -1
                and command_step_sent_idx != -1
                and command_first_send_idx < command_step_sent_idx
            )
            telemetry_checks["callback_logs_help_next_pressed"] = "help_next_pressed" in help_callback_src
            telemetry_checks["callback_logs_help_step_sent"] = "help_step_sent" in help_callback_src
            callback_send_idx = help_callback_src.find("await target_message.reply_text")
            callback_step_sent_idx = help_callback_src.find("help_step_sent")
            telemetry_checks["callback_help_step_sent_after_send"] = (
                callback_send_idx != -1
                and callback_step_sent_idx != -1
                and callback_send_idx < callback_step_sent_idx
            )
            telemetry_checks["callback_logs_help_completed_popup"] = "help_flow_completed_popup" in help_callback_src
            callback_done_answer_idx = help_callback_src.find("await query.answer(HELP_DONE_POPUP_TEXT")
            callback_done_log_idx = help_callback_src.find("help_flow_completed_popup")
            telemetry_checks["callback_help_completed_popup_after_answer"] = (
                callback_done_answer_idx != -1
                and callback_done_log_idx != -1
                and callback_done_answer_idx < callback_done_log_idx
            )
            telemetry_checks["callback_logs_help_invalid"] = "help_callback_invalid" in help_callback_src
        except Exception:
            pass
        dbg.section("help_telemetry", telemetry_checks)
        if not all(telemetry_checks.values()):
            dbg.problem("help_telemetry_hooks_missing", {"checks": telemetry_checks})

        commands = _extract_commands(help_commands)
        expected = {"help", "alerts", "birthdays", "tags", "cancel"}
        missing = sorted(expected - commands)
        forbidden = sorted(commands - expected)

        dbg.section("help_commands", {
            "found": sorted(commands),
            "missing": missing,
            "forbidden": forbidden,
        })

        if missing:
            dbg.problem("help_missing_commands", {"missing": missing})
        if forbidden:
            dbg.problem("help_forbidden_commands", {"forbidden": forbidden})

        system_commands = _extract_commands(help_system)
        system_expected = {"status", "settings"}
        system_missing = sorted(system_expected - system_commands)
        system_forbidden = sorted(system_commands - system_expected)
        dbg.section("help_system_commands", {
            "found": sorted(system_commands),
            "missing": system_missing,
            "forbidden": system_forbidden,
        })
        if system_missing:
            dbg.problem("help_system_missing_commands", {"missing": system_missing})
        if system_forbidden:
            dbg.problem("help_system_forbidden_commands", {"forbidden": system_forbidden})

        admin_has_info_header = "<b>Admin Info</b>" in help_admin
        admin_has_manage_cmd = "/manage" in help_admin
        developer_has_info_header = "<b>Developer Info</b>" in help_developer
        developer_has_admin_permissions = "all admin permissions" in help_developer.lower()
        developer_has_manage_cmd = "/manage" in help_developer

        dbg.section("role_sections", {
            "admin_info_header": admin_has_info_header,
            "admin_mentions_manage_command": admin_has_manage_cmd,
            "developer_info_header": developer_has_info_header,
            "developer_mentions_admin_permissions": developer_has_admin_permissions,
            "developer_mentions_manage_command": developer_has_manage_cmd,
        })

        if not admin_has_info_header:
            dbg.problem("help_admin_header_missing")
        if not admin_has_manage_cmd:
            dbg.problem("help_admin_command_missing")
        if not developer_has_info_header:
            dbg.problem("help_developer_header_missing")
        if not developer_has_admin_permissions:
            dbg.problem("help_developer_permissions_missing")
        if not developer_has_manage_cmd:
            dbg.problem("help_developer_command_missing")
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    dbg.finish(
        summary_lines=[f"FAIL: {code}" for code in dbg.problems],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
