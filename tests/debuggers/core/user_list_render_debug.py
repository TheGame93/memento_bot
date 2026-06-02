#!/usr/bin/env python3
import asyncio
import os
import sys
import types


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

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "user_list_render_debug"
FEATURE_TITLE = "User List Render"

IMPORT_ERROR = None
try:
    from telegram.error import BadRequest
    from modules.handlers.list_alerts import LIST_CONTEXT_KEY
    from modules.handlers import user_list as user_list_handlers
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _StorageStub:
    def __init__(self, *, meta_by_user_id=None):
        self.events = []
        self.meta_by_user_id = meta_by_user_id or {}

    def get_user_meta(self, user_id):
        meta = self.meta_by_user_id.get(str(user_id))
        if isinstance(meta, dict):
            return dict(meta)
        return {"username": f"user{user_id}"}

    def get_all_alerts(self, _user_id):
        return {"alerts": [], "tags": []}

    def log_user_event(self, user_id, event_type, payload):
        self.events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": payload or {},
        })
        return True


class _BotStub:
    def __init__(self, *, fail_on_send_index=None, fail_with=None, fail_with_exception=None):
        self.sent = []
        self._fail_on_send_index = fail_on_send_index
        self._fail_with = fail_with
        self._fail_with_exception = fail_with_exception

    async def send_message(self, chat_id, text, **kwargs):
        send_idx = len(self.sent)
        if self._fail_on_send_index is not None and send_idx == int(self._fail_on_send_index):
            if self._fail_with_exception is not None:
                raise self._fail_with_exception
            raise BadRequest(self._fail_with or "Chat not found")
        self.sent.append({
            "chat_id": chat_id,
            "text": text,
            "kwargs": kwargs,
        })
        return types.SimpleNamespace(message_id=1000 + send_idx)


class _MessageStub:
    def __init__(self, *, chat_id=999, fail_on_reply_index=None, fail_with=None):
        self.chat_id = chat_id
        self.replies = []
        self._fail_on_reply_index = fail_on_reply_index
        self._fail_with = fail_with

    async def reply_text(self, text, **kwargs):
        reply_idx = len(self.replies)
        if self._fail_on_reply_index is not None and reply_idx == int(self._fail_on_reply_index):
            raise BadRequest(self._fail_with or "Chat not found")
        self.replies.append({"text": text, "kwargs": kwargs})
        return types.SimpleNamespace(message_id=2000 + reply_idx)


class _ContextStub:
    def __init__(self, *, bot=None):
        self.user_data = {}
        self.bot = bot or _BotStub()


class _CallbackQueryStub:
    def __init__(self, *, message=None, edit_fail_with=None):
        self.message = message
        self.edits = []
        self._edit_fail_with = edit_fail_with

    async def edit_message_text(self, text, **kwargs):
        if self._edit_fail_with is not None:
            raise BadRequest(self._edit_fail_with)
        self.edits.append({"text": text, "kwargs": kwargs})
        return types.SimpleNamespace(message_id=123)


class _UpdateStub:
    def __init__(self, *, user_id=999, callback_query=None, effective_message=None, message=None):
        self.effective_user = types.SimpleNamespace(id=user_id)
        self.callback_query = callback_query
        self.effective_message = effective_message
        self.message = message


def _find_event(events, event_name):
    for item in events:
        if item.get("event") == event_name:
            return item
    return None


def _has_back_markup(value):
    if value is None:
        return False
    keyboard = getattr(value, "inline_keyboard", None)
    if not isinstance(keyboard, (list, tuple)):
        return False
    for row in keyboard:
        if not isinstance(row, (list, tuple)):
            continue
        for btn in row:
            if getattr(btn, "text", "") == "⬅️ Back":
                return True
    return False


def _entries_from_alias_map(alias_map):
    seen = set()
    entries = []
    for uid in (alias_map or {}).values():
        if uid in seen:
            continue
        seen.add(uid)
        entries.append({"id": str(uid), "role": "user"})
    if not entries:
        entries = [{"id": "8101", "role": "user"}]
    return entries


