#!/usr/bin/env python3
import copy
import logging
import os
import sys
import tempfile
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
from _lib.runtime import run_async, seed_mainbot_runtime
from _lib.warnings_policy import suppress_ptb_user_warning

ROOT_DIR = add_project_root_to_path(__file__)
SCRIPT_TITLE = "detail_media_fallback_debug"
FEATURE_TITLE = "Detail Media Fallback"


def _parse_cli_args(args):
    unknown = []
    for token in args:
        if token in ("--quiet", "--verbose"):
            continue
        unknown.append(token)
    return unknown


class _FakePhoto:
    def __init__(self, file_id):
        self.file_id = file_id


class _FakeSentMessage:
    def __init__(self, photo_file_id=None):
        self.photo = []
        if photo_file_id:
            self.photo = [_FakePhoto(photo_file_id)]


class _FakeBot:
    def __init__(self, bad_file_ids=None, local_file_id="healed_local_file_id"):
        self.bad_file_ids = set(bad_file_ids or set())
        self.local_file_id = local_file_id
        self.photo_calls = []
        self.message_calls = []

    async def send_photo(self, chat_id, photo, caption, reply_markup=None, parse_mode=None):
        from telegram.error import BadRequest

        call = {
            "chat_id": chat_id,
            "photo_is_str": isinstance(photo, str),
            "photo_value": photo if isinstance(photo, str) else getattr(photo, "name", "<stream>"),
            "caption_len": len(caption or ""),
            "has_reply_markup": bool(reply_markup),
            "parse_mode": parse_mode,
        }
        self.photo_calls.append(call)
        if isinstance(photo, str):
            if photo in self.bad_file_ids:
                raise BadRequest("Wrong file identifier/HTTP URL specified")
            return _FakeSentMessage(photo_file_id=photo)
        return _FakeSentMessage(photo_file_id=self.local_file_id)

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.message_calls.append({
            "chat_id": chat_id,
            "text_len": len(text or ""),
            "has_reply_markup": bool(reply_markup),
            "parse_mode": parse_mode,
        })
        return _FakeSentMessage()


class _FakeStorage:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.alerts = {}
        self.user_events = []
        self.update_calls = []

    def _user_root(self, user_id):
        return os.path.join(self.root_dir, str(user_id))

    def setup_user(self, user_id):
        images_dir = os.path.join(self._user_root(user_id), "images")
        os.makedirs(images_dir, exist_ok=True)
        return images_dir

    def set_alert(self, user_id, alert):
        key = (str(user_id), alert.get("id"))
        self.alerts[key] = copy.deepcopy(alert)

    def get_alert_by_id(self, user_id, alert_id):
        return self.alerts.get((str(user_id), alert_id))

    def get_all_alerts(self, user_id):
        uid = str(user_id)
        items = []
        for (candidate_uid, _), alert in self.alerts.items():
            if candidate_uid == uid:
                items.append(alert)
        return {"alerts": items}

    def get_user_prefs(self, user_id):
        return {}

    def update_alert_fields(self, user_id, alert_id, updates):
        alert = self.get_alert_by_id(user_id, alert_id)
        if not alert:
            return False
        self.update_calls.append({
            "user_id": str(user_id),
            "alert_id": alert_id,
            "updates": dict(updates or {}),
        })
        alert.update(updates or {})
        return True

    def log_user_event(self, user_id, event_type, payload=None):
        self.user_events.append({
            "user_id": str(user_id),
            "event": event_type,
            "payload": dict(payload or {}),
        })
        return True

    def resolve_local_image_path(self, user_id, local_image_path, require_exists=False):
        if not isinstance(local_image_path, str):
            return None
        raw = local_image_path.strip()
        if not raw:
            return None
        normalized = os.path.normpath(raw.replace("\\", "/")).replace("\\", "/")
        if normalized in {"", ".", ".."}:
            return None
        if normalized.startswith("../") or "/../" in normalized:
            return None
        if normalized.startswith("/"):
            return None
        if normalized == "images":
            return None
        if not normalized.startswith("images/"):
            return None

        user_root = os.path.realpath(self._user_root(user_id))
        images_root = os.path.realpath(os.path.join(user_root, "images"))
        candidate = os.path.realpath(os.path.join(user_root, normalized))
        try:
            if os.path.commonpath([candidate, user_root]) != user_root:
                return None
            if os.path.commonpath([candidate, images_root]) != images_root:
                return None
        except Exception:
            return None
        if require_exists and not os.path.isfile(candidate):
            return None
        return candidate


class _DummyUser:
    def __init__(self, user_id):
        self.id = user_id


class _DummyTextMessage:
    def __init__(self, text):
        self.text = text


