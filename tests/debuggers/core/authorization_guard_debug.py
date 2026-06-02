#!/usr/bin/env python3
import asyncio
import importlib
import json
import os
import sys
import tempfile
import warnings


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
SCRIPT_TITLE = "authorization_guard_debug"
FEATURE_TITLE = "Authorization Guard"

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


def _write_whitelist(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)



def _load_guard():
    try:
        from telegram.warnings import PTBUserWarning
        warnings.filterwarnings("ignore", category=PTBUserWarning)
    except Exception:
        warnings.filterwarnings("ignore", category=UserWarning)

    import importlib
    paths_module = importlib.import_module("modules.shared.paths")
    importlib.reload(paths_module)
    authz_module = importlib.import_module("modules.security.authz")
    importlib.reload(authz_module)
    storage_module = importlib.import_module("modules.storage")
    importlib.reload(storage_module)
    if "mainbot" in sys.modules:
        importlib.reload(sys.modules["mainbot"])
    else:
        importlib.import_module("mainbot")
    from mainbot import authorization_guard, storage
    return authorization_guard, storage


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self, text=None):
        self.text = text
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


class _DummyUpdate:
    def __init__(self, user_id, text="/status", callback_data=None):
        self.effective_user = _DummyUser(user_id)
        self.effective_message = _DummyMessage(text)
        self.callback_query = None
        if callback_data is not None:
            self.callback_query = _DummyCallbackQuery(callback_data)


class _DummyCallbackQuery:
    def __init__(self, data):
        self.data = data

    async def answer(self, text=None, show_alert=None):
        return None


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class _DummyContext:
    def __init__(self, bot):
        self.bot = bot
        self.user_data = {}


async def _run_guard_with_whitelist(temp_dir, actor_id, target_id):
    whitelist_path = os.path.join(temp_dir, "system", "whitelist.json")
    _write_whitelist(whitelist_path, {"users": [{"id": actor_id, "role": "developer"}]})

    old_cwd = os.getcwd()
    os.chdir(temp_dir)
    try:
        guard, _storage = _load_guard()
        update = _DummyUpdate(actor_id)
        bot = _DummyBot()
        context = _DummyContext(bot)
        context.user_data["acting_as_user_id"] = target_id
        await guard(update, context)
        return {
            "acting_as_cleared": "acting_as_user_id" not in context.user_data,
            "messages_sent": bot.sent,
        }
    finally:
        os.chdir(old_cwd)


def _test_acting_as_clear():
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_data_dir = os.environ.get("BOT_DATA_DIR")
        os.environ["BOT_DATA_DIR"] = tmpdir
        try:
            result = asyncio.run(_run_guard_with_whitelist(tmpdir, actor_id=123, target_id=999))
        finally:
            if previous_data_dir is None:
                os.environ.pop("BOT_DATA_DIR", None)
            else:
                os.environ["BOT_DATA_DIR"] = previous_data_dir

        checks = {
            "cleared": result.get("acting_as_cleared") is True,
            "notice_sent": any("Acting as cleared" in msg for _, msg in result.get("messages_sent", [])),
        }
        print_section("acting_as_clear", {"result": result, "checks": checks})
        if not all(checks.values()):
            _log_problem("guard_failed", {"checks": checks, "result": result})


def _test_maintenance_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_data_dir = os.environ.get("BOT_DATA_DIR")
        os.environ["BOT_DATA_DIR"] = tmpdir
        whitelist_path = os.path.join(tmpdir, "system", "whitelist.json")
        _write_whitelist(whitelist_path, {"users": [{"id": 321, "role": "user"}]})

        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            guard, storage = _load_guard()
            storage.setup_user_space(321)
            storage.update_user_meta(321, {
                "acting_as_lock": {
                    "by": "999",
                    "started_at": "2026-02-10T10:00:00",
                    "expires_at": "2099-02-10T10:00:00",
                }
            })

            update = _DummyUpdate(321, text="/add")
            bot = _DummyBot()
            context = _DummyContext(bot)
            blocked = False
            try:
                asyncio.run(guard(update, context))
            except Exception:
                blocked = True

            update_read = _DummyUpdate(321, text="/status")
            bot_read = _DummyBot()
            context_read = _DummyContext(bot_read)
            allowed = True
            try:
                asyncio.run(guard(update_read, context_read))
            except Exception:
                allowed = False

            print_section("maintenance_lock", {
                "blocked_add": blocked,
                "allowed_status": allowed,
                "messages": update.effective_message.replies,
            })
            if not blocked or not allowed:
                _log_problem("guard_failed", {
                    "blocked_add": blocked,
                    "allowed_status": allowed,
                })
        finally:
            os.chdir(old_cwd)
            if previous_data_dir is None:
                os.environ.pop("BOT_DATA_DIR", None)
            else:
                os.environ["BOT_DATA_DIR"] = previous_data_dir


