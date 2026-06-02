import asyncio
import sys


class _FakeStorage:
    def __init__(self, payload=None):
        self._payload = payload or {"alerts": [], "tags": []}
        self.events = []
        self.bulk_save_calls = []
        self._bulk_save_result = {"ok": True, "saved_count": None, "ids": None, "failure_reason": None}

    def set_payload(self, payload):
        self._payload = payload or {"alerts": [], "tags": []}

    def get_all_alerts(self, user_id):
        return self._payload

    def get_user_prefs(self, user_id):
        return {
            "birthday_default_time": "09:00",
            "birthday_evening_before_time": "18:00",
        }

    def log_user_event(self, user_id, event_type, payload):
        self.events.append({
            "user_id": str(user_id),
            "event_type": event_type,
            "payload": payload or {},
        })

    def setup_user_space(self, user_id):
        return True

    def set_bulk_save_result(self, result):
        self._bulk_save_result = dict(result or {})

    def save_birthdays_bulk(self, user_id, entries, *, source="settings_bulk_import"):
        normalized_entries = list(entries or [])
        self.bulk_save_calls.append({
            "user_id": str(user_id),
            "entries_count": len(normalized_entries),
            "source": source,
        })

        result = dict(self._bulk_save_result or {})
        ok = bool(result.get("ok", False))
        if ok:
            if result.get("saved_count") is None:
                result["saved_count"] = len(normalized_entries)
            if result.get("ids") is None:
                result["ids"] = [f"id_{idx + 1}" for idx in range(int(result.get("saved_count") or 0))]
            result["failure_reason"] = None
        else:
            result["saved_count"] = int(result.get("saved_count") or 0)
            result["ids"] = list(result.get("ids") or [])
            result["failure_reason"] = str(result.get("failure_reason") or "unknown")
        result["ok"] = ok
        return result


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyMessage:
    def __init__(self):
        self.replies = []
        self.edits = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({
            "text": text,
            "kwargs": kwargs,
        })

    async def edit_text(self, text, **kwargs):
        self.edits.append({
            "text": text,
            "kwargs": kwargs,
        })


class _DummyCallbackQuery:
    def __init__(self, callback_data):
        self.data = callback_data
        self.message = _DummyMessage()
        self.answered = False

    async def answer(self, *args, **kwargs):
        self.answered = True

    async def edit_message_text(self, text, **kwargs):
        await self.message.edit_text(text, **kwargs)


class _DummyUpdate:
    def __init__(self, user_id, callback_data):
        self.effective_user = _DummyUser(user_id)
        self.callback_query = _DummyCallbackQuery(callback_data)
        self.message = None
        self.effective_message = self.callback_query.message


class _DummyContext:
    def __init__(self, user_data=None):
        self.user_data = dict(user_data or {})
        self.bot_data = {}


def _seed_runtime(context, storage):
    """Install runtime storage in context bot_data for handler-edge DI lookups."""

    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    if storage is None:
        return
    set_bot_runtime(
        context.bot_data,
        BotRuntime(storage=storage, api_failure_tracker=None),
    )


def _extract_callback_rows(reply_markup):
    rows = []
    if not reply_markup:
        return rows
    for row in getattr(reply_markup, "inline_keyboard", []):
        rows.append([getattr(button, "callback_data", None) for button in row])
    return rows


def _extract_export_lines(text):
    lines = []
    for raw in (text or "").splitlines():
        clean = raw.strip()
        if " :: " in clean and not clean.startswith("Format:"):
            lines.append(clean)
    return lines


def _last_event(storage, event_type):
    for event in reversed(storage.events):
        if event.get("event_type") == event_type:
            return event
    return None


async def _run_callback(base_handlers, user_id, callback_data, user_data=None):
    update = _DummyUpdate(user_id=user_id, callback_data=callback_data)
    context = _DummyContext(user_data=user_data)
    mainbot_mod = sys.modules.get("mainbot")
    _seed_runtime(context, getattr(mainbot_mod, "storage", None))
    await base_handlers.handle_settings_callback(update, context)
    return update, context


def _sample_birthdays_payload():
    return {
        "alerts": [
            {"type": 6, "title": "Zed Zero", "schedule": {"date": "2/2"}, "birth_year": None, "tags": []},
            {"type": 6, "title": "Alice Alloy", "schedule": {"date": "3/1"}, "birth_year": 1990, "tags": ["👥 Friends", "❤️ Love"]},
            {"type": 6, "title": "Bruno Brown", "schedule": {"date": "10/5"}, "birth_year": None, "tags": ["❤️ Love"]},
            {"type": 1, "title": "Not birthday", "schedule": {"time": "10:00"}},
        ],
        "tags": ["👥 Friends", "❤️ Love", "💼 Work"],
    }