class _DummyShortcutUpdate:
    def __init__(self, user_id, text="/01"):
        self.effective_user = _DummyUser(user_id)
        self.effective_message = _DummyTextMessage(text)
        self.message = self.effective_message


class _DummyQueryMessage:
    def __init__(self, with_photo=False):
        self.photo = [object()] if with_photo else None
        self.reply_markup = None
        self.deleted = False

    async def delete(self):
        self.deleted = True


class _DummyCallbackQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answers = []
        self.caption_edits = []
        self.text_edits = []

    async def answer(self, text=None, show_alert=None):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_caption(self, caption, reply_markup=None, parse_mode=None):
        self.caption_edits.append({
            "caption_len": len(caption or ""),
            "has_reply_markup": bool(reply_markup),
            "parse_mode": parse_mode,
        })

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.text_edits.append({
            "text_len": len(text or ""),
            "has_reply_markup": bool(reply_markup),
            "parse_mode": parse_mode,
        })


class _DummyManageUpdate:
    def __init__(self, user_id, query):
        self.effective_user = _DummyUser(user_id)
        self.callback_query = query


class _DummyContext:
    def __init__(self, bot, user_data=None):
        self.bot = bot
        self.user_data = dict(user_data or {})
        self.bot_data = {}


def _install_fake_mainbot(storage_obj):
    original = sys.modules.get("mainbot")
    fake_module = types.ModuleType("mainbot")
    fake_module.storage = storage_obj
    fake_module.API_FAILURE_TRACKER = None
    sys.modules["mainbot"] = fake_module
    return original


def _restore_mainbot(original):
    if original is None:
        sys.modules.pop("mainbot", None)
    else:
        sys.modules["mainbot"] = original


def _build_alert(alert_id, image_id=None, local_image_path=None):
    return {
        "id": alert_id,
        "title": "Revisione Toyota",
        "type": 5,
        "type_name": "One Time",
        "schedule": {"date": "01/01/2099", "time": "10:00"},
        "pre_alerts": [],
        "tags": [],
        "active": True,
        "image_id": image_id,
        "local_image_path": local_image_path,
    }


def _last_result_event(storage, alert_id):
    results = [
        e for e in storage.user_events
        if e.get("event") == "alert_detail_open_result"
        and isinstance(e.get("payload"), dict)
        and e.get("payload", {}).get("alert_id") == alert_id
    ]
    if not results:
        return None
    return results[-1]


def _last_attempt_event(storage, alert_id):
    attempts = [
        e for e in storage.user_events
        if e.get("event") == "alert_detail_open_attempt"
        and isinstance(e.get("payload"), dict)
        and e.get("payload", {}).get("alert_id") == alert_id
    ]
    if not attempts:
        return None
    return attempts[-1]


def _run_shortcut_case(list_alerts, storage, bot, user_id, alert_id, source_hint="alerts"):
    original_mainbot = _install_fake_mainbot(storage)
    try:
        update = _DummyShortcutUpdate(user_id, text="/07")
        context = _DummyContext(bot, user_data={})
        seed_mainbot_runtime(sys.modules["mainbot"], app=context, storage=storage)
        run_async(list_alerts.send_alert_detail_by_id(update, context, alert_id, source_hint=source_hint))
        return context
    finally:
        _restore_mainbot(original_mainbot)


def _run_manage_info_case(list_alerts, storage, bot, user_id, alert_id):
    original_mainbot = _install_fake_mainbot(storage)
    try:
        message = _DummyQueryMessage(with_photo=False)
        query = _DummyCallbackQuery(data=f"manage_info_{alert_id}", message=message)
        update = _DummyManageUpdate(user_id, query)
        context = _DummyContext(bot, user_data={"manage_source": "alerts"})
        seed_mainbot_runtime(sys.modules["mainbot"], app=context, storage=storage)
        run_async(list_alerts.handle_management(update, context))
        return query, message, context
    finally:
        _restore_mainbot(original_mainbot)


def _touch_file(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"img")


