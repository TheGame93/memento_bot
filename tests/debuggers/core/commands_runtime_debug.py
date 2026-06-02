#!/usr/bin/env python3
import asyncio
import os
import sys
import tempfile


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
from _lib.runtime import run_async, seed_mainbot_runtime
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "commands_runtime_debug"
FEATURE_TITLE = "Command Runtime"
SYNC_TO_THREAD = True


def _patch_asyncio_to_thread():
    async def _sync_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    asyncio.to_thread = _sync_to_thread


class DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class DummyMessage:
    def __init__(self):
        self.replies = []
        self.document = None

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})

    async def reply_document(self, document, **kwargs):
        filename = kwargs.get("filename") or getattr(document, "name", None)
        self.replies.append({"document": filename, "kwargs": kwargs})


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class DummyUpdate:
    def __init__(self, user_id):
        self.effective_user = DummyUser(user_id)
        self.message = DummyMessage()
        self.effective_message = self.message
        self.callback_query = None


class DummyContext:
    def __init__(self, args=None):
        self.bot = DummyBot()
        self.user_data = {}
        self.bot_data = {}
        self.args = args or []


def _extract_inline_labels(reply_markup):
    if not reply_markup:
        return []
    labels = []
    for row in getattr(reply_markup, "inline_keyboard", []):
        for button in row:
            labels.append(getattr(button, "text", ""))
    return labels


async def _run_command(
    dbg,
    handler,
    label,
    mainbot_module,
    runtime_storage,
    args=None,
    min_reply_count=1,
    require_next_button=False,
):
    update = DummyUpdate(1)
    context = DummyContext(args=args)
    seed_mainbot_runtime(mainbot_module, app=context, storage=runtime_storage)
    await handler(update, context)
    replied = bool(update.message.replies) or bool(context.bot.sent)
    reply_count = len(update.message.replies)
    first_reply_markup = update.message.replies[0]["kwargs"].get("reply_markup") if update.message.replies else None
    first_reply_labels = _extract_inline_labels(first_reply_markup)
    has_next_button = any("Next" in label for label in first_reply_labels)
    dbg.section(f"{label}_result", {
        "replied": replied,
        "reply_count": reply_count,
        "min_reply_count": min_reply_count,
        "sent_count": len(context.bot.sent),
        "first_reply_has_next_button": has_next_button,
        "first_reply_inline_labels": first_reply_labels,
    })
    if not replied:
        dbg.problem("no_reply", {"command": label})
        return
    if reply_count < min_reply_count:
        dbg.problem("reply_count_too_low", {
            "command": label,
            "reply_count": reply_count,
            "min_reply_count": min_reply_count,
        })
    if require_next_button and not has_next_button:
        dbg.problem("missing_next_button", {
            "command": label,
            "first_reply_inline_labels": first_reply_labels,
        })


async def _run_cancel_case(
    dbg,
    handler,
    label,
    user_data,
    expected_text,
    mainbot_module,
    runtime_storage,
    expected_cleared_keys=None,
):
    update = DummyUpdate(1)
    context = DummyContext()
    seed_mainbot_runtime(mainbot_module, app=context, storage=runtime_storage)
    context.user_data.update(user_data or {})
    await handler(update, context)
    reply_text = update.message.replies[-1]["text"] if update.message.replies else None
    cleared_keys = expected_cleared_keys or []
    checks = {
        "reply_contains": bool(reply_text and expected_text in reply_text),
        "cleared_keys": all(key not in context.user_data for key in cleared_keys),
    }
    dbg.section(f"{label}_cancel", {
        "reply_text": reply_text,
        "expected_text": expected_text,
        "cleared_keys": cleared_keys,
        "checks": checks,
    })
    if not checks["reply_contains"]:
        dbg.problem("cancel_message_mismatch", {
            "label": label,
            "reply_text": reply_text,
            "expected_text": expected_text,
        })
    if not checks["cleared_keys"]:
        dbg.problem("cancel_state_not_cleared", {
            "label": label,
            "remaining_keys": sorted(context.user_data.keys()),
        })


async def _wrapper_probe_command(update, context):
    await update.message.reply_text("WRAPPED_COMMAND_OUTPUT")


