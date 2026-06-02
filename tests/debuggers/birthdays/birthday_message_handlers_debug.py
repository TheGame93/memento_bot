#!/usr/bin/env python3
import os
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch


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
from _lib.runtime import run_async

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "birthday_message_handlers_debug"
FEATURE_TITLE = "Birthday Message Handlers"

IMPORT_ERROR = None
try:
    from modules import constants as C
    from modules.handlers.scheduler_handlers import (
        handle_bday_msg_style,
        handle_bday_noted,
    )
    from modules.handlers.birthday_flow.message_suggestions.callbacks import (
        build_bday_msg_callback,
        build_bday_noted_callback,
        decode_bday_msg_callback,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
    IMPORT_ERROR = exc


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _StrictQuery:
    def __init__(self, data):
        self.data = data
        self.answer_attempts = 0
        self.answers = []
        self.message = SimpleNamespace(message_id=101, photo=None)

    async def answer(self, text=None, show_alert=False):
        self.answer_attempts += 1
        if self.answer_attempts > 1:
            raise RuntimeError("callback_answer_called_twice")
        self.answers.append({"text": text, "show_alert": bool(show_alert)})


class _DummyBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "kwargs": dict(kwargs),
            }
        )


class _StorageStub:
    def __init__(self):
        self.alerts = {}
        self.events = []
        self._prefs = {}

    def get_alert_by_id(self, user_id, alert_id):
        value = self.alerts.get(alert_id)
        return dict(value) if isinstance(value, dict) else None

    def log_user_event(self, user_id, event_type, payload=None):
        self.events.append(
            {
                "user_id": str(user_id),
                "event_type": event_type,
                "payload": dict(payload or {}),
            }
        )

    def get_user_prefs(self, user_id):
        return dict(self._prefs)


async def _run_handler(handler, callback_data, storage, user_id=777):
    from modules.shared.runtime_context import BotRuntime, set_bot_runtime

    query = _StrictQuery(callback_data)
    bot_data = {}
    context = SimpleNamespace(bot=_DummyBot(), bot_data=bot_data, user_data={})
    set_bot_runtime(bot_data, BotRuntime(storage=storage, api_failure_tracker=None))
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id),
    )
    err = None
    try:
        await handler(update, context)
    except Exception as exc:  # pragma: no cover
        err = str(exc)
    return {
        "query": query,
        "context": context,
        "storage": storage,
        "error": err,
    }


def _event_exists(events, event_type, predicate):
    for event in events:
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload", {})
        if predicate(payload):
            return True
    return False


def _event_payload(events, event_type, predicate=None):
    for event in events:
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload", {})
        if predicate is None or predicate(payload):
            return payload
    return None


def _payload_has_no_raw_text(payload):
    if not isinstance(payload, dict):
        return False
    forbidden_keys = {"text", "message", "raw_text", "generated_text", "suggestion", "title"}
    return all(key not in payload for key in forbidden_keys)


