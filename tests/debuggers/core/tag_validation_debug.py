#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tempfile
import types


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
from _lib.runtime import run_async
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "tag_validation_debug"
FEATURE_TITLE = "Tag Validation"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _StorageStub:
    def __init__(self):
        self.log_events = []
        self.add_calls = []

    def log_user_event(self, user_id, event_type, payload=None):
        self.log_events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": payload or {},
        })
        return True

    def add_user_tag(self, user_id, tag):
        self.add_calls.append({"user_id": user_id, "tag": tag})
        return True, None

    def rename_user_tag(self, user_id, old_tag, new_tag):
        self.add_calls.append({"user_id": user_id, "old_tag": old_tag, "new_tag": new_tag})
        return True, None


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({
            "text": text,
            "kwargs": kwargs,
        })
        return types.SimpleNamespace(message_id=100 + len(self.replies))


class _DummyUpdate:
    def __init__(self, user_id, text):
        self.effective_user = _DummyUser(user_id)
        self.message = _DummyMessage(text)
        self.effective_message = self.message
        self.callback_query = None


class _DummyContext:
    def __init__(self):
        self.user_data = {}


def _last_event(events, name):
    matches = [item for item in events if item.get("event") == name]
    return matches[-1] if matches else None


def _run_format_rules_check(dbg):
    from modules.tags_logic import validate_tag_format

    _, ctrl_msg = validate_tag_format("🍕 Food\x00Bar")
    checks = {
        "valid_basic": validate_tag_format("🍕 Food")[0] is True,
        "invalid_underscore": validate_tag_format("🍕 Foo_bar")[0] is False,
        "invalid_star": validate_tag_format("🍕 Foo*bar")[0] is False,
        "invalid_backtick": validate_tag_format("🍕 Foo`bar")[0] is False,
        "invalid_lbracket": validate_tag_format("🍕 Foo[bar")[0] is False,
        "invalid_rbracket": validate_tag_format("🍕 Foo]bar")[0] is False,
        "ctrl_char_fires": validate_tag_format("🍕 Food\x00Bar")[0] is False,
        "ctrl_char_msg_updated": "tab" not in ctrl_msg.lower() and "newline" not in ctrl_msg.lower(),
    }

    _, msg_underscore = validate_tag_format("🍕 Foo_bar")
    _, msg_star = validate_tag_format("🍕 Foo*bar")
    _, msg_backtick = validate_tag_format("🍕 Foo`bar")
    _, msg_lbracket = validate_tag_format("🍕 Foo[bar")
    _, msg_rbracket = validate_tag_format("🍕 Foo]bar")
    reason_checks = {
        "underscore_reason": "_" in msg_underscore,
        "star_reason": "*" in msg_star,
        "backtick_reason": "`" in msg_backtick,
        "lbracket_reason": "[" in msg_lbracket,
        "rbracket_reason": "]" in msg_rbracket,
    }

    dbg.section("tag_format_rules", {
        "checks": checks,
        "reason_checks": reason_checks,
        "messages": {
            "underscore": msg_underscore,
            "star": msg_star,
            "backtick": msg_backtick,
            "lbracket": msg_lbracket,
            "rbracket": msg_rbracket,
        },
    })
    if not all(checks.values()) or not all(reason_checks.values()):
        dbg.problem("tag_format_rules_failed", {"checks": checks, "reason_checks": reason_checks})


