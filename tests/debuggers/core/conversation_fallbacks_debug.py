#!/usr/bin/env python3
import asyncio
import os
import sys
import warnings

warnings.simplefilter("ignore")

try:
    from telegram.warnings import PTBUserWarning
except Exception:  # pragma: no cover - defensive import guard
    PTBUserWarning = UserWarning

warnings.filterwarnings(
    "ignore",
    message=r"If 'per_message=False'.*per_ settings in ConversationHandler.*",
    category=PTBUserWarning,
)


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
SCRIPT_TITLE = "conversation_fallbacks_debug"
FEATURE_TITLE = "Conversation Fallbacks"

IMPORT_ERROR = None
try:
    from telegram.ext import CommandHandler, ConversationHandler
    from modules.handlers.base import lifecycle
    from modules.handlers.base import conversation_fallbacks as cf
    from modules.handlers import add_alert as add_alert_handlers
    from modules.handlers.birthday_flow import flow as birthday_flow_handlers
    from modules.handlers.edit_flow import flow as edit_flow_handlers
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _DummyMessage:
    def __init__(self, text=None):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({"text": text, "kwargs": kwargs})


class _DummyUpdate:
    def __init__(self, *, chat_id=1001, user_id=2002, include_chat=True, include_user=True):
        self.effective_chat = _DummyChat(chat_id) if include_chat else None
        self.effective_user = _DummyUser(user_id) if include_user else None
        self.message = _DummyMessage()
        self.effective_message = self.message
        self.callback_query = None


class _DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.bot = _DummyBot()


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class _FakeStorage:
    def __init__(self):
        self.events = []

    def log_user_event(self, user_id, event_type, payload):
        self.events.append(
            {
                "user_id": user_id,
                "event_type": event_type,
                "payload": payload,
            }
        )


async def _noop_callback(update, context):
    return None


def _make_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("noop", _noop_callback)],
        states={},
        fallbacks=[],
    )


def _conversation_map(handler):
    conversations = getattr(handler, "conversations", None)
    if isinstance(conversations, dict):
        return conversations
    conversations = getattr(handler, "_conversations", None)
    if isinstance(conversations, dict):
        return conversations
    raise RuntimeError("ConversationHandler does not expose a mutable conversations map.")


def _handler_key(chat_id, user_id):
    return (chat_id, user_id)


def _reset_registry():
    cf._REGISTERED_HANDLERS.clear()


def _run_registry_shape_checks(dbg):
    _reset_registry()
    handler_a = _make_handler()
    handler_b = _make_handler()
    cf.register_conversation_handler(handler_a)
    cf.register_conversation_handler(handler_a)
    cf.register_conversation_handler(handler_b)

    iterated = list(cf.iter_registered_conversation_handlers())
    checks = {
        "register_idempotent_identity": iterated.count(handler_a) == 1,
        "register_keeps_insertion_order": iterated == [handler_a, handler_b],
    }
    dbg.section("registry_shape", {"checks": checks, "count": len(iterated)})
    if not all(checks.values()):
        dbg.problem("registry_shape_failed", {"checks": checks})


