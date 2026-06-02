#!/usr/bin/env python3
import ast
import os
import re
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
SCRIPT_TITLE = "commands_registry_debug"
FEATURE_TITLE = "Commands Registry"


def _extract_command_handlers(text):
    pattern = re.compile(r"CommandHandler\(\s*['\"]([^'\"]+)['\"]")
    return set(pattern.findall(text))


def _extract_menu_commands(text):
    try:
        tree = ast.parse(text)
    except Exception:
        return set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "post_init":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = [t for t in stmt.targets if isinstance(t, ast.Name)]
            if not any(t.id == "commands" for t in targets):
                continue
            value = stmt.value
            if not isinstance(value, ast.List):
                return set()
            extracted = set()
            for item in value.elts:
                if not isinstance(item, ast.Call):
                    continue
                func = item.func
                func_name = None
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr
                if func_name != "BotCommand":
                    continue
                if item.args and isinstance(item.args[0], ast.Constant) and isinstance(item.args[0].value, str):
                    extracted.add(item.args[0].value)
            return extracted
    return set()


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})

        mainbot_path = os.path.join(ROOT_DIR, "mainbot.py")
        with open(mainbot_path, "r", encoding="utf-8") as handle:
            content = handle.read()

        commands = _extract_command_handlers(content)
        expected_handlers = {
            "start",
            "manage",
            "alerts",
            "help",
            "status",
            "settings",
            "cancel",
            "birthdays",
            "tags",
        }
        missing_handlers = sorted(expected_handlers - commands)
        forbidden_handlers = sorted(commands - expected_handlers)

        dbg.section("handler_registry", {
            "commands": sorted(commands),
            "expected_handlers": sorted(expected_handlers),
            "missing_handlers": missing_handlers,
            "forbidden_handlers": forbidden_handlers,
        })

        if missing_handlers or forbidden_handlers:
            dbg.problem("handler_registry_mismatch", {
                "missing_handlers": missing_handlers,
                "forbidden_handlers": forbidden_handlers,
            })

        try:
            from modules import constants as C
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        scheduler_handlers_path = os.path.join(
            ROOT_DIR, "modules", "handlers", "scheduler_handlers.py"
        )
        with open(scheduler_handlers_path, "r", encoding="utf-8") as handle:
            scheduler_handlers_content = handle.read()

        notif_back_pattern = re.search(
            r"CallbackQueryHandler\(\s*handle_notif_back\s*,\s*pattern=f[\"']\^\{C\.CB_NOTIF_BACK\}[\"']\s*\)",
            scheduler_handlers_content,
        )
        scheduler_checks = {
            "mainbot_uses_get_scheduler_handlers": "for handler in get_scheduler_handlers():" in content,
            "notif_back_handler_registered": bool(notif_back_pattern),
            "notif_back_constant_prefix": getattr(C, "CB_NOTIF_BACK", "") == "nback_",
        }
        dbg.section("scheduler_callback_registry", {"checks": scheduler_checks})
        if not all(scheduler_checks.values()):
            dbg.problem("scheduler_callback_registry_failed", {"checks": scheduler_checks})

        reserved = set(getattr(C, "SHORTCODE_RESERVED_COMMANDS", set()))
        missing_reserved = sorted(commands - reserved)

        dbg.section("command_registry", {
            "commands": sorted(commands),
            "reserved": sorted(reserved),
            "missing_reserved": missing_reserved,
        })

        if missing_reserved:
            dbg.problem("reserved_missing", {"missing_reserved": missing_reserved})

        menu_commands = _extract_menu_commands(content)
        expected_menu = {"help", "alerts", "birthdays", "tags", "cancel", "settings", "status"}
        missing_menu = sorted(expected_menu - menu_commands)
        forbidden_menu = sorted(menu_commands - expected_menu)

        dbg.section("menu_registry", {
            "menu_commands": sorted(menu_commands),
            "expected_menu": sorted(expected_menu),
            "missing_menu": missing_menu,
            "forbidden_menu": forbidden_menu,
        })

        if missing_menu or forbidden_menu:
            dbg.problem("menu_mismatch", {
                "missing_menu": missing_menu,
                "forbidden_menu": forbidden_menu,
            })

        add_alert_path = os.path.join(ROOT_DIR, "modules", "handlers", "add_alert.py")
        with open(add_alert_path, "r", encoding="utf-8") as handle:
            add_alert_content = handle.read()
        has_add_entrypoint = "CommandHandler('add'" in add_alert_content or 'CommandHandler("add"' in add_alert_content
        dbg.section("add_flow_entrypoints", {
            "has_add_entrypoint": has_add_entrypoint,
        })
        if has_add_entrypoint:
            dbg.problem("legacy_add_entrypoint_present")
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    status = "FAIL" if dbg.problems else "OK"
    dbg.finish(summary_lines=[f"registry: {status}"])


if __name__ == "__main__":
    main()
