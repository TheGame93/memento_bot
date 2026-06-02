"""Runtime dependency bundle utilities shared by bootstrap and handler adapters."""

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any


_BOT_RUNTIME_KEY = "bot_runtime"


@dataclass(frozen=True)
class BotRuntime:
    """Carry bootstrap-owned runtime services for handler-edge dependency lookup."""

    storage: Any
    api_failure_tracker: Any


def _resolve_bot_data(context: Any) -> MutableMapping:
    if isinstance(context, MutableMapping):
        return context
    bot_data = getattr(context, "bot_data", None)
    if isinstance(bot_data, MutableMapping):
        return bot_data
    raise RuntimeError("PTB bot_data is unavailable; bootstrap runtime is not wired.")


def set_bot_runtime(bot_data, runtime: BotRuntime) -> BotRuntime:
    """Persist the bootstrap-owned runtime bundle in PTB bot_data."""

    if not isinstance(runtime, BotRuntime):
        raise TypeError("runtime must be an instance of BotRuntime.")
    target = _resolve_bot_data(bot_data)
    target[_BOT_RUNTIME_KEY] = runtime
    return runtime


def get_bot_runtime(context) -> BotRuntime:
    """Return the runtime bundle from PTB context and fail fast when missing."""

    bot_data = _resolve_bot_data(context)
    runtime = bot_data.get(_BOT_RUNTIME_KEY)
    if isinstance(runtime, BotRuntime):
        return runtime
    raise RuntimeError("Bot runtime is missing from PTB bot_data.")


def get_runtime_storage(context):
    """Return the shared StorageManager from the runtime bundle."""

    return get_bot_runtime(context).storage


def get_runtime_api_failure_tracker(context):
    """Return the shared ApiFailureTracker from the runtime bundle."""

    return get_bot_runtime(context).api_failure_tracker