async def _run_invalid_flow_check(dbg, mainbot):
    storage = _StorageStub()
    update = _DummyUpdate(5001, "🍕 Foo_bar")
    context = _DummyContext()
    context.user_data["expecting_tag_name"] = True

    old_storage = mainbot.storage
    old_tags_dashboard_start = mainbot.tags_dashboard_start
    old_timezone_query = mainbot.handle_timezone_query_input
    try:
        mainbot.storage = storage

        async def _fake_tags_dashboard_start(_update, _context):
            return None

        async def _fake_timezone_query(_update, _context):
            return False

        mainbot.tags_dashboard_start = _fake_tags_dashboard_start
        mainbot.handle_timezone_query_input = _fake_timezone_query

        raised_stop = False
        try:
            await mainbot.global_text_handler(update, context)
        except mainbot.ApplicationHandlerStop:
            raised_stop = True

        invalid_event = _last_event(storage.log_events, "tag_add_invalid_format")
        checks = {
            "raised_stop": raised_stop,
            "still_expecting_tag": context.user_data.get("expecting_tag_name") is True,
            "no_add_user_tag_call": len(storage.add_calls) == 0,
            "reply_sent": len(update.message.replies) == 1,
            "reply_mentions_invalid": bool(update.message.replies and "Invalid tag format" in update.message.replies[0]["text"]),
            "invalid_event_logged": isinstance(invalid_event, dict),
            "invalid_event_has_len": isinstance((invalid_event or {}).get("payload", {}).get("tag_len"), int),
            "invalid_event_has_hash": isinstance((invalid_event or {}).get("payload", {}).get("tag_hash"), str),
            "invalid_event_has_reason": (invalid_event or {}).get("payload", {}).get("reason_code") == "invalid_tag_format",
        }
        dbg.section("invalid_tag_flow", {
            "checks": checks,
            "log_events": storage.log_events,
            "replies": update.message.replies,
        })
        if not all(checks.values()):
            dbg.problem("invalid_tag_flow_failed", {"checks": checks})
    finally:
        mainbot.storage = old_storage
        mainbot.tags_dashboard_start = old_tags_dashboard_start
        mainbot.handle_timezone_query_input = old_timezone_query


async def _run_acting_as_target_check(dbg, mainbot):
    storage = _StorageStub()
    update = _DummyUpdate(6001, "🍕 GoodTag")
    context = _DummyContext()
    context.user_data["expecting_tag_name"] = True
    context.user_data["acting_as_user_id"] = 7777

    calls = {"dashboard": 0}

    old_storage = mainbot.storage
    old_tags_dashboard_start = mainbot.tags_dashboard_start
    old_timezone_query = mainbot.handle_timezone_query_input
    try:
        mainbot.storage = storage

        async def _fake_tags_dashboard_start(_update, _context):
            calls["dashboard"] += 1
            return None

        async def _fake_timezone_query(_update, _context):
            return False

        mainbot.tags_dashboard_start = _fake_tags_dashboard_start
        mainbot.handle_timezone_query_input = _fake_timezone_query

        raised_stop = False
        try:
            await mainbot.global_text_handler(update, context)
        except mainbot.ApplicationHandlerStop:
            raised_stop = True

        success_event = _last_event(storage.log_events, "tag_add_success")
        checks = {
            "raised_stop": raised_stop,
            "one_add_call": len(storage.add_calls) == 1,
            "add_uses_target_user": bool(storage.add_calls) and str(storage.add_calls[0]["user_id"]) == "7777",
            "expecting_tag_cleared": context.user_data.get("expecting_tag_name") is False,
            "dashboard_called_once": calls["dashboard"] == 1,
            "success_event_logged": isinstance(success_event, dict),
            "success_event_has_acting_as": isinstance((success_event or {}).get("payload", {}).get("acting_as"), dict),
            "reply_is_html": bool(update.message.replies) and update.message.replies[0]["kwargs"].get("parse_mode") == "HTML",
        }
        dbg.section("acting_as_target_flow", {
            "checks": checks,
            "add_calls": storage.add_calls,
            "log_events": storage.log_events,
            "replies": update.message.replies,
        })
        if not all(checks.values()):
            dbg.problem("acting_as_target_flow_failed", {"checks": checks})
    finally:
        mainbot.storage = old_storage
        mainbot.tags_dashboard_start = old_tags_dashboard_start
        mainbot.handle_timezone_query_input = old_timezone_query


