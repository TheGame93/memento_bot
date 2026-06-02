#!/usr/bin/env python3
import inspect
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
SCRIPT_TITLE = "api_wrapper_install_debug"
FEATURE_TITLE = "API Wrapper Installation"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _DummyMessage:
    def __init__(self):
        self.message_id = 101


class _DummyBot:
    async def send_message(self, chat_id, text, **kwargs):
        return _DummyMessage()

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        return _DummyMessage()

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
        return _DummyMessage()

    async def send_document(self, chat_id, document, caption=None, **kwargs):
        return _DummyMessage()

    async def edit_message_caption(self, chat_id=None, message_id=None, inline_message_id=None, caption=None, **kwargs):
        return _DummyMessage()

    async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
        return _DummyMessage()


class _DummyApp:
    def __init__(self):
        self.bot = _DummyBot()


def _test_wrapper_idempotency(dbg, mainbot):
    app = _DummyApp()
    bot_class = type(app.bot)

    orig_send = bot_class.send_message
    orig_photo = bot_class.send_photo
    orig_edit = bot_class.edit_message_text
    orig_document = bot_class.send_document
    orig_caption = bot_class.edit_message_caption
    orig_markup = bot_class.edit_message_reply_markup

    mainbot._install_bot_api_wrappers(app)
    wrapped_send = bot_class.send_message
    wrapped_photo = bot_class.send_photo
    wrapped_edit = bot_class.edit_message_text
    wrapped_document = bot_class.send_document
    wrapped_caption = bot_class.edit_message_caption
    wrapped_markup = bot_class.edit_message_reply_markup

    mainbot._install_bot_api_wrappers(app)
    wrapped_send_second = bot_class.send_message
    wrapped_photo_second = bot_class.send_photo
    wrapped_edit_second = bot_class.edit_message_text
    wrapped_document_second = bot_class.send_document
    wrapped_caption_second = bot_class.edit_message_caption
    wrapped_markup_second = bot_class.edit_message_reply_markup

    checks = {
        "wrapped_send": wrapped_send is not orig_send,
        "wrapped_photo": wrapped_photo is not orig_photo,
        "wrapped_edit": wrapped_edit is not orig_edit,
        "wrapped_document": wrapped_document is not orig_document,
        "wrapped_caption": wrapped_caption is not orig_caption,
        "wrapped_markup": wrapped_markup is not orig_markup,
        "idempotent_send": wrapped_send is wrapped_send_second,
        "idempotent_photo": wrapped_photo is wrapped_photo_second,
        "idempotent_edit": wrapped_edit is wrapped_edit_second,
        "idempotent_document": wrapped_document is wrapped_document_second,
        "idempotent_caption": wrapped_caption is wrapped_caption_second,
        "idempotent_markup": wrapped_markup is wrapped_markup_second,
        "orig_send_preserved": getattr(bot_class, "_orig_send_message", None) is orig_send,
        "orig_photo_preserved": getattr(bot_class, "_orig_send_photo", None) is orig_photo,
        "orig_edit_preserved": getattr(bot_class, "_orig_edit_message_text", None) is orig_edit,
        "orig_document_preserved": getattr(bot_class, "_orig_send_document", None) is orig_document,
        "orig_caption_preserved": getattr(bot_class, "_orig_edit_message_caption", None) is orig_caption,
        "orig_markup_preserved": getattr(bot_class, "_orig_edit_message_reply_markup", None) is orig_markup,
    }
    dbg.section("wrapper_idempotency", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("wrapper_idempotency_failed", {"checks": checks})


def _test_edit_message_context_extraction(dbg, mainbot):
    class _CtxBot:
        async def edit_message_text(self, text, chat_id=None, message_id=None, **kwargs):
            return _DummyMessage()

    orig_method = _CtxBot.edit_message_text
    standard = mainbot._extract_api_context(
        "edit_message_text",
        orig_method,
        ("hello", 123, 456),
        {},
    )
    legacy = mainbot._extract_api_context(
        "edit_message_text",
        orig_method,
        (123, 456, "legacy"),
        {},
    )
    checks = {
        "standard_chat_id": standard.get("chat_id") == 123,
        "standard_text": standard.get("text") == "hello",
        "standard_message_id": standard.get("message_id") == 456,
        "legacy_chat_id": legacy.get("chat_id") == 123,
        "legacy_text": legacy.get("text") == "legacy",
        "legacy_message_id": legacy.get("message_id") == 456,
    }
    dbg.section("edit_message_context", {"checks": checks, "standard": standard, "legacy": legacy})
    if not all(checks.values()):
        dbg.problem("edit_message_context_failed", {"checks": checks, "standard": standard, "legacy": legacy})


def _test_additional_context_extraction(dbg, mainbot):
    class _DocBot:
        async def send_document(self, chat_id, document, caption=None, **kwargs):
            return _DummyMessage()

    class _EditBot:
        async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
            return _DummyMessage()

    doc_ctx = mainbot._extract_api_context(
        "send_document",
        _DocBot.send_document,
        (111, object(), "doc caption"),
        {},
    )
    inline_ctx = mainbot._extract_api_context(
        "edit_message_reply_markup",
        _EditBot.edit_message_reply_markup,
        (),
        {"inline_message_id": "abc123"},
    )
    checks = {
        "doc_chat_id": doc_ctx.get("chat_id") == 111,
        "doc_caption": doc_ctx.get("caption") == "doc caption",
        "inline_message_id": inline_ctx.get("inline_message_id") == "abc123",
        "inline_chat_id_is_none": inline_ctx.get("chat_id") is None,
    }
    dbg.section("additional_context", {"checks": checks, "doc": doc_ctx, "inline": inline_ctx})
    if not all(checks.values()):
        dbg.problem("additional_context_failed", {"checks": checks, "doc": doc_ctx, "inline": inline_ctx})


def _test_post_init_uses_installer(dbg, mainbot):
    source = inspect.getsource(mainbot.post_init)
    checks = {
        "installer_called": "_install_bot_api_wrappers(application)" in source,
        "legacy_inline_removed": "send_message_logged" not in source,
    }
    dbg.section("post_init_callsite", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("post_init_wrapper_callsite_failed", {"checks": checks})


def _test_wrapper_recovery_hook(dbg, mainbot):
    source = inspect.getsource(mainbot._run_api_with_retry)
    idx_await = source.find("await run_with_retry(")
    idx_close = source.find("_maybe_close_polling_network_window_on_success(operation)")
    checks = {
        "async_helper": inspect.iscoroutinefunction(mainbot._run_api_with_retry),
        "awaits_retry_runner": idx_await != -1,
        "calls_recovery_close_helper": idx_close != -1,
        "close_after_success": idx_await != -1 and idx_close != -1 and idx_close > idx_await,
    }
    dbg.section("wrapper_recovery_hook", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("wrapper_recovery_hook_failed", {"checks": checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})
        suppress_ptb_user_warning()

        try:
            import mainbot
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_wrapper_idempotency(dbg, mainbot)
        _test_edit_message_context_extraction(dbg, mainbot)
        _test_additional_context_extraction(dbg, mainbot)
        _test_post_init_uses_installer(dbg, mainbot)
        _test_wrapper_recovery_hook(dbg, mainbot)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    idempotent_ok = not dbg.has_problem("wrapper_idempotency_failed")
    context_ok = not dbg.has_problem("edit_message_context_failed")
    additional_context_ok = not dbg.has_problem("additional_context_failed")
    callsite_ok = not dbg.has_problem("post_init_wrapper_callsite_failed")
    recovery_hook_ok = not dbg.has_problem("wrapper_recovery_hook_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"idempotency: {'OK' if idempotent_ok else 'FAIL'}",
        f"context: {'OK' if context_ok else 'FAIL'}",
        f"context_extra: {'OK' if additional_context_ok else 'FAIL'}",
        f"callsite: {'OK' if callsite_ok else 'FAIL'}",
        f"recovery_hook: {'OK' if recovery_hook_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