def run_mode_open_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    update, _context = asyncio.run(_run_callback(base_handlers, 9001, "settings_bday_bulk_export"))
    edits = update.callback_query.message.edits
    mode_event = _last_event(storage, "birthday_bulk_export_mode_opened")
    edit = edits[-1] if edits else {}
    callback_rows = _extract_callback_rows((edit.get("kwargs") or {}).get("reply_markup"))
    checks = {
        "answer_called": update.callback_query.answered is True,
        "has_edit": bool(edit),
        "mode_title_present": "Bulk Birthday Export" in (edit.get("text") or ""),
        "row_everything_bytag": callback_rows[0] == ["settings_bday_bulk_export_everything", "settings_bday_bulk_export_bytag"] if callback_rows else False,
        "row_back_birthdays": callback_rows[1] == ["settings_bdays"] if len(callback_rows) > 1 else False,
        "mode_event_logged": bool(mode_event),
    }
    return {
        "edit": edit,
        "callback_rows": callback_rows,
        "mode_event": mode_event,
        "checks": checks,
    }


def run_everything_export_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    update, _context = asyncio.run(_run_callback(base_handlers, 9002, "settings_bday_bulk_export_everything"))
    replies = update.callback_query.message.replies
    export_reply = replies[0] if replies else {}
    export_lines = _extract_export_lines(export_reply.get("text") or "")
    summary_edit = update.callback_query.message.edits[-1] if update.callback_query.message.edits else {}
    sent_event = _last_event(storage, "birthday_bulk_export_sent")
    payload_text = str((sent_event or {}).get("payload") or {})

    checks = {
        "answer_called": update.callback_query.answered is True,
        "has_export_reply": bool(export_reply),
        "everything_header_present": "Birthday bulk export - Everything" in (export_reply.get("text") or ""),
        "lines_sorted": export_lines[:3] == [
            "Alice Alloy :: 03/01/1990 :: Friends, Love",
            "Bruno Brown :: 10/05 :: Love",
            "Zed Zero :: 02/02 :: Untagged",
        ],
        "summary_edit_present": "Bulk export completed." in (summary_edit.get("text") or ""),
        "event_logged": bool(sent_event),
        "event_mode_everything": (sent_event or {}).get("payload", {}).get("mode") == "everything",
        "event_no_raw_name_leak": "Alice Alloy" not in payload_text and "Bruno Brown" not in payload_text,
        "reply_chunks_within_limit": all(len((row or {}).get("text") or "") <= 3900 for row in replies),
    }
    return {
        "replies": replies,
        "summary_edit": summary_edit,
        "sent_event": sent_event,
        "export_lines": export_lines,
        "checks": checks,
    }


def run_bytag_export_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    update, _context = asyncio.run(_run_callback(base_handlers, 9003, "settings_bday_bulk_export_bytag"))
    replies = update.callback_query.message.replies
    joined = "\n\n".join((row or {}).get("text") or "" for row in replies)
    sent_event = _last_event(storage, "birthday_bulk_export_sent")
    per_message_tag_headers = [
        ((row or {}).get("text") or "").count("Tag:")
        for row in replies
    ]
    checks = {
        "has_replies": len(replies) >= 1,
        "multiple_messages_expected": len(replies) >= 3,
        "friends_block_present": "Tag: Friends" in joined,
        "love_block_present": "Tag: Love" in joined,
        "untagged_block_present": "Tag: Untagged" in joined,
        "single_tag_block_per_message": all(count <= 1 for count in per_message_tag_headers),
        "multitag_fanout_present": joined.count("Alice Alloy :: 03/01/1990 :: Friends, Love") == 2,
        "event_mode_bytag": (sent_event or {}).get("payload", {}).get("mode") == "by_tag",
        "event_messages_sent_matches": (sent_event or {}).get("payload", {}).get("messages_sent") == len(replies),
        "reply_chunks_within_limit": all(len((row or {}).get("text") or "") <= 3900 for row in replies),
    }
    return {
        "replies": replies,
        "sent_event": sent_event,
        "joined": joined,
        "per_message_tag_headers": per_message_tag_headers,
        "checks": checks,
    }


