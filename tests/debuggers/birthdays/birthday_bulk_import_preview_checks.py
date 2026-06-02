import asyncio


class _FakeStorage:
    def __init__(self, user_tags=None):
        self._user_tags = list(user_tags or [])
        self.events = []

    def get_user_tags(self, user_id):
        return list(self._user_tags)

    def log_user_event(self, user_id, event_type, payload):
        self.events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": payload or {},
        })


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({
            "text": text,
            "kwargs": kwargs,
        })


class _DummyUpdate:
    def __init__(self, user_id, text):
        self.effective_user = _DummyUser(user_id)
        self.message = _DummyMessage(text)
        self.effective_message = self.message
        self.callback_query = None


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = dict(user_data or {})
        self.bot = None


def _extract_callback_rows(reply_markup):
    rows = []
    if not reply_markup:
        return rows
    for row in getattr(reply_markup, "inline_keyboard", []):
        rows.append([getattr(button, "callback_data", None) for button in row])
    return rows


def _last_event(storage, event_type):
    for event in reversed(storage.events):
        if event.get("event_type") == event_type:
            return event
    return None


def _run_text_handler(mainbot_mod, update, context):
    try:
        asyncio.run(mainbot_mod.global_text_handler(update, context))
    except mainbot_mod.ApplicationHandlerStop:
        return True
    return False


def run_preview_success_checks(mainbot_mod):
    storage = _FakeStorage(["👥 Friends", "❤️ Love"])
    original_storage = mainbot_mod.storage
    mainbot_mod.storage = storage
    try:
        raw_text = "\n".join([
            "Nadia Ricci :: 2/12/1993 :: Friends",
            "Paolo Paoloni :: 3/04 :: friendss",
            "Bad colon : 04/04 :: Love",
            "Bad date :: 31/11/2020 :: Friends",
        ])
        update = _DummyUpdate(9101, raw_text)
        context = _DummyContext({"expecting_bday_bulk_import_message": True})
        stopped = _run_text_handler(mainbot_mod, update, context)
        replies = update.message.replies
        session = context.user_data.get("bday_bulk_import_session") or {}
        summary = session.get("summary") or {}
        event = _last_event(storage, "birthday_bulk_import_parsed")
        callback_rows = _extract_callback_rows((replies[-1] or {}).get("kwargs", {}).get("reply_markup")) if replies else []
        joined_text = "\n\n".join((item or {}).get("text") or "" for item in replies)
        payload_text = str((event or {}).get("payload") or {})

        checks = {
            "stopped": stopped,
            "replies_sent": len(replies) >= 1,
            "has_preview_title": "Birthday Bulk Import Preview" in joined_text,
            "has_invalid_section": "Invalid lines" in joined_text,
            "has_name_date_line": "line 1: <code>Nadia Ricci | 02/12/1993</code>" in joined_text,
            "has_tag_row_indent": "" in joined_text,
            "name_line_not_inline_with_tag_fields": "line 1: <code>Nadia Ricci | 02/12/1993</code> | provided=" not in joined_text,
            "expecting_flag_cleared": "expecting_bday_bulk_import_message" not in context.user_data,
            "session_stored": bool(session),
            "summary_counts_ok": summary.get("valid_lines") == 2 and summary.get("invalid_lines") == 2,
            "summary_tag_item_counts_ok": summary.get("provided_tag_items") == 2 and summary.get("resolved_tag_items") == 1 and summary.get("unresolved_tags") == 1,
            "summary_suggestion_counts_ok": summary.get("suggestions_over_threshold") == 1 and summary.get("entries_with_unresolved_tags") == 1,
            "decision_keyboard_rows": callback_rows == [
                ["settings_bday_bulk_import_continue"],
                ["settings_bday_bulk_import_edit"],
                ["settings_bday_bulk_import_gototags"],
            ],
            "event_logged": bool(event),
            "event_text_meta_present": "input_len" in (event or {}).get("payload", {}) and "input_hash" in (event or {}).get("payload", {}),
            "event_tag_item_counts_ok": (event or {}).get("payload", {}).get("provided_tag_items") == 2 and (event or {}).get("payload", {}).get("resolved_tag_items") == 1,
            "event_suggestion_counts_ok": (event or {}).get("payload", {}).get("suggestions_over_threshold") == 1 and (event or {}).get("payload", {}).get("entries_with_unresolved_tags") == 1,
            "event_no_raw_name_leak": "Nadia Ricci" not in payload_text and "Paolo Paoloni" not in payload_text,
            "preview_no_invalid_raw_line_echo": "Bad colon : 04/04 :: Love" not in joined_text,
        }

        return {
            "replies": replies,
            "session": session,
            "event": event,
            "callback_rows": callback_rows,
            "checks": checks,
        }
    finally:
        mainbot_mod.storage = original_storage


def run_preview_lines_limit_checks(mainbot_mod):
    storage = _FakeStorage(["👥 Friends"])
    original_storage = mainbot_mod.storage
    mainbot_mod.storage = storage
    try:
        raw_text = "\n".join(
            f"User {idx} :: 1/1/1990 :: Friends"
            for idx in range(1, 302)
        )
        update = _DummyUpdate(9102, raw_text)
        context = _DummyContext({"expecting_bday_bulk_import_message": True})
        stopped = _run_text_handler(mainbot_mod, update, context)
        replies = update.message.replies
        session = context.user_data.get("bday_bulk_import_session") or {}
        summary = session.get("summary") or {}
        event = _last_event(storage, "birthday_bulk_import_parsed")
        joined_text = "\n\n".join((item or {}).get("text") or "" for item in replies)
        reason_counts = summary.get("reason_counts") or {}

        checks = {
            "stopped": stopped,
            "replies_sent": len(replies) >= 1,
            "blocked_message_present": "Import blocked:" in joined_text,
            "expecting_flag_cleared": "expecting_bday_bulk_import_message" not in context.user_data,
            "session_stored": bool(session),
            "limit_flag_in_summary": summary.get("lines_limit_exceeded") is True,
            "valid_lines_zero": summary.get("valid_lines") == 0,
            "summary_tag_items_zero": summary.get("provided_tag_items") == 0 and summary.get("resolved_tag_items") == 0 and summary.get("unresolved_tags") == 0,
            "reason_lines_limit": reason_counts.get("lines_limit_exceeded") == 1,
            "event_logged": bool(event),
            "event_limit_flag": (event or {}).get("payload", {}).get("lines_limit_exceeded") is True,
            "event_tag_items_zero": (event or {}).get("payload", {}).get("provided_tag_items") == 0 and (event or {}).get("payload", {}).get("resolved_tag_items") == 0 and (event or {}).get("payload", {}).get("unresolved_tags") == 0,
        }

        return {
            "replies": replies,
            "session": session,
            "event": event,
            "checks": checks,
        }
    finally:
        mainbot_mod.storage = original_storage