async def _run_show_user_list_case(
    *,
    chunks,
    alias_map,
    overflowed,
    callback=True,
    query_has_message=True,
    edit_fail_with=None,
    bot_fail_on_send_index=None,
    bot_fail_with=None,
    bot_fail_with_exception=None,
    use_context=True,
    non_callback_use_effective_message=True,
):
    original_list = user_list_handlers.list_whitelist_users
    original_build_chunks = user_list_handlers._build_users_chunks

    storage = _StorageStub()
    context = _ContextStub(bot=_BotStub(
        fail_on_send_index=bot_fail_on_send_index,
        fail_with=bot_fail_with,
        fail_with_exception=bot_fail_with_exception,
    )) if use_context else None

    if callback:
        query_message = _MessageStub(chat_id=777) if query_has_message else None
        query = _CallbackQueryStub(message=query_message, edit_fail_with=edit_fail_with)
        update = _UpdateStub(user_id=999, callback_query=query)
    else:
        effective_message = _MessageStub(chat_id=888) if non_callback_use_effective_message else None
        message = None if non_callback_use_effective_message else _MessageStub(chat_id=889)
        update = _UpdateStub(user_id=999, callback_query=None, effective_message=effective_message, message=message)

    try:
        user_list_handlers.list_whitelist_users = lambda: _entries_from_alias_map(alias_map)
        user_list_handlers._build_users_chunks = lambda *_args, **_kwargs: (list(chunks), dict(alias_map), bool(overflowed))
        await user_list_handlers.show_user_list(update, context, storage, role="admin", origin="manage")
    finally:
        user_list_handlers.list_whitelist_users = original_list
        user_list_handlers._build_users_chunks = original_build_chunks

    return update, context, storage


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        tuple_value = user_list_handlers.format_user_summary({}, last_seen=None, first_start=None)
        tuple_checks = {
            "is_tuple": isinstance(tuple_value, tuple) and len(tuple_value) == 2,
            "compact_triplet": isinstance(tuple_value, tuple) and tuple_value[1] == "0-0-0",
        }
        dbg.section("format_summary_type", {"checks": tuple_checks, "value": tuple_value})
        if not all(tuple_checks.values()):
            dbg.problem("user_list_render_failed", {"step": "format_summary_type", "checks": tuple_checks})

        # 1) single-chunk callback edit
        one_chunks = ["👥 **Whitelisted Users**\n**USERS**\n/01 @alpha | 1-0-0"]
        one_alias = {"01": "8101"}
        update1, context1, storage1 = asyncio.run(_run_show_user_list_case(
            chunks=one_chunks,
            alias_map=one_alias,
            overflowed=False,
            callback=True,
            query_has_message=True,
        ))
        event1 = _find_event(storage1.events, "manage_user_list_rendered")
        payload1 = event1.get("payload") if isinstance(event1, dict) else {}
        list_ctx1 = (context1.user_data or {}).get(LIST_CONTEXT_KEY) if context1 is not None else {}
        check1 = {
            "single_edit": len(update1.callback_query.edits) == 1,
            "no_continuation_send": len(context1.bot.sent) == 0,
            "back_on_single_chunk": _has_back_markup(update1.callback_query.edits[0]["kwargs"].get("reply_markup")) if update1.callback_query.edits else False,
            "parse_mode_markdown": update1.callback_query.edits[0]["kwargs"].get("parse_mode") == "Markdown" if update1.callback_query.edits else False,
            "alias_context_saved": isinstance(list_ctx1, dict) and list_ctx1.get("alias_map") == one_alias,
            "delivery_callback_edit": payload1.get("delivery") == "callback_edit",
            "chunks_total_1": payload1.get("chunks_total") == 1,
            "continuations_0": payload1.get("continuation_messages_sent") == 0,
        }
        dbg.section("single_chunk_callback", {"checks": check1, "event_payload": payload1})
        if not all(check1.values()):
            dbg.problem("user_list_render_failed", {"step": "single_chunk_callback", "checks": check1})

        # 2) multi-chunk callback: first edit + continuation sends
        multi_chunks = [
            "👥 **Whitelisted Users**\n**USERS**\n/01 @alpha | 1-0-0",
            "👥 **Whitelisted Users** (cont.)\n/02 @bravo | 2-0-0",
            "👥 **Whitelisted Users** (cont.)\n/03 @charlie | 3-0-0",
        ]
        multi_alias = {"01": "8201", "02": "8202", "03": "8203"}
        update2, context2, storage2 = asyncio.run(_run_show_user_list_case(
            chunks=multi_chunks,
            alias_map=multi_alias,
            overflowed=False,
            callback=True,
            query_has_message=True,
        ))
        event2 = _find_event(storage2.events, "manage_user_list_rendered")
        payload2 = event2.get("payload") if isinstance(event2, dict) else {}
        list_ctx2 = (context2.user_data or {}).get(LIST_CONTEXT_KEY) if context2 is not None else {}
        edit_markup2 = update2.callback_query.edits[0]["kwargs"].get("reply_markup") if update2.callback_query.edits else None
        sent2 = context2.bot.sent if context2 is not None else []
        check2 = {
            "first_chunk_edited": len(update2.callback_query.edits) == 1,
            "continuations_sent": len(sent2) == 2,
            "first_chunk_no_back": not _has_back_markup(edit_markup2),
            "middle_chunk_no_back": len(sent2) >= 1 and not _has_back_markup(sent2[0]["kwargs"].get("reply_markup")),
            "last_chunk_has_back": len(sent2) >= 2 and _has_back_markup(sent2[1]["kwargs"].get("reply_markup")),
            "all_markdown": all(row.get("kwargs", {}).get("parse_mode") == "Markdown" for row in sent2),
            "alias_continuity": isinstance(list_ctx2, dict) and list_ctx2.get("alias_map") == multi_alias,
            "delivery_callback_edit": payload2.get("delivery") == "callback_edit",
            "chunks_total_3": payload2.get("chunks_total") == 3,
            "continuations_2": payload2.get("continuation_messages_sent") == 2,
            "no_oversize_notice": not any("too long" in (row.get("text", "").lower()) for row in sent2),
        }
        dbg.section("multi_chunk_callback", {"checks": check2, "event_payload": payload2})
        if not all(check2.values()):
            dbg.problem("user_list_render_failed", {"step": "multi_chunk_callback", "checks": check2})

        # 3) callback without query.message -> all-send fallback
        update3, context3, storage3 = asyncio.run(_run_show_user_list_case(
            chunks=multi_chunks,
            alias_map=multi_alias,
            overflowed=False,
            callback=True,
            query_has_message=False,
        ))
        event3 = _find_event(storage3.events, "manage_user_list_rendered")
        payload3 = event3.get("payload") if isinstance(event3, dict) else {}
        sent3 = context3.bot.sent if context3 is not None else []
        check3 = {
            "no_edit_attempt": len(update3.callback_query.edits) == 0,
            "all_chunks_sent": len(sent3) == 3,
            "final_chunk_back_only": len(sent3) == 3 and not _has_back_markup(sent3[0]["kwargs"].get("reply_markup")) and _has_back_markup(sent3[2]["kwargs"].get("reply_markup")),
            "delivery_chat_send": payload3.get("delivery") == "chat_send",
            "continuations_2": payload3.get("continuation_messages_sent") == 2,
        }
        dbg.section("callback_missing_message", {"checks": check3, "event_payload": payload3})
        if not all(check3.values()):
            dbg.problem("user_list_render_failed", {"step": "callback_missing_message", "checks": check3})

        # 3b) callback without query.message + send failure on first chunk => fail-soft log path
        update3b, context3b, storage3b = asyncio.run(_run_show_user_list_case(
            chunks=multi_chunks,
            alias_map=multi_alias,
            overflowed=False,
            callback=True,
            query_has_message=False,
            bot_fail_on_send_index=0,
            bot_fail_with="Chat not found",
        ))
        event3b = _find_event(storage3b.events, "manage_user_list_render_failed")
        payload3b = event3b.get("payload") if isinstance(event3b, dict) else {}
        sent3b = context3b.bot.sent if context3b is not None else []
        check3b = {
            "failure_logged": event3b is not None,
            "reason_bad_request": payload3b.get("reason") == "bad_request",
            "delivery_chat_send": payload3b.get("delivery") == "chat_send",
            "no_messages_sent": len(sent3b) == 0,
            "no_edit_attempt": len(update3b.callback_query.edits) == 0,
            "metadata_only": "text" not in payload3b and "text_len" in payload3b and "text_hash" in payload3b,
        }
        dbg.section("callback_missing_message_send_failure", {"checks": check3b, "event_payload": payload3b})
        if not all(check3b.values()):
            dbg.problem("user_list_render_failed", {"step": "callback_missing_message_send_failure", "checks": check3b})

        # 4) non-callback delivery path
        update4, context4, storage4 = asyncio.run(_run_show_user_list_case(
            chunks=multi_chunks,
            alias_map=multi_alias,
            overflowed=False,
            callback=False,
            query_has_message=False,
        ))
        event4 = _find_event(storage4.events, "manage_user_list_rendered")
        payload4 = event4.get("payload") if isinstance(event4, dict) else {}
        replies4 = update4.effective_message.replies if update4.effective_message is not None else []
        check4 = {
            "replies_sent": len(replies4) == 3,
            "bot_unused": len(context4.bot.sent) == 0 if context4 is not None else False,
            "final_chunk_back_only": len(replies4) == 3 and not _has_back_markup(replies4[0]["kwargs"].get("reply_markup")) and _has_back_markup(replies4[2]["kwargs"].get("reply_markup")),
            "delivery_chat_send": payload4.get("delivery") == "chat_send",
            "continuations_2": payload4.get("continuation_messages_sent") == 2,
        }
        dbg.section("non_callback_path", {"checks": check4, "event_payload": payload4})
        if not all(check4.values()):
            dbg.problem("user_list_render_failed", {"step": "non_callback_path", "checks": check4})

        # 5) message-not-modified on chunk 1, continuation still sent
        two_chunks = [
            "👥 **Whitelisted Users**\n**USERS**\n/01 @alpha | 1-0-0",
            "👥 **Whitelisted Users** (cont.)\n/02 @bravo | 2-0-0",
        ]
        two_alias = {"01": "8301", "02": "8302"}
        update5, context5, storage5 = asyncio.run(_run_show_user_list_case(
            chunks=two_chunks,
            alias_map=two_alias,
            overflowed=False,
            callback=True,
            query_has_message=True,
            edit_fail_with="Message is not modified",
        ))
        event5 = _find_event(storage5.events, "manage_user_list_rendered")
        payload5 = event5.get("payload") if isinstance(event5, dict) else {}
        sent5 = context5.bot.sent if context5 is not None else []
        check5 = {
            "no_failure_event": _find_event(storage5.events, "manage_user_list_render_failed") is None,
            "continuation_sent": len(sent5) == 1,
            "delivery_noop": payload5.get("delivery") == "message_not_modified",
            "reason_noop": payload5.get("reason") == "message_not_modified",
            "continuations_1": payload5.get("continuation_messages_sent") == 1,
            "still_markdown": len(sent5) == 1 and sent5[0].get("kwargs", {}).get("parse_mode") == "Markdown",
            "no_edit_recorded": len(update5.callback_query.edits) == 0,
        }
        dbg.section("message_not_modified", {"checks": check5, "event_payload": payload5})
        if not all(check5.values()):
            dbg.problem("user_list_render_failed", {"step": "message_not_modified", "checks": check5})

        # 6) overflowed + too long reject => fail-soft oversize notice
        huge_chunk = ["👥 **Whitelisted Users**\n**USERS**\n/01 @huge | 999-999-999"]
        huge_alias = {"01": "8401"}
        _update6, context6, storage6 = asyncio.run(_run_show_user_list_case(
            chunks=huge_chunk,
            alias_map=huge_alias,
            overflowed=True,
            callback=True,
            query_has_message=True,
            edit_fail_with="Message is too long",
        ))
        event6 = _find_event(storage6.events, "manage_user_list_render_failed")
        payload6 = event6.get("payload") if isinstance(event6, dict) else {}
        sent6 = context6.bot.sent if context6 is not None else []
        check6 = {
            "failure_logged": event6 is not None,
            "reason_too_long": payload6.get("reason") == "telegram_message_too_long",
            "oversize_notice_sent": any("too long" in (row.get("text", "").lower()) for row in sent6),
            "metadata_only": "text" not in payload6 and "text_len" in payload6 and "text_hash" in payload6,
        }
        dbg.section("overflow_too_long", {"checks": check6, "event_payload": payload6})
        if not all(check6.values()):
            dbg.problem("user_list_render_failed", {"step": "overflow_too_long", "checks": check6})

        # 7) partial continuation failure after earlier success
        _update7, context7, storage7 = asyncio.run(_run_show_user_list_case(
            chunks=multi_chunks,
            alias_map=multi_alias,
            overflowed=False,
            callback=True,
            query_has_message=True,
            bot_fail_on_send_index=1,
            bot_fail_with="Chat not found",
        ))
        event7 = _find_event(storage7.events, "manage_user_list_render_failed")
        payload7 = event7.get("payload") if isinstance(event7, dict) else {}
        sent7 = context7.bot.sent if context7 is not None else []
        check7 = {
            "failure_logged": event7 is not None,
            "partial_sent_once": len(sent7) == 1,
            "reason_bad_request": payload7.get("reason") == "bad_request",
            "delivery_chunk1_preserved": payload7.get("delivery") == "callback_edit",
            "continuations_count_1": payload7.get("continuation_messages_sent") == 1,
            "metadata_only": "text" not in payload7 and "text_len" in payload7 and "text_hash" in payload7,
            "no_oversize_notice": not any("too long" in (row.get("text", "").lower()) for row in sent7),
        }
        dbg.section("partial_delivery_failure", {"checks": check7, "event_payload": payload7})
        if not all(check7.values()):
            dbg.problem("user_list_render_failed", {"step": "partial_delivery_failure", "checks": check7})

        # 8) partial continuation failure with non-BadRequest exception => normalized failure
        _update8, context8, storage8 = asyncio.run(_run_show_user_list_case(
            chunks=multi_chunks,
            alias_map=multi_alias,
            overflowed=False,
            callback=True,
            query_has_message=True,
            bot_fail_on_send_index=1,
            bot_fail_with_exception=RuntimeError("network down"),
        ))
        event8 = _find_event(storage8.events, "manage_user_list_render_failed")
        payload8 = event8.get("payload") if isinstance(event8, dict) else {}
        sent8 = context8.bot.sent if context8 is not None else []
        check8 = {
            "failure_logged": event8 is not None,
            "partial_sent_once": len(sent8) == 1,
            "reason_other": payload8.get("reason") == "other",
            "delivery_chunk1_preserved": payload8.get("delivery") == "callback_edit",
            "continuations_count_1": payload8.get("continuation_messages_sent") == 1,
            "metadata_only": "text" not in payload8 and "text_len" in payload8 and "text_hash" in payload8,
        }
        dbg.section("partial_delivery_failure_runtime", {"checks": check8, "event_payload": payload8})
        if not all(check8.values()):
            dbg.problem("user_list_render_failed", {"step": "partial_delivery_failure_runtime", "checks": check8})

        # 9) missing target fallback preserved
        update9, _context9, storage9 = asyncio.run(_run_show_user_list_case(
            chunks=two_chunks,
            alias_map=two_alias,
            overflowed=False,
            callback=True,
            query_has_message=False,
            use_context=False,
        ))
        event9 = _find_event(storage9.events, "manage_user_list_render_failed")
        payload9 = event9.get("payload") if isinstance(event9, dict) else {}
        check9 = {
            "failure_logged": event9 is not None,
            "reason_missing_target": payload9.get("reason") == "missing_delivery_target",
            "delivery_chat_send": payload9.get("delivery") == "chat_send",
            "no_edit_attempt": len(update9.callback_query.edits) == 0,
        }
        dbg.section("missing_target", {"checks": check9, "event_payload": payload9})
        if not all(check9.values()):
            dbg.problem("user_list_render_failed", {"step": "missing_target", "checks": check9})
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem("user_list_render_failed")
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"render: {'OK' if checks_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