def _run_conversation_key_checks(dbg):
    normal = _DummyUpdate(chat_id=77, user_id=88)
    missing_chat = _DummyUpdate(include_chat=False)
    missing_user = _DummyUpdate(include_user=False)
    checks = {
        "normal_key": cf._conversation_key_for_update(normal) == (77, 88),
        "missing_chat_none": cf._conversation_key_for_update(missing_chat) is None,
        "missing_user_none": cf._conversation_key_for_update(missing_user) is None,
    }
    dbg.section("conversation_key", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("conversation_key_failed", {"checks": checks})


def _run_end_registered_conversations_checks(dbg):
    _reset_registry()
    handler_a = _make_handler()
    handler_b = _make_handler()
    handler_c = _make_handler()
    cf.register_conversation_handler(handler_a)
    cf.register_conversation_handler(handler_b)
    cf.register_conversation_handler(handler_c)

    key_target = (101, 202)
    key_other = (303, 404)
    map_a = _conversation_map(handler_a)
    map_b = _conversation_map(handler_b)
    map_c = _conversation_map(handler_c)
    map_a[key_target] = 1
    map_b[key_target] = 2
    map_c[key_other] = 3

    removed = cf.end_registered_conversations(_DummyUpdate(chat_id=101, user_id=202))
    checks = {
        "removed_count_matches": removed == 2,
        "target_removed_a": key_target not in map_a,
        "target_removed_b": key_target not in map_b,
        "other_key_preserved": map_c.get(key_other) == 3,
    }
    dbg.section("end_registered_conversations", {"checks": checks, "removed": removed})
    if not all(checks.values()):
        dbg.problem("end_registered_conversations_failed", {"checks": checks, "removed": removed})


def _run_command_map_and_builder_checks(dbg):
    expected = ("alerts", "birthdays", "help", "manage", "settings", "status", "tags")
    cmd_set = set(cf.IMPLICIT_CANCEL_COMMANDS)
    mapping_keys = set(cf._IMPLICIT_CANCEL_TARGETS.keys())

    module_snapshot = {name: sys.modules.get(name) for name, _ in cf._IMPLICIT_CANCEL_TARGETS.values()}
    target_modules_before = {name for name, module in module_snapshot.items() if module is not None}
    handlers = cf.build_implicit_cancel_fallbacks()
    target_modules_after = {name for name, _ in cf._IMPLICIT_CANCEL_TARGETS.values() if sys.modules.get(name) is not None}
    newly_loaded = sorted(target_modules_after - target_modules_before)

    built_commands = []
    for handler in handlers:
        if isinstance(handler, CommandHandler):
            built_commands.extend(sorted(handler.commands))

    checks = {
        "commands_exact": tuple(cf.IMPLICIT_CANCEL_COMMANDS) == expected,
        "commands_unique": len(cmd_set) == len(cf.IMPLICIT_CANCEL_COMMANDS),
        "commands_excludes_start": "start" not in cmd_set,
        "mapping_matches_commands": mapping_keys == cmd_set,
        "builder_count_is_seven": len(handlers) == 7,
        "builder_all_command_handlers": all(isinstance(h, CommandHandler) for h in handlers),
        "builder_commands_match": tuple(built_commands) == expected,
        "builder_no_target_imports": not newly_loaded,
    }
    dbg.section(
        "command_map_builder",
        {
            "checks": checks,
            "newly_loaded_targets": newly_loaded,
            "built_commands": built_commands,
        },
    )
    if not all(checks.values()):
        dbg.problem("command_map_builder_failed", {"checks": checks, "newly_loaded_targets": newly_loaded})


def _run_target_resolution_checks(dbg):
    from modules.handlers.alerts import alerts_start
    from modules.handlers.base import help_command, settings, status
    from modules.handlers.birthdays import birthday_start
    from modules.handlers.manage import manage_dashboard_start
    from modules.handlers.tags_dashboard import tags_dashboard_start

    expected = {
        "alerts": alerts_start,
        "birthdays": birthday_start,
        "help": help_command,
        "manage": manage_dashboard_start,
        "settings": settings,
        "status": status,
        "tags": tags_dashboard_start,
    }
    resolved = {name: cf._resolve_implicit_cancel_target(name) for name in cf.IMPLICIT_CANCEL_COMMANDS}
    checks = {f"resolve_{name}": resolved[name] is target for name, target in expected.items()}
    dbg.section("target_resolution", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("target_resolution_failed", {"checks": checks})


async def _run_lifecycle_cancel_checks(dbg):
    _reset_registry()
    storage = _FakeStorage()
    context = _DummyContext()
    set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))

    handler_a = _make_handler()
    handler_b = _make_handler()
    cf.register_conversation_handler(handler_a)
    cf.register_conversation_handler(handler_b)
    key = (501, 601)
    map_a = _conversation_map(handler_a)
    map_b = _conversation_map(handler_b)
    map_a[key] = "a"
    map_b[key] = "b"

    update = _DummyUpdate(chat_id=501, user_id=601)
    await lifecycle.cancel(update, context)

    reply = update.message.replies[-1] if update.message.replies else {}
    event = storage.events[-1] if storage.events else {}
    checks_registry_only = {
        "both_registry_keys_removed": key not in map_a and key not in map_b,
        "single_command_cancel_event": len(storage.events) == 1 and event.get("event_type") == "command_cancel",
        "was_active_true_from_registry_only": bool(event.get("payload", {}).get("was_active")),
        "cancel_text_exact": reply.get("text") == "❌ Operation cancelled. Returning to idle state.",
        "parse_mode_none": "parse_mode" not in reply.get("kwargs", {}),
    }
    dbg.section("lifecycle_cancel_registry", {"checks": checks_registry_only, "event": event, "reply": reply})
    if not all(checks_registry_only.values()):
        dbg.problem("lifecycle_cancel_registry_failed", {"checks": checks_registry_only, "event": event, "reply": reply})

    _reset_registry()
    storage_2 = _FakeStorage()
    context_2 = _DummyContext()
    context_2.user_data["pending_pre_alerts"] = []
    set_bot_runtime(context_2.bot_data, BotRuntime(storage=storage_2, api_failure_tracker=None))
    update_2 = _DummyUpdate(chat_id=502, user_id=602)
    await lifecycle.cancel(update_2, context_2)

    reply_2 = update_2.message.replies[-1] if update_2.message.replies else {}
    event_2 = storage_2.events[-1] if storage_2.events else {}
    checks_transient_only = {
        "transient_cleared": "pending_pre_alerts" not in context_2.user_data,
        "single_command_cancel_event": len(storage_2.events) == 1 and event_2.get("event_type") == "command_cancel",
        "was_active_true_from_transient": bool(event_2.get("payload", {}).get("was_active")),
        "cancel_text_exact": reply_2.get("text") == "❌ Operation cancelled. Returning to idle state.",
        "parse_mode_none": "parse_mode" not in reply_2.get("kwargs", {}),
    }
    dbg.section("lifecycle_cancel_transient", {"checks": checks_transient_only, "event": event_2, "reply": reply_2})
    if not all(checks_transient_only.values()):
        dbg.problem("lifecycle_cancel_transient_failed", {"checks": checks_transient_only, "event": event_2, "reply": reply_2})