def _check_zodiac_note_prepend(dbg):
    now = datetime(2026, 3, 10, 10, 0, 0)
    alert_id = "bday_zodiac_note"

    def _build_storage(*, birth_year, prefs=None):
        storage = _StorageStub()
        storage._prefs = dict(prefs or {})
        alert = {
            "id": alert_id,
            "type": 6,
            "title": "Best Friend",
            "schedule": {"date": "15/03"},
            "tags": ["🫂 Friends"],
        }
        if birth_year is not None:
            alert["birth_year"] = birth_year
        storage.alerts[alert_id] = alert
        return storage

    callback = build_bday_msg_callback("zodiac", alert_id, now)

    storage_note = _build_storage(birth_year=1990)
    with patch(
        "modules.handlers.birthday_flow.message_suggestions.inference._random.choice",
        return_value=False,
    ):
        result_note = run_async(_run_handler(handle_bday_msg_style, callback, storage_note))
    note_text = (
        result_note["context"].bot.sent_messages[0]["text"]
        if result_note["context"].bot.sent_messages
        else ""
    )

    storage_no_eastern = _build_storage(birth_year=None)
    result_no_eastern = run_async(_run_handler(handle_bday_msg_style, callback, storage_no_eastern))
    no_eastern_text = (
        result_no_eastern["context"].bot.sent_messages[0]["text"]
        if result_no_eastern["context"].bot.sent_messages
        else ""
    )

    storage_explicit = _build_storage(
        birth_year=1990,
        prefs={"birthday_zodiac_mode": C.BIRTHDAY_ZODIAC_MODE_WESTERN},
    )
    result_explicit = run_async(_run_handler(handle_bday_msg_style, callback, storage_explicit))
    explicit_text = (
        result_explicit["context"].bot.sent_messages[0]["text"]
        if result_explicit["context"].bot.sent_messages
        else ""
    )

    checks = {
        "note_case_no_exception": result_note["error"] is None,
        "note_case_sent_once": len(result_note["context"].bot.sent_messages) == 1,
        "note_case_starts_with_note": note_text.startswith("(zodiac randomly picked"),
        "no_eastern_no_exception": result_no_eastern["error"] is None,
        "no_eastern_sent_once": len(result_no_eastern["context"].bot.sent_messages) == 1,
        "no_eastern_no_note": not no_eastern_text.startswith("(zodiac randomly picked"),
        "explicit_mode_no_exception": result_explicit["error"] is None,
        "explicit_mode_sent_once": len(result_explicit["context"].bot.sent_messages) == 1,
        "explicit_mode_no_note": "(zodiac randomly picked" not in explicit_text,
    }

    dbg.section(
        "bday_zodiac_note_prepend",
        {
            "checks": checks,
            "note_case_text": note_text,
            "no_eastern_text": no_eastern_text,
            "explicit_mode_text": explicit_text,
        },
    )
    if not all(checks.values()):
        dbg.problem("birthday_message_zodiac_note_prepend_failed", {"checks": checks})