def _test_onboarding_bypass():
    with tempfile.TemporaryDirectory() as tmpdir:
        previous_data_dir = os.environ.get("BOT_DATA_DIR")
        os.environ["BOT_DATA_DIR"] = tmpdir
        whitelist_path = os.path.join(tmpdir, "system", "whitelist.json")
        _write_whitelist(whitelist_path, {"users": [{"id": 999, "role": "developer"}]})

        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            guard, _storage = _load_guard()

            blocked = False
            try:
                asyncio.run(guard(_DummyUpdate(111, text="/status"), _DummyContext(_DummyBot())))
            except Exception:
                blocked = True

            allow_text = True
            text_context = _DummyContext(_DummyBot())
            text_context.user_data["expecting_start_request_message"] = True
            try:
                asyncio.run(guard(_DummyUpdate(111, text="I am Carol"), text_context))
            except Exception:
                allow_text = False

            allow_cancel = True
            cancel_context = _DummyContext(_DummyBot())
            cancel_context.user_data["start_request_confirm_pending"] = True
            try:
                asyncio.run(guard(_DummyUpdate(111, text="/cancel"), cancel_context))
            except Exception:
                allow_cancel = False

            allow_callback = True
            callback_context = _DummyContext(_DummyBot())
            try:
                asyncio.run(guard(_DummyUpdate(111, text=None, callback_data="startreq_proceed"), callback_context))
            except Exception:
                allow_callback = False
            allow_edit_callback = True
            callback_edit_context = _DummyContext(_DummyBot())
            try:
                asyncio.run(guard(_DummyUpdate(111, text=None, callback_data="startreq_edit_yes"), callback_edit_context))
            except Exception:
                allow_edit_callback = False

            whitelisted_cleanup_ok = True
            cleanup_context = _DummyContext(_DummyBot())
            cleanup_context.user_data["expecting_start_request_message"] = True
            cleanup_context.user_data["start_request_message_draft"] = "stale"
            cleanup_context.user_data["start_request_confirm_pending"] = True
            try:
                asyncio.run(guard(_DummyUpdate(999, text="/help"), cleanup_context))
            except Exception:
                whitelisted_cleanup_ok = False
            flags_cleared = not any(
                key in cleanup_context.user_data
                for key in (
                    "expecting_start_request_message",
                    "start_request_message_draft",
                    "start_request_confirm_pending",
                )
            )

            checks = {
                "normal_unauthorized_blocked": blocked,
                "onboarding_text_allowed": allow_text,
                "onboarding_cancel_allowed": allow_cancel,
                "onboarding_callback_allowed": allow_callback,
                "onboarding_edit_callback_allowed": allow_edit_callback,
                "whitelisted_cleanup_allowed": whitelisted_cleanup_ok,
                "whitelisted_flags_cleared": flags_cleared,
            }
            print_section("onboarding_bypass", {"checks": checks})
            if not all(checks.values()):
                _log_problem("guard_failed", {"checks": checks})
        finally:
            os.chdir(old_cwd)
            if previous_data_dir is None:
                os.environ.pop("BOT_DATA_DIR", None)
            else:
                os.environ["BOT_DATA_DIR"] = previous_data_dir


def main():
    global _DBG
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    _DBG = dbg
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        _test_acting_as_clear()
        _test_maintenance_lock()
        _test_onboarding_bypass()
    except ModuleNotFoundError as exc:
        dbg.mark_dependency_error(exc)
        dbg.finish(exit_on_problems=False)
        return
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        _DBG = None

    guard_ok = not dbg.has_problem("guard_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"guard: {'OK' if guard_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