async def _run_step2a_add_alert_checks(dbg):
    _reset_registry()
    key = _handler_key(701, 801)

    class _SpyStorage:
        def __init__(self):
            self.events = []
            self._alerts = {}

        def log_user_event(self, user_id, event_type, payload):
            self.events.append({"user_id": user_id, "event_type": event_type, "payload": payload})

        def get_all_alerts(self, user_id):
            return self._alerts.get(user_id) or {"alerts": [], "tags": []}

        def setup_user_space(self, user_id):
            self._alerts.setdefault(user_id, {"alerts": [], "tags": []})

    # Wiring checks on add_alert_handler fallbacks.
    fallback_list = list(getattr(add_alert_handlers.add_alert_handler, "fallbacks", []) or [])
    fallback_commands = []
    for handler in fallback_list:
        if isinstance(handler, CommandHandler):
            fallback_commands.extend(sorted(handler.commands))
    checks_wiring = {
        "fallback_count_expected": len(fallback_list) == 8,
        "local_cancel_first": bool(fallback_list) and isinstance(fallback_list[0], CommandHandler) and tuple(sorted(fallback_list[0].commands)) == ("cancel",),
        "implicit_commands_match": tuple(fallback_commands[1:]) == cf.IMPLICIT_CANCEL_COMMANDS,
    }
    dbg.section("step2a_wiring", {"checks": checks_wiring, "commands": fallback_commands})
    if not all(checks_wiring.values()):
        dbg.problem("step2a_wiring_failed", {"checks": checks_wiring, "commands": fallback_commands})

    # Local /cancel should clear add_alert + any other registered handler key and not emit command_cancel.
    storage_local = _SpyStorage()
    context_local = _DummyContext()
    set_bot_runtime(context_local.bot_data, BotRuntime(storage=storage_local, api_failure_tracker=None))
    update_local = _DummyUpdate(chat_id=key[0], user_id=key[1])
    context_local.user_data["temp_alert"] = {"title": "x"}

    secondary_handler = _make_handler()
    cf.register_conversation_handler(add_alert_handlers.add_alert_handler)
    cf.register_conversation_handler(secondary_handler)
    _conversation_map(add_alert_handlers.add_alert_handler)[key] = 10
    _conversation_map(secondary_handler)[key] = 20

    local_result = await add_alert_handlers.cancel(update_local, context_local)
    local_reply = update_local.message.replies[-1] if update_local.message.replies else {}
    checks_local_cancel = {
        "returns_end": local_result == ConversationHandler.END,
        "both_keys_cleared": key not in _conversation_map(add_alert_handlers.add_alert_handler) and key not in _conversation_map(secondary_handler),
        "local_text_preserved": local_reply.get("text") == "⏹️ **Cancelled.**",
        "local_parse_mode_markdown": local_reply.get("kwargs", {}).get("parse_mode") == "Markdown",
        "no_command_cancel_event": not any(event.get("event_type") == "command_cancel" for event in storage_local.events),
    }
    dbg.section("step2a_local_cancel", {"checks": checks_local_cancel, "reply": local_reply, "events": storage_local.events})
    if not all(checks_local_cancel.values()):
        dbg.problem("step2a_local_cancel_failed", {"checks": checks_local_cancel})

    # Implicit fallback commands should run lifecycle.cancel then target handler and clear add_alert conversation key.
    import modules.handlers.alerts as alerts_mod
    import modules.handlers.birthdays as birthdays_mod
    import modules.handlers.base as base_mod
    import modules.handlers.manage as manage_mod
    import modules.handlers.tags_dashboard as tags_mod

    originals = {
        ("alerts", "alerts_start"): alerts_mod.alerts_start,
        ("birthdays", "birthday_start"): birthdays_mod.birthday_start,
        ("help", "help_command"): base_mod.help_command,
        ("manage", "manage_dashboard_start"): manage_mod.manage_dashboard_start,
        ("settings", "settings"): base_mod.settings,
        ("status", "status"): base_mod.status,
        ("tags", "tags_dashboard_start"): tags_mod.tags_dashboard_start,
    }
    call_trace = []

    async def _spy_target(update, context):
        label = context.user_data.get("_expected_command")
        call_trace.append(label)
        await update.message.reply_text(f"TARGET:{label}")

    alerts_mod.alerts_start = _spy_target
    birthdays_mod.birthday_start = _spy_target
    base_mod.help_command = _spy_target
    manage_mod.manage_dashboard_start = _spy_target
    base_mod.settings = _spy_target
    base_mod.status = _spy_target
    tags_mod.tags_dashboard_start = _spy_target

    implicit_handlers = [h for h in fallback_list[1:] if isinstance(h, CommandHandler)]
    implicit_ok = True
    detail_rows = []
    try:
        for idx, command_name in enumerate(cf.IMPLICIT_CANCEL_COMMANDS):
            storage = _SpyStorage()
            context = _DummyContext()
            set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
            context.user_data["_expected_command"] = command_name
            update = _DummyUpdate(chat_id=key[0], user_id=key[1] + idx + 1)
            run_key = _handler_key(update.effective_chat.id, update.effective_user.id)

            _reset_registry()
            cf.register_conversation_handler(add_alert_handlers.add_alert_handler)
            _conversation_map(add_alert_handlers.add_alert_handler)[run_key] = idx

            handler = implicit_handlers[idx]
            result = await handler.callback(update, context)
            replies = [item.get("text") for item in update.message.replies]
            command_cancel_events = [ev for ev in storage.events if ev.get("event_type") == "command_cancel"]
            row = {
                "command": command_name,
                "ended": run_key not in _conversation_map(add_alert_handlers.add_alert_handler),
                "returns_end": result == ConversationHandler.END,
                "event_once": len(command_cancel_events) == 1,
                "event_active_true": len(command_cancel_events) == 1 and bool(command_cancel_events[0].get("payload", {}).get("was_active")),
                "target_ran": f"TARGET:{command_name}" in replies and command_name in call_trace,
            }
            detail_rows.append(row)
            if not all(row.values()):
                implicit_ok = False
    finally:
        alerts_mod.alerts_start = originals[("alerts", "alerts_start")]
        birthdays_mod.birthday_start = originals[("birthdays", "birthday_start")]
        base_mod.help_command = originals[("help", "help_command")]
        manage_mod.manage_dashboard_start = originals[("manage", "manage_dashboard_start")]
        base_mod.settings = originals[("settings", "settings")]
        base_mod.status = originals[("status", "status")]
        tags_mod.tags_dashboard_start = originals[("tags", "tags_dashboard_start")]

    dbg.section("step2a_implicit_commands", {"rows": detail_rows, "ok": implicit_ok})
    if not implicit_ok:
        dbg.problem("step2a_implicit_commands_failed", {"rows": detail_rows})


