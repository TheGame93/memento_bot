import asyncio
import importlib
import logging
import sys
import warnings

from _lib.runtime import seed_mainbot_runtime

TEST_USER_ID = 111
_RUNTIME_MAINBOT = None
_RUNTIME_STORAGE = None


class FakeStorage:
    def __init__(self):
        self.whitelist = set()
        self.meta = {}
        self.events = []
        self.admin_id = "999"

    def is_user_whitelisted(self, user_id):
        return str(user_id) in self.whitelist

    def get_user_role(self, user_id):
        return "user" if self.is_user_whitelisted(user_id) else None

    def setup_user_space(self, user_id):
        return None

    def get_user_meta(self, user_id):
        return dict(self.meta.get(str(user_id), {}))

    def update_user_meta(self, user_id, updates):
        key = str(user_id)
        current = self.meta.get(key, {})
        current.update(updates or {})
        self.meta[key] = current
        return True

    def log_user_event(self, user_id, event, payload):
        self.events.append({
            "user_id": str(user_id),
            "event": event,
            "payload": payload or {},
        })
        return True


class DummyUser:
    def __init__(self, user_id, username="new_user", full_name="New User"):
        self.id = user_id
        self.username = username
        self.full_name = full_name
        self.first_name = "New"
        self.last_name = "User"


class DummyMessage:
    def __init__(self, text=None):
        self.text = text
        self.replies = []
        self.edits = []
        self.message_id = 100

    async def reply_text(self, text, **kwargs):
        payload = {"text": text, "kwargs": kwargs}
        self.replies.append(payload)
        return self

    async def edit_text(self, text, **kwargs):
        payload = {"text": text, "kwargs": kwargs}
        self.edits.append(payload)
        return self


class DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})
        return None


class DummyUpdate:
    def __init__(self, user_id=TEST_USER_ID, text=None, callback_data=None, message=None):
        self.effective_user = DummyUser(user_id)
        self.message = message or DummyMessage(text=text)
        self.effective_message = self.message
        self.callback_query = None
        if callback_data is not None:
            self.callback_query = DummyCallbackQuery(callback_data, self.message)


class DummyBot:
    def __init__(self):
        self.sent = []
        self.edited = []

    async def send_message(self, chat_id, text, **kwargs):
        message_id = len(self.sent) + 1
        self.sent.append({
            "chat_id": str(chat_id),
            "text": text,
            "kwargs": kwargs,
            "message_id": message_id,
        })
        return type("_SentMessage", (), {"message_id": message_id})()

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.edited.append({
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
            "kwargs": kwargs,
        })
        return True


class DummyContext:
    def __init__(self, bot=None):
        self.user_data = {}
        self.bot = bot or DummyBot()
        self.bot_data = {}
        self.args = []
        if _RUNTIME_MAINBOT is not None:
            seed_mainbot_runtime(_RUNTIME_MAINBOT, app=self, storage=_RUNTIME_STORAGE)


def load_runtime_modules(fake_storage):
    global _RUNTIME_MAINBOT, _RUNTIME_STORAGE

    try:
        from telegram.warnings import PTBUserWarning

        warnings.filterwarnings("ignore", category=PTBUserWarning)
    except Exception:
        warnings.filterwarnings("ignore", category=UserWarning)

    if "mainbot" in sys.modules:
        mainbot = importlib.reload(sys.modules["mainbot"])
    else:
        mainbot = importlib.import_module("mainbot")

    if "modules.handlers.base" in sys.modules:
        base_handlers = importlib.reload(sys.modules["modules.handlers.base"])
    else:
        base_handlers = importlib.import_module("modules.handlers.base")

    if "modules.security.whitelist_store" in sys.modules:
        whitelist_store = importlib.reload(sys.modules["modules.security.whitelist_store"])
    else:
        whitelist_store = importlib.import_module("modules.security.whitelist_store")

    seed_mainbot_runtime(mainbot, storage=fake_storage)
    _RUNTIME_MAINBOT = mainbot
    _RUNTIME_STORAGE = fake_storage
    logging.getLogger("modules.handlers.base").setLevel(logging.ERROR)
    return mainbot, base_handlers, whitelist_store


def _run(coro, application_handler_stop_cls):
    try:
        asyncio.run(coro)
    except application_handler_stop_cls:
        return