async def _run_implicit_pre_cancel_case(
    dbg,
    wrap_builder,
    label,
    user_data,
    expect_cancel,
    mainbot_module,
    runtime_storage,
):
    update = DummyUpdate(1)
    context = DummyContext()
    seed_mainbot_runtime(mainbot_module, app=context, storage=runtime_storage)
    context.user_data.update(user_data or {})
    wrapped = wrap_builder(_wrapper_probe_command)
    await wrapped(update, context)

    reply_texts = [entry.get("text") for entry in update.message.replies if isinstance(entry, dict)]
    cancel_text = "❌ Operation cancelled. Returning to idle state."
    command_text = "WRAPPED_COMMAND_OUTPUT"
    cancel_index = reply_texts.index(cancel_text) if cancel_text in reply_texts else None
    command_index = reply_texts.index(command_text) if command_text in reply_texts else None
    cancel_ran = cancel_index is not None
    command_ran = command_index is not None
    cancel_before_command = (
        cancel_index is not None and command_index is not None and cancel_index < command_index
    )
    pending_pre_alerts_present = "pending_pre_alerts" in context.user_data

    dbg.section(f"implicit_pre_cancel_{label}", {
        "reply_texts": reply_texts,
        "expect_cancel": expect_cancel,
        "cancel_ran": cancel_ran,
        "command_ran": command_ran,
        "cancel_before_command": cancel_before_command,
        "pending_pre_alerts_present_after": pending_pre_alerts_present,
    })
    if not command_ran:
        dbg.problem("implicit_pre_cancel_command_missing", {"label": label})
        return
    if expect_cancel and not cancel_ran:
        dbg.problem("implicit_pre_cancel_missing", {"label": label, "reply_texts": reply_texts})
    if not expect_cancel and cancel_ran:
        dbg.problem("implicit_pre_cancel_unexpected", {"label": label, "reply_texts": reply_texts})
    if expect_cancel and not cancel_before_command:
        dbg.problem("implicit_pre_cancel_order", {"label": label, "reply_texts": reply_texts})
    if expect_cancel and pending_pre_alerts_present:
        dbg.problem("implicit_pre_cancel_state_not_cleared", {
            "label": label,
            "remaining_keys": sorted(context.user_data.keys()),
        })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR, "sync_to_thread": SYNC_TO_THREAD})
        suppress_ptb_user_warning()

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            prev_data_dir = os.environ.get("BOT_DATA_DIR")
            prev_backup_dir = os.environ.get("BOT_BACKUP_DIR")
            os.environ["BOT_DATA_DIR"] = os.path.join(tmpdir, "data")
            os.environ["BOT_BACKUP_DIR"] = os.path.join(tmpdir, "backups")
            os.chdir(tmpdir)
            try:
                whitelist_path = os.path.join(os.environ["BOT_DATA_DIR"], "system", "whitelist.json")
                os.makedirs(os.path.dirname(whitelist_path), exist_ok=True)
                with open(whitelist_path, "w", encoding="utf-8") as handle:
                    handle.write("[1]")

                if SYNC_TO_THREAD:
                    _patch_asyncio_to_thread()

                try:
                    from modules.handlers import alerts as alerts_handlers
                    from modules.handlers import base as base_handlers
                    from modules.handlers import birthdays as birthdays_handlers
                    from modules.handlers import tags_dashboard as tags_handlers
                    import mainbot as mainbot_module
                except ModuleNotFoundError as exc:
                    dbg.mark_dependency_error(exc)
                    dbg.finish(exit_on_problems=False)
                    return
                runtime_storage = getattr(mainbot_module, "storage", None)

                run_async(_run_command(
                    dbg,
                    base_handlers.start,
                    "start",
                    mainbot_module,
                    runtime_storage,
                ))
                run_async(_run_command(
                    dbg,
                    base_handlers.help_command,
                    "help",
                    mainbot_module,
                    runtime_storage,
                    min_reply_count=1,
                    require_next_button=True,
                ))
                run_async(_run_command(dbg, base_handlers.status, "status", mainbot_module, runtime_storage))
                run_async(_run_command(dbg, base_handlers.settings, "settings", mainbot_module, runtime_storage))
                run_async(_run_command(dbg, alerts_handlers.alerts_start, "alerts", mainbot_module, runtime_storage))
                run_async(_run_command(
                    dbg,
                    birthdays_handlers.birthday_start,
                    "birthdays",
                    mainbot_module,
                    runtime_storage,
                ))
                run_async(_run_command(dbg, tags_handlers.tags_dashboard_start, "tags", mainbot_module, runtime_storage))
                run_async(_run_cancel_case(
                    dbg,
                    base_handlers.cancel,
                    "idle",
                    {},
                    "Nothing to cancel, you already are in idle state.",
                    mainbot_module,
                    runtime_storage,
                ))
                run_async(_run_cancel_case(
                    dbg,
                    base_handlers.cancel,
                    "active",
                    {"pending_pre_alerts": []},
                    "Operation cancelled. Returning to idle state.",
                    mainbot_module,
                    runtime_storage,
                    expected_cleared_keys=["pending_pre_alerts"],
                ))
                run_async(_run_implicit_pre_cancel_case(
                    dbg,
                    mainbot_module._wrap_with_implicit_pre_cancel,
                    "active_context",
                    {"pending_pre_alerts": []},
                    expect_cancel=True,
                    mainbot_module=mainbot_module,
                    runtime_storage=runtime_storage,
                ))
                run_async(_run_implicit_pre_cancel_case(
                    dbg,
                    mainbot_module._wrap_with_implicit_pre_cancel,
                    "idle_context",
                    {},
                    expect_cancel=False,
                    mainbot_module=mainbot_module,
                    runtime_storage=runtime_storage,
                ))
            finally:
                os.chdir(cwd)
                if prev_data_dir is None:
                    os.environ.pop("BOT_DATA_DIR", None)
                else:
                    os.environ["BOT_DATA_DIR"] = prev_data_dir
                if prev_backup_dir is None:
                    os.environ.pop("BOT_BACKUP_DIR", None)
                else:
                    os.environ["BOT_BACKUP_DIR"] = prev_backup_dir
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    ok = not dbg.problems
    dbg.finish(summary_lines=[f"runtime: {'OK' if ok else 'FAIL'}"])


if __name__ == "__main__":
    main()