def run_chunking_export_checks(base_handlers, mainbot_stub):
    many_birthdays = []
    for idx in range(1, 261):
        many_birthdays.append({
            "type": 6,
            "title": f"LongName Number {idx:03d} With Extra Words",
            "schedule": {"date": "1/1"},
            "birth_year": 1990,
            "tags": ["👥 Friends"],
        })
    storage = _FakeStorage({"alerts": many_birthdays, "tags": ["👥 Friends"]})
    mainbot_stub.storage = storage
    update, _context = asyncio.run(_run_callback(base_handlers, 9004, "settings_bday_bulk_export_everything"))
    replies = update.callback_query.message.replies
    sent_event = _last_event(storage, "birthday_bulk_export_sent")
    sent_count = (sent_event or {}).get("payload", {}).get("messages_sent")
    checks = {
        "chunking_multiple_messages": len(replies) > 1,
        "chunking_within_limit": all(len((row or {}).get("text") or "") <= 3900 for row in replies),
        "event_messages_sent_matches": sent_count == len(replies),
    }
    return {
        "reply_count": len(replies),
        "sent_event": sent_event,
        "checks": checks,
    }


def run_import_entry_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    update, _context = asyncio.run(_run_callback(base_handlers, 9005, "settings_bday_bulk_import"))
    replies = update.callback_query.message.replies
    reply_text = (replies[-1] or {}).get("text") if replies else ""
    context = _context
    event = _last_event(storage, "birthday_bulk_import_prompted")
    reply_markup = (replies[-1] or {}).get("kwargs", {}).get("reply_markup") if replies else None
    callback_rows = _extract_callback_rows(reply_markup)
    checks = {
        "has_reply": bool(replies),
        "prompt_contains_format": "Name :: DD/MM[/YYYY] :: Tag" in (reply_text or ""),
        "expecting_flag_set": context.user_data.get("expecting_bday_bulk_import_message") is True,
        "session_cleared": "bday_bulk_import_session" not in context.user_data,
        "prompt_back_only_keyboard": callback_rows == [["settings_bdays"]],
        "event_logged": bool(event),
        "event_source": (event or {}).get("payload", {}).get("source") == "settings",
    }
    return {
        "replies": replies,
        "context_user_data": dict(context.user_data),
        "callback_rows": callback_rows,
        "event": event,
        "checks": checks,
    }


def run_import_overlap_guard_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    update, context = asyncio.run(_run_callback(
        base_handlers,
        9006,
        "settings_bday_bulk_import",
        user_data={"expecting_backup_email": True},
    ))
    replies = update.callback_query.message.replies
    reply_text = (replies[-1] or {}).get("text") if replies else ""
    prompt_event = _last_event(storage, "birthday_bulk_import_prompted")
    checks = {
        "guard_reply_sent": bool(replies),
        "guard_text_present": "Finish the current flow" in (reply_text or ""),
        "no_prompt_event": prompt_event is None,
        "flag_not_set": context.user_data.get("expecting_bday_bulk_import_message") is not True,
    }
    return {
        "replies": replies,
        "context_user_data": dict(context.user_data),
        "prompt_event": prompt_event,
        "checks": checks,
    }


def run_import_overlap_guard_empty_session_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    update, context = asyncio.run(_run_callback(
        base_handlers,
        90061,
        "settings_bday_bulk_import",
        user_data={"bday_bulk_import_session": {}},
    ))
    replies = update.callback_query.message.replies
    reply_text = (replies[-1] or {}).get("text") if replies else ""
    prompt_event = _last_event(storage, "birthday_bulk_import_prompted")
    checks = {
        "guard_reply_sent": bool(replies),
        "guard_text_present": "Finish the current flow" in (reply_text or ""),
        "no_prompt_event": prompt_event is None,
        "flag_not_set": context.user_data.get("expecting_bday_bulk_import_message") is not True,
    }
    return {
        "replies": replies,
        "context_user_data": dict(context.user_data),
        "prompt_event": prompt_event,
        "checks": checks,
    }


