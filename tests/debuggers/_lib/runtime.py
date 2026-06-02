import asyncio


def run_async(coro):
    """Run one coroutine synchronously for debugger scripts."""

    return asyncio.run(coro)


def snapshot_mainbot_runtime(mainbot):
    """Capture current mainbot runtime globals so debuggers can restore them."""

    return {
        "storage": getattr(mainbot, "storage", None),
        "api_failure_tracker": getattr(mainbot, "API_FAILURE_TRACKER", None),
    }


def restore_mainbot_runtime(mainbot, snapshot):
    """Restore mainbot runtime globals from a snapshot captured earlier."""

    if not isinstance(snapshot, dict):
        return
    if "storage" in snapshot:
        mainbot.storage = snapshot.get("storage")
    if "api_failure_tracker" in snapshot:
        mainbot.API_FAILURE_TRACKER = snapshot.get("api_failure_tracker")


def seed_mainbot_runtime(mainbot, *, app=None, storage=None, api_failure_tracker=None):
    """Install debugger runtime in app.bot_data and mirror it to mainbot globals."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    runtime_storage = storage if storage is not None else getattr(mainbot, "storage", None)
    runtime_tracker = (
        api_failure_tracker
        if api_failure_tracker is not None
        else getattr(mainbot, "API_FAILURE_TRACKER", None)
    )
    runtime = BotRuntime(storage=runtime_storage, api_failure_tracker=runtime_tracker)

    if app is not None:
        bot_data = getattr(app, "bot_data", None)
        if bot_data is None:
            bot_data = {}
            setattr(app, "bot_data", bot_data)
        set_bot_runtime(bot_data, runtime)

    # Keep compatibility with existing code paths that still read bootstrap globals.
    mainbot.storage = runtime.storage
    mainbot.API_FAILURE_TRACKER = runtime.api_failure_tracker
    return runtime
