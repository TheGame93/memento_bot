import asyncio
import importlib
import logging
import sys
import warnings

from _lib.runtime import seed_mainbot_runtime


class FakeStorage:
    """Provide minimal storage behavior needed by admin request callback tests."""

    def __init__(self):
        self.admin_id = "999"
        self.meta = {}
        self.setup_calls = []

    def get_user_role(self, user_id):
        if str(user_id) == "999":
            return "admin"
        return None

    def setup_user_space(self, user_id):
        self.setup_calls.append(str(user_id))
        return None

    def get_user_meta(self, user_id):
        return dict(self.meta.get(str(user_id), {}))

    def update_user_meta(self, user_id, updates):
        key = str(user_id)
        current = self.meta.get(key, {})
        current.update(updates or {})
        self.meta[key] = current
        return True


class DummyUser:
    """Represent a Telegram-like user fixture for callback tests."""

    def __init__(self, user_id):
        self.id = int(user_id)
        self.username = f"user_{user_id}"
        self.full_name = f"User {user_id}"
        self.first_name = "User"
        self.last_name = str(user_id)


class DummyCallbackQuery:
    """Capture callback answers and active-message edits."""

    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})
        return None

    async def edit_message_text(self, text, **kwargs):
        payload = {"text": text, "kwargs": kwargs}
        self.edits.append(payload)
        return payload


class DummyUpdate:
    """Carry callback query and actor identity into handler execution."""

    def __init__(self, actor_id, callback_data):
        self.effective_user = DummyUser(actor_id)
        self.callback_query = DummyCallbackQuery(callback_data)


class DummyBot:
    """Capture stored-card edits and user notification sends."""

    def __init__(self):
        self.edited = []
        self.sent = []

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.edited.append({
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
            "kwargs": kwargs,
        })
        return True

    async def send_message(self, chat_id, text, **kwargs):
        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "kwargs": kwargs,
        }
        self.sent.append(payload)
        return type("_SentMessage", (), {"message_id": len(self.sent)})()


class DummyContext:
    """Provide callback handler context with bot and user_data."""

    def __init__(self, bot=None, storage=None):
        self.bot = bot or DummyBot()
        self.user_data = {}
        self.bot_data = {}
        self.args = []
        if storage is not None:
            _seed_runtime(self, storage)


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


def load_runtime_modules(fake_storage):
    """Load isolated runtime modules and bind shared runtime storage test doubles."""
    try:
        from telegram.warnings import PTBUserWarning

        warnings.filterwarnings("ignore", category=PTBUserWarning)
    except Exception:
        warnings.filterwarnings("ignore", category=UserWarning)

    if "mainbot" in sys.modules:
        mainbot = importlib.reload(sys.modules["mainbot"])
    else:
        mainbot = importlib.import_module("mainbot")

    if "modules.handlers.admin" in sys.modules:
        admin_handlers = importlib.reload(sys.modules["modules.handlers.admin"])
    else:
        admin_handlers = importlib.import_module("modules.handlers.admin")

    if "modules.security.whitelist_store" in sys.modules:
        whitelist_store = importlib.reload(sys.modules["modules.security.whitelist_store"])
    else:
        whitelist_store = importlib.import_module("modules.security.whitelist_store")

    seed_mainbot_runtime(mainbot, storage=fake_storage)
    logging.getLogger("modules.handlers.admin").setLevel(logging.ERROR)
    return mainbot, admin_handlers, whitelist_store


def _flatten_button_labels(markup):
    if not markup or not getattr(markup, "inline_keyboard", None):
        return []
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _find_pending_request(whitelist_store, user_id):
    uid = str(user_id)
    for record in whitelist_store.list_whitelist_requests():
        if isinstance(record, dict) and str(record.get("user_id")) == uid:
            return record
    return None


def _seed_pending_request(whitelist_store, user_id, message_id):
    """Create pending request plus one stored admin card reference."""
    now_iso = "2026-02-20T10:00:00"
    ensured = whitelist_store.ensure_whitelist_request(
        user_id=user_id,
        username=f"user_{user_id}",
        display_name=f"User {user_id}",
        request_message=f"Pending request from {user_id}",
        now_iso=now_iso,
    )
    whitelist_store.register_whitelist_request_message(
        user_id=user_id,
        chat_id="999",
        message_id=message_id,
        now_iso=now_iso,
    )
    whitelist_store.set_whitelist_request_notified(
        user_id=user_id,
        now_iso=now_iso,
    )
    return ensured


def _run(coro):
    return asyncio.run(coro)


def _exercise_action(dbg, admin_handlers, whitelist_store, storage, action, target_id):
    """Execute one admin action callback and assert lifecycle side effects."""
    bot = DummyBot()
    context = DummyContext(bot=bot, storage=storage)
    _seed_pending_request(whitelist_store, target_id, message_id=100 + int(target_id))

    before_pending = _find_pending_request(whitelist_store, target_id)
    callback_data = f"admin_req_{action}:{target_id}"
    update = DummyUpdate(actor_id=999, callback_data=callback_data)
    _run(admin_handlers.handle_admin_callback(update, context))

    after_pending = _find_pending_request(whitelist_store, target_id)
    state = whitelist_store.get_whitelist_request_state(target_id)
    action_status = "approved" if action == "approve" else "rejected"
    active_edit = update.callback_query.edits[-1] if update.callback_query.edits else {}
    active_markup = (active_edit.get("kwargs") or {}).get("reply_markup")
    active_labels = _flatten_button_labels(active_markup)

    checks = {
        "pending_seeded": isinstance(before_pending, dict),
        "callback_answered": len(update.callback_query.answers) == 1,
        "stored_cards_refreshed": len(bot.edited) >= 1,
        "stored_refresh_without_pending_keyboard": (
            len(bot.edited) >= 1
            and (bot.edited[-1].get("kwargs") or {}).get("reply_markup") is None
        ),
        "active_card_edited": bool(update.callback_query.edits),
        "active_card_has_back_only_keyboard": (
            bool(active_labels)
            and "⬅️ Back to Dashboard" in active_labels
            and "Approve" not in active_labels
            and "Reject" not in active_labels
            and "Set Name" not in active_labels
            and "Set Label Order" not in active_labels
        ),
        "pending_removed_from_live_list": after_pending is None,
        "state_status_resolved": isinstance(state, dict) and state.get("status") == action_status,
        "state_has_resolution_snapshot": (
            isinstance(state, dict)
            and isinstance(state.get("request"), dict)
            and bool(state.get("resolved_at"))
        ),
    }
    dbg.section(f"admin_req_{action}", {
        "target_id": str(target_id),
        "callback_data": callback_data,
        "bot_edited": bot.edited,
        "bot_sent": bot.sent,
        "active_edits": update.callback_query.edits,
        "state": state,
        "checks": checks,
    })
    if not all(checks.values()):
        dbg.problem("admin_request_actions_failed", {
            "action": action,
            "target_id": str(target_id),
            "checks": checks,
        })


def run_checks(dbg, admin_handlers, whitelist_store, storage):
    """Run approve/reject callback lifecycle assertions."""
    _exercise_action(dbg, admin_handlers, whitelist_store, storage, action="approve", target_id=111)
    _exercise_action(dbg, admin_handlers, whitelist_store, storage, action="reject", target_id=222)