def run_import_edit_decision_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    session = {"summary": {"valid_lines": 3, "unresolved_tags": 1}}
    update, context = asyncio.run(_run_callback(
        base_handlers,
        9007,
        "settings_bday_bulk_import_edit",
        user_data={"bday_bulk_import_session": session},
    ))
    replies = update.callback_query.message.replies
    reply_text = (replies[-1] or {}).get("text") if replies else ""
    reply_markup = (replies[-1] or {}).get("kwargs", {}).get("reply_markup") if replies else None
    callback_rows = _extract_callback_rows(reply_markup)
    event = _last_event(storage, "birthday_bulk_import_decision")
    checks = {
        "edit_reply_sent": bool(replies),
        "edit_text_present": "Send the revised bulk import message now" in (reply_text or ""),
        "edit_prompt_back_only_keyboard": callback_rows == [["settings_bdays"]],
        "expecting_flag_set": context.user_data.get("expecting_bday_bulk_import_message") is True,
        "session_removed": "bday_bulk_import_session" not in context.user_data,
        "event_logged": bool(event),
        "event_decision_edit": (event or {}).get("payload", {}).get("decision") == "edit",
        "event_counts_kept": (event or {}).get("payload", {}).get("valid_lines") == 3 and (event or {}).get("payload", {}).get("unresolved_tags") == 1,
    }
    return {
        "replies": replies,
        "context_user_data": dict(context.user_data),
        "event": event,
        "checks": checks,
    }


def run_import_continue_stale_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    update, context = asyncio.run(_run_callback(
        base_handlers,
        9008,
        "settings_bday_bulk_import_continue",
        user_data={"expecting_bday_bulk_import_message": True},
    ))
    replies = update.callback_query.message.replies
    reply_text = (replies[-1] or {}).get("text") if replies else ""
    event = _last_event(storage, "birthday_bulk_import_decision")
    checks = {
        "stale_reply_sent": bool(replies),
        "stale_text_present": "session missing or expired" in (reply_text or "").lower(),
        "flag_cleared": "expecting_bday_bulk_import_message" not in context.user_data,
        "session_cleared": "bday_bulk_import_session" not in context.user_data,
        "event_reason_stale": (event or {}).get("payload", {}).get("reason_code") == "session_missing_or_expired",
    }
    return {
        "replies": replies,
        "context_user_data": dict(context.user_data),
        "event": event,
        "checks": checks,
    }


def run_import_continue_missing_entries_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    session = {"summary": {"valid_lines": 5, "unresolved_tags": 2}}
    update, context = asyncio.run(_run_callback(
        base_handlers,
        9009,
        "settings_bday_bulk_import_continue",
        user_data={"bday_bulk_import_session": session},
    ))
    replies = update.callback_query.message.replies
    event = _last_event(storage, "birthday_bulk_import_decision")
    failed_event = _last_event(storage, "birthday_bulk_import_commit_failed")
    checks = {
        "missing_reply_sent": bool(replies),
        "missing_text_present": "no valid entries" in ((replies[-1] or {}).get("text") or "").lower(),
        "decision_event_continue": (event or {}).get("payload", {}).get("decision") == "continue",
        "event_counts_kept": (event or {}).get("payload", {}).get("valid_lines") == 5 and (event or {}).get("payload", {}).get("unresolved_tags") == 2,
        "commit_failed_event_logged": bool(failed_event),
        "failed_reason_missing_entries": (failed_event or {}).get("payload", {}).get("reason_code") == "session_entries_missing",
        "flags_cleared": "expecting_bday_bulk_import_message" not in context.user_data and "bday_bulk_import_session" not in context.user_data,
        "no_storage_commit_call": len(storage.bulk_save_calls) == 0,
    }
    return {
        "replies": replies,
        "context_user_data": dict(context.user_data),
        "event": event,
        "failed_event": failed_event,
        "bulk_save_calls": list(storage.bulk_save_calls),
        "checks": checks,
    }


def run_import_continue_commit_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    session = {
        "source": "settings_bulk_import",
        "entries": [
            {"line_no": 1, "name": "Alice Alloy", "date_ddmm": "03/01", "birth_year": 1990, "resolved_tags": ["👥 Friends", "💼 Work"]},
            {"line_no": 2, "name": "Bruno Brown", "date_ddmm": "10/05", "birth_year": None, "resolved_tags": []},
        ],
        "summary": {"valid_lines": 2, "unresolved_tags": 1},
    }
    update, context = asyncio.run(_run_callback(
        base_handlers,
        9010,
        "settings_bday_bulk_import_continue",
        user_data={"bday_bulk_import_session": session},
    ))
    replies = update.callback_query.message.replies
    joined = "\n\n".join((row or {}).get("text") or "" for row in replies)
    decision_event = _last_event(storage, "birthday_bulk_import_decision")
    committed_event = _last_event(storage, "birthday_bulk_import_committed")
    failed_event = _last_event(storage, "birthday_bulk_import_commit_failed")

    checks = {
        "decision_event_continue": (decision_event or {}).get("payload", {}).get("decision") == "continue",
        "storage_commit_called_once": len(storage.bulk_save_calls) == 1,
        "storage_source_propagated": (storage.bulk_save_calls[0] if storage.bulk_save_calls else {}).get("source") == "settings_bulk_import",
        "confirmation_title_present": "Birthday Bulk Import - Final Confirmation" in joined,
        "confirmation_multitag_render_present": "Alice Alloy :: 03/01/1990 :: Friends, Work" in joined,
        "success_message_present": "Birthday bulk import completed." in joined,
        "committed_event_logged": bool(committed_event),
        "committed_counts_ok": (committed_event or {}).get("payload", {}).get("imported_count") == 2 and (committed_event or {}).get("payload", {}).get("untagged_count") == 1,
        "duplicates_flag_true": (committed_event or {}).get("payload", {}).get("duplicates_possible") is True,
        "no_commit_failed_event": failed_event is None,
        "flags_cleared": "expecting_bday_bulk_import_message" not in context.user_data and "bday_bulk_import_session" not in context.user_data,
    }
    return {
        "replies": replies,
        "joined": joined,
        "context_user_data": dict(context.user_data),
        "decision_event": decision_event,
        "committed_event": committed_event,
        "failed_event": failed_event,
        "bulk_save_calls": list(storage.bulk_save_calls),
        "checks": checks,
    }