async def _run_step2b_birthday_checks(dbg):
    _reset_registry()
    key = _handler_key(711, 811)

    class _SpyStorage:
        def __init__(self):
            self.events = []
            self._alerts = {}

        def log_user_event(self, user_id, event_type, payload):
            self.events.append({"user_id": user_id, "event_type": event_type, "payload": payload})

        def get_all_alerts(self, user_id):
            return self._alerts.get(user_id) or {"alerts": [], "tags": []}

        def setup_user_space(self, user_id):
            self._alerts.setdefault(user_id, {"alerts": [], "tags": []})

    fallback_list = list(getattr(birthday_flow_handlers.birthday_add_handler, "fallbacks", []) or [])
    fallback_commands = []
    for handler in fallback_list:
        if isinstance(handler, CommandHandler):
            fallback_commands.extend(sorted(handler.commands))
    checks_wiring = {
        "fallback_count_expected": len(fallback_list) == 8,
        "local_cancel_first": bool(fallback_list) and isinstance(fallback_list[0], CommandHandler) and tuple(sorted(fallback_list[0].commands)) == ("cancel",),
        "implicit_commands_match": tuple(fallback_commands[1:]) == cf.IMPLICIT_CANCEL_COMMANDS,
    }
    dbg.section("step2b_wiring", {"checks": checks_wiring, "commands": fallback_commands})
    if not all(checks_wiring.values()):
        dbg.problem("step2b_wiring_failed", {"checks": checks_wiring, "commands": fallback_commands})

    storage_local = _SpyStorage()
    context_local = _DummyContext()
    set_bot_runtime(context_local.bot_data, BotRuntime(storage=storage_local, api_failure_tracker=None))
    update_local = _DummyUpdate(chat_id=key[0], user_id=key[1])
    context_local.user_data["temp_alert"] = {"title": "x"}

    secondary_handler = _make_handler()
    cf.register_conversation_handler(birthday_flow_handlers.birthday_add_handler)
    cf.register_conversation_handler(secondary_handler)
    _conversation_map(birthday_flow_handlers.birthday_add_handler)[key] = 10
    _conversation_map(secondary_handler)[key] = 20

    local_result = await birthday_flow_handlers.birthday_cancel(update_local, context_local)
    local_reply = update_local.message.replies[-1] if update_local.message.replies else {}
    checks_local_cancel = {
        "returns_end": local_result == ConversationHandler.END,
        "both_keys_cleared": key not in _conversation_map(birthday_flow_handlers.birthday_add_handler) and key not in _conversation_map(secondary_handler),
        "local_text_preserved": local_reply.get("text") == "⏹️ **Cancelled.**",
        "local_parse_mode_markdown": local_reply.get("kwargs", {}).get("parse_mode") == "Markdown",
        "no_command_cancel_event": not any(event.get("event_type") == "command_cancel" for event in storage_local.events),
    }
    dbg.section("step2b_local_cancel", {"checks": checks_local_cancel, "reply": local_reply, "events": storage_local.events})
    if not all(checks_local_cancel.values()):
        dbg.problem("step2b_local_cancel_failed", {"checks": checks_local_cancel})

    import modules.handlers.alerts as alerts_mod
    import modules.handlers.birthdays as birthdays_mod
    import modules.handlers.base as base_mod
    import modules.handlers.manage as manage_mod
    import modules.handlers.tags_dashboard as tags_mod

    originals = {
        ("alerts", "alerts_start"): alerts_mod.alerts_start,
        ("birthdays", "birthday_start"): birthdays_mod.birthday_start,
        ("help", "help_command"): base_mod.help_command,
        ("manage", "manage_dashboard_start"): manage_mod.manage_dashboard_start,
        ("settings", "settings"): base_mod.settings,
        ("status", "status"): base_mod.status,
        ("tags", "tags_dashboard_start"): tags_mod.tags_dashboard_start,
    }
    call_trace = []

    async def _spy_target(update, context):
        label = context.user_data.get("_expected_command")
        call_trace.append(label)
        await update.message.reply_text(f"TARGET:{label}")

    alerts_mod.alerts_start = _spy_target
    birthdays_mod.birthday_start = _spy_target
    base_mod.help_command = _spy_target
    manage_mod.manage_dashboard_start = _spy_target
    base_mod.settings = _spy_target
    base_mod.status = _spy_target
    tags_mod.tags_dashboard_start = _spy_target

    implicit_handlers = [h for h in fallback_list[1:] if isinstance(h, CommandHandler)]
    implicit_ok = True
    detail_rows = []
    try:
        for idx, command_name in enumerate(cf.IMPLICIT_CANCEL_COMMANDS):
            storage = _SpyStorage()
            context = _DummyContext()
            set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
            context.user_data["_expected_command"] = command_name
            update = _DummyUpdate(chat_id=key[0], user_id=key[1] + idx + 1)
            run_key = _handler_key(update.effective_chat.id, update.effective_user.id)

            _reset_registry()
            cf.register_conversation_handler(birthday_flow_handlers.birthday_add_handler)
            _conversation_map(birthday_flow_handlers.birthday_add_handler)[run_key] = idx

            handler = implicit_handlers[idx]
            result = await handler.callback(update, context)
            replies = [item.get("text") for item in update.message.replies]
            command_cancel_events = [ev for ev in storage.events if ev.get("event_type") == "command_cancel"]
            row = {
                "command": command_name,
                "ended": run_key not in _conversation_map(birthday_flow_handlers.birthday_add_handler),
                "returns_end": result == ConversationHandler.END,
                "event_once": len(command_cancel_events) == 1,
                "event_active_true": len(command_cancel_events) == 1 and bool(command_cancel_events[0].get("payload", {}).get("was_active")),
                "target_ran": f"TARGET:{command_name}" in replies and command_name in call_trace,
            }
            detail_rows.append(row)
            if not all(row.values()):
                implicit_ok = False
    finally:
        alerts_mod.alerts_start = originals[("alerts", "alerts_start")]
        birthdays_mod.birthday_start = originals[("birthdays", "birthday_start")]
        base_mod.help_command = originals[("help", "help_command")]
        manage_mod.manage_dashboard_start = originals[("manage", "manage_dashboard_start")]
        base_mod.settings = originals[("settings", "settings")]
        base_mod.status = originals[("status", "status")]
        tags_mod.tags_dashboard_start = originals[("tags", "tags_dashboard_start")]

    dbg.section("step2b_implicit_commands", {"rows": detail_rows, "ok": implicit_ok})
    if not implicit_ok:
        dbg.problem("step2b_implicit_commands_failed", {"rows": detail_rows})