def _test_invalid_image_id_falls_back_to_local_and_autoheals(dbg, list_alerts):
    with tempfile.TemporaryDirectory(prefix="detail_media_local_") as tmp_root:
        user_id = 5001
        storage = _FakeStorage(tmp_root)
        images_dir = storage.setup_user(user_id)
        local_rel = "images/toyota.jpg"
        local_abs = os.path.join(images_dir, "toyota.jpg")
        _touch_file(local_abs)
        storage.set_alert(user_id, _build_alert("a_local", image_id="bad_fileid", local_image_path=local_rel))
        bot = _FakeBot(bad_file_ids={"bad_fileid"}, local_file_id="healed_fileid_777")
        _run_shortcut_case(list_alerts, storage, bot, user_id, "a_local", source_hint="alerts")

        updated_alert = storage.get_alert_by_id(user_id, "a_local")
        attempt_event = _last_attempt_event(storage, "a_local")
        result_event = _last_result_event(storage, "a_local")
        checks = {
            "photo_attempted_twice": len(bot.photo_calls) == 2,
            "first_attempt_uses_image_id": len(bot.photo_calls) >= 1 and bot.photo_calls[0]["photo_is_str"] is True,
            "second_attempt_uses_local_file": len(bot.photo_calls) >= 2 and bot.photo_calls[1]["photo_is_str"] is False,
            "no_text_fallback": len(bot.message_calls) == 0,
            "image_id_autohealed": isinstance(updated_alert, dict) and updated_alert.get("image_id") == "healed_fileid_777",
            "result_delivery_local": isinstance(result_event, dict) and result_event["payload"].get("delivery_mode") == "local",
            "attempt_logged": isinstance(attempt_event, dict),
            "result_reason_autoheal": isinstance(result_event, dict) and result_event["payload"].get("reason_code") == "autoheal_image_id",
            "fallback_reason_invalid_image_id": isinstance(result_event, dict) and "invalid_image_id" in (result_event["payload"].get("fallback_reasons") or []),
        }
        dbg.section("invalid_image_id_local_fallback", {
            "checks": checks,
            "photo_calls": bot.photo_calls,
            "message_calls": bot.message_calls,
            "update_calls": storage.update_calls,
            "attempt_event": attempt_event,
            "result_event": result_event,
        })
        if not all(checks.values()):
            dbg.problem("invalid_image_id_local_fallback_failed", {
                "checks": checks,
                "photo_calls": bot.photo_calls,
                "message_calls": bot.message_calls,
                "update_calls": storage.update_calls,
                "attempt_event": attempt_event,
                "result_event": result_event,
            })


def _test_invalid_image_id_missing_local_falls_back_to_text(dbg, list_alerts):
    with tempfile.TemporaryDirectory(prefix="detail_media_text_") as tmp_root:
        user_id = 5002
        storage = _FakeStorage(tmp_root)
        storage.setup_user(user_id)
        storage.set_alert(user_id, _build_alert("a_text", image_id="bad_fileid", local_image_path="images/missing.jpg"))
        bot = _FakeBot(bad_file_ids={"bad_fileid"})
        _run_shortcut_case(list_alerts, storage, bot, user_id, "a_text", source_hint="alerts")

        attempt_event = _last_attempt_event(storage, "a_text")
        result_event = _last_result_event(storage, "a_text")
        checks = {
            "photo_attempted_once": len(bot.photo_calls) == 1,
            "text_fallback_sent": len(bot.message_calls) == 1,
            "autoheal_not_called": len(storage.update_calls) == 0,
            "result_delivery_text": isinstance(result_event, dict) and result_event["payload"].get("delivery_mode") in {"text", "text_plain"},
            "attempt_logged": isinstance(attempt_event, dict),
            "result_reason_fallback_text": isinstance(result_event, dict) and result_event["payload"].get("reason_code") == "fallback_to_text",
            "fallback_has_invalid_image_id": isinstance(result_event, dict) and "invalid_image_id" in (result_event["payload"].get("fallback_reasons") or []),
            "fallback_has_local_file_missing": isinstance(result_event, dict) and "local_file_missing" in (result_event["payload"].get("fallback_reasons") or []),
        }
        dbg.section("invalid_image_id_text_fallback", {
            "checks": checks,
            "photo_calls": bot.photo_calls,
            "message_calls": bot.message_calls,
            "update_calls": storage.update_calls,
            "attempt_event": attempt_event,
            "result_event": result_event,
        })
        if not all(checks.values()):
            dbg.problem("invalid_image_id_text_fallback_failed", {
                "checks": checks,
                "photo_calls": bot.photo_calls,
                "message_calls": bot.message_calls,
                "update_calls": storage.update_calls,
                "attempt_event": attempt_event,
                "result_event": result_event,
            })