def run_import_continue_failure_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    storage.set_bulk_save_result({
        "ok": False,
        "saved_count": 0,
        "ids": [],
        "failure_reason": "limit_reached",
    })
    mainbot_stub.storage = storage
    session = {
        "source": "settings_bulk_import",
        "entries": [
            {"line_no": 1, "name": "Alice Alloy", "date_ddmm": "03/01", "birth_year": 1990, "resolved_tags": ["👥 Friends"]},
        ],
        "summary": {"valid_lines": 1, "unresolved_tags": 0},
    }
    update, context = asyncio.run(_run_callback(
        base_handlers,
        9011,
        "settings_bday_bulk_import_continue",
        user_data={"bday_bulk_import_session": session},
    ))
    replies = update.callback_query.message.replies
    reply_text = (replies[-1] or {}).get("text") if replies else ""
    decision_event = _last_event(storage, "birthday_bulk_import_decision")
    failed_event = _last_event(storage, "birthday_bulk_import_commit_failed")
    committed_event = _last_event(storage, "birthday_bulk_import_committed")
    checks = {
        "failure_reply_sent": bool(replies),
        "failure_text_limit": "limit reached" in (reply_text or "").lower(),
        "decision_event_continue": (decision_event or {}).get("payload", {}).get("decision") == "continue",
        "commit_failed_event_logged": bool(failed_event),
        "failed_reason_limit": (failed_event or {}).get("payload", {}).get("reason_code") == "limit_reached",
        "no_committed_event": committed_event is None,
        "storage_commit_called_once": len(storage.bulk_save_calls) == 1,
        "flags_cleared": "expecting_bday_bulk_import_message" not in context.user_data and "bday_bulk_import_session" not in context.user_data,
    }
    return {
        "replies": replies,
        "context_user_data": dict(context.user_data),
        "decision_event": decision_event,
        "failed_event": failed_event,
        "committed_event": committed_event,
        "bulk_save_calls": list(storage.bulk_save_calls),
        "checks": checks,
    }


def run_import_gototags_checks(base_handlers, mainbot_stub):
    storage = _FakeStorage(_sample_birthdays_payload())
    mainbot_stub.storage = storage
    session = {"summary": {"valid_lines": 4, "unresolved_tags": 1}}
    update, context = asyncio.run(_run_callback(
        base_handlers,
        9012,
        "settings_bday_bulk_import_gototags",
        user_data={
            "expecting_bday_bulk_import_message": True,
            "bday_bulk_import_session": session,
        },
    ))
    decision_event = _last_event(storage, "birthday_bulk_import_decision")
    tags_event = _last_event(storage, "tags_dashboard_opened")
    edit = update.callback_query.message.edits[-1] if update.callback_query.message.edits else {}
    checks = {
        "dashboard_edited": bool(edit),
        "dashboard_title_present": "Tag Management Dashboard" in (edit.get("text") or ""),
        "decision_event_logged": bool(decision_event),
        "decision_is_gototags": (decision_event or {}).get("payload", {}).get("decision") == "gototags",
        "tags_dashboard_event_logged": bool(tags_event),
        "flags_cleared": "expecting_bday_bulk_import_message" not in context.user_data and "bday_bulk_import_session" not in context.user_data,
    }
    return {
        "edit": edit,
        "context_user_data": dict(context.user_data),
        "decision_event": decision_event,
        "tags_event": tags_event,
        "checks": checks,
    }