async def _run_step2c_edit_checks(dbg):
    _reset_registry()
    key = _handler_key(721, 821)

    class _SpyStorage:
        def __init__(self):
            self.events = []
            self._alerts = {}

        def log_user_event(self, user_id, event_type, payload):
            self.events.append({"user_id": user_id, "event_type": event_type, "payload": payload})

        def get_all_alerts(self, user_id):
            return self._alerts.get(user_id) or {"alerts": [], "tags": []}

        def setup_user_space(self, user_id):
            self._alerts.setdefault(user_id, {"alerts": [], "tags": []})

    fallback_list = list(getattr(edit_flow_handlers.edit_alert_handler, "fallbacks", []) or [])
    fallback_commands = []
    for handler in fallback_list:
        if isinstance(handler, CommandHandler):
            fallback_commands.extend(sorted(handler.commands))
    checks_wiring = {
        "fallback_count_expected": len(fallback_list) == 8,
        "local_cancel_first": bool(fallback_list) and isinstance(fallback_list[0], CommandHandler) and tuple(sorted(fallback_list[0].commands)) == ("cancel",),
        "implicit_commands_match": tuple(fallback_commands[1:]) == cf.IMPLICIT_CANCEL_COMMANDS,
    }
    dbg.section("step2c_wiring", {"checks": checks_wiring, "commands": fallback_commands})
    if not all(checks_wiring.values()):
        dbg.problem("step2c_wiring_failed", {"checks": checks_wiring, "commands": fallback_commands})

    storage_local = _SpyStorage()
    context_local = _DummyContext()
    set_bot_runtime(context_local.bot_data, BotRuntime(storage=storage_local, api_failure_tracker=None))
    update_local = _DummyUpdate(chat_id=key[0], user_id=key[1])
    context_local.user_data["temp_alert"] = {"title": "x"}

    secondary_handler = _make_handler()
    cf.register_conversation_handler(edit_flow_handlers.edit_alert_handler)
    cf.register_conversation_handler(secondary_handler)
    _conversation_map(edit_flow_handlers.edit_alert_handler)[key] = 10
    _conversation_map(secondary_handler)[key] = 20

    local_result = await edit_flow_handlers.cancel_edit(update_local, context_local)
    local_reply = update_local.message.replies[-1] if update_local.message.replies else {}
    checks_local_cancel = {
        "returns_end": local_result == ConversationHandler.END,
        "both_keys_cleared": key not in _conversation_map(edit_flow_handlers.edit_alert_handler) and key not in _conversation_map(secondary_handler),
        "local_text_preserved": local_reply.get("text") == "⏹️ Edit cancelled.",
        "no_command_cancel_event": not any(event.get("event_type") == "command_cancel" for event in storage_local.events),
    }
    dbg.section("step2c_local_cancel", {"checks": checks_local_cancel, "reply": local_reply, "events": storage_local.events})
    if not all(checks_local_cancel.values()):
        dbg.problem("step2c_local_cancel_failed", {"checks": checks_local_cancel})

    import modules.handlers.alerts as alerts_mod
    import modules.handlers.birthdays as birthdays_mod
    import modules.handlers.base as base_mod
    import modules.handlers.manage as manage_mod
    import modules.handlers.tags_dashboard as tags_mod

    originals = {
        ("alerts", "alerts_start"): alerts_mod.alerts_start,
        ("birthdays", "birthday_start"): birthdays_mod.birthday_start,
        ("help", "help_command"): base_mod.help_command,
        ("manage", "manage_dashboard_start"): manage_mod.manage_dashboard_start,
        ("settings", "settings"): base_mod.settings,
        ("status", "status"): base_mod.status,
        ("tags", "tags_dashboard_start"): tags_mod.tags_dashboard_start,
    }
    call_trace = []

    async def _spy_target(update, context):
        label = context.user_data.get("_expected_command")
        call_trace.append(label)
        await update.message.reply_text(f"TARGET:{label}")

    alerts_mod.alerts_start = _spy_target
    birthdays_mod.birthday_start = _spy_target
    base_mod.help_command = _spy_target
    manage_mod.manage_dashboard_start = _spy_target
    base_mod.settings = _spy_target
    base_mod.status = _spy_target
    tags_mod.tags_dashboard_start = _spy_target

    implicit_handlers = [h for h in fallback_list[1:] if isinstance(h, CommandHandler)]
    implicit_ok = True
    detail_rows = []
    try:
        for idx, command_name in enumerate(cf.IMPLICIT_CANCEL_COMMANDS):
            storage = _SpyStorage()
            context = _DummyContext()
            set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
            context.user_data["_expected_command"] = command_name
            update = _DummyUpdate(chat_id=key[0], user_id=key[1] + idx + 1)
            run_key = _handler_key(update.effective_chat.id, update.effective_user.id)

            _reset_registry()
            cf.register_conversation_handler(edit_flow_handlers.edit_alert_handler)
            _conversation_map(edit_flow_handlers.edit_alert_handler)[run_key] = idx

            handler = implicit_handlers[idx]
            result = await handler.callback(update, context)
            replies = [item.get("text") for item in update.message.replies]
            command_cancel_events = [ev for ev in storage.events if ev.get("event_type") == "command_cancel"]
            row = {
                "command": command_name,
                "ended": run_key not in _conversation_map(edit_flow_handlers.edit_alert_handler),
                "returns_end": result == ConversationHandler.END,
                "event_once": len(command_cancel_events) == 1,
                "event_active_true": len(command_cancel_events) == 1 and bool(command_cancel_events[0].get("payload", {}).get("was_active")),
                "target_ran": f"TARGET:{command_name}" in replies and command_name in call_trace,
            }
            detail_rows.append(row)
            if not all(row.values()):
                implicit_ok = False
    finally:
        alerts_mod.alerts_start = originals[("alerts", "alerts_start")]
        birthdays_mod.birthday_start = originals[("birthdays", "birthday_start")]
        base_mod.help_command = originals[("help", "help_command")]
        manage_mod.manage_dashboard_start = originals[("manage", "manage_dashboard_start")]
        base_mod.settings = originals[("settings", "settings")]
        base_mod.status = originals[("status", "status")]
        tags_mod.tags_dashboard_start = originals[("tags", "tags_dashboard_start")]

    dbg.section("step2c_implicit_commands", {"rows": detail_rows, "ok": implicit_ok})
    if not implicit_ok:
        dbg.problem("step2c_implicit_commands_failed", {"rows": detail_rows})