def _run_checks(dbg):
    _check_zodiac_note_prepend(dbg)

    now = datetime(2026, 3, 10, 10, 0, 0)

    # prompt shown path
    storage = _StorageStub()
    alert_id = "bday_prompt"
    storage.alerts[alert_id] = {
        "id": alert_id,
        "type": 6,
        "title": "Best Friend",
        "birth_year": 1995,
        "tags": ["🫂 Friends"],
    }
    noted_callback = build_bday_noted_callback(alert_id, now, now)
    result_prompt = run_async(_run_handler(handle_bday_noted, noted_callback, storage))
    sent_prompt = result_prompt["context"].bot.sent_messages[0] if result_prompt["context"].bot.sent_messages else {}
    prompt_keyboard = sent_prompt.get("kwargs", {}).get("reply_markup")
    prompt_callbacks = []
    decoded_prompt_callbacks_ok = True
    callback_lengths_ok = True
    if prompt_keyboard and getattr(prompt_keyboard, "inline_keyboard", None):
        for row in prompt_keyboard.inline_keyboard:
            for btn in row:
                cb = getattr(btn, "callback_data", "")
                prompt_callbacks.append(cb)
                callback_lengths_ok = callback_lengths_ok and len(str(cb).encode("utf-8")) <= 64
                decoded_prompt_callbacks_ok = decoded_prompt_callbacks_ok and decode_bday_msg_callback(cb).get("ok", False)

    prompt_noted_payload = _event_payload(
        storage.events,
        "bday_noted_pressed",
        lambda payload: payload.get("alert_id") == alert_id,
    )
    prompt_shown_payload = _event_payload(
        storage.events,
        "bday_msg_prompt_shown",
        lambda payload: payload.get("alert_id") == alert_id,
    )

    prompt_checks = {
        "no_exception": result_prompt["error"] is None,
        "single_answer_attempt": result_prompt["query"].answer_attempts == 1,
        "single_answer_recorded": len(result_prompt["query"].answers) == 1,
        "non_popup_ack": bool(result_prompt["query"].answers and not result_prompt["query"].answers[0]["show_alert"]),
        "prompt_sent_once": len(result_prompt["context"].bot.sent_messages) == 1,
        "prompt_has_5_buttons": len(prompt_callbacks) == 5,
        "prompt_callbacks_prefixed": all(str(cb).startswith(C.CB_BDAY_MSG) for cb in prompt_callbacks),
        "prompt_callbacks_decode_ok": decoded_prompt_callbacks_ok,
        "prompt_callbacks_fit": callback_lengths_ok,
        "bday_noted_event_logged": bool(prompt_noted_payload),
        "bday_noted_payload_fields": bool(
            prompt_noted_payload
            and prompt_noted_payload.get("alert_type") == 6
            and prompt_noted_payload.get("occ_ts_present") is True
            and isinstance(prompt_noted_payload.get("occ_iso"), str)
            and prompt_noted_payload.get("payload_source") in {"codec", "legacy"}
            and prompt_noted_payload.get("reason_code") is None
        ),
        "bday_noted_no_raw_text": _payload_has_no_raw_text(prompt_noted_payload),
        "bday_prompt_event_logged": bool(prompt_shown_payload),
        "bday_prompt_payload_fields": bool(
            prompt_shown_payload
            and prompt_shown_payload.get("alert_type") == 6
            and prompt_shown_payload.get("styles_count") == 5
            and isinstance(prompt_shown_payload.get("max_callback_len"), int)
            and isinstance(prompt_shown_payload.get("min_callback_len"), int)
            and prompt_shown_payload.get("payload_source") in {"codec", "legacy"}
        ),
        "bday_prompt_callback_diag_range": bool(
            prompt_shown_payload
            and 0 <= int(prompt_shown_payload.get("min_callback_len")) <= int(prompt_shown_payload.get("max_callback_len")) <= 64
        ),
        "bday_prompt_no_raw_text": _payload_has_no_raw_text(prompt_shown_payload),
    }
    dbg.section(
        "bday_noted_prompt_path",
        {
            "callback": noted_callback,
            "answers": result_prompt["query"].answers,
            "sent_messages": result_prompt["context"].bot.sent_messages,
            "events": storage.events,
            "checks": prompt_checks,
        },
    )
    if not all(prompt_checks.values()):
        dbg.problem("birthday_message_prompt_path_failed", {"checks": prompt_checks})

    # style selected path
    storage = _StorageStub()
    alert_id = "bday_style_ok"
    storage.alerts[alert_id] = {
        "id": alert_id,
        "type": 6,
        "title": "Best Friend",
        "birth_year": 1990,
        "tags": ["🫂 Friends"],
    }
    style_callback = build_bday_msg_callback("polite", alert_id, now)
    result_style = run_async(_run_handler(handle_bday_msg_style, style_callback, storage))
    style_selected_payload = _event_payload(
        storage.events,
        "bday_msg_style_selected",
        lambda payload: payload.get("alert_id") == alert_id and payload.get("style") == "polite",
    )
    generated_payload = _event_payload(
        storage.events,
        "bday_msg_generated",
        lambda payload: payload.get("alert_id") == alert_id and payload.get("style") == "polite",
    )
    style_checks = {
        "no_exception": result_style["error"] is None,
        "single_answer_attempt": result_style["query"].answer_attempts == 1,
        "single_answer_recorded": len(result_style["query"].answers) == 1,
        "non_popup_ack": bool(result_style["query"].answers and not result_style["query"].answers[0]["show_alert"]),
        "suggestion_sent_once": len(result_style["context"].bot.sent_messages) == 1,
        "style_selected_logged": bool(style_selected_payload),
        "style_selected_payload_fields": bool(
            style_selected_payload
            and style_selected_payload.get("alert_type") == 6
            and style_selected_payload.get("selection_result") == "selected"
            and style_selected_payload.get("template_id")
            and style_selected_payload.get("reason_code") is None
        ),
        "style_selected_no_raw_text": _payload_has_no_raw_text(style_selected_payload),
        "generated_logged": bool(generated_payload),
        "generated_payload_fields": bool(
            generated_payload
            and generated_payload.get("alert_type") == 6
            and generated_payload.get("template_id")
            and isinstance(generated_payload.get("candidate_count"), int)
            and isinstance(generated_payload.get("turning_age_known"), bool)
            and isinstance(generated_payload.get("tag_groups"), list)
            and isinstance(generated_payload.get("title_hints"), list)
        ),
        "generated_payload_no_raw_text": _payload_has_no_raw_text(generated_payload),
    }
    dbg.section(
        "bday_style_selected_path",
        {
            "answers": result_style["query"].answers,
            "sent_messages": result_style["context"].bot.sent_messages,
            "events": storage.events,
            "checks": style_checks,
        },
    )
    if not all(style_checks.values()):
        dbg.problem("birthday_message_style_selected_failed", {"checks": style_checks})

    # no-style path
    storage = _StorageStub()
    alert_id = "bday_style_no"
    storage.alerts[alert_id] = {"id": alert_id, "type": 6, "title": "Birthday"}
    no_callback = build_bday_msg_callback("no", alert_id, now)
    result_no = run_async(_run_handler(handle_bday_msg_style, no_callback, storage))
    no_style_payload = _event_payload(
        storage.events,
        "bday_msg_style_selected",
        lambda payload: payload.get("alert_id") == alert_id and payload.get("style") == "no",
    )
    no_checks = {
        "no_exception": result_no["error"] is None,
        "single_answer_attempt": result_no["query"].answer_attempts == 1,
        "single_answer_recorded": len(result_no["query"].answers) == 1,
        "sent_confirmation_once": len(result_no["context"].bot.sent_messages) == 1,
        "selection_declined_logged": bool(no_style_payload),
        "selection_declined_payload_fields": bool(
            no_style_payload
            and no_style_payload.get("alert_type") == 6
            and no_style_payload.get("selection_result") == "user_declined"
            and no_style_payload.get("reason_code") is None
        ),
        "selection_declined_no_raw_text": _payload_has_no_raw_text(no_style_payload),
    }
    dbg.section("bday_style_no_path", {"checks": no_checks, "events": storage.events, "answers": result_no["query"].answers})
    if not all(no_checks.values()):
        dbg.problem("birthday_message_no_style_failed", {"checks": no_checks})

    # alert missing path
    storage = _StorageStub()
    missing_callback = build_bday_msg_callback("polite", "missing_alert", now)
    result_missing = run_async(_run_handler(handle_bday_msg_style, missing_callback, storage))
    missing_style_payload = _event_payload(
        storage.events,
        "bday_msg_style_selected",
        lambda payload: payload.get("reason_code") == "alert_not_found",
    )
    missing_failed_payload = _event_payload(
        storage.events,
        "bday_msg_generation_failed",
        lambda payload: payload.get("reason_code") == "alert_not_found",
    )
    missing_checks = {
        "no_exception": result_missing["error"] is None,
        "single_answer_attempt": result_missing["query"].answer_attempts == 1,
        "popup_answer": bool(result_missing["query"].answers and result_missing["query"].answers[0]["show_alert"]),
        "missing_style_reason_logged": bool(
            missing_style_payload
            and missing_style_payload.get("alert_type") == 6
            and missing_style_payload.get("selection_result") == "failed"
            and missing_style_payload.get("style") == "polite"
            and missing_style_payload.get("alert_id") == "missing_alert"
        ),
        "missing_generation_reason_logged": bool(
            missing_failed_payload
            and missing_failed_payload.get("alert_type") == 6
            and missing_failed_payload.get("style") == "polite"
        ),
        "missing_no_raw_text": _payload_has_no_raw_text(missing_style_payload) and _payload_has_no_raw_text(missing_failed_payload),
    }
    dbg.section("bday_style_missing_alert", {"checks": missing_checks, "events": storage.events, "answers": result_missing["query"].answers})
    if not all(missing_checks.values()):
        dbg.problem("birthday_message_missing_alert_failed", {"checks": missing_checks})

    # malformed callback path
    storage = _StorageStub()
    malformed_result = run_async(_run_handler(handle_bday_msg_style, f"{C.CB_BDAY_MSG}bad", storage))
    malformed_style_payload = _event_payload(
        storage.events,
        "bday_msg_style_selected",
        lambda payload: payload.get("reason_code") == "callback_payload_invalid",
    )
    malformed_failed_payload = _event_payload(
        storage.events,
        "bday_msg_generation_failed",
        lambda payload: payload.get("reason_code") == "callback_payload_invalid",
    )
    malformed_checks = {
        "no_exception": malformed_result["error"] is None,
        "single_answer_attempt": malformed_result["query"].answer_attempts == 1,
        "popup_answer": bool(malformed_result["query"].answers and malformed_result["query"].answers[0]["show_alert"]),
        "invalid_style_reason_logged": bool(
            malformed_style_payload
            and malformed_style_payload.get("alert_type") == 6
            and malformed_style_payload.get("selection_result") == "failed"
            and malformed_style_payload.get("alert_id") is None
            and malformed_style_payload.get("style") is None
        ),
        "invalid_generation_reason_logged": bool(
            malformed_failed_payload
            and malformed_failed_payload.get("alert_type") == 6
            and malformed_failed_payload.get("alert_id") is None
            and malformed_failed_payload.get("style") is None
        ),
        "invalid_no_raw_text": _payload_has_no_raw_text(malformed_style_payload) and _payload_has_no_raw_text(malformed_failed_payload),
    }
    dbg.section("bday_style_malformed", {"checks": malformed_checks, "events": storage.events, "answers": malformed_result["query"].answers})
    if not all(malformed_checks.values()):
        dbg.problem("birthday_message_malformed_callback_failed", {"checks": malformed_checks})

    # invalid style path
    storage = _StorageStub()
    invalid_alert_id = "bday_invalid_style"
    storage.alerts[invalid_alert_id] = {"id": invalid_alert_id, "type": 6, "title": "Birthday"}
    invalid_callback = build_bday_msg_callback("alien", invalid_alert_id, now)
    invalid_result = run_async(_run_handler(handle_bday_msg_style, invalid_callback, storage))
    invalid_style_payload = _event_payload(
        storage.events,
        "bday_msg_style_selected",
        lambda payload: payload.get("reason_code") == "invalid_style",
    )
    invalid_failed_payload = _event_payload(
        storage.events,
        "bday_msg_generation_failed",
        lambda payload: payload.get("reason_code") == "invalid_style",
    )
    invalid_checks = {
        "no_exception": invalid_result["error"] is None,
        "single_answer_attempt": invalid_result["query"].answer_attempts == 1,
        "popup_answer": bool(invalid_result["query"].answers and invalid_result["query"].answers[0]["show_alert"]),
        "invalid_style_reason_logged": bool(
            invalid_style_payload
            and invalid_style_payload.get("alert_type") == 6
            and invalid_style_payload.get("selection_result") == "failed"
            and invalid_style_payload.get("alert_id") == invalid_alert_id
            and invalid_style_payload.get("style") == "alien"
        ),
        "invalid_generation_reason_logged": bool(
            invalid_failed_payload
            and invalid_failed_payload.get("alert_type") == 6
            and invalid_failed_payload.get("alert_id") == invalid_alert_id
            and invalid_failed_payload.get("style") == "alien"
        ),
        "invalid_no_raw_text": _payload_has_no_raw_text(invalid_style_payload) and _payload_has_no_raw_text(invalid_failed_payload),
    }
    dbg.section("bday_style_invalid_style", {"checks": invalid_checks, "events": storage.events, "answers": invalid_result["query"].answers})
    if not all(invalid_checks.values()):
        dbg.problem("birthday_message_invalid_style_failed", {"checks": invalid_checks})

    # wrong-type path
    storage = _StorageStub()
    wrong_type_alert_id = "wrong_type"
    storage.alerts[wrong_type_alert_id] = {"id": wrong_type_alert_id, "type": 3, "title": "Not birthday"}
    wrong_type_callback = build_bday_msg_callback("polite", wrong_type_alert_id, now)
    wrong_type_result = run_async(_run_handler(handle_bday_msg_style, wrong_type_callback, storage))
    wrong_type_style_payload = _event_payload(
        storage.events,
        "bday_msg_style_selected",
        lambda payload: payload.get("reason_code") == "alert_not_birthday",
    )
    wrong_type_failed_payload = _event_payload(
        storage.events,
        "bday_msg_generation_failed",
        lambda payload: payload.get("reason_code") == "alert_not_birthday",
    )
    wrong_type_checks = {
        "no_exception": wrong_type_result["error"] is None,
        "single_answer_attempt": wrong_type_result["query"].answer_attempts == 1,
        "popup_answer": bool(wrong_type_result["query"].answers and wrong_type_result["query"].answers[0]["show_alert"]),
        "wrong_type_style_reason_logged": bool(
            wrong_type_style_payload
            and wrong_type_style_payload.get("alert_type") == 6
            and wrong_type_style_payload.get("selection_result") == "failed"
            and wrong_type_style_payload.get("alert_id") == wrong_type_alert_id
            and wrong_type_style_payload.get("style") == "polite"
        ),
        "wrong_type_generation_reason_logged": bool(
            wrong_type_failed_payload
            and wrong_type_failed_payload.get("alert_type") == 6
            and wrong_type_failed_payload.get("alert_id") == wrong_type_alert_id
            and wrong_type_failed_payload.get("style") == "polite"
        ),
        "wrong_type_no_raw_text": _payload_has_no_raw_text(wrong_type_style_payload) and _payload_has_no_raw_text(wrong_type_failed_payload),
    }
    dbg.section("bday_style_wrong_type", {"checks": wrong_type_checks, "events": storage.events, "answers": wrong_type_result["query"].answers})
    if not all(wrong_type_checks.values()):
        dbg.problem("birthday_message_wrong_type_failed", {"checks": wrong_type_checks})

    # bday_noted alert missing path
    storage = _StorageStub()
    noted_missing_callback = build_bday_noted_callback("missing_alert", now, now)
    noted_missing_result = run_async(_run_handler(handle_bday_noted, noted_missing_callback, storage))
    noted_missing_pressed = _event_payload(
        storage.events,
        "bday_noted_pressed",
        lambda payload: payload.get("reason_code") == "alert_not_found",
    )
    noted_missing_failed = _event_payload(
        storage.events,
        "bday_msg_generation_failed",
        lambda payload: payload.get("reason_code") == "alert_not_found",
    )
    noted_missing_checks = {
        "no_exception": noted_missing_result["error"] is None,
        "single_answer_attempt": noted_missing_result["query"].answer_attempts == 1,
        "popup_answer": bool(noted_missing_result["query"].answers and noted_missing_result["query"].answers[0]["show_alert"]),
        "pressed_reason_logged": bool(
            noted_missing_pressed
            and noted_missing_pressed.get("alert_type") == 6
            and noted_missing_pressed.get("alert_id") == "missing_alert"
        ),
        "generation_reason_logged": bool(
            noted_missing_failed
            and noted_missing_failed.get("alert_type") == 6
            and noted_missing_failed.get("alert_id") == "missing_alert"
        ),
        "no_raw_text": _payload_has_no_raw_text(noted_missing_pressed) and _payload_has_no_raw_text(noted_missing_failed),
    }
    dbg.section(
        "bday_noted_missing_alert",
        {"checks": noted_missing_checks, "events": storage.events, "answers": noted_missing_result["query"].answers},
    )
    if not all(noted_missing_checks.values()):
        dbg.problem("birthday_message_noted_missing_alert_failed", {"checks": noted_missing_checks})

    # bday_noted wrong-type path
    storage = _StorageStub()
    wrong_type_noted_id = "bday_noted_wrong_type"
    storage.alerts[wrong_type_noted_id] = {"id": wrong_type_noted_id, "type": 3, "title": "Not birthday"}
    noted_wrong_type_callback = build_bday_noted_callback(wrong_type_noted_id, now, now)
    noted_wrong_type_result = run_async(_run_handler(handle_bday_noted, noted_wrong_type_callback, storage))
    noted_wrong_type_pressed = _event_payload(
        storage.events,
        "bday_noted_pressed",
        lambda payload: payload.get("reason_code") == "alert_not_birthday",
    )
    noted_wrong_type_failed = _event_payload(
        storage.events,
        "bday_msg_generation_failed",
        lambda payload: payload.get("reason_code") == "alert_not_birthday",
    )
    noted_wrong_type_checks = {
        "no_exception": noted_wrong_type_result["error"] is None,
        "single_answer_attempt": noted_wrong_type_result["query"].answer_attempts == 1,
        "popup_answer": bool(noted_wrong_type_result["query"].answers and noted_wrong_type_result["query"].answers[0]["show_alert"]),
        "pressed_reason_logged": bool(
            noted_wrong_type_pressed
            and noted_wrong_type_pressed.get("alert_type") == 6
            and noted_wrong_type_pressed.get("alert_id") == wrong_type_noted_id
        ),
        "generation_reason_logged": bool(
            noted_wrong_type_failed
            and noted_wrong_type_failed.get("alert_type") == 6
            and noted_wrong_type_failed.get("alert_id") == wrong_type_noted_id
        ),
        "no_raw_text": _payload_has_no_raw_text(noted_wrong_type_pressed) and _payload_has_no_raw_text(noted_wrong_type_failed),
    }
    dbg.section(
        "bday_noted_wrong_type",
        {"checks": noted_wrong_type_checks, "events": storage.events, "answers": noted_wrong_type_result["query"].answers},
    )
    if not all(noted_wrong_type_checks.values()):
        dbg.problem("birthday_message_noted_wrong_type_failed", {"checks": noted_wrong_type_checks})

    # bday_noted malformed callback path
    storage = _StorageStub()
    noted_invalid_result = run_async(_run_handler(handle_bday_noted, f"{C.CB_BDAY_NOTED}bad", storage))
    noted_invalid_pressed = _event_payload(
        storage.events,
        "bday_noted_pressed",
        lambda payload: payload.get("reason_code") == "callback_payload_invalid",
    )
    noted_invalid_failed = _event_payload(
        storage.events,
        "bday_msg_generation_failed",
        lambda payload: payload.get("reason_code") == "callback_payload_invalid",
    )
    noted_invalid_checks = {
        "no_exception": noted_invalid_result["error"] is None,
        "single_answer_attempt": noted_invalid_result["query"].answer_attempts == 1,
        "popup_answer": bool(noted_invalid_result["query"].answers and noted_invalid_result["query"].answers[0]["show_alert"]),
        "pressed_reason_logged": bool(
            noted_invalid_pressed
            and noted_invalid_pressed.get("alert_type") == 6
            and noted_invalid_pressed.get("alert_id") is None
            and noted_invalid_pressed.get("payload_source") is None
            and noted_invalid_pressed.get("occ_ts_present") is False
        ),
        "generation_failure_logged": bool(
            noted_invalid_failed
            and noted_invalid_failed.get("alert_type") == 6
            and noted_invalid_failed.get("alert_id") is None
            and noted_invalid_failed.get("style") is None
        ),
        "no_raw_text": _payload_has_no_raw_text(noted_invalid_pressed) and _payload_has_no_raw_text(noted_invalid_failed),
    }
    dbg.section(
        "bday_noted_malformed",
        {"checks": noted_invalid_checks, "events": storage.events, "answers": noted_invalid_result["query"].answers},
    )
    if not all(noted_invalid_checks.values()):
        dbg.problem("birthday_message_noted_malformed_failed", {"checks": noted_invalid_checks})


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    try:
        unknown = _parse_cli_args(dbg.args)
        if unknown:
            dbg.problem("cli_args_unknown", {"unknown": unknown, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        if IMPORT_ERROR is not None:
            dbg.mark_dependency_error(IMPORT_ERROR)
            dbg.finish(exit_on_problems=False)
            return

        _run_checks(dbg)

    except Exception as exc:  # pragma: no cover
        dbg.problem("unhandled_exception", {"error": str(exc)})

    checks_ok = not dbg.has_problem(
        "birthday_message_prompt_path_failed",
        "birthday_message_style_selected_failed",
        "birthday_message_no_style_failed",
        "birthday_message_missing_alert_failed",
        "birthday_message_malformed_callback_failed",
        "birthday_message_invalid_style_failed",
        "birthday_message_wrong_type_failed",
        "birthday_message_noted_missing_alert_failed",
        "birthday_message_noted_wrong_type_failed",
        "birthday_message_noted_malformed_failed",
        "birthday_message_zodiac_note_prepend_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(
        summary_lines=[
            f"birthday_message_handlers: {'OK' if checks_ok else 'FAIL'}",
            f"runtime: {'OK' if runtime_ok else 'FAIL'}",
            f"logfile: {dbg.log_path}",
        ],
        summary_only_on_problems=True,
    )


if __name__ == "__main__":
    main()
