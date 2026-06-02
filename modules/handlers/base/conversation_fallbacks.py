"""Build lazy implicit-cancel command fallbacks and manage handler registry state."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable
from typing import Any

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler

_REGISTERED_HANDLERS: list[ConversationHandler] = []

IMPLICIT_CANCEL_COMMANDS: tuple[str, ...] = (
    "alerts",
    "birthdays",
    "help",
    "manage",
    "settings",
    "status",
    "tags",
)

_IMPLICIT_CANCEL_TARGETS: dict[str, tuple[str, str]] = {
    "alerts": ("modules.handlers.alerts", "alerts_start"),
    "birthdays": ("modules.handlers.birthdays", "birthday_start"),
    "help": ("modules.handlers.base", "help_command"),
    "manage": ("modules.handlers.manage", "manage_dashboard_start"),
    "settings": ("modules.handlers.base", "settings"),
    "status": ("modules.handlers.base", "status"),
    "tags": ("modules.handlers.tags_dashboard", "tags_dashboard_start"),
}


def register_conversation_handler(handler: ConversationHandler) -> None:
    """Register a ConversationHandler for the implicit-cancel registry walk."""

    for registered in _REGISTERED_HANDLERS:
        if registered is handler:
            return
    _REGISTERED_HANDLERS.append(handler)


def iter_registered_conversation_handlers() -> Iterable[ConversationHandler]:
    """Yield ConversationHandlers registered for orphan-state cleanup, in registration order."""

    for handler in _REGISTERED_HANDLERS:
        yield handler


def _conversation_key_for_update(update: Update) -> tuple[int, int] | None:
    """Build the (chat_id, user_id) PTB conversation key for `update`, or None when not derivable."""

    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    chat_id = getattr(chat, "id", None)
    user_id = getattr(user, "id", None)
    if chat_id is None or user_id is None:
        return None
    return (chat_id, user_id)


def end_registered_conversations(update: Update) -> int:
    """Force-end any orphaned ConversationHandler state for this update key and return count ended."""

    key = _conversation_key_for_update(update)
    if key is None:
        return 0

    ended_count = 0
    for handler in iter_registered_conversation_handlers():
        conversations = getattr(handler, "conversations", None)
        if conversations is None:
            conversations = getattr(handler, "_conversations", None)
        if not isinstance(conversations, dict):
            continue
        if conversations.pop(key, None) is not None:
            ended_count += 1
    return ended_count


def _resolve_implicit_cancel_target(command_name: str) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Any]:
    module_path, attr_name = _IMPLICIT_CANCEL_TARGETS[command_name]
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def _build_implicit_cancel_callback(command_name: str):
    async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from modules.handlers.base.lifecycle import cancel

        await cancel(update, context)
        target_handler = _resolve_implicit_cancel_target(command_name)
        await target_handler(update, context)
        return ConversationHandler.END

    return _callback


def build_implicit_cancel_fallbacks() -> list[CommandHandler]:
    """Build lazy cancel+dispatch fallback handlers for alerts, birthdays, help, manage, settings, status, and tags."""

    return [
        CommandHandler(command_name, _build_implicit_cancel_callback(command_name))
        for command_name in IMPLICIT_CANCEL_COMMANDS
    ]