def _find_request_for_user(whitelist_store, user_id):
    uid = str(user_id)
    records = whitelist_store.list_whitelist_requests()
    if not isinstance(records, list):
        return None
    # Prefer the most recent matching record if state contains duplicates.
    for record in reversed(records):
        if isinstance(record, dict) and str(record.get("user_id")) == uid:
            return record
    return None


def _extract_labels(reply_payload):
    markup = (reply_payload.get("kwargs") or {}).get("reply_markup") if isinstance(reply_payload, dict) else None
    if not markup or not getattr(markup, "inline_keyboard", None):
        return []
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _extract_callback_rows(message_payload):
    """Return flattened callback button rows from a dummy bot payload."""
    markup = (message_payload.get("kwargs") or {}).get("reply_markup") if isinstance(message_payload, dict) else None
    if not markup or not getattr(markup, "inline_keyboard", None):
        return []
    rows = []
    for row in markup.inline_keyboard:
        rows.append([{
            "text": getattr(btn, "text", None),
            "callback_data": getattr(btn, "callback_data", None),
        } for btn in row])
    return rows


def _callback_payloads_for_rows(rows):
    """Collect callback payloads from extracted inline-keyboard rows."""
    values = []
    for row in rows:
        for item in row:
            if isinstance(item, dict):
                payload = item.get("callback_data")
                if payload is not None:
                    values.append(str(payload))
    return values


def _has_expected_request_actions(rows):
    """Check that the pending-request action keyboard rows are present."""
    labels = [item.get("text") for row in rows for item in row if isinstance(item, dict)]
    return labels == ["Approve", "Reject", "Set Name", "Set Label Order"]