def _test_valid_image_id_uses_primary_path(dbg, list_alerts):
    with tempfile.TemporaryDirectory(prefix="detail_media_primary_") as tmp_root:
        user_id = 5003
        storage = _FakeStorage(tmp_root)
        storage.setup_user(user_id)
        storage.set_alert(user_id, _build_alert("a_primary", image_id="good_fileid", local_image_path="images/unused.jpg"))
        bot = _FakeBot()
        _run_shortcut_case(list_alerts, storage, bot, user_id, "a_primary", source_hint="alerts")

        attempt_event = _last_attempt_event(storage, "a_primary")
        result_event = _last_result_event(storage, "a_primary")
        checks = {
            "photo_attempted_once": len(bot.photo_calls) == 1,
            "primary_uses_file_id": len(bot.photo_calls) >= 1 and bot.photo_calls[0]["photo_is_str"] is True,
            "no_text_fallback": len(bot.message_calls) == 0,
            "no_autoheal_update": len(storage.update_calls) == 0,
            "result_delivery_image_id": isinstance(result_event, dict) and result_event["payload"].get("delivery_mode") == "image_id",
            "attempt_logged": isinstance(attempt_event, dict),
            "result_reason_image_id_ok": isinstance(result_event, dict) and result_event["payload"].get("reason_code") == "image_id_ok",
        }
        dbg.section("valid_image_id_primary_path", {
            "checks": checks,
            "photo_calls": bot.photo_calls,
            "message_calls": bot.message_calls,
            "update_calls": storage.update_calls,
            "attempt_event": attempt_event,
            "result_event": result_event,
        })
        if not all(checks.values()):
            dbg.problem("valid_image_id_primary_path_failed", {
                "checks": checks,
                "photo_calls": bot.photo_calls,
                "message_calls": bot.message_calls,
                "update_calls": storage.update_calls,
                "attempt_event": attempt_event,
                "result_event": result_event,
            })


def _test_manage_info_uses_same_fallback_flow(dbg, list_alerts):
    with tempfile.TemporaryDirectory(prefix="detail_media_manage_") as tmp_root:
        user_id = 5004
        storage = _FakeStorage(tmp_root)
        images_dir = storage.setup_user(user_id)
        _touch_file(os.path.join(images_dir, "toyota.jpg"))
        storage.set_alert(user_id, _build_alert("amanage", image_id="bad_fileid", local_image_path="images/toyota.jpg"))
        bot = _FakeBot(bad_file_ids={"bad_fileid"}, local_file_id="healed_manage_fileid")
        query, old_message, _ = _run_manage_info_case(list_alerts, storage, bot, user_id, "amanage")

        attempt_event = _last_attempt_event(storage, "amanage")
        result_event = _last_result_event(storage, "amanage")
        checks = {
            "photo_attempted_twice": len(bot.photo_calls) == 2,
            "old_message_deleted": old_message.deleted is True,
            "no_query_edit_fallback": len(query.text_edits) == 0 and len(query.caption_edits) == 0,
            "result_delivery_local": isinstance(result_event, dict) and result_event["payload"].get("delivery_mode") == "local",
            "attempt_logged": isinstance(attempt_event, dict),
            "result_reason_autoheal": isinstance(result_event, dict) and result_event["payload"].get("reason_code") == "autoheal_image_id",
        }
        dbg.section("manage_info_fallback", {
            "checks": checks,
            "photo_calls": bot.photo_calls,
            "message_calls": bot.message_calls,
            "query_answers": query.answers,
            "attempt_event": attempt_event,
            "result_event": result_event,
        })
        if not all(checks.values()):
            dbg.problem("manage_info_fallback_failed", {
                "checks": checks,
                "photo_calls": bot.photo_calls,
                "message_calls": bot.message_calls,
                "query_answers": query.answers,
                "attempt_event": attempt_event,
                "result_event": result_event,
            })


def main():
    dbg = DebugHarness.create(__file__, SCRIPT_TITLE, FEATURE_TITLE)
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        suppress_ptb_user_warning()

        unknown_args = _parse_cli_args(dbg.args)
        if unknown_args:
            dbg.problem("cli_args_unknown", {"unknown": unknown_args, "args": dbg.args})

        dbg.run_meta({"project_root": ROOT_DIR})

        try:
            from modules.handlers import list_alerts
        except ModuleNotFoundError as exc:
            dbg.mark_dependency_error(exc)
            dbg.finish(exit_on_problems=False)
            return

        _test_invalid_image_id_falls_back_to_local_and_autoheals(dbg, list_alerts)
        _test_invalid_image_id_missing_local_falls_back_to_text(dbg, list_alerts)
        _test_valid_image_id_uses_primary_path(dbg, list_alerts)
        _test_manage_info_uses_same_fallback_flow(dbg, list_alerts)
    except Exception as exc:
        dbg.problem("unhandled_exception", {"error": str(exc)})
    finally:
        logging.disable(previous_disable_level)

    fallback_ok = not dbg.has_problem(
        "invalid_image_id_local_fallback_failed",
        "invalid_image_id_text_fallback_failed",
        "valid_image_id_primary_path_failed",
        "manage_info_fallback_failed",
    )
    runtime_ok = not dbg.has_problem("unhandled_exception", "cli_args_unknown")
    dbg.finish(summary_lines=[
        f"fallback: {'OK' if fallback_ok else 'FAIL'}",
        f"runtime: {'OK' if runtime_ok else 'FAIL'}",
        f"logfile: {dbg.log_path}",
    ], summary_only_on_problems=True)


if __name__ == "__main__":
    main()