async def _run_rename_acting_as_target_check(dbg, mainbot):
    storage = _StorageStub()
    update = _DummyUpdate(6002, "🔥 NewName")
    context = _DummyContext()
    context.user_data["expecting_tag_rename"] = True
    context.user_data["tag_rename_old"] = "🍕 Food"
    context.user_data["acting_as_user_id"] = 8888

    calls = {"dashboard": 0}

    old_storage = mainbot.storage
    old_tags_dashboard_start = mainbot.tags_dashboard_start
    old_timezone_query = mainbot.handle_timezone_query_input
    try:
        mainbot.storage = storage

        async def _fake_tags_dashboard_start(_update, _context):
            calls["dashboard"] += 1
            return None

        async def _fake_timezone_query(_update, _context):
            return False

        mainbot.tags_dashboard_start = _fake_tags_dashboard_start
        mainbot.handle_timezone_query_input = _fake_timezone_query

        raised_stop = False
        try:
            await mainbot.global_text_handler(update, context)
        except mainbot.ApplicationHandlerStop:
            raised_stop = True

        rename_calls = [c for c in storage.add_calls if "old_tag" in c]
        success_event = _last_event(storage.log_events, "tag_rename_success")
        checks = {
            "raised_stop": raised_stop,
            "one_rename_call": len(rename_calls) == 1,
            "rename_uses_target_user": bool(rename_calls) and str(rename_calls[0]["user_id"]) == "8888",
            "rename_old_tag_passed": bool(rename_calls) and rename_calls[0]["old_tag"] == "🍕 Food",
            "rename_new_tag_passed": bool(rename_calls) and rename_calls[0]["new_tag"] == "🔥 NewName",
            "rename_state_cleared": context.user_data.get("expecting_tag_rename") is None,
            "dashboard_called_once": calls["dashboard"] == 1,
            "success_event_logged": isinstance(success_event, dict),
            "success_event_has_acting_as": isinstance((success_event or {}).get("payload", {}).get("acting_as"), dict),
        }
        dbg.section("rename_acting_as_target_flow", {
            "checks": checks,
            "rename_calls": rename_calls,
            "log_events": storage.log_events,
            "replies": update.message.replies,
        })
        if not all(checks.values()):
            dbg.problem("rename_acting_as_target_flow_failed", {"checks": checks})
    finally:
        mainbot.storage = old_storage
        mainbot.tags_dashboard_start = old_tags_dashboard_start
        mainbot.handle_timezone_query_input = old_timezone_query


def _run_rename_storage_check(dbg):
    from modules.storage import StorageManager

    tmpdir = tempfile.mkdtemp()
    try:
        sm = StorageManager(base_data_dir=tmpdir)
        sm.log_user_event = lambda *a, **kw: True  # suppress log side-effects

        user_id = "rename_test_user"
        sm.setup_user_space(user_id)

        # Write controlled test data directly (test setup only)
        alerts_path = sm._alerts_path(user_id)
        initial = {
            "tags": ["🍕 Food", "🏠 Home"],
            "alerts": [
                {"id": "a1", "type": 1, "tags": ["🍕 Food"]},
                {"id": "a2", "type": 1, "tags": ["🏠 Home", "🍕 Food"]},
            ],
        }
        with open(alerts_path, "w", encoding="utf-8") as f:
            json.dump(initial, f)

        # 1. Happy path
        ok, reason = sm.rename_user_tag(user_id, "🍕 Food", "🔥 Spicy")
        data = sm.get_all_alerts(user_id)
        tags = data.get("tags", [])
        alerts = data.get("alerts", [])
        happy_checks = {
            "returns_true": ok is True,
            "no_error": reason is None,
            "new_tag_in_master": "🔥 Spicy" in tags,
            "old_tag_gone": "🍕 Food" not in tags,
            "sorted_after_rename": tags.index("🏠 Home") < tags.index("🔥 Spicy"),
            "single_tag_alert_updated": alerts[0].get("tags") == ["🔥 Spicy"],
            "multi_tag_alert_updated": alerts[1].get("tags") == ["🏠 Home", "🔥 Spicy"],
        }

        # 2. Same-tag guard (using current state after happy path)
        ok2, reason2 = sm.rename_user_tag(user_id, "🔥 Spicy", "🔥 Spicy")
        same_tag_checks = {
            "returns_false": ok2 is False,
            "reason_same_tag": reason2 == "same_tag",
        }

        # 3. Name duplicate (reset test data)
        with open(alerts_path, "w", encoding="utf-8") as f:
            json.dump({"tags": ["🍕 Food", "🏠 Home"], "alerts": []}, f)
        ok3, reason3 = sm.rename_user_tag(user_id, "🍕 Food", "🔔 hOmE")
        name_dup_checks = {
            "returns_false": ok3 is False,
            "reason_name_duplicate": isinstance(reason3, str) and reason3.startswith("name_duplicate:"),
            "reason_names_home": isinstance(reason3, str) and "🏠 Home" in reason3,
        }

        # 4. Not found
        ok4, reason4 = sm.rename_user_tag(user_id, "❌ Ghost", "🔥 New")
        not_found_checks = {
            "returns_false": ok4 is False,
            "reason_not_found": reason4 == "not_found",
        }

        all_checks = {**happy_checks, **same_tag_checks, **name_dup_checks, **not_found_checks}
        dbg.section("rename_storage", {
            "happy": happy_checks,
            "same_tag": same_tag_checks,
            "name_dup": name_dup_checks,
            "not_found": not_found_checks,
        })
        if not all(all_checks.values()):
            dbg.problem("rename_storage_failed", {"checks": all_checks})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _run_rename_handler_check(dbg, mainbot):
    # Test: invalid format input during rename flow
    storage = _StorageStub()
    update = _DummyUpdate(5002, "no_emoji_no_space")
    context = _DummyContext()
    context.user_data["expecting_tag_rename"] = True
    context.user_data["tag_rename_old"] = "🍕 Food"

    old_storage = mainbot.storage
    old_tags_dashboard_start = mainbot.tags_dashboard_start
    old_timezone_query = mainbot.handle_timezone_query_input
    try:
        mainbot.storage = storage

        async def _fake_tags_dashboard_start(_update, _context):
            return None

        async def _fake_timezone_query(_update, _context):
            return False

        mainbot.tags_dashboard_start = _fake_tags_dashboard_start
        mainbot.handle_timezone_query_input = _fake_timezone_query

        raised_stop = False
        try:
            await mainbot.global_text_handler(update, context)
        except mainbot.ApplicationHandlerStop:
            raised_stop = True

        invalid_event = _last_event(storage.log_events, "tag_rename_invalid_format")
        checks = {
            "raised_stop": raised_stop,
            "rename_state_preserved": context.user_data.get("expecting_tag_rename") is True,
            "no_rename_call": all("old_tag" not in c for c in storage.add_calls),
            "reply_sent": len(update.message.replies) == 1,
            "reply_mentions_invalid": bool(update.message.replies and "Invalid tag format" in update.message.replies[0]["text"]),
            "event_logged": isinstance(invalid_event, dict),
            "event_has_old_tag_len": isinstance((invalid_event or {}).get("payload", {}).get("old_tag_len"), int),
            "event_has_old_tag_hash": isinstance((invalid_event or {}).get("payload", {}).get("old_tag_hash"), str),
            "event_has_new_tag_len": isinstance((invalid_event or {}).get("payload", {}).get("new_tag_len"), int),
            "event_has_new_tag_hash": isinstance((invalid_event or {}).get("payload", {}).get("new_tag_hash"), str),
        }
        dbg.section("rename_handler_invalid", {
            "checks": checks,
            "log_events": storage.log_events,
            "replies": update.message.replies,
        })
        if not all(checks.values()):
            dbg.problem("rename_handler_invalid_failed", {"checks": checks})
    finally:
        mainbot.storage = old_storage
        mainbot.tags_dashboard_start = old_tags_dashboard_start
        mainbot.handle_timezone_query_input = old_timezone_query