def _test_start_auto_create_recap(dbg, base_handlers, whitelist_store):
    bot = DummyBot()
    context = DummyContext(bot=bot)
    update_start = DummyUpdate(text="/start")
    asyncio.run(base_handlers.start(update_start, context))

    replies = update_start.message.replies
    recap = replies[-1] if replies else {}
    recap_text = recap.get("text", "")
    labels = _extract_labels(recap)
    record = _find_request_for_user(whitelist_store, TEST_USER_ID)
    state = whitelist_store.get_whitelist_request_state(TEST_USER_ID)

    checks = {
        "recap_sent": bool(replies),
        "recap_mentions_pending": "Waiting for approval" in recap_text,
        "recap_mentions_modify": "Do you want to modify it?" in recap_text,
        "buttons_yes_no": labels == ["Yes", "No"],
        "request_created": isinstance(record, dict),
        "auto_message_stored": isinstance(record, dict) and "Auto /start request" in (record.get("request_message") or ""),
        "count_is_one": isinstance(record, dict) and int(record.get("request_count", 0)) == 1,
        "state_pending": isinstance(state, dict) and state.get("status") == "pending",
        "no_edit_listener_active": context.user_data.get("expecting_start_request_message") is not True,
        "admin_notified_once": len(bot.sent) == 1,
    }
    dbg.section("start_auto_create", {
        "reply": recap,
        "labels": labels,
        "record": record,
        "state": state,
        "bot_sent": bot.sent,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("start_auto_create_failed", {"checks": checks})
    return bot, context


def _test_repeated_start_idempotent(dbg, base_handlers, whitelist_store, bot):
    before = _find_request_for_user(whitelist_store, TEST_USER_ID)
    before_count = int(before.get("request_count", 0)) if isinstance(before, dict) else None
    before_sent = len(bot.sent)
    context = DummyContext(bot=bot)
    update = DummyUpdate(text="/start")
    asyncio.run(base_handlers.start(update, context))
    after = _find_request_for_user(whitelist_store, TEST_USER_ID)
    after_count = int(after.get("request_count", 0)) if isinstance(after, dict) else None
    checks = {
        "record_still_exists": isinstance(after, dict),
        "count_not_incremented": before_count is not None and after_count == before_count,
        "no_extra_notify": len(bot.sent) == before_sent,
    }
    dbg.section("start_repeated_idempotent", {
        "before": before,
        "after": after,
        "bot_sent_before": before_sent,
        "bot_sent_after": len(bot.sent),
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("start_repeated_idempotent_failed", {"checks": checks})


def _test_edit_yes_and_message_update(dbg, mainbot, base_handlers, whitelist_store, application_handler_stop_cls):
    bot = DummyBot()
    bootstrap_context = DummyContext(bot=bot)
    asyncio.run(base_handlers.start(DummyUpdate(text="/start"), bootstrap_context))
    before = _find_request_for_user(whitelist_store, TEST_USER_ID)
    before_count = int(before.get("request_count", 0)) if isinstance(before, dict) else None

    context = DummyContext(bot=bot)
    update_yes = DummyUpdate(callback_data=base_handlers.START_REQUEST_EDIT_YES_CB)
    asyncio.run(base_handlers.handle_start_request_callback(update_yes, context))
    yes_reply = update_yes.message.edits[-1]["text"] if update_yes.message.edits else ""

    update_text = DummyUpdate(text="I am Carol, invited by Alice.")
    _run(mainbot.global_text_handler(update_text, context), application_handler_stop_cls)
    text_reply = update_text.message.replies[-1] if update_text.message.replies else {}
    labels = _extract_labels(text_reply)
    after = _find_request_for_user(whitelist_store, TEST_USER_ID)
    after_state = whitelist_store.get_whitelist_request_state(TEST_USER_ID)

    checks = {
        "yes_enables_listener": context.user_data.get("expecting_start_request_message") is not True,
        "yes_prompt_sent": "Send the new message" in yes_reply,
        "message_updated": isinstance(after, dict) and after.get("request_message") == "I am Carol, invited by Alice.",
        "count_unchanged": before_count is not None and int(after.get("request_count", 0)) == before_count,
        "state_synced": isinstance(after_state, dict) and after_state.get("request_message") == "I am Carol, invited by Alice.",
        "admin_message_edited": len(bot.edited) >= 1,
        "keyboard_preserved_after_pending_edit": (
            len(bot.edited) >= 1
            and (bot.edited[-1].get("kwargs") or {}).get("reply_markup") is not None
        ),
        "recap_buttons_yes_no": labels == ["Yes", "No"],
    }
    dbg.section("start_edit_message", {
        "yes_reply": yes_reply,
        "text_reply": text_reply,
        "labels": labels,
        "before": before,
        "after": after,
        "state": after_state,
        "bot_edited": bot.edited,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("start_edit_message_failed", {"checks": checks})


def _test_multi_request_notifications(dbg, base_handlers):
    """Validate pending notifications remain distinct and actionable per requester."""
    bot = DummyBot()
    first_user_id = 333

    context_one = DummyContext(bot=bot)
    asyncio.run(base_handlers.start(DummyUpdate(user_id=first_user_id, text="/start"), context_one))

    second_user_id = 444
    context_two = DummyContext(bot=bot)
    asyncio.run(base_handlers.start(DummyUpdate(user_id=second_user_id, text="/start"), context_two))

    first_payload = bot.sent[0] if len(bot.sent) > 0 else {}
    second_payload = bot.sent[1] if len(bot.sent) > 1 else {}
    first_rows = _extract_callback_rows(first_payload)
    second_rows = _extract_callback_rows(second_payload)
    first_callbacks = _callback_payloads_for_rows(first_rows)
    second_callbacks = _callback_payloads_for_rows(second_rows)

    checks = {
        "two_messages_sent": len(bot.sent) == 2,
        "first_has_reply_markup": (first_payload.get("kwargs") or {}).get("reply_markup") is not None,
        "second_has_reply_markup": (second_payload.get("kwargs") or {}).get("reply_markup") is not None,
        "first_has_expected_actions": _has_expected_request_actions(first_rows),
        "second_has_expected_actions": _has_expected_request_actions(second_rows),
        "first_callbacks_match_first_user": (
            bool(first_callbacks) and all(cb.endswith(f":{first_user_id}") for cb in first_callbacks)
        ),
        "second_callbacks_match_second_user": (
            bool(second_callbacks) and all(cb.endswith(f":{second_user_id}") for cb in second_callbacks)
        ),
    }
    dbg.section("multi_request_notifications", {
        "sent": bot.sent,
        "first_callbacks": first_callbacks,
        "second_callbacks": second_callbacks,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("multi_request_notifications_failed", {"checks": checks})


def _test_stale_resolved_recovery(dbg, base_handlers, whitelist_store):
    bot = DummyBot()
    context = DummyContext(bot=bot)
    asyncio.run(base_handlers.start(DummyUpdate(text="/start"), context))
    whitelist_store.resolve_whitelist_request(
        user_id=TEST_USER_ID,
        action="rejected",
        actor_id=999,
        actor_role="admin",
        actor_label="AdminUser",
        now_iso="2026-02-20T10:00:00",
    )
    whitelist_store.upsert_whitelist_request(
        user_id=TEST_USER_ID,
        request_message="orphan stale request",
        now_iso="2026-02-20T10:05:00",
    )

    context2 = DummyContext(bot=bot)
    asyncio.run(base_handlers.start(DummyUpdate(text="/start"), context2))
    repaired = _find_request_for_user(whitelist_store, TEST_USER_ID)
    repaired_state = whitelist_store.get_whitelist_request_state(TEST_USER_ID)
    checks = {
        "record_recreated": isinstance(repaired, dict),
        "state_repaired_pending": isinstance(repaired_state, dict) and repaired_state.get("status") == "pending",
        "stale_message_replaced": isinstance(repaired, dict) and repaired.get("request_message") != "orphan stale request",
    }
    dbg.section("start_stale_resolved_recovery", {
        "record": repaired,
        "state": repaired_state,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("start_stale_recovery_failed", {"checks": checks})


def _test_nontext_during_onboarding(dbg, mainbot, application_handler_stop_cls):
    context_a = DummyContext()
    context_a.user_data["expecting_start_request_message"] = True
    update_a = DummyUpdate(text=None)
    update_a.message.text = None
    update_a.effective_message = update_a.message
    _run(mainbot.authorization_guard(update_a, context_a), application_handler_stop_cls)
    replies_a = update_a.message.replies
    reply_a = replies_a[-1]["text"] if replies_a else ""

    context_b = DummyContext()
    context_b.user_data["start_request_confirm_pending"] = True
    update_b = DummyUpdate(text=None)
    update_b.message.text = None
    update_b.effective_message = update_b.message
    _run(mainbot.authorization_guard(update_b, context_b), application_handler_stop_cls)
    replies_b = update_b.message.replies
    reply_b = replies_b[-1]["text"] if replies_b else ""

    checks = {
        "active_reply_sent": bool(replies_a),
        "active_mentions_text": "text message" in reply_a.lower(),
        "confirm_reply_sent": bool(replies_b),
        "confirm_mentions_buttons": "buttons" in reply_b.lower(),
    }
    dbg.section("nontext_during_onboarding", {
        "reply_active": reply_a,
        "reply_confirm": reply_b,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("nontext_during_onboarding_failed", {"checks": checks})


def _test_command_conflict_during_onboarding(dbg, mainbot, application_handler_stop_cls):
    context = DummyContext()
    context.user_data["expecting_start_request_message"] = True
    update = DummyUpdate(text="/help")
    blocked = False
    try:
        asyncio.run(mainbot.authorization_guard(update, context))
    except application_handler_stop_cls:
        blocked = True
    replies = update.message.replies
    reply_text = replies[-1]["text"] if replies else ""
    checks = {
        "blocked": blocked,
        "reply_sent": bool(replies),
        "mentions_message": "waiting for the message" in reply_text.lower(),
        "mentions_cancel": "/cancel" in reply_text,
    }
    dbg.section("command_conflict_onboarding", {"reply": reply_text, "checks": checks})
    if not all(checks.values()):
        dbg.problem("command_conflict_onboarding_failed", {"checks": checks})


def _test_legacy_callback_no_mutation(dbg, base_handlers, whitelist_store):
    bootstrap = DummyContext(bot=DummyBot())
    asyncio.run(base_handlers.start(DummyUpdate(text="/start"), bootstrap))
    before = _find_request_for_user(whitelist_store, TEST_USER_ID)
    before_count = int(before.get("request_count", 0)) if isinstance(before, dict) else None

    legacy_ctx = DummyContext(bot=DummyBot())
    legacy_update = DummyUpdate(callback_data=base_handlers.START_REQUEST_PROCEED_CB)
    asyncio.run(base_handlers.handle_start_request_callback(legacy_update, legacy_ctx))
    after = _find_request_for_user(whitelist_store, TEST_USER_ID)
    after_count = int(after.get("request_count", 0)) if isinstance(after, dict) else None
    reply_text = legacy_update.message.edits[-1]["text"] if legacy_update.message.edits else ""
    checks = {
        "count_unchanged": before_count is not None and after_count == before_count,
        "expired_reply": "no longer valid" in reply_text.lower(),
        "context_cleared": not legacy_ctx.user_data.get("expecting_start_request_message"),
    }
    dbg.section("legacy_callback_no_mutation", {
        "before": before,
        "after": after,
        "reply": reply_text,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("legacy_callback_no_mutation_failed", {"checks": checks})


def _test_whitelisted_onboarding_flags_cleared(dbg, mainbot, base_handlers, application_handler_stop_cls):
    # Simulate approval happened while user was waiting to edit onboarding message.
    if _RUNTIME_STORAGE is not None:
        _RUNTIME_STORAGE.whitelist.add(str(TEST_USER_ID))
    context_guard = DummyContext()
    context_guard.user_data["expecting_start_request_message"] = True
    context_guard.user_data["start_request_message_draft"] = "stale"
    context_guard.user_data["start_request_confirm_pending"] = True
    update_guard = DummyUpdate(text="normal user text after approval")
    _run(mainbot.authorization_guard(update_guard, context_guard), application_handler_stop_cls)
    cleared_by_guard = not any(
        key in context_guard.user_data
        for key in ("expecting_start_request_message", "start_request_message_draft", "start_request_confirm_pending")
    )

    # /start should also defensively clear stale onboarding leftovers for authorized users.
    context_start = DummyContext()
    context_start.user_data["expecting_start_request_message"] = True
    context_start.user_data["start_request_message_draft"] = "stale"
    context_start.user_data["start_request_confirm_pending"] = True
    update_start = DummyUpdate(text="/start")
    asyncio.run(base_handlers.start(update_start, context_start))
    cleared_by_start = not any(
        key in context_start.user_data
        for key in ("expecting_start_request_message", "start_request_message_draft", "start_request_confirm_pending")
    )

    checks = {
        "cleared_by_guard": cleared_by_guard,
        "cleared_by_start": cleared_by_start,
    }
    dbg.section("whitelisted_onboarding_flags", {"checks": checks})
    if not all(checks.values()):
        dbg.problem("whitelisted_onboarding_flags_failed", {"checks": checks})


def _test_legacy_confirm_flag_expired(dbg, mainbot, application_handler_stop_cls):
    context = DummyContext()
    context.user_data["start_request_confirm_pending"] = True
    context.user_data["start_request_message_draft"] = "legacy draft"
    update = DummyUpdate(text="hello")
    _run(mainbot.global_text_handler(update, context), application_handler_stop_cls)
    reply = update.message.replies[-1]["text"] if update.message.replies else ""
    checks = {
        "reply_sent": bool(update.message.replies),
        "mentions_expired": "expired" in reply.lower(),
        "mentions_start": "/start" in reply,
        "confirm_flag_removed": "start_request_confirm_pending" not in context.user_data,
        "draft_removed": "start_request_message_draft" not in context.user_data,
    }
    dbg.section("legacy_confirm_flag", {"reply": reply, "checks": checks})
    if not all(checks.values()):
        dbg.problem("legacy_confirm_flag_failed", {"checks": checks})


def run_checks(dbg, mainbot, base_handlers, whitelist_store, application_handler_stop_cls):
    bot, _context = _test_start_auto_create_recap(dbg, base_handlers, whitelist_store)
    _test_repeated_start_idempotent(dbg, base_handlers, whitelist_store, bot)
    _test_edit_yes_and_message_update(dbg, mainbot, base_handlers, whitelist_store, application_handler_stop_cls)
    _test_multi_request_notifications(dbg, base_handlers)
    _test_stale_resolved_recovery(dbg, base_handlers, whitelist_store)
    _test_nontext_during_onboarding(dbg, mainbot, application_handler_stop_cls)
    _test_command_conflict_during_onboarding(dbg, mainbot, application_handler_stop_cls)
    _test_legacy_callback_no_mutation(dbg, base_handlers, whitelist_store)
    _test_whitelisted_onboarding_flags_cleared(dbg, mainbot, base_handlers, application_handler_stop_cls)
    _test_legacy_confirm_flag_expired(dbg, mainbot, application_handler_stop_cls)
