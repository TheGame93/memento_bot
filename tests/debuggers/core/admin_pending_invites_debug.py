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
SCRIPT_TITLE = "admin_pending_invites_debug"
FEATURE_TITLE = "Admin Pending Invites"

IMPORT_ERROR = None
try:
    import modules.handlers.admin as admin_handlers
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


def _test_empty_list():
    text, alias_map = admin_handlers._build_invites_list([])
    checks = {
        "has_empty_label": "No pending invites" in text,
        "alias_empty": alias_map == {},
    }
    print_section("empty_list", {"text": text, "alias_map": alias_map, "checks": checks})
    if not all(checks.values()):
        _log_problem("pending_invites_failed", {"step": "empty_list", "checks": checks})


def _test_alias_map_and_tokens():
    invites = [
        {
            "user_id": "123",
            "username": "alpha",
            "display_name": "Alpha User",
            "role": "user",
            "invited_by": "9",
            "invited_at": "2026-02-13T10:00:00",
        },
        {
            "username": "beta",
            "display_name": "Beta User",
            "role": "admin",
            "invited_by": "10",
            "invited_at": "2026-02-13T11:00:00",
        },
    ]
    text, alias_map = admin_handlers._build_invites_list(invites)
    token_values = sorted(alias_map.values())
    checks = {
        "has_title": "Pending Invites" in text,
        "has_aliases": "/01" in text and "/02" in text,
        "alias_count": len(alias_map) == 2,
        "tokens_expected": token_values == ["id:123", "u:beta"],
        "role_hidden": "(role:" not in text,
    }
    print_section("alias_map", {"text": text, "alias_map": alias_map, "checks": checks})
    if not all(checks.values()):
        _log_problem("pending_invites_failed", {"step": "alias_map", "checks": checks})


def _test_inviter_label_fallback():
    class _StorageStub:
        def __init__(self):
            self._meta = {
                "9": {"custom_name": "Admin Nine", "username": "admin9", "display_name": "Admin User"},
            }

        def get_user_meta(self, user_id):
            return self._meta.get(str(user_id), {})

    invites = [{
        "user_id": "123",
        "username": "alpha",
        "display_name": "Alpha User",
        "invited_by": "9",
        "invited_at": "2026-02-13T10:00:00",
    }]
    text, _alias_map = admin_handlers._build_invites_list(invites, storage=_StorageStub())
    detail = admin_handlers._invite_detail_text(invites[0], storage=_StorageStub())
    checks = {
        "list_uses_label": "by Admin Nine" in text,
        "detail_uses_label": "Invited by: Admin Nine" in detail,
    }
    print_section("inviter_label", {"list_text": text, "detail_text": detail, "checks": checks})
    if not all(checks.values()):
        _log_problem("pending_invites_failed", {"step": "inviter_label", "checks": checks})


def _test_token_roundtrip():
    original_find = admin_handlers.find_whitelist_invite
    lookup = {
        "123": {"user_id": "123", "username": "alpha"},
        "beta": {"username": "beta"},
    }

    def _fake_find_whitelist_invite(user_id=None, username=None):
        if user_id is not None:
            return lookup.get(str(user_id))
        if username is not None:
            return lookup.get(str(username))
        return None

    admin_handlers.find_whitelist_invite = _fake_find_whitelist_invite
    try:
        rec_id = admin_handlers._find_invite_by_token("id:123")
        rec_uname = admin_handlers._find_invite_by_token("u:beta")
        rec_bad = admin_handlers._find_invite_by_token("x:zzz")
        checks = {
            "id_lookup": isinstance(rec_id, dict) and rec_id.get("user_id") == "123",
            "username_lookup": isinstance(rec_uname, dict) and rec_uname.get("username") == "beta",
            "bad_lookup_none": rec_bad is None,
        }
        print_section("token_roundtrip", {"checks": checks, "id": rec_id, "uname": rec_uname, "bad": rec_bad})
        if not all(checks.values()):
            _log_problem("pending_invites_failed", {"step": "token_roundtrip", "checks": checks})
    finally:
        admin_handlers.find_whitelist_invite = original_find


