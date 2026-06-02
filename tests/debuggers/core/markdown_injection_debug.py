#!/usr/bin/env python3
"""Debugger for markdown injection resilience (markdown hardening plan).

Covers:
- md_escape core behaviour (basic, None/empty, newlines)
- md_escape_inline_code and md_escape_multiline_text helper coverage
- md_escape_fence_content (fence breakout prevention)
- summary_flow markdown helper migration (no local _safe_code)
- birthday summary markdown escaping for inline-code/fence contexts
- static inventory checks for step-9 handler hardening targets
- additional_info fence rendering (summary_flow + list_alerts)
- input length limits (title, additional_info, custom_name)
- centralized import static analysis (no local _md_escape defs)

Scheduler title escaping is tested in scheduler_behavior_debug.py and
is NOT duplicated here.
"""
import os
import sys


def _find_debuggers_root(start_path):
    current = os.path.abspath(os.path.dirname(start_path))
    while True:
        if os.path.basename(current) == "debuggers" and os.path.isdir(
            os.path.join(current, "_lib")
        ):
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
SCRIPT_TITLE = "markdown_injection_debug"
FEATURE_TITLE = "Markdown Injection Resilience"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


# ── Test 1: md_escape basic ───────────────────────────────────────────
def _test_md_escape_basic(dbg, md_escape):
    checks = {}
    # Each markdown-sensitive char should be backslash-escaped
    result = md_escape("hello *world* _foo_ `bar` [link] end\\done")
    checks["asterisk_escaped"] = "\\*world\\*" in result
    checks["underscore_escaped"] = "\\_foo\\_" in result
    checks["backtick_escaped"] = "\\`bar\\`" in result
    checks["bracket_escaped"] = "\\[link]" in result  # only [ is escaped
    checks["backslash_escaped"] = "end\\\\done" in result
    checks["no_raw_markdown"] = (
        "*world*" not in result.replace("\\*world\\*", "")
    )
    dbg.section("md_escape_basic", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("md_escape_basic_failed", {"checks": checks, "result": result})


# ── Test 2: md_escape None and empty ──────────────────────────────────
def _test_md_escape_none_empty(dbg, md_escape):
    checks = {
        "none_returns_empty": md_escape(None) == "",
        "empty_returns_empty": md_escape("") == "",
        "int_coerced": isinstance(md_escape(42), str) and "42" in md_escape(42),
    }
    dbg.section("md_escape_none_empty", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("md_escape_none_empty_failed", {"checks": checks})


# ── Test 3: md_escape newlines ────────────────────────────────────────
def _test_md_escape_newlines(dbg, md_escape):
    result = md_escape("line1\nline2\r\nline3")
    checks = {
        "no_newlines": "\n" not in result and "\r" not in result,
        "collapsed_to_spaces": "line1 line2 line3" in result,
    }
    dbg.section("md_escape_newlines", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("md_escape_newlines_failed", {"checks": checks, "result": result})


# ── Test 4: md_escape_fence_content ───────────────────────────────────
def _test_fence_content(dbg, md_escape_fence_content):
    checks = {}
    # Triple backtick breakout must be neutralized
    result = md_escape_fence_content("before ``` after")
    checks["triple_backtick_replaced"] = "```" not in result
    checks["replaced_with_quotes"] = "'''" in result
    # None and empty handling
    checks["none_returns_empty"] = md_escape_fence_content(None) == ""
    checks["empty_returns_empty"] = md_escape_fence_content("") == ""
    # Single/double backticks should be preserved (they're harmless inside fences)
    single = md_escape_fence_content("a `b` c")
    checks["single_backtick_preserved"] = "`b`" in single
    dbg.section("md_escape_fence_content", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("md_escape_fence_content_failed", {"checks": checks})


# ── Test 5: md_escape_inline_code ─────────────────────────────────────
def _test_md_escape_inline_code(dbg, md_escape_inline_code):
    checks = {}
    result = md_escape_inline_code("hello `world`\nline2")
    checks["backtick_replaced"] = "`" not in result
    checks["replaced_with_quote"] = "'" in result
    checks["newlines_collapsed"] = "\n" not in result and "hello 'world' line2" in result
    checks["none_returns_empty"] = md_escape_inline_code(None) == ""
    dbg.section("md_escape_inline_code", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("md_escape_inline_code_failed", {"checks": checks})


# ── Test 6: md_escape_multiline_text ──────────────────────────────────
def _test_md_escape_multiline_text(dbg, md_escape_multiline_text):
    result = md_escape_multiline_text("row1 *bold*\nrow2 _u_ [x] `c` \\tail")
    checks = {
        "newline_preserved": "\n" in result and result.count("\n") == 1,
        "line1_escaped": "row1 \\*bold\\*" in result,
        "line2_escaped": "row2 \\_u\\_ \\[x] \\`c\\` \\\\tail" in result,
        "none_returns_empty": md_escape_multiline_text(None) == "",
    }
    dbg.section("md_escape_multiline_text", {"result": result, "checks": checks})
    if not all(checks.values()):
        dbg.problem("md_escape_multiline_text_failed", {"checks": checks, "result": result})


# ── Test 7: summary_flow helper migration ─────────────────────────────
def _test_summary_flow_helper_migration(dbg):
    rel_path = "modules/handlers/add_flow/summary_flow.py"
    abs_path = os.path.join(ROOT_DIR, rel_path)
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        dbg.problem("summary_flow_helper_migration_failed", {
            "reason": "read_error",
            "error": str(exc),
        })
        return

    checks = {
        "imports_inline_helper": "md_escape_inline_code" in content,
        "no_local_safe_code_def": "def _safe_code(" not in content,
        "uses_inline_helper_calls": content.count("md_escape_inline_code(") >= 6,
    }
    dbg.section("summary_flow_helper_migration", {"checks": checks, "path": rel_path})
    if not all(checks.values()):
        dbg.problem("summary_flow_helper_migration_failed", {"checks": checks, "path": rel_path})


# ── Test 8: summary_flow additional_info fence ────────────────────────
def _test_summary_flow_fence(dbg, format_alert_summary):
    data = {
        "type": 3,
        "type_name": "Weekly",
        "title": "Test",
        "schedule": {"time": "10:00", "weekdays": ["Mon"], "interval": 1},
        "pre_alerts": [],
        "additional_info": "line1\n```\ninjected markdown\n```\nline2",
        "tags": [],
    }
    result = format_alert_summary(data)
    # The triple backtick inside additional_info must be neutralized
    # Count opening/closing fences: the result should have exactly one
    # code fence pair (the wrapping one), not extra ones from injection
    fence_count = result.count("```")
    checks = {
        "exactly_two_fences": fence_count == 2,
        "injected_fence_neutralized": "'''" in result,
        "contains_additional_info_header": "Additional Info" in result,
    }
    dbg.section("summary_flow_fence", {
        "fence_count": fence_count,
        "checks": checks,
        "result_excerpt": result[:500],
    })
    if not all(checks.values()):
        dbg.problem("summary_flow_fence_failed", {"checks": checks})


# ── Test 9: list_alerts additional_info fence ─────────────────────────
def _test_list_alerts_fence(dbg, _format_additional_info_block):
    alert = {"additional_info": "data\n```\nbreak out\n```\nmore"}
    result = _format_additional_info_block(alert)
    fence_count = result.count("```")
    checks = {
        "exactly_two_fences": fence_count == 2,
        "injected_fence_neutralized": "'''" in result,
    }
    dbg.section("list_alerts_fence", {
        "fence_count": fence_count,
        "checks": checks,
        "result_excerpt": result[:300],
    })
    if not all(checks.values()):
        dbg.problem("list_alerts_fence_failed", {"checks": checks})


# ── Test 10: birthday summary inline/fence safety ─────────────────────
def _test_birthday_summary_markdown_safety(dbg, format_birthday_summary):
    data = {
        "type": 6,
        "title": "Al`ice_*",
        "shortcode": "b`day_test",
        "schedule": {"date": "01/01", "time": "08:30"},
        "pre_alerts": [],
        "additional_info": "first\n```\ninjected\n```\nlast",
        "tags": ["fri`ends", "fam_ily"],
    }
    result = format_birthday_summary(data)
    fence_count = result.count("```")
    checks = {
        "title_inline_sanitized": "**Name:** `Al'ice_*`" in result,
        "shortcut_inline_sanitized": "**Shortcut:** `/b'day_test`" in result,
        "date_inline_present": "**Date:** `01/01`" in result,
        "time_inline_present": "**Time:** `08:30`" in result,
        "tags_inline_sanitized": "**Tags:** `fri'ends, fam_ily`" in result,
        "fence_pair_preserved": fence_count == 2,
        "fence_breakout_neutralized": "'''" in result,
    }
    dbg.section("birthday_summary_markdown_safety", {
        "checks": checks,
        "fence_count": fence_count,
        "result_excerpt": result[:600],
    })
    if not all(checks.values()):
        dbg.problem("birthday_summary_markdown_safety_failed", {"checks": checks})


# ── Test 11: step-9 static hardening inventory ────────────────────────
def _test_step9_static_inventory(dbg):
    checks = {}

    def _read(rel_path):
        abs_path = os.path.join(ROOT_DIR, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    render_src = _read("modules/handlers/birthday_flow/render.py")
    developer_src = _read("modules/handlers/developer.py")

    checks["birthday_summary_uses_inline_helper"] = "md_escape_inline_code" in render_src
    checks["birthday_summary_uses_fence_helper"] = "md_escape_fence_content" in render_src
    checks["birthday_summary_no_raw_info_fence"] = "f\"**Additional Info:**\\n```\\n{info}\\n```\\n\"" not in render_src
    checks["developer_invalid_role_sanitized"] = "Invalid role: `{_md_escape_inline_code(new_role)}`" in developer_src

    dbg.section("step9_static_inventory", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("step9_static_inventory_failed", {"checks": checks})


# ── Test 12: input length limits ──────────────────────────────────────
def _test_length_limits(dbg, C):
    checks = {
        "title_max_len_defined": hasattr(C, "TITLE_MAX_LEN"),
        "additional_info_max_len_defined": hasattr(C, "ADDITIONAL_INFO_MAX_LEN"),
        "custom_name_max_len_defined": hasattr(C, "CUSTOM_NAME_MAX_LEN"),
    }
    if checks["title_max_len_defined"]:
        checks["title_max_len_reasonable"] = 50 <= C.TITLE_MAX_LEN <= 500
    if checks["additional_info_max_len_defined"]:
        checks["additional_info_max_len_reasonable"] = 500 <= C.ADDITIONAL_INFO_MAX_LEN <= 10000
    if checks["custom_name_max_len_defined"]:
        checks["custom_name_max_len_reasonable"] = 20 <= C.CUSTOM_NAME_MAX_LEN <= 300
    dbg.section("length_limits", {
        "TITLE_MAX_LEN": getattr(C, "TITLE_MAX_LEN", "MISSING"),
        "ADDITIONAL_INFO_MAX_LEN": getattr(C, "ADDITIONAL_INFO_MAX_LEN", "MISSING"),
        "CUSTOM_NAME_MAX_LEN": getattr(C, "CUSTOM_NAME_MAX_LEN", "MISSING"),
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("length_limits_failed", {"checks": checks})


# ── Test 13: input-validation telemetry hooks ────────────────────────
def _test_input_validation_telemetry_hooks(dbg):
    checks = {}

    def _contains(rel_path, needle):
        abs_path = os.path.join(ROOT_DIR, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                return needle in f.read()
        except Exception:
            return False

    checks["title_too_long_logged_add_flow"] = _contains(
        "modules/handlers/add_flow/flow_start.py",
        "title_input_too_long",
    )
    checks["title_too_long_logged_birthday"] = _contains(
        "modules/handlers/birthday_flow/flow.py",
        "title_input_too_long",
    )
    checks["additional_info_too_long_logged_settings"] = _contains(
        "modules/handlers/add_flow/settings_flow.py",
        "additional_info_input_too_long",
    )
    checks["additional_info_too_long_logged_edit"] = (
        _contains("modules/handlers/list_alerts.py", "additional_info_input_too_long")
        or _contains(
            "modules/handlers/list_alerts/manage_actions.py",
            "additional_info_input_too_long",
        )
    )
    checks["custom_name_too_long_logged"] = _contains(
        "mainbot.py",
        "custom_name_input_too_long",
    )

    dbg.section("validation_telemetry_hooks", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("validation_telemetry_hooks_missing", {"checks": checks})


# ── Test 14: centralized import static analysis ──────────────────────
def _test_centralized_imports(dbg):
    """Verify no module defines a local _md_escape / md_escape function
    outside of the canonical markdown_utils.py."""
    import glob as glob_mod

    canonical = os.path.join(ROOT_DIR, "modules", "shared", "markdown_utils.py")
    pattern = os.path.join(ROOT_DIR, "modules", "**", "*.py")
    violations = []
    for filepath in glob_mod.glob(pattern, recursive=True):
        if os.path.abspath(filepath) == os.path.abspath(canonical):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    stripped = line.lstrip()
                    if stripped.startswith("def _md_escape(") or stripped.startswith("def md_escape("):
                        violations.append(f"{os.path.relpath(filepath, ROOT_DIR)}:{line_no}")
        except Exception:
            pass

    checks = {"no_local_definitions": len(violations) == 0}
    dbg.section("centralized_imports", {
        "canonical": os.path.relpath(canonical, ROOT_DIR),
        "violations": violations,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("centralized_imports_violation", {
            "violations": violations,
            "checks": checks,
        })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown = _parse_cli_args(dbg.args)
        if unknown:
            dbg.problem("cli_args_unknown", {"unknown": unknown, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            from modules.shared.markdown_utils import (
                md_escape,
                md_escape_fence_content,
                md_escape_inline_code,
                md_escape_multiline_text,
            )
            from modules.handlers.add_flow.summary_flow import format_alert_summary
            from modules.handlers.birthday_flow.render import format_birthday_summary
            from modules.handlers.list_alerts import _format_additional_info_block
            from modules import constants as C
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        # Pure function tests (no stubs needed)
        _test_md_escape_basic(dbg, md_escape)
        _test_md_escape_none_empty(dbg, md_escape)
        _test_md_escape_newlines(dbg, md_escape)
        _test_md_escape_inline_code(dbg, md_escape_inline_code)
        _test_md_escape_multiline_text(dbg, md_escape_multiline_text)
        _test_fence_content(dbg, md_escape_fence_content)
        _test_summary_flow_helper_migration(dbg)
        _test_summary_flow_fence(dbg, format_alert_summary)
        _test_list_alerts_fence(dbg, _format_additional_info_block)
        _test_birthday_summary_markdown_safety(dbg, format_birthday_summary)
        _test_step9_static_inventory(dbg)
        _test_length_limits(dbg, C)
        _test_input_validation_telemetry_hooks(dbg)
        _test_centralized_imports(dbg)

    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    escape_ok = not dbg.has_problem(
        "md_escape_basic_failed",
        "md_escape_none_empty_failed",
        "md_escape_newlines_failed",
        "md_escape_inline_code_failed",
        "md_escape_multiline_text_failed",
        "md_escape_fence_content_failed",
    )
    rendering_ok = not dbg.has_problem(
        "summary_flow_helper_migration_failed",
        "summary_flow_fence_failed",
        "list_alerts_fence_failed",
        "birthday_summary_markdown_safety_failed",
        "step9_static_inventory_failed",
    )
    limits_ok = not dbg.has_problem("length_limits_failed")
    telemetry_ok = not dbg.has_problem("validation_telemetry_hooks_missing")
    imports_ok = not dbg.has_problem("centralized_imports_violation")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")

    dbg.finish(summary_lines=[
        f"escape_functions: {'OK' if escape_ok else 'FAIL'}",
        f"rendering: {'OK' if rendering_ok else 'FAIL'}",
        f"length_limits: {'OK' if limits_ok else 'FAIL'}",
        f"validation_telemetry: {'OK' if telemetry_ok else 'FAIL'}",
        f"centralized_imports: {'OK' if imports_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