def _run_normalize_check(dbg):
    from modules.tags_logic import normalize_tag_input
    checks = {
        "collapses_internal_spaces": normalize_tag_input("🍕  Food  Bar") == "🍕 Food Bar",
        "strips_outer_spaces": normalize_tag_input("  🍕 Food  ") == "🍕 Food",
        "normalizes_tab_newline": normalize_tag_input("🍕\tFood\nBar") == "🍕 Food Bar",
        "empty_string_safe": normalize_tag_input("") == "",
        "none_safe": normalize_tag_input(None) == "",
    }
    dbg.section("normalize_input", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("normalize_input_failed", {"checks": checks})


def _run_add_sort_check(dbg):
    from modules.storage import StorageManager

    tmpdir = tempfile.mkdtemp()
    try:
        sm = StorageManager(base_data_dir=tmpdir)
        sm.log_user_event = lambda *a, **kw: True  # suppress log side-effects

        user_id = "add_sort_test_user"
        sm.setup_user_space(user_id)

        alerts_path = sm._alerts_path(user_id)
        with open(alerts_path, "w", encoding="utf-8") as f:
            json.dump({"tags": ["🔥 Spicy"], "alerts": []}, f)

        ok, _ = sm.add_user_tag(user_id, "🍕 Food")
        dup_ok, dup_reason = sm.add_user_tag(user_id, "🍔 fOoD")
        data = sm.get_all_alerts(user_id)
        tags = data.get("tags", [])
        checks = {
            "returns_success": ok is True,
            "both_present": "🍕 Food" in tags and "🔥 Spicy" in tags,
            "food_before_spicy": (
                "🍕 Food" in tags and "🔥 Spicy" in tags
                and tags.index("🍕 Food") < tags.index("🔥 Spicy")
            ),
            "case_insensitive_duplicate_rejected": dup_ok is False,
            "duplicate_reason_name_duplicate": isinstance(dup_reason, str) and dup_reason.startswith("name_duplicate:"),
            "duplicate_reason_points_existing": isinstance(dup_reason, str) and "🍕 Food" in dup_reason,
        }
        dbg.section("add_sort", {"checks": checks, "tags": tags, "dup_reason": dup_reason})
        if not all(checks.values()):
            dbg.problem("add_sort_failed", {"checks": checks})
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _run_orphan_partition_helpers_check(dbg):
    from modules.tags_logic import (
        alert_has_any_orphan_tag,
        partition_used_tags_by_master_order,
    )

    master_tags = ["🏠 Home", "🍕 Food", "🍕 Food", "🧰 Work"]
    alerts = [
        {"id": "a1", "tags": ["🍕 Food", "legacy_no_emoji", "🍕 Food"]},
        {"id": "a2", "tags": ["🧰 Work", "legacy_no_emoji_2"]},
        {"id": "a3", "tags": ["🏠 Home", "legacy_no_emoji"]},
        {"id": "a4", "tags": "not-a-list"},
        {"id": "a5", "tags": [None, 7]},
        "bad_alert_shape",
    ]

    used_known, orphan_tags = partition_used_tags_by_master_order(alerts, master_tags)
    checks = {
        "known_tags_follow_master_order": used_known == ["🏠 Home", "🍕 Food", "🧰 Work"],
        "orphan_tags_first_seen_order": orphan_tags == ["legacy_no_emoji", "legacy_no_emoji_2", "7"],
        "orphan_tags_deduplicated": orphan_tags.count("legacy_no_emoji") == 1,
        "has_orphan_true": alert_has_any_orphan_tag(
            {"tags": ["🍕 Food", "legacy_no_emoji"]},
            master_tags,
        )
        is True,
        "has_orphan_false_known_only": alert_has_any_orphan_tag(
            {"tags": ["🏠 Home", "🍕 Food"]},
            master_tags,
        )
        is False,
        "has_orphan_false_bad_shape": alert_has_any_orphan_tag(
            {"tags": "not-a-list"},
            master_tags,
        )
        is False,
    }

    dbg.section("orphan_partition_helpers", {
        "checks": checks,
        "used_known": used_known,
        "orphan_tags": orphan_tags,
    })
    if not all(checks.values()):
        dbg.problem("orphan_partition_helpers_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown = _parse_cli_args(dbg.args)
        if unknown:
            dbg.problem("cli_args_unknown", {"unknown": unknown, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            import mainbot
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _run_format_rules_check(dbg)
        _run_normalize_check(dbg)
        run_async(_run_invalid_flow_check(dbg, mainbot))
        run_async(_run_acting_as_target_check(dbg, mainbot))
        run_async(_run_rename_acting_as_target_check(dbg, mainbot))
        _run_rename_storage_check(dbg)
        _run_add_sort_check(dbg)
        _run_orphan_partition_helpers_check(dbg)
        run_async(_run_rename_handler_check(dbg, mainbot))
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    format_ok = not dbg.has_problem("tag_format_rules_failed")
    normalize_ok = not dbg.has_problem("normalize_input_failed")
    invalid_ok = not dbg.has_problem("invalid_tag_flow_failed")
    acting_ok = not dbg.has_problem("acting_as_target_flow_failed")
    rename_acting_ok = not dbg.has_problem("rename_acting_as_target_flow_failed")
    rename_storage_ok = not dbg.has_problem("rename_storage_failed")
    add_sort_ok = not dbg.has_problem("add_sort_failed")
    orphan_partition_ok = not dbg.has_problem("orphan_partition_helpers_failed")
    rename_handler_ok = not dbg.has_problem("rename_handler_invalid_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"format_rules: {'OK' if format_ok else 'FAIL'}",
        f"normalize_input: {'OK' if normalize_ok else 'FAIL'}",
        f"invalid_flow: {'OK' if invalid_ok else 'FAIL'}",
        f"acting_as_target: {'OK' if acting_ok else 'FAIL'}",
        f"rename_acting_as_target: {'OK' if rename_acting_ok else 'FAIL'}",
        f"rename_storage: {'OK' if rename_storage_ok else 'FAIL'}",
        f"add_sort: {'OK' if add_sort_ok else 'FAIL'}",
        f"orphan_partition_helpers: {'OK' if orphan_partition_ok else 'FAIL'}",
        f"rename_handler: {'OK' if rename_handler_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