def _test_revoke_by_id_and_username():
    original_remove = admin_handlers.remove_whitelist_invite
    calls = []

    def _fake_remove_whitelist_invite(user_id=None, username=None):
        calls.append({"user_id": user_id, "username": username})
        return True

    admin_handlers.remove_whitelist_invite = _fake_remove_whitelist_invite
    try:
        ok_id = admin_handlers._remove_invite_record({"user_id": "77", "username": "name77"})
        ok_uname = admin_handlers._remove_invite_record({"username": "name88"})
        checks = {
            "id_removed": ok_id is True,
            "username_removed": ok_uname is True,
            "id_call_first": calls and str(calls[0].get("user_id")) == "77",
            "uname_call_second": len(calls) > 1 and calls[1].get("username") == "name88",
        }
        print_section("revoke", {"calls": calls, "checks": checks})
        if not all(checks.values()):
            _log_problem("pending_invites_failed", {"step": "revoke", "checks": checks})
    finally:
        admin_handlers.remove_whitelist_invite = original_remove


def _test_prune_stale_id_invites():
    class _StorageStub:
        def is_user_whitelisted(self, target_id):
            return str(target_id) == "123"

    original_list = admin_handlers.list_whitelist_invites
    original_remove = admin_handlers.remove_whitelist_invite
    original_log_system = admin_handlers.log_system
    remove_calls = []
    log_calls = []

    def _fake_list_whitelist_invites():
        return [
            {"user_id": "123", "username": "alpha", "invited_at": "2026-02-13T10:00:00"},
            {"user_id": "456", "username": "beta", "invited_at": "2026-02-13T11:00:00"},
            {"username": "gamma", "invited_at": "2026-02-13T12:00:00"},
        ]

    def _fake_remove_whitelist_invite(user_id=None, username=None):
        remove_calls.append({"user_id": user_id, "username": username})
        return True

    def _fake_log_system(category, event, payload=None, level=None):
        log_calls.append({"category": category, "event": event, "payload": payload, "level": level})

    admin_handlers.list_whitelist_invites = _fake_list_whitelist_invites
    admin_handlers.remove_whitelist_invite = _fake_remove_whitelist_invite
    admin_handlers.log_system = _fake_log_system
    try:
        count = admin_handlers._prune_stale_id_invites(_StorageStub(), actor_id="9")
        checks = {
            "pruned_one": count == 1,
            "removed_id_123": any(str(c.get("user_id")) == "123" for c in remove_calls),
            "not_removed_username_only": all(c.get("username") is None for c in remove_calls),
            "logged_audit": any(c.get("category") == "admin_audit" for c in log_calls),
            "logged_security": any(c.get("category") == "security" for c in log_calls),
        }
        print_section("prune_stale", {"count": count, "remove_calls": remove_calls, "checks": checks})
        if not all(checks.values()):
            _log_problem("pending_invites_failed", {"step": "prune_stale", "checks": checks})
    finally:
        admin_handlers.list_whitelist_invites = original_list
        admin_handlers.remove_whitelist_invite = original_remove
        admin_handlers.log_system = original_log_system


def _test_callback_token_safety():
    record_ok = {"username": "a" * 32}
    record_long = {"username": "a" * 33}
    token_ok = admin_handlers._invite_token_from_record(record_ok)
    token_long = admin_handlers._invite_token_from_record(record_long)
    cb_ok = f"admin_invite_revoke_confirm:{token_ok}" if token_ok else ""
    checks = {
        "token_ok_exists": bool(token_ok),
        "token_long_none": token_long is None,
        "callback_safe": admin_handlers._callback_data_safe(cb_ok),
    }
    print_section("callback_safety", {"token_ok": token_ok, "token_long": token_long, "checks": checks})
    if not all(checks.values()):
        _log_problem("pending_invites_failed", {"step": "callback_safety", "checks": checks})


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

        _test_empty_list()
        _test_alias_map_and_tokens()
        _test_inviter_label_fallback()
        _test_token_roundtrip()
        _test_revoke_by_id_and_username()
        _test_prune_stale_id_invites()
        _test_callback_token_safety()
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    checks_ok = not dbg.has_problem("pending_invites_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"pending_invites: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