async def _run_step2d_integration_checks(dbg):
    import modules.handlers.birthdays as birthdays_mod
    import modules.handlers.base as base_mod
    import mainbot as mainbot_mod
    from modules import constants as C

    source_path = os.path.join(ROOT_DIR, "mainbot.py")
    with open(source_path, "r", encoding="utf-8") as handle:
        source_text = handle.read()

    checks_source = {
        "register_add_handler": "register_conversation_handler(add_alert_handler)" in source_text,
        "register_birthday_handler": "register_conversation_handler(birthday_add_handler)" in source_text,
        "register_edit_handler": "register_conversation_handler(edit_alert_handler)" in source_text,
        "wrap_alerts_unchanged": "CommandHandler('alerts', _wrap_with_implicit_pre_cancel(alerts_start))" in source_text,
        "wrap_birthdays_unchanged": "CommandHandler('birthdays', _wrap_with_implicit_pre_cancel(birthday_start))" in source_text,
        "start_not_implicit_command": "start" not in cf.IMPLICIT_CANCEL_COMMANDS,
    }
    dbg.section("step2d_source_wiring", {"checks": checks_source})
    if not all(checks_source.values()):
        dbg.problem("step2d_source_wiring_failed", {"checks": checks_source})

    class _SpyStorage:
        def __init__(self):
            self.events = []
            self._alerts = {}

        def log_user_event(self, user_id, event_type, payload):
            self.events.append({"user_id": user_id, "event_type": event_type, "payload": payload})

        def get_all_alerts(self, user_id):
            return self._alerts.get(user_id) or {"alerts": [], "tags": []}

        def setup_user_space(self, user_id):
            self._alerts.setdefault(user_id, {"alerts": [], "tags": []})

    # Original bug regression path:
    # add flow active -> /birthdays implicit fallback -> birthday flow title input stays in birthday flow.
    _reset_registry()
    storage = _SpyStorage()
    context = _DummyContext()
    set_bot_runtime(context.bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
    context.user_data["temp_alert"] = {"type": 1, "title": ""}
    update = _DummyUpdate(chat_id=731, user_id=831)
    run_key = _handler_key(update.effective_chat.id, update.effective_user.id)
    cf.register_conversation_handler(add_alert_handlers.add_alert_handler)
    _conversation_map(add_alert_handlers.add_alert_handler)[run_key] = "GET_TITLE"

    birthdays_fallback = None
    for handler in list(getattr(add_alert_handlers.add_alert_handler, "fallbacks", []) or [])[1:]:
        if isinstance(handler, CommandHandler) and "birthdays" in getattr(handler, "commands", []):
            birthdays_fallback = handler
            break

    if birthdays_fallback is None:
        dbg.problem("step2d_birthdays_fallback_missing", {})
        return

    fallback_result = await birthdays_fallback.callback(update, context)

    # Emulate starting birthday add then entering single-word name.
    context.user_data["temp_alert"] = {"type": 6, "schedule": {}, "tags": [], "pre_alerts": [], "additional_info": ""}
    title_update = _DummyUpdate(chat_id=731, user_id=831)
    title_update.message = _DummyMessage(text="Mario")
    title_update.effective_message = title_update.message
    title_state = await birthday_flow_handlers.birthday_get_title(title_update, context)
    title_reply = title_update.message.replies[-1]["text"] if title_update.message.replies else ""

    command_cancel_events = [ev for ev in storage.events if ev.get("event_type") == "command_cancel"]
    checks_bugfix = {
        "fallback_returns_end": fallback_result == ConversationHandler.END,
        "add_handler_key_cleared": run_key not in _conversation_map(add_alert_handlers.add_alert_handler),
        "single_command_cancel": len(command_cancel_events) == 1,
        "birthday_title_state": title_state == C.BDAY_NAME_CONFIRM,
        "birthday_prompt_rendered": "single word" in title_reply.lower(),
        "not_alert_type_prompt": "alert type" not in title_reply.lower(),
    }
    dbg.section(
        "step2d_bugfix_path",
        {"checks": checks_bugfix, "title_reply": title_reply, "events": storage.events},
    )
    if not all(checks_bugfix.values()):
        dbg.problem("step2d_bugfix_path_failed", {"checks": checks_bugfix, "title_reply": title_reply})

    # /start regression: start is not a fallback command and should not clear active add conversation key.
    _reset_registry()
    storage_start = _SpyStorage()
    context_start = _DummyContext()
    set_bot_runtime(context_start.bot_data, BotRuntime(storage=storage_start, api_failure_tracker=None))
    context_start.user_data["temp_alert"] = {"title": "x"}
    start_update = _DummyUpdate(chat_id=741, user_id=841)
    start_key = _handler_key(start_update.effective_chat.id, start_update.effective_user.id)
    cf.register_conversation_handler(add_alert_handlers.add_alert_handler)
    _conversation_map(add_alert_handlers.add_alert_handler)[start_key] = "GET_TITLE"
    # Verify no start fallback was wired on add handler.
    fallback_command_names = []
    for handler in list(getattr(add_alert_handlers.add_alert_handler, "fallbacks", []) or []):
        if isinstance(handler, CommandHandler):
            fallback_command_names.extend(list(getattr(handler, "commands", [])))
    checks_start_guard = {
        "start_not_in_fallbacks": "start" not in fallback_command_names,
        "start_key_still_present": start_key in _conversation_map(add_alert_handlers.add_alert_handler),
    }
    dbg.section("step2d_start_guard", {"checks": checks_start_guard, "fallback_commands": sorted(fallback_command_names)})
    if not all(checks_start_guard.values()):
        dbg.problem("step2d_start_guard_failed", {"checks": checks_start_guard})

    # No-active-conversation path still delegates through wrapper + cancel when transient context exists.
    async def _wrapped_probe(update, context):
        await update.message.reply_text("WRAPPED_PROBE_OK")

    wrapped = mainbot_mod._wrap_with_implicit_pre_cancel(_wrapped_probe)
    no_conv_update = _DummyUpdate(chat_id=751, user_id=851)
    no_conv_context = _DummyContext()
    set_bot_runtime(no_conv_context.bot_data, BotRuntime(storage=_SpyStorage(), api_failure_tracker=None))
    no_conv_context.user_data["expecting_birthday_search"] = True
    await wrapped(no_conv_update, no_conv_context)
    wrapped_replies = [entry.get("text", "") for entry in no_conv_update.message.replies]
    checks_no_conv = {
        "cancel_message_emitted": any("Operation cancelled. Returning to idle state." in text for text in wrapped_replies),
        "wrapped_probe_emitted": any("WRAPPED_PROBE_OK" in text for text in wrapped_replies),
        "transient_cleared": "expecting_birthday_search" not in no_conv_context.user_data,
    }
    dbg.section("step2d_no_active_wrapper", {"checks": checks_no_conv, "replies": wrapped_replies})
    if not all(checks_no_conv.values()):
        dbg.problem("step2d_no_active_wrapper_failed", {"checks": checks_no_conv, "replies": wrapped_replies})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        suppress_ptb_user_warning()
        _run_registry_shape_checks(dbg)
        _run_conversation_key_checks(dbg)
        _run_end_registered_conversations_checks(dbg)
        _run_command_map_and_builder_checks(dbg)
        _run_target_resolution_checks(dbg)
        asyncio.run(_run_lifecycle_cancel_checks(dbg))
        asyncio.run(_run_step2a_add_alert_checks(dbg))
        asyncio.run(_run_step2b_birthday_checks(dbg))
        asyncio.run(_run_step2c_edit_checks(dbg))
        asyncio.run(_run_step2d_integration_checks(dbg))
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        if "cf" in globals():
            _reset_registry()

    checks_ok = not dbg.has_problem(
        "registry_shape_failed",
        "conversation_key_failed",
        "end_registered_conversations_failed",
        "command_map_builder_failed",
        "target_resolution_failed",
        "lifecycle_cancel_registry_failed",
        "lifecycle_cancel_transient_failed",
        "step2a_wiring_failed",
        "step2a_local_cancel_failed",
        "step2a_implicit_commands_failed",
        "step2b_wiring_failed",
        "step2b_local_cancel_failed",
        "step2b_implicit_commands_failed",
        "step2c_wiring_failed",
        "step2c_local_cancel_failed",
        "step2c_implicit_commands_failed",
        "step2d_source_wiring_failed",
        "step2d_birthdays_fallback_missing",
        "step2d_bugfix_path_failed",
        "step2d_start_guard_failed",
        "step2d_no_active_wrapper_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception")
    dbg.finish(summary_lines=[
        f"conversation_fallbacks: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
